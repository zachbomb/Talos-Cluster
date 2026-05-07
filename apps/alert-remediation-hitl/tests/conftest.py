"""Shared test fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from alert_remediation_hitl.state import StateStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "state.db")


@pytest.fixture
def store(tmp_db: str) -> StateStore:
    s = StateStore(tmp_db)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _set_state_db_env(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_DB_PATH", tmp_db)
