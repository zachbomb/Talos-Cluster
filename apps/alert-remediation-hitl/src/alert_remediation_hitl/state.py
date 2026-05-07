"""SQLite state machine for HITL alert lifecycles.

State enum (per origin R14):
    Pending      — buttons posted, no click yet
    Approved     — playbook running
    Snoozed      — silenced for fixed 1h via AM silence
    Ignored      — terminal-for-this-instance
    Auto-resolved — alert resolved before any click
    Succeeded    — playbook exit 0
    Failed       — playbook non-zero exit
    Timeout      — playbook hit activeDeadlineSeconds
    Orphaned     — receiver crashed between INSERT and Discord post (rev-2)

All writes use INSERT ON CONFLICT(fingerprint) DO UPDATE so concurrent
reconciler + AM webhook redelivery don't race on UNIQUE constraint.
Transitions are guarded by `UPDATE ... WHERE fingerprint=? AND state IN (...)`
so invalid transitions reject silently (rowcount=0).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class State(StrEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    SNOOZED = "Snoozed"
    IGNORED = "Ignored"
    AUTO_RESOLVED = "Auto-resolved"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    TIMEOUT = "Timeout"
    ORPHANED = "Orphaned"


TERMINAL_STATES = frozenset(
    {State.SUCCEEDED, State.FAILED, State.TIMEOUT, State.AUTO_RESOLVED, State.IGNORED, State.ORPHANED}
)
NON_TERMINAL_STATES = frozenset({State.PENDING, State.APPROVED, State.SNOOZED})


@dataclass
class StateRow:
    fingerprint: str
    state: State
    alertname: str | None
    created_at: str
    updated_at: str
    nonce: str | None
    key_id: str | None
    nonce_created_at_ms: int | None
    correlation_id: str | None
    snooze_until: str | None
    job_name: str | None
    playbook: str | None
    audit_json: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StateRow":
        return cls(
            fingerprint=row["fingerprint"],
            state=State(row["state"]),
            alertname=row["alertname"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            nonce=row["nonce"],
            key_id=row["key_id"],
            nonce_created_at_ms=row["nonce_created_at_ms"],
            correlation_id=row["correlation_id"],
            snooze_until=row["snooze_until"],
            job_name=row["job_name"],
            playbook=row["playbook"],
            audit_json=row["audit_json"],
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS hitl_state (
    fingerprint TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    alertname TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    nonce TEXT,
    key_id TEXT,
    nonce_created_at_ms INTEGER,
    correlation_id TEXT,
    snooze_until TEXT,
    job_name TEXT,
    playbook TEXT,
    audit_json TEXT
);
CREATE INDEX IF NOT EXISTS hitl_state_state_idx ON hitl_state(state);
"""


class StateStore:
    """Thread-safe SQLite-backed state store with WAL mode + busy_timeout."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        # Mandatory PRAGMAs per plan U11 — without WAL mode the default
        # journal_mode=DELETE serializes ALL access and surfaces SQLITE_BUSY
        # under concurrent reconciler + webhook + interaction load.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _now_iso() -> str:
        # Local import to allow freezegun/time-travel patching in tests.
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    def health_check(self) -> bool:
        """Used by the /health liveness probe — locked/corrupted DB returns False."""
        try:
            with self._lock:
                cur = self._conn.execute("SELECT 1")
                return cur.fetchone() is not None
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------ writes

    def upsert_pending(
        self,
        fingerprint: str,
        *,
        alertname: str | None,
        playbook: str | None,
        correlation_id: str | None,
    ) -> None:
        """Insert a Pending row OR refresh an existing one.

        Idempotent for AM webhook redelivery — repeated POSTs of the same
        fingerprint do not error or duplicate state.
        """
        now = self._now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO hitl_state (
                    fingerprint, state, alertname, playbook, correlation_id,
                    created_at, updated_at
                ) VALUES (?, 'Pending', ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    correlation_id = COALESCE(hitl_state.correlation_id, excluded.correlation_id),
                    alertname = COALESCE(hitl_state.alertname, excluded.alertname),
                    playbook = COALESCE(hitl_state.playbook, excluded.playbook),
                    updated_at = excluded.updated_at
                """,
                (fingerprint, alertname, playbook, correlation_id, now, now),
            )

    def set_correlation_id(self, fingerprint: str, correlation_id: str) -> None:
        """Stamp the Discord message id after a successful bot post."""
        now = self._now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE hitl_state SET correlation_id = ?, updated_at = ? WHERE fingerprint = ?",
                (correlation_id, now, fingerprint),
            )

    def transition(
        self,
        fingerprint: str,
        *,
        from_states: Iterable[State],
        to_state: State,
        nonce: str | None = None,
        key_id: str | None = None,
        nonce_created_at_ms: int | None = None,
        snooze_until: str | None = None,
        job_name: str | None = None,
        audit_extra: dict[str, object] | None = None,
    ) -> bool:
        """Guarded transition. Returns True if a row was updated, False if not.

        False → either fingerprint doesn't exist OR current state isn't in
        from_states. Caller decides what to do (typically: reply "stale" or
        "already executed").
        """
        now = self._now_iso()
        from_list = ",".join(f"'{s.value}'" for s in from_states)
        audit_json = json.dumps(audit_extra) if audit_extra else None
        with self._lock:
            cur = self._conn.execute(
                f"""
                UPDATE hitl_state
                SET state = ?,
                    updated_at = ?,
                    nonce = COALESCE(?, nonce),
                    key_id = COALESCE(?, key_id),
                    nonce_created_at_ms = COALESCE(?, nonce_created_at_ms),
                    snooze_until = COALESCE(?, snooze_until),
                    job_name = COALESCE(?, job_name),
                    audit_json = COALESCE(?, audit_json)
                WHERE fingerprint = ? AND state IN ({from_list})
                """,
                (
                    to_state.value,
                    now,
                    nonce,
                    key_id,
                    nonce_created_at_ms,
                    snooze_until,
                    job_name,
                    audit_json,
                    fingerprint,
                ),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------ reads

    def get(self, fingerprint: str) -> StateRow | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM hitl_state WHERE fingerprint = ?", (fingerprint,)
            )
            row = cur.fetchone()
            return StateRow.from_row(row) if row else None

    def list_in_states(self, states: Iterable[State]) -> list[StateRow]:
        state_list = ",".join(f"'{s.value}'" for s in states)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM hitl_state WHERE state IN ({state_list})"
            )
            return [StateRow.from_row(r) for r in cur.fetchall()]


# Default factory for FastAPI Depends; tests construct StateStore directly.
def get_default_state_store(db_path: str | None = None) -> StateStore:
    path = db_path or os.environ.get("STATE_DB_PATH", "/var/lib/hitl/state.db")
    return StateStore(path)
