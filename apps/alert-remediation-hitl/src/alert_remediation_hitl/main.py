"""FastAPI app for the HITL receiver.

Endpoints:
  POST /interactions       — Discord callback (signature-verified, raw body).
  POST /webhook/<receiver> — Alertmanager webhook (registers Pending state + posts buttons).
  GET  /health             — liveness; includes SQLite SELECT 1.
  GET  /ready              — readiness; 503 until lifespan/reconciler completes.
  GET  /metrics            — Prometheus counters.

Security: handler signatures intentionally avoid Pydantic body models on
endpoints where signature verification needs raw bytes (`/interactions`).
Reading `await request.body()` first is mandatory — see plan U11 +
docs/brainstorms/2026-05-07-cluster-alerting-hitl-requirements.md (R8).
"""
from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from . import audit, discord_client, nonce, state
from .alertmanager_client import AlertmanagerClient
from .discord_client import DiscordClient, verify_signature
from .nonce import NonceKey
from .playbooks import JobDispatcher, PlaybookRegistry
from .reconciler import Reconciler
from .settings import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

INTERACTION_PING = 1
INTERACTION_MESSAGE_COMPONENT = 3
RESPONSE_PONG = 1
RESPONSE_DEFERRED_UPDATE = 6
RESPONSE_CHANNEL_MESSAGE = 4

CUSTOM_ID_PREFIX = "hitl"
SNOOZE_DURATION_SECONDS = 3600  # 1 hour, fixed (origin R15)


# ----------------------------------------------------------------- counters
class Counters:
    """Plain dict-backed Prometheus counter shim — keeps deps minimal."""

    def __init__(self) -> None:
        self.interactions_total: dict[str, int] = {}
        self.state_transitions_total: dict[tuple[str, str], int] = {}
        self.playbook_runs_total: dict[tuple[str, str], int] = {}
        self.replay_rejected_total = 0
        self.pending_orphaned_total = 0
        self.signature_rejected_total: dict[str, int] = {}

    def render(self) -> str:
        lines: list[str] = []
        lines.append("# HELP hitl_interactions_total Discord interactions handled by result.")
        lines.append("# TYPE hitl_interactions_total counter")
        for k, v in sorted(self.interactions_total.items()):
            lines.append(f'hitl_interactions_total{{result="{k}"}} {v}')
        lines.append("# HELP hitl_state_transitions_total HITL state machine transitions.")
        lines.append("# TYPE hitl_state_transitions_total counter")
        for (src, dst), v in sorted(self.state_transitions_total.items()):
            lines.append(f'hitl_state_transitions_total{{from="{src}",to="{dst}"}} {v}')
        lines.append("# HELP hitl_playbook_runs_total Playbook executions by outcome.")
        lines.append("# TYPE hitl_playbook_runs_total counter")
        for (pb, outcome), v in sorted(self.playbook_runs_total.items()):
            lines.append(
                f'hitl_playbook_runs_total{{playbook="{pb}",outcome="{outcome}"}} {v}'
            )
        lines.append("# HELP hitl_replay_rejected_total Replay attempts rejected.")
        lines.append("# TYPE hitl_replay_rejected_total counter")
        lines.append(f"hitl_replay_rejected_total {self.replay_rejected_total}")
        lines.append("# HELP hitl_pending_orphaned_total Orphan-Pending rows detected.")
        lines.append("# TYPE hitl_pending_orphaned_total counter")
        lines.append(f"hitl_pending_orphaned_total {self.pending_orphaned_total}")
        lines.append("# HELP hitl_signature_rejected_total Discord signature verifications rejected.")
        lines.append("# TYPE hitl_signature_rejected_total counter")
        for k, v in sorted(self.signature_rejected_total.items()):
            lines.append(f'hitl_signature_rejected_total{{reason="{k}"}} {v}')
        return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ AppState
class AppState:
    """Shared container assembled at lifespan startup."""

    settings: Settings
    store: state.StateStore
    discord: DiscordClient
    am: AlertmanagerClient
    jobs: JobDispatcher | None
    registry: PlaybookRegistry
    counters: Counters
    nonce_keys: list[NonceKey]
    is_ready: bool

    def __init__(self) -> None:
        self.is_ready = False


# ------------------------------------------------------------------ helpers
def _make_nonce_keys(s: Settings) -> list[NonceKey]:
    keys = [NonceKey(s.current_key_id, s.hitl_replay_secret_current.encode("utf-8"))]
    if s.hitl_replay_secret_prior and s.prior_key_id:
        keys.append(NonceKey(s.prior_key_id, s.hitl_replay_secret_prior.encode("utf-8")))
    return keys


def _bump(counter: dict, key: object) -> None:  # type: ignore[type-arg]
    counter[key] = counter.get(key, 0) + 1


def _record_transition(app_state: AppState, src: state.State, dst: state.State) -> None:
    _bump(app_state.counters.state_transitions_total, (src.value, dst.value))


# --------------------------------------------------- /interactions handlers
async def _handle_message_component(
    payload: dict[str, Any],
    *,
    app_state: AppState,
) -> dict[str, Any]:
    """Dispatch an Approve/Snooze/Ignore button click."""
    user = payload.get("member", {}).get("user") or payload.get("user", {})
    user_id = str(user.get("id", "")) if user else ""
    actor = user_id if user_id else "unknown"

    custom_id = payload.get("data", {}).get("custom_id", "")
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != CUSTOM_ID_PREFIX:
        _bump(app_state.counters.interactions_total, "bad_custom_id")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Unrecognized button.", "flags": 64},
        }
    _, action, fingerprint = parts

    if user_id not in app_state.settings.operator_allowlist:
        _bump(app_state.counters.interactions_total, "rejected_unauthorized")
        audit.emit(
            "rejected_unauthorized",
            fingerprint=fingerprint,
            actor=actor,
            outcome="rejected_unauthorized",
            action=action,
        )
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Not authorized.", "flags": 64},
        }

    row = app_state.store.get(fingerprint)
    if row is None:
        _bump(app_state.counters.interactions_total, "stale_no_row")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Stale alert (no state row).", "flags": 64},
        }

    if action == "approve":
        return await _handle_approve(payload, app_state, row, actor)
    if action == "snooze":
        return await _handle_snooze(app_state, row, actor)
    if action == "ignore":
        return await _handle_ignore(app_state, row, actor)
    return {
        "type": RESPONSE_CHANNEL_MESSAGE,
        "data": {"content": f"Unknown action {action}.", "flags": 64},
    }


async def _handle_approve(
    payload: dict[str, Any],
    app_state: AppState,
    row: state.StateRow,
    actor: str,
) -> dict[str, Any]:
    if row.state is state.State.APPROVED and row.nonce is not None:
        # Idempotent double-click — already executed.
        _bump(app_state.counters.interactions_total, "approve_already_executed")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Already executed.", "flags": 64},
        }
    if row.state is not state.State.PENDING:
        _bump(app_state.counters.interactions_total, "approve_not_pending")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": f"Cannot approve from state {row.state.value}.", "flags": 64},
        }
    if not row.playbook:
        _bump(app_state.counters.interactions_total, "approve_no_playbook")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "No playbook bound to this alert.", "flags": 64},
        }
    pb = app_state.registry.get(row.playbook)
    if pb is None:
        _bump(app_state.counters.interactions_total, "approve_unknown_playbook")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": f"Unknown playbook {row.playbook}.", "flags": 64},
        }
    # Generate a fresh nonce + dispatch the Job.
    current_key = app_state.nonce_keys[0]
    n = nonce.generate(row.fingerprint, current_key)
    if app_state.jobs is None:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Job dispatcher unavailable.", "flags": 64},
        }
    job_name = app_state.jobs.create_job(playbook=pb, fingerprint=row.fingerprint)
    transitioned = app_state.store.transition(
        row.fingerprint,
        from_states=[state.State.PENDING],
        to_state=state.State.APPROVED,
        nonce=n.value,
        key_id=n.key_id,
        nonce_created_at_ms=n.created_at_ms,
        job_name=job_name,
    )
    if not transitioned:
        # Race — somebody beat us. Reply stale.
        _bump(app_state.counters.interactions_total, "approve_race")
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "State changed mid-click; refresh.", "flags": 64},
        }
    _record_transition(app_state, state.State.PENDING, state.State.APPROVED)
    _bump(app_state.counters.interactions_total, "approved")
    audit.emit(
        "approved",
        fingerprint=row.fingerprint,
        alertname=row.alertname,
        actor=actor,
        playbook=row.playbook,
        correlation_id=row.correlation_id,
        job_name=job_name,
    )
    return {"type": RESPONSE_DEFERRED_UPDATE}


async def _handle_snooze(
    app_state: AppState,
    row: state.StateRow,
    actor: str,
) -> dict[str, Any]:
    if row.state is not state.State.PENDING:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": f"Cannot snooze from {row.state.value}.", "flags": 64},
        }
    if not row.alert_labels:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "Cannot snooze: no label set recorded for this alert.", "flags": 64},
        }
    silence_id = await app_state.am.create_silence(
        labels=row.alert_labels,
        creator=f"hitl-bot:{actor}",
        comment=f"Snoozed by Discord user {actor} (fingerprint={row.fingerprint})",
        duration_seconds=SNOOZE_DURATION_SECONDS,
    )
    transitioned = app_state.store.transition(
        row.fingerprint,
        from_states=[state.State.PENDING],
        to_state=state.State.SNOOZED,
        snooze_until=silence_id,
    )
    if not transitioned:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "State changed mid-click; refresh.", "flags": 64},
        }
    _record_transition(app_state, state.State.PENDING, state.State.SNOOZED)
    _bump(app_state.counters.interactions_total, "snoozed")
    audit.emit(
        "snoozed",
        fingerprint=row.fingerprint,
        alertname=row.alertname,
        actor=actor,
        correlation_id=row.correlation_id,
        silence_id=silence_id,
    )
    return {"type": RESPONSE_DEFERRED_UPDATE}


async def _handle_ignore(
    app_state: AppState,
    row: state.StateRow,
    actor: str,
) -> dict[str, Any]:
    if row.state is not state.State.PENDING:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": f"Cannot ignore from {row.state.value}.", "flags": 64},
        }
    transitioned = app_state.store.transition(
        row.fingerprint,
        from_states=[state.State.PENDING],
        to_state=state.State.IGNORED,
    )
    if not transitioned:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {"content": "State changed mid-click; refresh.", "flags": 64},
        }
    _record_transition(app_state, state.State.PENDING, state.State.IGNORED)
    _bump(app_state.counters.interactions_total, "ignored")
    audit.emit(
        "ignored",
        fingerprint=row.fingerprint,
        alertname=row.alertname,
        actor=actor,
        correlation_id=row.correlation_id,
    )
    return {"type": RESPONSE_DEFERRED_UPDATE}


# ------------------------------------------------------------------- factory
def create_app(*, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    audit.configure_root_logger(settings.log_level)

    app_state = AppState()
    app = FastAPI(title="alert-remediation-hitl")

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_state.settings = settings
        app_state.counters = Counters()
        app_state.store = state.StateStore(settings.state_db_path)
        app_state.discord = DiscordClient(
            bot_token=settings.discord_bot_token,
            api_base=settings.discord_api_base,
            rate_limit_per_second=settings.discord_rate_limit_per_second,
            connect_timeout=settings.http_connect_timeout_seconds,
            read_timeout=settings.http_read_timeout_seconds,
            max_retries=settings.http_max_retries,
        )
        app_state.am = AlertmanagerClient(
            base_url=settings.alertmanager_url,
            connect_timeout=settings.http_connect_timeout_seconds,
            read_timeout=settings.http_read_timeout_seconds,
        )
        app_state.registry = PlaybookRegistry(settings.playbook_registry_path)
        app_state.registry.load()
        try:
            app_state.jobs = JobDispatcher(settings.kube_namespace)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Job dispatcher init failed: %s", exc)
            app_state.jobs = None
        app_state.nonce_keys = _make_nonce_keys(settings)

        async def _retry_pending_post(row: state.StateRow) -> bool:
            try:
                content = (
                    f"⚠️ Alert pending review: **{row.alertname or row.fingerprint}**\n"
                    f"Fingerprint: `{row.fingerprint}`"
                )
                msg_id = await app_state.discord.post_button_message(
                    channel_id=settings.discord_channel_id,
                    content=content,
                    custom_id_prefix=CUSTOM_ID_PREFIX,
                    fingerprint=row.fingerprint,
                )
                app_state.store.set_correlation_id(row.fingerprint, msg_id)
                return True
            except Exception:  # noqa: BLE001
                return False

        reconciler = Reconciler(
            store=app_state.store,
            am_client=app_state.am,
            job_dispatcher=app_state.jobs,
            retry_pending_post=_retry_pending_post,
        )
        await reconciler.run()
        app_state.is_ready = True
        _LOGGER.info("Lifespan complete; HTTP listener ready.")
        try:
            yield
        finally:
            app_state.is_ready = False
            await app_state.discord.aclose()
            await app_state.am.aclose()
            app_state.store.close()

    app.router.lifespan_context = lifespan

    # ---------------------------------------------------------- endpoints

    @app.get("/health")
    async def health() -> Response:
        if not app_state.store.health_check():
            return Response(content="unhealthy", status_code=503)
        return Response(content="ok", status_code=200)

    @app.get("/ready")
    async def ready() -> Response:
        if not app_state.is_ready:
            return Response(content="not ready", status_code=503)
        return Response(content="ready", status_code=200)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(
            content=app_state.counters.render(),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/interactions")
    async def interactions(request: Request) -> Response:
        # CRITICAL — must read raw bytes BEFORE any parse so signature verify
        # is cryptographically meaningful. Do NOT add a Pydantic body model.
        raw_body = await request.body()
        sig = request.headers.get("X-Signature-Ed25519")
        ts = request.headers.get("X-Signature-Timestamp")
        check = verify_signature(
            raw_body=raw_body,
            signature_hex=sig,
            timestamp=ts,
            public_key_hex=settings.discord_app_public_key,
            timestamp_window_seconds=settings.timestamp_window_seconds,
        )
        if not check.ok:
            _bump(app_state.counters.signature_rejected_total, check.reason or "unknown")
            audit.emit(
                "signature_rejected",
                outcome=check.reason,
                clock_skew_ms=check.clock_skew_ms,
            )
            raise HTTPException(status_code=401, detail="invalid signature")

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc

        kind = payload.get("type")
        if kind == INTERACTION_PING:
            return Response(content=json.dumps({"type": RESPONSE_PONG}), media_type="application/json")
        if kind == INTERACTION_MESSAGE_COMPONENT:
            response = await _handle_message_component(payload, app_state=app_state)
            return Response(content=json.dumps(response), media_type="application/json")
        return Response(content=json.dumps({"type": RESPONSE_PONG}), media_type="application/json")

    @app.post("/webhook/{receiver}")
    async def webhook(receiver: str, request: Request) -> Response:
        payload = await request.json()
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            fingerprint = alert.get("fingerprint")
            if not fingerprint:
                continue
            playbook_name = labels.get("remediation")
            if not playbook_name:
                # No remediation label — receiver doesn't register state for this.
                continue
            app_state.store.upsert_pending(
                fingerprint,
                alertname=labels.get("alertname"),
                playbook=playbook_name,
                correlation_id=None,
                alert_labels=dict(labels),
            )
            try:
                content = (
                    f"⚠️ {labels.get('severity', 'alert').upper()}: "
                    f"**{labels.get('alertname', fingerprint)}**\n"
                    f"{alert.get('annotations', {}).get('summary', '')}\n"
                    f"Fingerprint: `{fingerprint}` · Playbook: `{playbook_name}`"
                )
                msg_id = await app_state.discord.post_button_message(
                    channel_id=settings.discord_channel_id,
                    content=content,
                    custom_id_prefix=CUSTOM_ID_PREFIX,
                    fingerprint=fingerprint,
                )
                app_state.store.set_correlation_id(fingerprint, msg_id)
                audit.emit(
                    "posted",
                    fingerprint=fingerprint,
                    alertname=labels.get("alertname"),
                    playbook=playbook_name,
                    correlation_id=msg_id,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("Failed to post Discord message for %s", fingerprint)
                audit.emit(
                    "post_failed",
                    fingerprint=fingerprint,
                    alertname=labels.get("alertname"),
                    error=str(exc),
                )
        return Response(content="ok", status_code=200)

    return app


# Production app — uvicorn imports this.
app = create_app()


__all__ = ["create_app", "app", "discord_client"]
