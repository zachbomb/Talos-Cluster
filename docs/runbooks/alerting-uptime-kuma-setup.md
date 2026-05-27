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

## Step 2 — Create an HTTP-keyword monitor for Watchdog

**Design note (2026-05-27 pivot):** the original design pushed Watchdog from AM
→ Kuma's `/api/push/<token>`. That endpoint is GET-only and rejected every AM
POST with 404, causing `AlertmanagerFailedToSendAlerts` / `…ClusterFailedToSendAlerts`
to flap at 98% webhook failure. Pivoted to Kuma polling AM directly — same
sink-independence (Kuma is the only thing watching AM), no transport mismatch.

1. uptime-kuma UI → Add New Monitor.
2. Type: **HTTP(s) - Keyword**.
3. Friendly name: `cluster-watchdog` (matches R18a label).
4. URL: `http://kube-prometheus-stack-alertmanager.kube-prometheus-stack.svc.cluster.local:9093/api/v2/alerts?filter=alertname%3DWatchdog`
5. Method: **GET**.
6. Keyword: `Watchdog` (must appear in the AM JSON response while the alert is firing).
7. Heartbeat Interval: **60s** (matches the rule's evaluation cadence).
8. Retry Interval: **60s**.
9. Maximum Retries: **3** (≈3 consecutive misses → alert — ≈3-4min detection floor).
10. Resend notification: **1** (re-page once if still down).
11. Save.

When Alertmanager is healthy, the Watchdog rule is always firing → the keyword is
always present in the response → Kuma sees "up". When AM is unreachable or has
silenced/stopped routing alerts, the keyword goes missing → Kuma fires Pushover.

## Step 3 — (Nothing to wire on AM side)

In the old push design AM had a `watchdog-uptime-kuma` receiver pointing at the
Kuma push URL. Under the polling design AM is the *target*, not the source:
the Watchdog alert routes to `"null"` in AlertmanagerConfig and Kuma observes
it via the `/api/v2/alerts` endpoint.

If migrating from an existing push-based setup, remove the
`watchdog-uptime-kuma` receiver and the `watchdog-uptime-kuma-url` key from
`alertmanager-secret.secret.yaml` — both are dead code under the polling design.

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
