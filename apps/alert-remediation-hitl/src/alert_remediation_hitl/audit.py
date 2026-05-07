"""Structured JSON audit logging to stdout for Loki ingestion (R17)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from typing import Any

_LOGGER = logging.getLogger("alert-remediation-hitl.audit")


def _now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="milliseconds")


def emit(
    event: str,
    *,
    fingerprint: str | None = None,
    alertname: str | None = None,
    actor: str = "system",
    playbook: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    duration_ms: int | None = None,
    clock_skew_ms: int | None = None,
    **extra: Any,
) -> None:
    """Emit one structured JSON log line.

    Required fields per origin R17. Extra kwargs are merged in for ad-hoc
    context. Output is one JSON object per line on stdout — Promtail/Alloy
    parse and ship to Loki.
    """
    record: dict[str, Any] = {
        "timestamp": _now(),
        "app": "alert-remediation-hitl",
        "event": event,
        "actor": actor,
    }
    if fingerprint is not None:
        record["fingerprint"] = fingerprint
    if alertname is not None:
        record["alertname"] = alertname
    if playbook is not None:
        record["playbook"] = playbook
    if outcome is not None:
        record["outcome"] = outcome
    if correlation_id is not None:
        record["correlation_id"] = correlation_id
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    if clock_skew_ms is not None:
        record["clock_skew_ms"] = clock_skew_ms
    for k, v in extra.items():
        if v is not None:
            record[k] = v

    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def configure_root_logger(level: str = "INFO") -> None:
    """Wire stdlib logging through stdout in plain format (audit emits JSON itself)."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
