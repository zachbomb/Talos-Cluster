# alert-remediation-hitl

In-cluster human-in-the-loop receiver for Prometheus Alertmanager. Posts
Discord button messages for alerts carrying a `remediation: <playbook>` label;
on Approve, launches a Kubernetes Job to run the named playbook.

Lives at `clusters/main/kubernetes/system/alert-remediation/` (manifests).
This directory holds the receiver source.

Plan: `docs/plans/2026-05-07-001-feat-alerting-hitl-framework-plan.md`
Origin: `docs/brainstorms/2026-05-07-cluster-alerting-hitl-requirements.md`

## Modules

| Module | Purpose |
|---|---|
| `main.py` | FastAPI app with lifespan-managed reconciler + `/interactions`, `/webhook/<receiver>`, `/health`, `/ready`, `/metrics`. |
| `settings.py` | Env-var configuration via pydantic-settings. |
| `state.py` | SQLite (WAL) state machine with `INSERT ON CONFLICT` + guarded transitions. |
| `nonce.py` | HMAC-SHA256(server-secret, fingerprint \|\| server_wall_clock_ms). Key rotation via `key_id` storage. |
| `discord_client.py` | Bot API: signature verify, post/edit message, action-row buttons, async rate-limit (token bucket + 429 Retry-After). |
| `alertmanager_client.py` | AM API: silence create/expire, alert state query. |
| `playbooks.py` | YAML playbook registry + K8s Job dispatcher. |
| `reconciler.py` | Startup reconciliation per R14: Snoozed→AM check, Approved→Job adoption, orphan-Pending detection. |
| `audit.py` | Structured JSON audit logging to stdout (Loki via Promtail/Alloy). |

## Local development

```bash
pip install -e '.[test]'
pytest
```

## Container build

The GitHub Actions workflow at `.github/workflows/alert-remediation-image.yaml` (U12) builds
and pushes to `ghcr.io/<owner>/alert-remediation-hitl@sha256:<digest>` on push
to `main`. The deployment manifest references the digest, never `:latest`.

## Configuration (env vars)

| Var | Description |
|---|---|
| `DISCORD_APP_PUBLIC_KEY` | Application public key (ConfigMap, NOT Secret — public material). |
| `DISCORD_BOT_TOKEN` | Bot token (Secret). |
| `DISCORD_CHANNEL_ID` | Target channel for alert button messages. |
| `OPERATOR_ALLOWLIST` | JSON array of allowed Discord user IDs (Secret). |
| `HITL_REPLAY_SECRET_CURRENT` | Current HMAC key (Secret). |
| `HITL_REPLAY_SECRET_PRIOR` | Prior HMAC key during 24h rotation overlap (Secret, optional). |
| `CURRENT_KEY_ID` / `PRIOR_KEY_ID` | Key identifiers for nonce verify routing. |
| `ALERTMANAGER_URL` | In-cluster AM endpoint. |
| `KUBE_NAMESPACE` | Namespace for Job creation (default `alert-remediation`). |
| `PLAYBOOK_REGISTRY_PATH` | Path to `playbook-registry.yaml` ConfigMap mount. |
| `KNOWN_HOSTS_PATH` | Path to UDM-SE known_hosts ConfigMap mount. |
| `STATE_DB_PATH` | SQLite DB path (default `/var/lib/hitl/state.db`). |
| `TIMESTAMP_WINDOW_SECONDS` | Symmetric Discord interaction timestamp window (default 60). |
| `LOG_LEVEL` | `INFO` / `DEBUG`. |
| `PORT` / `HOST` | uvicorn bind address. |
