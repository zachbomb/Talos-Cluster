"""HMAC nonce determinism + replay rejection + key rotation tests (R22)."""
from __future__ import annotations

from alert_remediation_hitl.nonce import NonceKey, generate, verify


KEY_V1 = NonceKey("v1", b"a" * 32)
KEY_V2 = NonceKey("v2", b"b" * 32)


def test_deterministic_for_fixed_inputs():
    n1 = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    n2 = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    assert n1.value == n2.value
    assert n1.key_id == n2.key_id == "v1"
    assert n1.created_at_ms == 1700000000000


def test_different_fingerprints_yield_different_nonces():
    """Rev-2 finding: collision-resistance smoke test."""
    n_a = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    n_b = generate("fp-B", KEY_V1, created_at_ms=1700000000000)
    assert n_a.value != n_b.value


def test_different_timestamps_yield_different_nonces():
    """Rev-2 finding: proves the timestamp is in the HMAC input.
    If a bug dropped timestamp from the HMAC, both nonces would be identical.
    """
    n_t1 = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    n_t2 = generate("fp-A", KEY_V1, created_at_ms=1700000000001)
    assert n_t1.value != n_t2.value


def test_verify_happy_path():
    n = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    ok, reason = verify(
        n.value,
        fingerprint="fp-A",
        stored_created_at_ms=1700000000000,
        stored_key_id="v1",
        keys=[KEY_V1],
    )
    assert ok
    assert reason is None


def test_verify_rejects_tampered_value():
    n = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    bad = "0" * len(n.value)
    ok, reason = verify(
        bad,
        fingerprint="fp-A",
        stored_created_at_ms=1700000000000,
        stored_key_id="v1",
        keys=[KEY_V1],
    )
    assert not ok
    assert reason == "mismatch"


def test_verify_rejects_wrong_fingerprint_for_stored_nonce():
    """If we changed the fingerprint we're verifying against, the HMAC won't match."""
    n = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    ok, reason = verify(
        n.value,
        fingerprint="fp-B",  # different fingerprint
        stored_created_at_ms=1700000000000,
        stored_key_id="v1",
        keys=[KEY_V1],
    )
    assert not ok
    assert reason == "mismatch"


def test_verify_rejects_unknown_key_id():
    n = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    ok, reason = verify(
        n.value,
        fingerprint="fp-A",
        stored_created_at_ms=1700000000000,
        stored_key_id="v99",  # not in keys
        keys=[KEY_V1],
    )
    assert not ok
    assert reason == "key_unknown"


def test_key_rotation_with_overlap():
    """During the 24h overlap window, both keys are accepted. The verifier
    routes by stored_key_id so old nonces stay valid while new ones use v2.
    """
    old_nonce = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    new_nonce = generate("fp-A", KEY_V2, created_at_ms=1700000001000)
    keys_during_overlap = [KEY_V2, KEY_V1]

    ok_old, _ = verify(
        old_nonce.value,
        fingerprint="fp-A",
        stored_created_at_ms=1700000000000,
        stored_key_id="v1",
        keys=keys_during_overlap,
    )
    ok_new, _ = verify(
        new_nonce.value,
        fingerprint="fp-A",
        stored_created_at_ms=1700000001000,
        stored_key_id="v2",
        keys=keys_during_overlap,
    )
    assert ok_old
    assert ok_new


def test_key_rotation_after_overlap_old_key_rejected():
    """After overlap, only current key remains in the list. Old nonces fail."""
    old_nonce = generate("fp-A", KEY_V1, created_at_ms=1700000000000)
    keys_after_overlap = [KEY_V2]

    ok, reason = verify(
        old_nonce.value,
        fingerprint="fp-A",
        stored_created_at_ms=1700000000000,
        stored_key_id="v1",
        keys=keys_after_overlap,
    )
    assert not ok
    assert reason == "key_unknown"
