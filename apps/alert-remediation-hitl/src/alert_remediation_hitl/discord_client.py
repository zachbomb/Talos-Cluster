"""Discord Bot API client + Ed25519 signature verification + rate limit.

Signature verification uses raw request body bytes — the FastAPI handler in
main.py MUST take `request: Request` only (no Pydantic body model) and read
`await request.body()` first. Verifying the parsed/re-serialized body would
fail because Discord signs the original byte sequence.

Rate limit: local async token bucket at the configured req/s. Honors 429
Retry-After. The webhook handler in main.py queues bot posts asynchronously
so AM webhooks always get 200 even when Discord is rate-limiting.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignatureCheck:
    ok: bool
    reason: str | None = None
    clock_skew_ms: int | None = None


def verify_signature(
    *,
    raw_body: bytes,
    signature_hex: str | None,
    timestamp: str | None,
    public_key_hex: str,
    timestamp_window_seconds: int = 60,
    now_seconds: float | None = None,
) -> SignatureCheck:
    """Verify Discord interaction signature against raw body bytes.

    Symmetric ±N second window — rejects timestamps both in the past AND
    future relative to wall-clock. The future-direction check catches
    one-sided implementations like `now - ts > 60` that silently accept
    future-skewed signatures.
    """
    if not signature_hex or not timestamp:
        return SignatureCheck(False, "missing_headers")

    try:
        ts_int = int(timestamp)
    except ValueError:
        return SignatureCheck(False, "timestamp_unparseable")

    now = now_seconds if now_seconds is not None else time.time()
    skew_seconds = now - ts_int
    skew_ms = int(skew_seconds * 1000)
    if abs(skew_seconds) > timestamp_window_seconds:
        return SignatureCheck(False, "timestamp_outside_window", clock_skew_ms=skew_ms)

    try:
        verify_key = VerifyKey(bytes.fromhex(public_key_hex))
        verify_key.verify(timestamp.encode("utf-8") + raw_body, bytes.fromhex(signature_hex))
    except (BadSignatureError, ValueError):
        return SignatureCheck(False, "signature_mismatch", clock_skew_ms=skew_ms)

    return SignatureCheck(True, clock_skew_ms=skew_ms)


class _TokenBucket:
    """Simple async token bucket — N tokens per second, burst = N."""

    def __init__(self, rate_per_second: float):
        self.rate = rate_per_second
        self.tokens = rate_per_second
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        # Iterative loop — recursion would risk stack overflow under sustained
        # rate-limit waits.
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
                self.last_refill = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            await asyncio.sleep(wait)


class DiscordClient:
    """Thin Discord Bot API client with rate-limit + 429 retry handling."""

    def __init__(
        self,
        *,
        bot_token: str,
        api_base: str,
        rate_limit_per_second: float,
        connect_timeout: float,
        read_timeout: float,
        max_retries: int,
    ):
        self._bot_token = bot_token
        self._api_base = api_base.rstrip("/")
        self._bucket = _TokenBucket(rate_limit_per_second)
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=read_timeout),
            headers={"Authorization": f"Bot {bot_token}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._api_base}{path}"
        for attempt in range(self._max_retries + 1):
            await self._bucket.acquire()
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(2**attempt * 0.1)
                continue
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                _LOGGER.warning("Discord 429 — backing off %s s (attempt %d)", retry_after, attempt)
                await asyncio.sleep(retry_after)
                continue
            return resp
        return resp  # type: ignore[unreachable]

    async def post_button_message(
        self,
        *,
        channel_id: str,
        content: str,
        custom_id_prefix: str,
        fingerprint: str,
    ) -> str:
        """Post a message with three action-row buttons (Approve/Snooze/Ignore).
        Returns the Discord message id (used as correlation_id).
        """
        components = [
            {
                "type": 1,  # action row
                "components": [
                    {
                        "type": 2,  # button
                        "style": 3,  # green / success
                        "label": "Approve",
                        "custom_id": f"{custom_id_prefix}:approve:{fingerprint}",
                    },
                    {
                        "type": 2,
                        "style": 2,  # grey / secondary
                        "label": "Snooze 1h",
                        "custom_id": f"{custom_id_prefix}:snooze:{fingerprint}",
                    },
                    {
                        "type": 2,
                        "style": 4,  # red / danger
                        "label": "Ignore",
                        "custom_id": f"{custom_id_prefix}:ignore:{fingerprint}",
                    },
                ],
            }
        ]
        body = {"content": content, "components": components}
        resp = await self._request(
            "POST", f"/channels/{channel_id}/messages", json=body
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["id"])

    async def edit_message(
        self,
        *,
        channel_id: str,
        message_id: str,
        content: str | None = None,
        disable_components: bool = False,
    ) -> None:
        """Edit an existing message (e.g., to mark Recovered ✓ or disable buttons).

        Requires the bot's OAuth permissions to include `Manage Messages` on the
        target channel — the 15-min interaction-token edit endpoint expires
        before most playbook outcomes (Per Phase 3 Prerequisites runbook).
        """
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if disable_components:
            body["components"] = []
        resp = await self._request(
            "PATCH", f"/channels/{channel_id}/messages/{message_id}", json=body
        )
        resp.raise_for_status()

    async def respond_to_interaction(
        self,
        *,
        interaction_id: str,
        interaction_token: str,
        response_type: int = 6,  # 6 = DEFERRED_UPDATE_MESSAGE
        content: str | None = None,
        ephemeral: bool = False,
    ) -> None:
        """Respond to a Discord interaction. Type 6 acks without editing.
        Use type 4 (CHANNEL_MESSAGE_WITH_SOURCE) when sending an ephemeral
        "Not authorized" or "Already executed" reply.
        """
        body: dict[str, Any] = {"type": response_type}
        if content is not None:
            data: dict[str, Any] = {"content": content}
            if ephemeral:
                data["flags"] = 64  # EPHEMERAL
            body["data"] = data
        resp = await self._request(
            "POST",
            f"/interactions/{interaction_id}/{interaction_token}/callback",
            json=body,
        )
        resp.raise_for_status()


# Helper used by main.py — Discord Pings are pure type-1 responses.
async def respond_pong(send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    await send({"type": 1})
