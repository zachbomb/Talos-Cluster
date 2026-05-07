---
title: Cluster alerting framework with human-in-the-loop Discord remediation
type: feat
status: active
date: 2026-05-07
---

# Cluster alerting framework with human-in-the-loop Discord remediation

## Summary

Stand up a cluster-wide alerting framework: enable Prometheus Alertmanager, route alerts to Discord through two receivers (direct webhook for critical, Notifiarr-relay for warning/info), and add a human-in-the-loop remediation channel where actionable alerts post Approve / Snooze / Ignore buttons in Discord and clicking Approve triggers a scoped cluster action via an in-cluster handler. BGP session health is the inaugural alert + remediation pair; future alerts plug into the framework as additive PRs.

---

## Problem Frame

Today, Prometheus is scraping cluster metrics including `cilium_bgp_control_plane_session_state`, but Alertmanager is `enabled: false` in the kube-prometheus-stack helm-release — there is no alerting pipeline. When BGP between Cilium and UDM-SE went down on 2026-05-06 due to a 0-byte `on_boot.d` script after a UDM reboot, the failure was discovered only when VPN clients reported losing access to LB IPs. UDM-side cron healthcheck (Layer 1) and uptime-kuma TCP probe (Layer 2 / Path A) cover fast failure detection, but neither offers metric-aware coverage or an interactive recovery path.

The work proposes Layer 2 / Path B of the defense pyramid: a structured alerting framework with HITL remediation. Critical alerts must reach the operator without a single point of failure; non-critical alerts get richer formatting via the existing Notifiarr instance; and alerts that have a known remediation playbook post that playbook as a one-click Discord action so recovery is auditable, scoped (least-privilege RBAC), and not silently autonomous.

---

## Requirements

- R1. Stand up Prometheus Alertmanager (currently `enabled: false` in `clusters/main/kubernetes/system/kube-prometheus-stack/app/helm-release.yaml`) with persistent storage for alert state across restarts.
- R2. Configure two Alertmanager receivers: a direct Discord webhook for `critical` severity, and a Notifiarr-relay receiver for `warning` and `info` severities.
- R3. Implement a severity-based routing tree such that critical alerts bypass the Notifiarr path entirely (single-point-of-failure mitigation).
- R4. Define a three-level severity taxonomy and apply it consistently to every PrometheusRule: **critical** (infra down, page-worthy), **warning** (degraded, action within hours), **info** (FYI, no action).
- R5. Ship a PrometheusRule for BGP session health that fires when `cilium_bgp_control_plane_session_state != 1` for ≥ 60s. Severity = critical.
- R6. Provide a human-in-the-loop remediation channel: alerts with a registered remediation playbook post Approve / Snooze / Ignore buttons in Discord; clicking Approve triggers the playbook through an in-cluster handler.
- R7. The remediation handler must run with a scoped Kubernetes ServiceAccount per playbook (least privilege; never `cluster-admin`).
- R8. Approval authorization: only specific Discord user ID(s) (operator allowlist) can trigger remediation actions; clicks from unauthorized users are rejected and logged.
- R9. Audit trail: every fire/approve/snooze/ignore event and every remediation outcome (succeeded/failed/timed out) is logged to Loki for queryable history.
- R10. Provide a remediation playbook for the BGP alert that re-runs `/data/on_boot.d/15-cluster-bgp.sh` on UDM-SE — manual fast-path recovery without waiting for the 5-minute cron.
- R11. Internal-only ingress for Alertmanager UI (and the HITL receiver UI if applicable), gated by the existing `internal-secure-chain` middleware.
- R12. All Discord webhook URLs, Notifiarr endpoint URLs, Discord bot tokens, and UDM SSH credentials must be stored as SOPS-encrypted Kubernetes Secrets — never in `clusterenv.yaml` or `clustersettings.secret.yaml` plaintext.

---

## Scope Boundaries

### Deferred for later

- Concrete PrometheusRules and remediation playbooks beyond BGP. Each new alert + optional playbook lands as a separate PR plugged into the framework.
- Email, SMS, mobile push, or PagerDuty notification channels.
- Multi-cluster Alertmanager federation.
- Custom Alertmanager UI or chatops queries beyond what the chosen receiver provides.

### Outside this product's identity

- Fully autonomous remediation that runs without human approval. The cron BGP healthcheck on UDM-SE remains the only no-approval auto-fix in the system; everything in this framework requires explicit Discord approval.
- A general-purpose chatops bot. The Discord interaction surface is alert-centric (Approve / Snooze / Ignore on alerts that arrive); not a free-form command interface for cluster operations.
- Replacement of the uptime-kuma TCP probe (Path A from the defense pyramid). Path A and Path B coexist; uptime-kuma provides fast layer-3 monitoring, this framework provides metric-aware deeper coverage with optional HITL action.

### Deferred to Follow-Up Work

- Audit log dashboards in Grafana (Loki has the data; the dashboard design is its own work).
- Alert noise tuning: this framework will likely surface false positives once live; tuning thresholds and group-wait values is iterative and lives outside this initial implementation.
- Documentation for adding new alerts + playbooks once the framework lands (a `docs/runbooks/adding-an-alert.md` or similar).

---

## Key Decisions

- **Dual-receiver routing (direct + Notifiarr) instead of single-channel**: Notifiarr enriches with app-aware cards but adds a dependency. Routing critical alerts direct removes Notifiarr from the SPOF chain for incidents that genuinely require immediate attention; warning/info goes through Notifiarr for richer formatting where small delays don't matter.
- **Framework-first scope (with BGP as proof-of-concept) instead of BGP-only**: future alerts are inevitable. Building the framework once now means each subsequent alert is a small additive PR rather than re-litigating receiver/routing decisions.
- **HITL via Discord buttons instead of fully autonomous or fully manual**: fully autonomous risks cascading failure when a misfiring alert triggers a destructive remediation; fully manual loses the speed advantage of having the runbook codified. Discord buttons give a deliberate-but-fast path with a human in every loop.
- **Build-vs-buy lean toward Robusta**: Robusta is the canonical OSS Prometheus playbook engine with native HITL support, a helm chart, and Discord integration. Lower ops burden than a hand-rolled webhook handler. Validate the fit during planning; if Robusta is too heavy or its Discord interactive component support is incomplete, fall back to a small custom service.
- **Secrets in SOPS-encrypted K8s Secrets, never `clusterenv`**: webhook URLs and bot tokens are credential-equivalent and should not live in the variable-substitution ConfigMap. The repo's existing `*.secret.yaml` SOPS pattern is the right home.
- **Per-playbook ServiceAccounts (not a single shared one)**: a misconfigured BGP-recovery playbook should not be able to delete pods cluster-wide. Each playbook gets only the RBAC verbs/resources it explicitly needs.

---

## Outstanding Questions

### Resolved during brainstorm

- *Should we use Notifiarr or a direct webhook?* → Both, severity-routed.
- *Should we cover only BGP or build a framework?* → Framework now, BGP as POC.
- *Should remediation be autonomous, manual, or HITL?* → HITL via Discord buttons.

### Deferred to planning

- **Robusta fit**: confirm Robusta's Discord interactive components support is mature enough; if not, scope a small custom receiver. The spike should be small (~30 min) and lives in the planning phase.
- **Severity classification per future alert**: the taxonomy is defined here; assigning severity to future PrometheusRules is per-rule work in their respective PRs.
- **Group-wait, repeat-interval, group-by labels** for Alertmanager routes: defaults will be sensible (5s wait, 4h critical repeat, 12h warning repeat, group by `alertname`+`severity`) but final tuning is implementation-time and revisited after live noise feedback.
- **Audit log retention in Loki**: rely on Loki's existing retention policy; no plan-time decision needed unless retention turns out to be insufficient.
- **Does Robusta need its own ingress, or only Alertmanager?** Implementation-time question depending on whether Robusta exposes a UI we want to reach.
- **UDM SSH credential storage shape**: SOPS Secret shape (key file vs password) decided at planning time based on UDM's current SSH config.

---

## Sources & References

- Companion plan: `docs/plans/2026-05-05-002-feat-cilium-l2-announcements-plan.md` (Phase A / Cilium L2 work, of which this alerting layer is the monitoring follow-up)
- UDM persistence script (Layer 1 of defense pyramid): `docs/network/udm-se/15-cluster-bgp.sh`
- BGP setup doc (cluster side): `docs/network/udm-se-bgp.md`
- Cilium BGP metric exposed today (verified live): `cilium_bgp_control_plane_session_state`, scraped via `cilium-agent` ServiceMonitor in `kube-system`
- Existing TrueCharts pattern for SOPS Secrets: see any `*.secret.yaml` under `clusters/main/kubernetes/`
- Robusta upstream: https://docs.robusta.dev/
- Notifiarr running in cluster: `media/notifiarr` namespace
