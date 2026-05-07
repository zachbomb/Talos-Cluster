"""SQLite state machine tests — table-driven over 10+ transitions plus
invalid-transition rejection (R14).
"""
from __future__ import annotations

import pytest

from alert_remediation_hitl.state import State, StateStore


@pytest.fixture
def fp(store: StateStore) -> str:
    """A row in Pending state with playbook + correlation_id set."""
    fingerprint = "abc123fingerprint"
    store.upsert_pending(
        fingerprint,
        alertname="BGPSessionDown",
        playbook="bgp-recovery",
        correlation_id="msg-1",
    )
    return fingerprint


def _set_state(store: StateStore, fingerprint: str, target: State) -> None:
    """Test helper — short-circuit a transition to set up a starting state."""
    row = store.get(fingerprint)
    assert row is not None
    store.transition(
        fingerprint,
        from_states=[row.state],
        to_state=target,
    )


# ---------------------------------------------------------- valid transitions
@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (State.PENDING, State.APPROVED),
        (State.PENDING, State.SNOOZED),
        (State.PENDING, State.IGNORED),
        (State.PENDING, State.AUTO_RESOLVED),
        (State.SNOOZED, State.PENDING),
        (State.SNOOZED, State.AUTO_RESOLVED),
        (State.APPROVED, State.SUCCEEDED),
        (State.APPROVED, State.FAILED),
        (State.APPROVED, State.TIMEOUT),
        (State.PENDING, State.ORPHANED),
    ],
)
def test_valid_transitions(store: StateStore, fp: str, from_state: State, to_state: State) -> None:
    if from_state is not State.PENDING:
        _set_state(store, fp, from_state)
    ok = store.transition(fp, from_states=[from_state], to_state=to_state)
    assert ok
    row = store.get(fp)
    assert row is not None
    assert row.state is to_state


# -------------------------------------------------- invalid-transition rejection
@pytest.mark.parametrize(
    ("terminal_state", "attempted_target"),
    [
        (State.SUCCEEDED, State.APPROVED),
        (State.FAILED, State.APPROVED),
        (State.TIMEOUT, State.APPROVED),
        (State.AUTO_RESOLVED, State.APPROVED),
        (State.IGNORED, State.APPROVED),
        (State.ORPHANED, State.APPROVED),
    ],
)
def test_terminal_states_reject_transition_to_approved(
    store: StateStore, fp: str, terminal_state: State, attempted_target: State
) -> None:
    _set_state(store, fp, terminal_state)
    ok = store.transition(
        fp, from_states=[State.PENDING], to_state=attempted_target
    )
    assert not ok
    # State unchanged.
    assert store.get(fp).state is terminal_state  # type: ignore[union-attr]


# ------------------------------------------------------ idempotent upsert
def test_upsert_pending_idempotent(store: StateStore) -> None:
    """AM webhook redelivery must not duplicate rows or error."""
    fingerprint = "idempotent-fp"
    store.upsert_pending(
        fingerprint, alertname="X", playbook="bgp-recovery", correlation_id=None
    )
    # Second post — would error on plain INSERT, but ON CONFLICT clause should absorb.
    store.upsert_pending(
        fingerprint, alertname="X", playbook="bgp-recovery", correlation_id="msg-99"
    )
    row = store.get(fingerprint)
    assert row is not None
    assert row.state is State.PENDING
    assert row.correlation_id == "msg-99"


def test_upsert_pending_preserves_existing_correlation_id(store: StateStore) -> None:
    """COALESCE clause keeps the original correlation_id when redelivery has None."""
    fingerprint = "coalesce-fp"
    store.upsert_pending(
        fingerprint, alertname="X", playbook="bgp-recovery", correlation_id="msg-1"
    )
    store.upsert_pending(
        fingerprint, alertname="X", playbook="bgp-recovery", correlation_id=None
    )
    row = store.get(fingerprint)
    assert row is not None
    assert row.correlation_id == "msg-1"


# -------------------------------------------------------- list_in_states
def test_list_in_states_filters_correctly(store: StateStore) -> None:
    store.upsert_pending("p1", alertname="A", playbook="bgp-recovery", correlation_id=None)
    store.upsert_pending("p2", alertname="B", playbook="bgp-recovery", correlation_id=None)
    _set_state(store, "p2", State.SUCCEEDED)
    pendings = store.list_in_states([State.PENDING])
    succeededs = store.list_in_states([State.SUCCEEDED])
    assert {r.fingerprint for r in pendings} == {"p1"}
    assert {r.fingerprint for r in succeededs} == {"p2"}


def test_health_check_returns_true_on_open_db(store: StateStore) -> None:
    assert store.health_check() is True
