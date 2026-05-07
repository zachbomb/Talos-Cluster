"""Startup reconciliation per origin R14 + plan rev-2 orphan-Pending fix.

Runs synchronously in FastAPI lifespan BEFORE binding the HTTP listener so
that no Discord interaction can race against a still-reconciling state DB.

Branches (per plan U11 pseudo-flow):

  Snoozed → query AM:
    - alert resolved during downtime → expireSilence + transition Auto-resolved
    - alert still firing → no-op (silence still valid)

  Approved → list Jobs by alerting.local/fingerprint label:
    - Job running → adopt and watch (do NOT relaunch)
    - Job missing → transition Timeout, emit remediation_failed audit
    - 2+ Jobs found (unexpected) → fail loudly, do NOT pick one silently

  Pending with correlation_id NOT NULL → no-op (button still live).

  Pending with correlation_id IS NULL (rev-2 orphan-post case) → retry the
  bot post once. If that also fails, transition to Orphaned terminal state.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from .alertmanager_client import AlertmanagerClient
from .audit import emit as audit_emit
from .playbooks import JobDispatcher
from .state import State, StateRow, StateStore

_LOGGER = logging.getLogger(__name__)


class Reconciler:
    def __init__(
        self,
        *,
        store: StateStore,
        am_client: AlertmanagerClient,
        job_dispatcher: JobDispatcher | None,
        retry_pending_post: Callable[[StateRow], Awaitable[bool]],
    ):
        self._store = store
        self._am = am_client
        self._jobs = job_dispatcher
        self._retry_pending_post = retry_pending_post

    async def run(self) -> None:
        """Reconcile all non-terminal rows. Called once at startup."""
        rows = self._store.list_in_states(
            [State.PENDING, State.APPROVED, State.SNOOZED]
        )
        _LOGGER.info("Reconciler starting; %d non-terminal rows to inspect", len(rows))
        for row in rows:
            try:
                if row.state is State.SNOOZED:
                    await self._reconcile_snoozed(row)
                elif row.state is State.APPROVED:
                    await self._reconcile_approved(row)
                elif row.state is State.PENDING:
                    await self._reconcile_pending(row)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("Reconciler error for %s", row.fingerprint)
                audit_emit(
                    "reconciler_error",
                    fingerprint=row.fingerprint,
                    alertname=row.alertname,
                    error=str(exc),
                )
        _LOGGER.info("Reconciler complete.")

    # ---------------------------------------------------------- Snoozed branch

    async def _reconcile_snoozed(self, row: StateRow) -> None:
        am_state = await self._am.get_alert_state(row.fingerprint)
        if am_state is None:
            # Alert resolved during downtime → cancel the silence (R15 cancel-on-resolve).
            silences = await self._am.list_silences_by_fingerprint(row.fingerprint)
            for silence in silences:
                await self._am.expire_silence(silence["id"])
            self._store.transition(
                row.fingerprint,
                from_states=[State.SNOOZED],
                to_state=State.AUTO_RESOLVED,
            )
            audit_emit(
                "silence_cancelled_on_resolve",
                fingerprint=row.fingerprint,
                alertname=row.alertname,
            )
        else:
            # Still firing — silence is still valid; reconciler is a no-op.
            audit_emit(
                "reconcile_snoozed_still_firing",
                fingerprint=row.fingerprint,
                alertname=row.alertname,
            )

    # --------------------------------------------------------- Approved branch

    async def _reconcile_approved(self, row: StateRow) -> None:
        if self._jobs is None or row.job_name is None:
            audit_emit(
                "reconcile_approved_no_job_dispatcher",
                fingerprint=row.fingerprint,
            )
            return
        jobs = self._jobs.find_existing_jobs(row.fingerprint)
        if len(jobs) > 1:
            # Per plan rev-2: fail loudly with audit; do NOT pick one silently.
            audit_emit(
                "duplicate_jobs_detected",
                fingerprint=row.fingerprint,
                job_count=len(jobs),
            )
            return
        if len(jobs) == 0:
            # Job missing — orphaned by GC during downtime. Treat as Timeout.
            self._store.transition(
                row.fingerprint,
                from_states=[State.APPROVED],
                to_state=State.TIMEOUT,
                audit_extra={"reconcile_outcome": "job_missing_at_restart"},
            )
            audit_emit(
                "remediation_failed",
                fingerprint=row.fingerprint,
                alertname=row.alertname,
                playbook=row.playbook,
                outcome="job_missing_at_restart",
            )
            return
        # Exactly one Job: adopt by reading current status (background watcher
        # in main.py picks it up from there).
        audit_emit(
            "reconcile_approved_adopted",
            fingerprint=row.fingerprint,
            playbook=row.playbook,
        )

    # ---------------------------------------------------------- Pending branch

    async def _reconcile_pending(self, row: StateRow) -> None:
        if row.correlation_id:
            # Button message is live in Discord — click handler will resume.
            return
        # Orphan-Pending (rev-2): receiver crashed between INSERT and Discord
        # post. Retry once. If that fails, transition to terminal Orphaned.
        ok = await self._retry_pending_post(row)
        if ok:
            audit_emit(
                "pending_orphaned_recovered",
                fingerprint=row.fingerprint,
                alertname=row.alertname,
            )
        else:
            self._store.transition(
                row.fingerprint,
                from_states=[State.PENDING],
                to_state=State.ORPHANED,
            )
            audit_emit(
                "pending_orphaned",
                fingerprint=row.fingerprint,
                alertname=row.alertname,
                outcome="discord_post_retry_failed",
            )
