"""Thin Alertmanager API client.

Used to:
  - Create silences (Snooze action).
  - Expire silences (cancel-on-resolve, gameday step 11).
  - Query alerts by fingerprint to determine current state during reconciliation.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)


class AlertmanagerClient:
    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout: float,
        read_timeout: float,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=read_timeout),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_alert_state(self, fingerprint: str) -> str | None:
        """Return AM's current state for an alert fingerprint.

        Possible values: 'active' (firing), 'suppressed' (inhibited or silenced),
        'unprocessed', None (alert not present — typically resolved).
        """
        resp = await self._client.get(f"{self._base_url}/api/v2/alerts")
        resp.raise_for_status()
        for alert in resp.json():
            if alert.get("fingerprint") == fingerprint:
                return alert.get("status", {}).get("state")
        return None

    async def create_silence(
        self,
        *,
        labels: dict[str, str],
        creator: str,
        comment: str,
        duration_seconds: int,
    ) -> str:
        """Create an AM silence matching the given alert label set.

        AM matchers operate on alert *labels*, not on metadata like
        fingerprint. Pass the alert's full label set (alertname, severity,
        instance, etc.) and we build one matcher per label so the silence
        is as specific as the alert.

        Returns the silence id so it can be expired later (cancel-on-resolve).
        """
        if not labels:
            raise ValueError("create_silence requires at least one label to match against")
        now = dt.datetime.now(tz=dt.timezone.utc)
        ends = now + dt.timedelta(seconds=duration_seconds)
        matchers = [
            {"name": k, "value": v, "isRegex": False, "isEqual": True}
            for k, v in sorted(labels.items())
        ]
        body = {
            "matchers": matchers,
            "startsAt": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "endsAt": ends.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "createdBy": creator,
            "comment": comment,
        }
        resp = await self._client.post(f"{self._base_url}/api/v2/silences", json=body)
        resp.raise_for_status()
        return str(resp.json()["silenceID"])

    async def expire_silence(self, silence_id: str) -> None:
        """Expire (delete) a silence. Used by cancel-on-resolve in reconciler."""
        resp = await self._client.delete(f"{self._base_url}/api/v2/silence/{silence_id}")
        # 404 here means the silence was already gone — fine for cancel-on-resolve.
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    async def list_silences_for_labels(self, labels: dict[str, str]) -> list[dict[str, Any]]:
        """Find active silences whose matcher set fully equals the given labels.

        Used by the reconciler's cancel-on-resolve path: we created the
        silence with `matchers = [{name=k, value=v} for each label]`, so we
        can find it by checking that the silence's matcher set equals the
        full label set we know about.
        """
        if not labels:
            return []
        resp = await self._client.get(f"{self._base_url}/api/v2/silences")
        resp.raise_for_status()
        target = {(k, v) for k, v in labels.items()}
        out = []
        for silence in resp.json():
            if silence.get("status", {}).get("state") == "expired":
                continue
            silence_set = {
                (m.get("name"), m.get("value"))
                for m in silence.get("matchers", [])
                if not m.get("isRegex")
            }
            if silence_set == target:
                out.append(silence)
        return out
