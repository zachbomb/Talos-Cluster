"""Reconciler tests — covers all branches per plan U11 + rev-2 orphan-Pending fix."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alert_remediation_hitl.reconciler import Reconciler
from alert_remediation_hitl.state import State, StateStore


@pytest.fixture
def am_mock() -> MagicMock:
    am = MagicMock()
    am.get_alert_state = AsyncMock(return_value=None)
    am.list_silences_by_fingerprint = AsyncMock(return_value=[])
    am.expire_silence = AsyncMock(return_value=None)
    return am


@pytest.fixture
def jobs_mock() -> MagicMock:
    jobs = MagicMock()
    jobs.find_existing_jobs = MagicMock(return_value=[])
    return jobs


@pytest.fixture
def retry_mock() -> AsyncMock:
    return AsyncMock(return_value=True)


# ------------------------------------------------------ Snoozed → Auto-resolved
async def test_snoozed_alert_resolved_during_downtime(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    fp = "snz-resolved"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="m1")
    store.transition(fp, from_states=[State.PENDING], to_state=State.SNOOZED)
    am_mock.get_alert_state.return_value = None  # alert resolved
    am_mock.list_silences_by_fingerprint.return_value = [{"id": "sil-1"}]
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    assert store.get(fp).state is State.AUTO_RESOLVED  # type: ignore[union-attr]
    am_mock.expire_silence.assert_awaited_once_with("sil-1")


# ---------------------------------------------------- Snoozed still firing → no-op
async def test_snoozed_alert_still_firing_no_op(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    """Negative pair to the cancel-on-resolve case. Reconciler MUST NOT
    cancel a still-valid silence.
    """
    fp = "snz-firing"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="m1")
    store.transition(fp, from_states=[State.PENDING], to_state=State.SNOOZED)
    am_mock.get_alert_state.return_value = "active"  # still firing
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    assert store.get(fp).state is State.SNOOZED  # unchanged  # type: ignore[union-attr]
    am_mock.expire_silence.assert_not_awaited()


# ---------------------------------------------------- Approved + Job exists → adopt
async def test_approved_with_running_job_adopts(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    fp = "apr-running"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="m1")
    store.transition(
        fp,
        from_states=[State.PENDING],
        to_state=State.APPROVED,
        job_name="hitl-bgp-recovery-aprrunning",
    )
    jobs_mock.find_existing_jobs.return_value = [MagicMock()]  # one Job
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    # No transition — adopted (still Approved)
    assert store.get(fp).state is State.APPROVED  # type: ignore[union-attr]


# ------------------------------------------------ Approved + Job missing → Timeout
async def test_approved_with_missing_job_transitions_timeout(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    fp = "apr-missing"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="m1")
    store.transition(
        fp,
        from_states=[State.PENDING],
        to_state=State.APPROVED,
        job_name="hitl-bgp-recovery-aprmissing",
    )
    jobs_mock.find_existing_jobs.return_value = []  # no Jobs
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    assert store.get(fp).state is State.TIMEOUT  # type: ignore[union-attr]


# --------------------------------- Approved + duplicate Jobs → fail loud, no transition
async def test_approved_with_duplicate_jobs_fails_loud(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    fp = "apr-dup"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="m1")
    store.transition(
        fp,
        from_states=[State.PENDING],
        to_state=State.APPROVED,
        job_name="hitl-bgp-recovery-aprdup",
    )
    jobs_mock.find_existing_jobs.return_value = [MagicMock(), MagicMock()]
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    # Should NOT silently pick one — state stays Approved, audit logs duplicate.
    assert store.get(fp).state is State.APPROVED  # type: ignore[union-attr]


# ---------------------------------------------------- Pending with msg → no-op
async def test_pending_with_correlation_id_no_op(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock, retry_mock: AsyncMock
):
    fp = "pen-live"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id="msg-99")
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry_mock
    )
    await rec.run()
    # No retry called — correlation_id is not None.
    retry_mock.assert_not_awaited()
    assert store.get(fp).state is State.PENDING  # type: ignore[union-attr]


# ---------------------------- Pending without msg → orphan retry succeeds
async def test_orphan_pending_retry_succeeds(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock
):
    fp = "pen-orphan-recover"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id=None)
    retry = AsyncMock(return_value=True)
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry
    )
    await rec.run()
    retry.assert_awaited_once()
    # State stays Pending — orphan recovered.
    assert store.get(fp).state is State.PENDING  # type: ignore[union-attr]


# ------------------------- Pending without msg → orphan retry fails → Orphaned
async def test_orphan_pending_retry_fails_transitions_orphaned(
    store: StateStore, am_mock: MagicMock, jobs_mock: MagicMock
):
    fp = "pen-orphan-fail"
    store.upsert_pending(fp, alertname="X", playbook="bgp-recovery", correlation_id=None)
    retry = AsyncMock(return_value=False)
    rec = Reconciler(
        store=store, am_client=am_mock, job_dispatcher=jobs_mock, retry_pending_post=retry
    )
    await rec.run()
    retry.assert_awaited_once()
    assert store.get(fp).state is State.ORPHANED  # type: ignore[union-attr]
