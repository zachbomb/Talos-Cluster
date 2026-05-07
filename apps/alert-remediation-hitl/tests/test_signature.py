"""Discord Ed25519 signature verification tests (R8 + R9).

Includes the critical FUTURE-timestamp test (rev-2 finding) — a one-sided
implementation `now - ts > 60` would silently accept future-skewed signatures.
The symmetric ±60s window must reject both directions.
"""
from __future__ import annotations

import time

import pytest
from nacl.signing import SigningKey

from alert_remediation_hitl.discord_client import verify_signature


@pytest.fixture
def keypair() -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    pk_hex = sk.verify_key.encode().hex()
    return sk, pk_hex


def _sign(sk: SigningKey, timestamp: str, body: bytes) -> str:
    return sk.sign(timestamp.encode("utf-8") + body).signature.hex()


def test_happy_path(keypair):
    sk, pk = keypair
    body = b'{"type":1}'
    ts = str(int(time.time()))
    sig = _sign(sk, ts, body)
    result = verify_signature(
        raw_body=body, signature_hex=sig, timestamp=ts, public_key_hex=pk
    )
    assert result.ok
    assert result.reason is None


def test_missing_signature_header(keypair):
    _, pk = keypair
    result = verify_signature(
        raw_body=b'{"type":1}', signature_hex=None, timestamp="123", public_key_hex=pk
    )
    assert not result.ok
    assert result.reason == "missing_headers"


def test_missing_timestamp_header(keypair):
    sk, pk = keypair
    body = b'{"type":1}'
    ts = "123"
    sig = _sign(sk, ts, body)
    result = verify_signature(
        raw_body=body, signature_hex=sig, timestamp=None, public_key_hex=pk
    )
    assert not result.ok
    assert result.reason == "missing_headers"


def test_unparseable_timestamp(keypair):
    _, pk = keypair
    result = verify_signature(
        raw_body=b'{}', signature_hex="00" * 64, timestamp="not-a-number", public_key_hex=pk
    )
    assert not result.ok
    assert result.reason == "timestamp_unparseable"


def test_tampered_body_rejected(keypair):
    sk, pk = keypair
    original = b'{"type":3,"data":{"custom_id":"hitl:approve:abc"}}'
    ts = str(int(time.time()))
    sig = _sign(sk, ts, original)
    tampered = b'{"type":3,"data":{"custom_id":"hitl:approve:DIFFERENT"}}'
    result = verify_signature(
        raw_body=tampered, signature_hex=sig, timestamp=ts, public_key_hex=pk
    )
    assert not result.ok
    assert result.reason == "signature_mismatch"


def test_tampered_timestamp_rejected(keypair):
    sk, pk = keypair
    body = b'{"type":1}'
    real_ts_int = int(time.time())
    real_ts = str(real_ts_int)
    sig = _sign(sk, real_ts, body)
    # Derive the forged timestamp deterministically from real_ts so the test
    # can never accidentally produce real_ts == forged_ts on a slow CI runner.
    forged_ts = str(real_ts_int - 1)
    result = verify_signature(
        raw_body=body, signature_hex=sig, timestamp=forged_ts, public_key_hex=pk
    )
    assert not result.ok
    assert result.reason == "signature_mismatch"


def test_timestamp_too_old_rejected(keypair):
    sk, pk = keypair
    body = b'{"type":1}'
    now = time.time()
    old_ts = str(int(now) - 65)  # 65 s in past — outside ±60 window
    sig = _sign(sk, old_ts, body)
    result = verify_signature(
        raw_body=body,
        signature_hex=sig,
        timestamp=old_ts,
        public_key_hex=pk,
        timestamp_window_seconds=60,
        now_seconds=now,
    )
    assert not result.ok
    assert result.reason == "timestamp_outside_window"
    assert result.clock_skew_ms is not None
    assert result.clock_skew_ms >= 65000


def test_timestamp_too_new_rejected(keypair):
    """Rev-2 finding: future-direction skew must also be rejected.
    A naive `now - ts > 60` check would pass this; the symmetric `abs(...)`
    check is the correct guard.
    """
    sk, pk = keypair
    body = b'{"type":1}'
    now = time.time()
    future_ts = str(int(now) + 65)  # 65 s in future
    sig = _sign(sk, future_ts, body)
    result = verify_signature(
        raw_body=body,
        signature_hex=sig,
        timestamp=future_ts,
        public_key_hex=pk,
        timestamp_window_seconds=60,
        now_seconds=now,
    )
    assert not result.ok
    assert result.reason == "timestamp_outside_window"
    assert result.clock_skew_ms is not None
    assert result.clock_skew_ms <= -60000  # at least 60s in the future, sub-second slack


def test_timestamp_within_window_accepted(keypair):
    sk, pk = keypair
    body = b'{"type":1}'
    now = time.time()
    ts = str(int(now) - 30)
    sig = _sign(sk, ts, body)
    result = verify_signature(
        raw_body=body,
        signature_hex=sig,
        timestamp=ts,
        public_key_hex=pk,
        timestamp_window_seconds=60,
        now_seconds=now,
    )
    assert result.ok
