"""Env-var configuration via pydantic-settings."""
from __future__ import annotations

import json

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    discord_app_public_key: str = Field(..., min_length=64)
    discord_bot_token: str = Field(..., min_length=1)
    discord_channel_id: str = Field(..., min_length=1)
    discord_api_base: str = "https://discord.com/api/v10"

    operator_allowlist: list[str] = Field(default_factory=list)

    hitl_replay_secret_current: str = Field(..., min_length=32)
    hitl_replay_secret_prior: str | None = None
    current_key_id: str = "v1"
    prior_key_id: str | None = None

    alertmanager_url: str = (
        "http://kube-prometheus-stack-alertmanager.kube-prometheus-stack.svc.cluster.local:9093"
    )

    kube_namespace: str = "alert-remediation"
    playbook_registry_path: str = "/etc/hitl/playbook-registry.yaml"
    known_hosts_path: str = "/etc/hitl/udm-known-hosts"

    state_db_path: str = "/var/lib/hitl/state.db"
    timestamp_window_seconds: int = 60
    discord_rate_limit_per_second: float = 4.0
    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 10.0
    http_max_retries: int = 3

    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080

    @field_validator("operator_allowlist", mode="before")
    @classmethod
    def _parse_allowlist(cls, v: object) -> list[str]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as exc:  # pragma: no cover - validation
                raise ValueError(f"OPERATOR_ALLOWLIST must be a JSON array: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("OPERATOR_ALLOWLIST must be a JSON array")
            return [str(item) for item in parsed]
        if isinstance(v, list):
            return [str(item) for item in v]
        return []


def get_settings() -> Settings:
    """Factory used by FastAPI Depends and tests."""
    return Settings()  # type: ignore[call-arg]
