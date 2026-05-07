"""HMAC nonce generation + verification (R22).

The nonce binds an alert fingerprint to a server-generated timestamp so that
replay of an old (signed-and-in-window) Discord interaction payload cannot
re-execute a playbook. Per origin R22, the timestamp input MUST be
server-generated wall-clock at nonce creation — NEVER client-supplied.

Two-key rotation: a 24h overlap window during which both `current` and
`prior` keys are accepted. After overlap, only `current` is accepted.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class NonceKey:
    """One HMAC key with an identifier so verify can route by key_id."""

    key_id: str
    secret: bytes


@dataclass(frozen=True)
class Nonce:
    value: str
    key_id: str
    created_at_ms: int


def now_ms() -> int:
    """Server-generated wall-clock ms. Monkeypatchable for tests via freezegun."""
    return int(time.time() * 1000)


def generate(fingerprint: str, key: NonceKey, *, created_at_ms: int | None = None) -> Nonce:
    """Generate a single-use nonce bound to (fingerprint, server_ts_ms, key)."""
    ts = created_at_ms if created_at_ms is not None else now_ms()
    msg = f"{fingerprint}|{ts}".encode("utf-8")
    digest = hmac.new(key.secret, msg, hashlib.sha256).hexdigest()[:32]
    return Nonce(value=digest, key_id=key.key_id, created_at_ms=ts)


def verify(
    candidate_value: str,
    *,
    fingerprint: str,
    stored_created_at_ms: int,
    stored_key_id: str,
    keys: list[NonceKey],
) -> tuple[bool, str | None]:
    """Verify a candidate nonce value matches what would be produced for
    (fingerprint, stored_created_at_ms, stored_key_id).

    Returns (ok, reason). reason is one of:
      - None on success
      - "key_unknown" — stored_key_id doesn't match any key in `keys`
      - "mismatch" — HMAC didn't match (tampered, wrong fingerprint, or
        wrong stored_created_at_ms)
    """
    matching = next((k for k in keys if k.key_id == stored_key_id), None)
    if matching is None:
        return False, "key_unknown"
    expected = generate(
        fingerprint, matching, created_at_ms=stored_created_at_ms
    ).value
    if hmac.compare_digest(candidate_value, expected):
        return True, None
    return False, "mismatch"
