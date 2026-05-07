# uptime-kuma: Watchdog + meta-monitoring setup

This runbook configures uptime-kuma as the sink-independent backstop for the
Alertmanager pipeline. uptime-kuma alerts via Pushover (or ntfy) when:

1. **Watchdog heartbeats stop** — Alertmanager or Prometheus is down.
2. **Prometheus health probe fails** — Prometheus itself is unreachable.
3. **Notifiarr health probe fails** — the warning/info path is broken.

All three are independent of the Discord/Notifiarr/Alertmanager sink, satisfying
[R18 a/b/c in the brainstorm](../brainstorms/2026-05-07-cluster-alerting-hitl-requirements.md).

## Prerequisites

- uptime-kuma is running at `http://uptime-kuma.monitoring.svc.cluster.local:3001`
  (see `clusters/main/kubernetes/system/uptime-kuma/`).
- Pushover or ntfy account with API credentials.
- Access to the uptime-kuma admin UI (LAN-internal, behind `internal-secure-chain`).

## Step 1 — Create a notification channel

1. uptime-kuma UI → Settings (gear icon) → Notifications → Setup Notification.
2. Choose **Pushover** (or **ntfy**).
3. Populate credentials:
   - Pushover: `User Key`, `Application Token`, optional sound (e.g., `siren`).
   - ntfy: server URL (`https://ntfy.sh` for hosted), topic name (a private string).
4. Click **Test** to verify the notification reaches your phone.
5. Save. Default-apply to new monitors: **YES**.

This channel is the cluster's last-resort alert path. **Do NOT use the Discord webhook**
here — it would defeat the sink-independence.

## Step 2 — Create a push monitor for Watchdog

1. uptime-kuma UI → Add New Monitor.
2. Type: **Push**.
3. Friendly name: `cluster-watchdog` (matches the brainstorm's R18a label).
4. Heartbeat Interval: **60s** (matches the rule's evaluation cadence).
5. Maximum Retries: **3** (≈3 missed heartbeats before alert — ≈3-4min detection floor).
6. Resend notification: **1** (re-page once if still down).
7. Save.
8. Copy the **push URL** from the monitor's detail page — it looks like:
   `http://uptime-kuma.monitoring.svc.cluster.local:3001/api/push/<TOKEN>?status=up&msg=OK&ping=`.

## Step 3 — Wire the push URL into Alertmanager

The push URL must reach the Watchdog AM route. Decrypt the secret and paste:

```bash
sops clusters/main/kubernetes/system/kube-prometheus-stack/app/alertmanager-secret.secret.yaml
# Replace REPLACE_ME_UPTIME_KUMA_PUSH_URL with the push URL from Step 2.
# Save (sops re-encrypts on save).
```

Commit + push. Flux reconciles, AM picks up the new URL, and within ~1 minute
heartbeats start arriving in uptime-kuma.

## Step 4 — Create a Prometheus health probe (R18c)

1. uptime-kuma UI → Add New Monitor.
2. Type: **HTTP(s)**.
3. Friendly name: `prometheus-health`.
4. URL: `http://kube-prometheus-stack-prometheus.kube-prometheus-stack.svc.cluster.local:9090/-/healthy`.
5. Heartbeat Interval: **30s**.
6. Retry Interval: **30s**.
7. Maximum Retries: **3** (90s detection floor).
8. Save.

This probes Prometheus directly — covers the failure mode where Prometheus is
down so the Watchdog rule itself never fires.

## Step 5 — Create a Notifiarr health probe (R18b)

1. uptime-kuma UI → Add New Monitor.
2. Type: **HTTP(s)**.
3. Friendly name: `notifiarr-health`.
4. URL: `http://notifiarr.media.svc.cluster.local:5454/healthz` (or whichever endpoint
   Notifiarr exposes — `/api/version` works as a fallback).
5. Heartbeat Interval: **30s**.
6. Retry Interval: **30s**.
7. Maximum Retries: **4** (≈2-min detection floor — matches R18b's 2-min `for:`).
8. Save.

This replaces the rev-1 plan's blackbox-exporter dependency. Routing
critical-severity Notifiarr-down via uptime-kuma → Pushover satisfies R18b's
"warning/info path is silently broken" intent without deploying a separate
exporter.

## Verification

- Inside uptime-kuma UI, all three monitors (`cluster-watchdog`, `prometheus-health`, `notifiarr-health`) should be green within 5 min of setup.
- Manual test: scale Alertmanager to 0 replicas — Watchdog notification fires
  via Pushover/ntfy within 5 min.
- Manual test: scale Notifiarr to 0 replicas — `notifiarr-health` notification
  fires within ~2 min.
- All notifications should NOT route through Discord — that's the entire point
  of sink independence.

## What this DOES NOT replace

- The R5 BGP PrometheusRule (Phase 2) — that fires through the regular AM path
  (Discord direct via `discord-critical`). uptime-kuma's old TCP/179 probe
  remains as Layer 2A backstop, not the primary BGP alert.
- Discord/Notifiarr-routed alerts for normal operational concerns. uptime-kuma
  exists ONLY to catch the case where the regular alerting pipeline itself is
  down.

## Notes

- uptime-kuma push monitor URLs are **secrets** (anyone with the URL can post
  fake heartbeats). Store the URL in the SOPS-encrypted `alertmanager-secret`,
  not in plain manifests.
- If you migrate uptime-kuma off-cluster (e.g., to a Proxmox LXC) for true
  fate-isolation, update all four monitor URLs and the AM webhook URL to point
  at the new endpoint. See plan's "Deferred to Follow-Up Work".
