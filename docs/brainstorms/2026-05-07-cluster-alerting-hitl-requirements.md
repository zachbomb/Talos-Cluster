---
title: Cluster alerting framework with human-in-the-loop Discord remediation
type: feat
status: active
date: 2026-05-07
revision: 3
---

# Cluster alerting framework with human-in-the-loop Discord remediation

## Summary

Stand up a cluster-wide alerting framework: enable Prometheus Alertmanager, route alerts to Discord through two receivers (direct webhook for critical, Notifiarr-relay for warning/info), and add a human-in-the-loop remediation channel where actionable alerts post Approve / Snooze / Ignore buttons in Discord and clicking Approve triggers a scoped cluster action via an in-cluster handler. Cilium BGP session health is the inaugural alert + remediation pair; future alerts plug into the framework as additive PRs.

---

## Problem Frame

Today, Prometheus is scraping cluster metrics including `cilium_bgp_control_plane_session_state`, but Alertmanager is `enabled: false` in the kube-prometheus-stack helm-release — there is no alerting pipeline. When BGP between Cilium and UDM-SE went down on 2026-05-06 due to a 0-byte `on_boot.d` script after a UDM reboot, the failure was discovered only when VPN clients reported losing access to LB IPs. UDM-side cron healthcheck (Layer 1) and uptime-kuma TCP probe (Layer 2A) cover fast failure detection, but neither offers metric-aware coverage or an interactive recovery path.

The work proposes Layer 2B of the defense pyramid: a structured alerting framework with HITL remediation. Critical alerts must reach the operator without a single point of failure; non-critical alerts get richer formatting via the existing Notifiarr instance; alerts that have a known remediation playbook post that playbook as a one-click Discord action so recovery is auditable, scoped (least-privilege RBAC), and not silently autonomous.

---

## Requirements

### Alertmanager + Routing

- R1. **Alertmanager + persistent storage.** Enable Prometheus Alertmanager (currently `enabled: false`) with a `1Gi` Longhorn PVC, `storageClass: longhorn`. Persistent state must include active silences and notification log so they survive pod restarts. **Acceptance:** create a silence via API, delete the AM pod, confirm the silence is still active after pod recreation.
- R2. **Two receivers.** Configure a direct Discord webhook receiver (`discord-critical`) and a Notifiarr-relay receiver (`notifiarr-default`). Receivers reference webhook URLs via `secretKeyRef` in the AlertmanagerConfig CRD — never `${VAR}` Flux interpolation, since webhook tokens may contain characters that conflict with envsubst.
- R3. **Severity-based routing — exclusive, never duplicating.** The Alertmanager route tree splits by `severity` label: `critical` → `discord-critical` ONLY; `warning` → `notifiarr-default` ONLY; `info` → Loki/Grafana annotations only (per R4, NOT Discord). Routing is mutually exclusive — each alert lands on exactly one receiver, never both. Implemented via `continue: false` on every leaf match (verified by R6's CI guard: a route tree where `continue: true` reaches a Discord receiver fails CI). Routing config: `group_by: [alertname, severity]` (excluding `instance` to coalesce cascade-failures into one notification stream); `group_wait: 30s`; `group_interval: 5m`; `repeat_interval: 4h` for critical, `12h` for warning, `24h` for info.
- R4. **Severity taxonomy with objective rubric.** Three severities — `critical`, `warning`, `info` — with a written decision rubric so future PRs land alerts consistently:
   - **critical**: user-facing impact present *now* AND no auto-recovery path *AND* the operator should respond within minutes (24/7).
   - **warning**: degraded state *or* trending toward failure; operator should respond within hours; auto-recovery may be in progress.
   - **info**: FYI; do not interrupt the operator. **`info` MUST NOT route to Discord** — it routes to Loki/Grafana annotations only. Avoids training the operator to ignore Discord pings.
   - **Flap classification rule:** alerts that transition between firing and resolved 4+ times within a 30-minute window MUST be reclassified down one severity tier (critical → warning, warning → info) for the remainder of that window via a companion `_flapping` rule using `changes(ALERTS_FOR_STATE{...}[30m]) >= 4`. Prevents "alarm fatigue from flapping" anti-pattern where a single intermittent condition produces continuous critical pages.
- R5. **BGP session alert (POC rule).** PrometheusRule firing on `cilium_bgp_control_plane_session_state != 1` with `for: 60s`, labels `severity: critical`, `remediation: bgp-recovery` (see R12 — playbook registration contract). **Acceptance:** stop FRR on UDM-SE; alert reaches the direct Discord webhook within 90s with severity=critical formatting; restore FRR; alert resolves within 60s.
- R6. **Severity-routing + manifest-shape CI guard.** Every PrometheusRule PR must pass two validations: (a) `amtool` routing-tree check — severity in {critical, warning, info}; mis-tagged severity (`warn`, `severity-1`, etc.) fails CI; route exclusivity per R3 (no `continue: true` reaching a Discord receiver); (b) `kubectl apply --dry-run=server` against AlertmanagerConfig CRD shape, since `amtool` validates the in-Alertmanager route format but not the Kubernetes CRD wrapper Flux ships. Both validations together catch the two distinct regression classes (route-logic mistakes and CRD-shape drift) the dual-receiver design is vulnerable to.

### Human-in-the-Loop Remediation

- R7. **HITL receiver with Discord interactive callbacks.** Alerts carrying the `remediation` label post a Discord message with three action buttons — Approve / Snooze / Ignore — generated by an in-cluster handler ("HITL receiver"). Handler receives Discord interaction callbacks, validates them, and triggers playbooks. See R8-R11 for security and R14 for state machine.
- R8. **Discord Ed25519 signature verification (security blocker).** The HITL handler MUST verify the `X-Signature-Ed25519` header against `X-Signature-Timestamp` + body using Discord's published application public key on every interaction request. Unsigned or signature-mismatched requests are rejected with HTTP 401 before any further processing. Without this, R10's user-ID allowlist is bypassable by any forged POST. **Storage:** the application public key is non-sensitive published material — stored in a ConfigMap (`discord-app-public-key`), NOT a Secret. Secret storage would falsely signal sensitivity and trigger SOPS handling for a value Discord publishes openly. The bot token, by contrast, IS sensitive and stays in a SOPS-encrypted Secret (R20).
- R9. **Timestamp replay protection (security blocker).** The HITL handler MUST reject any interaction request whose `X-Signature-Timestamp` is more than 60 seconds older OR more than 60 seconds newer than wall-clock (a symmetric ±60s window, widened from Discord's 5s baseline guidance to absorb realistic NTP drift in a home-lab cluster where `chrony` may drift up to ~1s before re-sync). Pods MUST run with `chrony` synced to a reliable NTP source; if NTP sync is lost for >2min, signature checks fail closed (reject). The 60s window is documented in R17 audit logs as `clock_skew_ms` so drift is observable.
- R10. **Approval authorization.** A SOPS-encrypted Secret holds the operator's Discord user ID(s) ("operator allowlist"). Approve, Snooze, and Ignore are ALL gated to this allowlist (Snooze and Ignore are gated identically to Approve to prevent drive-by silencing of real alerts). Unauthorized clicks reply with an ephemeral Discord message ("Not authorized") AND emit a Loki audit event with `outcome: rejected_unauthorized`. Authorization happens AFTER R8/R9 succeed.
- R11. **HITL endpoint exposure path.** The Discord interaction callback endpoint must be reachable from the public internet (Discord's servers must reach it) — therefore it cannot live behind `internal-secure-chain`. Exposure path:
   - **Hostname:** `discord-hitl.${BASE_DOMAIN}` — this hostname MUST be added to the existing Cloudflare Tunnel ingress rules alongside the current allowlist; the additive nature is the only change to the tunnel config.
   - **Edge (Cloudflare) defenses (composed, not alternatives):** (1) Cloudflare WAF custom rule that gates POST `/interactions` on Ed25519 signature header presence (`http.request.headers["x-signature-ed25519"][0] ne ""` AND `http.request.headers["x-signature-timestamp"][0] ne ""`) — drops unsigned junk before it reaches the cluster; (2) rate-limit rule: 10 req/s per source IP; (3) Cloudflare Bot Management or Turnstile NOT used (Discord doesn't carry a browser fingerprint). IP-range allowlisting at the WAF is **not** specified — Discord does not publish a stable, machine-readable IP range list, so layered signature-header gating + rate-limiting is the actual defensive posture, with R8's Ed25519 verify as the authoritative authentication layer in-cluster.
   - **In-cluster (Traefik) middleware:** `bouncer` (CrowdSec) + a dedicated `discord-callback-chain` (NOT `internal-secure-chain`, which would 403 Discord). The chain explicitly does NOT include `local-whitelist` — the endpoint must accept public-internet sources.
   - Alertmanager UI and any HITL receiver UI are separately behind `internal-secure-chain` for operator access only — they share neither hostname nor middleware chain with the callback endpoint.
- R12. **Playbook registration contract.** A PrometheusRule declares that it has a remediation playbook by setting a `remediation: <playbook-name>` label. The HITL receiver matches the label against a registry of playbooks; only labelled alerts post Approve/Snooze/Ignore buttons. Playbooks are defined as YAML manifests under `clusters/main/kubernetes/system/<receiver-namespace>/playbooks/<name>/{playbook.yaml, rbac.yaml}` co-located. A CI check (kyverno or similar) validates that the ServiceAccount referenced in the playbook exists in the same Kustomization. **This is the framework's primary extensibility seam.**
- R13. **Per-playbook ServiceAccount with RBAC bound to verbs/resources actually needed.** Each playbook has a dedicated ServiceAccount; never `cluster-admin`. The BGP-recovery playbook's SA needs only `Secret/get` for the UDM SSH credential — no `pods/exec`, no `nodes`, no workload-mutation verbs. This SA pattern is documented as the reference for future SSH-only playbooks.
- R14. **HITL state machine.** Each alert instance has one of these states: `Pending` (buttons posted, no click yet) → `Approved` (playbook running) → `Succeeded` / `Failed` / `Timeout` (terminal); `Pending` → `Snoozed` (silenced for fixed duration) → `Pending` (after snooze expires); `Pending` → `Ignored` (terminal-for-this-alert-instance, but Prometheus continues evaluating — Ignored prevents the *current* button cycle from prompting again, not the alert from re-firing on its next evaluation); `Pending` → `Auto-resolved` (alert resolved before any click — buttons disabled, follow-up message posted, subsequent clicks return "stale"). Each transition emits a structured Loki event (R17). **Keying:** state is keyed primarily on Prometheus alert `fingerprint` (the canonical immutable identifier across re-evaluations); `alertname` is denormalized for query convenience but never used as a uniqueness key. Concurrent alerts have independent state. Approve is **idempotent** per alert instance: the first click runs the playbook; subsequent clicks (network blip, double-click) acknowledge "already executed" without re-running.
   - **Durability across restart (must-fix from review).** State MUST survive HITL receiver pod restarts. Two acceptable mechanisms — the choice is deferred to /ce-plan based on the Robusta spike outcome: (a) **Robusta path:** rely on Robusta's built-in PostgreSQL state store (CNPG-backed if Robusta is chosen); (b) **Custom-receiver path:** a CRD `HITLAlertState` (`apiVersion: alerting.local/v1`) with one CR per alert fingerprint, status subresource for state field, finalizer to prevent GC during in-flight playbook. K8s API is the durable store; the receiver pod is stateless. A pod restart loses no Pending state because Pending lives in the CR, not the pod. Acceptance test: post buttons → kill receiver pod → wait for re-elect → click Approve → playbook runs (state was preserved).
- R15. **Snooze semantics — bounded, persisted, and explicitly cancelled on resolve.** Snooze creates an Alertmanager silence (via AM API) for a fixed duration of 1 hour (no operator-specified duration to keep interaction surface alert-centric, not chatops). Silences persist across AM restarts (R1). When snooze expires with the alert still firing, fresh buttons are posted with a new correlation ID and an audit event records the re-prompt; original buttons are inert.
   - **Silence cancellation lifecycle (must-fix from review).** A snooze silence MUST be explicitly cancelled (AM `expireSilence` API call) when the underlying alert transitions to `Auto-resolved` BEFORE the silence's natural expiry. Without this cancel-on-resolve, the next legitimate firing of the same alert during the still-active silence window is silently swallowed — a known anti-pattern in PagerDuty/Robusta deployments. The HITL receiver listens for AM resolution webhooks scoped to alerts in `Snoozed` state and issues `expireSilence` on transition. Audit event `silence_cancelled_on_resolve` recorded per R17. Manual cancellation (operator clicks "Unsnooze" if exposed) and natural AM expiry are the two other valid termination paths; all three are tested.
- R16. **HITL failure escalation.** If a playbook fails (`Failed` or `Timeout` per R14), the HITL receiver emits a follow-up critical alert `remediation_failed` tagged with the original alert ID, routed direct (skip Notifiarr), and explicitly NOT auto-retryable. The operator must explicitly intervene. Distinct outcome codes: `ssh-unreachable`, `ssh-auth-failed`, `script-nonzero`, `script-zero-but-condition-persists`, `timeout`. Each code becomes a named test scenario.

### Audit + Observability

- R17. **Structured audit log schema.** Every HITL event (button posted, click received, signature validated, authorization checked, playbook started, playbook completed) emits a structured JSON log line to Loki with required fields: `timestamp` (RFC3339), `alertname`, `fingerprint` (Prometheus alert fingerprint), `event` (e.g., `posted`, `approved`, `snoozed`, `rejected_unauthorized`, `playbook_started`, `playbook_succeeded`), `actor` (Discord user ID or `system`), `playbook` (when applicable), `outcome` (when applicable, see R16), `correlation_id`, `duration_ms` (when applicable). Loki labels: `app=alert-remediation`, `severity`, `playbook`. **Acceptance:** a single LogQL query returns the full lifecycle of one alert by `fingerprint`.
- R18. **Alerting-pipeline meta-monitoring with sink independence.** Two safeguards, designed so neither relies on the system being monitored:
  - (a) **Watchdog → uptime-kuma push (sink-independent).** PrometheusRule `Watchdog` fires every 5 minutes with `severity: info` and the corresponding Alertmanager route emits a heartbeat HTTP POST to an uptime-kuma push monitor. uptime-kuma alerts on heartbeat-stop via its OWN notification channels (Pushover or ntfy.sh — explicitly NOT Discord/Notifiarr/Alertmanager), so "Alertmanager is down" or "Discord/Notifiarr API is failing" still surface. The independence is the whole point: a watchdog that flows through the sink it's monitoring is circular and cannot detect the failure mode it exists for. Uptime-kuma's notification channel for this monitor is the framework's only deliberately-different sink and is documented as such.
  - (b) **NotifiarrDown → Discord direct (severity-routed bypass).** PrometheusRule `NotifiarrDown` fires with `severity: critical` (routed via `discord-critical` per R3, bypassing Notifiarr by routing rule) when blackbox-exporter probes report Notifiarr unreachable for 2+ minutes — covers "warning/info path is silently broken."
  - (c) **PrometheusDown / scrape-failure detection.** A separate uptime-kuma monitor (HTTP) probes the Prometheus `/-/healthy` endpoint every 30s and alerts via the same independent Pushover/ntfy channel as (a) — covers the "Prometheus itself is down so Watchdog never fires" failure mode that (a) alone would miss.
  - **Phase placement:** R18 is part of Phase 1 (not Phase 3) — the meta-monitoring is meaningful from the moment Alertmanager is enabled, and adding it later means Phase 1/2 ship without it.
- R19. **Internal-only ingress for Alertmanager UI.** Hostname `alert.sf.${BASE_DOMAIN}` behind `internal-secure-chain` (LAN/VPN gated). HITL receiver UI (if the chosen receiver exposes one) gets the same gating; if it cannot be exposed only to operator-allowlisted Discord users, it is NOT exposed at all (operator uses port-forward).

### Secrets

- R20. **Credential storage by sensitivity class.**
   - **SOPS-encrypted Secrets** (sensitive material): Discord webhook URL, Discord bot token, Notifiarr endpoint URL + token, operator Discord user ID allowlist (R10), UDM SSH private key (R21), uptime-kuma push token (R18a), Pushover/ntfy credentials (R18a sink). Referenced via `secretKeyRef` in AlertmanagerConfig and Pod env/volume mounts; never logged. Never written into `clusterenv.yaml` or `clustersettings.secret.yaml` — dedicated `*.secret.yaml` files per resource.
   - **ConfigMap (non-sensitive published material):** Discord application public key (R8), known_hosts pin for UDM-SE (R21). These are public-by-design values; storing them as Secrets falsely signals sensitivity, makes rotation harder, and clutters SOPS scope.
   - The receiver's deployment manifest mounts both classes; the distinction is operationally important because Secrets require SOPS round-trips on every edit while ConfigMaps don't.
- R21. **UDM SSH credential constrained to least-privilege.** The cluster-side SSH credential authenticates as a dedicated unprivileged user on UDM-SE — NOT root. The user's `~/.ssh/authorized_keys` entry uses `command="/data/on_boot.d/15-cluster-bgp.sh"` to constrain the key to running ONLY that one script (and `no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty` to limit footprint). Host-key pinning is enforced via a `known_hosts` ConfigMap mounted into the playbook pod — `StrictHostKeyChecking=yes`, never `=no`. The Discord bot's permission integer is constrained to: `Send Messages` + `Use Application Commands` + `Manage Messages` (own messages only) on the single designated alert channel; explicitly deny `Administrator`.

### BGP Playbook (POC)

- R22. **BGP-recovery playbook.** When triggered (Approve from a `remediation: bgp-recovery` alert), the playbook SSHs to UDM-SE per R21 and runs `/data/on_boot.d/15-cluster-bgp.sh`. The playbook is idempotent (the underlying script is idempotent). Replay-defense is layered:
   - **Per-instance nonce:** the HITL receiver generates a single-use nonce on transition `Pending → Approved`, defined as `HMAC-SHA256(server-secret, alert.fingerprint || timestamp)` truncated to 16 bytes hex. The nonce is stored in the durable state record (R14). Playbook execution consumes the nonce; subsequent attempts to execute the same `(fingerprint, nonce)` tuple are rejected with audit event `replay_rejected`. The HMAC key (`hitl-replay-secret`) is a SOPS Secret rotated on operator demand.
   - **Receiver-side rate-limit:** 1 invocation per 5 minutes per `(fingerprint, playbook)` tuple — coordinated with R5's `for: 60s` (so a re-trigger requires a sustained 60s + 5min cooldown).
   - **Coordination with R8/R9/R14:** the nonce is the LAST line of defense; R8 (signature) and R9 (timestamp window) reject forged/replayed requests at the edge, R14's idempotent state machine rejects double-clicks at the state layer, R22's nonce defends against the residual case where a stale-but-signed-and-in-window payload arrives after state reset.

---

## Framework Completion Criteria

The framework is "done" enough to ship BGP and treat all subsequent alerts as additive PRs when ALL of these are true:

- [ ] Alertmanager running with PVC-backed silences (R1)
- [ ] Both receivers configured + routing tree live, mutually exclusive (R2, R3)
- [ ] Severity rubric + flap classification documented (R4)
- [ ] Severity-routing + CRD-shape CI guard active (R6)
- [ ] HITL receiver running with Ed25519 signature verification + replay protection + authorization (R7, R8, R9, R10)
- [ ] HITL endpoint exposed via Cloudflare Tunnel with header-gating WAF + rate-limit (R11)
- [ ] Playbook registration contract documented (R12) + reference RBAC pattern (R13)
- [ ] State machine implemented with durability across pod restart (R14)
- [ ] Snooze with explicit cancel-on-resolve + failure escalation (R15, R16)
- [ ] Structured audit log schema producing queryable lifecycle (R17)
- [ ] Sink-independent Watchdog + NotifiarrDown + PrometheusDown meta-monitoring active (R18)
- [ ] Credentials class-separated: Secrets vs ConfigMap (R20)
- [ ] Replay-defense layered: signature + timestamp + state idempotence + per-instance nonce (R8, R9, R14, R22)
- [ ] BGP rule (R5) firing end-to-end with HITL playbook (R22) successfully recovers a real induced outage
- [ ] A second hypothetical alert PR (e.g., disk-near-full) needs zero framework changes — only `kustomization.yaml` + a new PrometheusRule + (optionally) a new playbook YAML

The last item is the proof point: if adding alert #2 requires touching framework code, the framework isn't done.

---

## Phasing

Implementation lands in three phases, each independently mergeable:

### Phase 1 — Alertmanager + Routing + Meta-monitoring (no HITL)
R1, R2, R3, R4, R6, R18 (a/b/c — Watchdog, NotifiarrDown, PrometheusDown), R19, R20 (subset: webhook URLs + Pushover/ntfy creds for R18a sink). **Acceptance criteria:** (a) Alertmanager pod running with PVC-backed silences surviving pod restart; (b) `amtool` + `kubectl --dry-run=server` CI guard passes on a PR introducing a deliberately-malformed PrometheusRule (must fail); (c) Watchdog heartbeat reaches uptime-kuma every 5min for 24h continuously; (d) deliberately killing Alertmanager triggers an uptime-kuma Pushover/ntfy notification within 10min via the R18a independent path. Outcome: Alertmanager is up, both receivers wired, severity routing live, meta-monitoring catches its own failures, but no remediation buttons.

### Phase 2 — BGP Alert (no HITL)
R5. **Acceptance criteria:** (a) inducing BGP down on UDM-SE causes a critical alert to land in `discord-critical` within 90s of the 60s `for:` window expiring; (b) restoring BGP causes alert to resolve within 60s; (c) flap-classification rule (R4) demotes a 4x-flapping BGP condition from critical to warning within the 30min window. No buttons, no remediation — just the alert.

### Phase 3 — HITL + BGP Playbook
R7, R8, R9, R10, R11, R12, R13, R14 (including durability test), R15 (including silence-cancel-on-resolve test), R16, R17, R20 (remaining secrets + ConfigMap), R21, R22 (including nonce + rate-limit). **Acceptance criteria:** all gameday scenarios in the Validation section pass on first run; HITL receiver pod kill-and-recover preserves Pending state; unauthorized click produces `rejected_unauthorized` audit event; replay of an already-consumed nonce produces `replay_rejected` audit event. Outcome: BGP alert posts buttons; Approve runs the recovery playbook; everything is auditable; framework is complete.

Each phase is testable on its own. ce-plan should preserve this phasing in implementation units.

---

## HITL State Machine

```
┌────────────┐     Approve+sig+ts+auth        ┌──────────────────┐
│  Pending   │ ───────────────────────────▶  │  Approved         │
│ (buttons)  │                                │  (playbook running)│
│            │ ◀─── snooze expires ───┐       └────────┬──────────┘
└──┬─────────┘                        │                ↓
   │                                  │      ┌─────────────────────┐
   │ Snooze (sig+ts+auth)             │      │ Succeeded / Failed /│
   ↓                                  │      │ Timeout (terminal,  │
┌────────────┐                        │      │ R14 + R16)          │
│  Snoozed   │ ───────────────────────┘      └─────────────────────┘
│ (1h fixed) │
└─┬──────────┘
  │ Ignore (sig+ts+auth)
  ↓
┌────────────┐
│  Ignored   │  (alert silenced for one notification cycle;
│ (terminal) │   Prometheus keeps evaluating)
└────────────┘

  │ Auto-resolve at any time before terminal:
  ↓
┌──────────────────┐
│  Auto-resolved   │  (buttons disabled; "stale" reply on click)
│  (terminal)      │
└──────────────────┘
```

Every transition emits a Loki audit event per R17. State is keyed on `(alertname, fingerprint)`.

---

## Scope Boundaries

### Deferred for later

- Concrete PrometheusRules and remediation playbooks beyond BGP. Each new alert + optional playbook lands as a separate PR plugged into the framework.
- Email, SMS, mobile push, or PagerDuty notification channels.
- Multi-cluster Alertmanager federation.
- Custom Alertmanager UI or chatops queries beyond what the chosen receiver provides.

### Outside this product's identity

- Fully autonomous remediation that runs without human approval. The cron BGP healthcheck on UDM-SE remains the only no-approval auto-fix in the system; everything in this framework requires explicit Discord approval.
- A general-purpose chatops bot. The Discord interaction surface is alert-centric only — Approve / Snooze / Ignore on alerts that arrive; not a free-form command interface.
- Replacement of the uptime-kuma TCP probe (Layer 2A from the defense pyramid). Path A and Path B coexist; uptime-kuma provides fast layer-3 monitoring, this framework provides metric-aware deeper coverage with optional HITL action. To prevent duplicate-pager noise: when R5 ships, the uptime-kuma BGP probe is reconfigured to only alert on layer-3 (TCP/179 unreachable) rather than session-state, which Layer 2B owns. Same outage produces one notification stream from Layer 2B, with Layer 2A as silent backstop.

### Deferred to Follow-Up Work

- Audit log dashboards in Grafana (Loki has the data per R17; the dashboard design is its own work).
- Alert noise tuning beyond the v1 thresholds: framework will likely surface false positives once live; tuning is iterative.
- `docs/runbooks/adding-an-alert.md` template (1-page guide showing how to author a new alert + playbook PR using the registration contract).
- Secondary critical sink (ntfy.sh, SMTP, Pushover) as a backstop if Discord itself goes down. Currently accepted-as-SPOF; document this gap explicitly.
- Tamper-resistant audit log forwarding (e.g., HITL events also posted to a private Discord audit thread so Loki tampering doesn't fully cover tracks). Defense-in-depth for a future iteration.

---

## Key Decisions

- **Dual-receiver routing (direct + Notifiarr) instead of single-channel**: Notifiarr enriches with app-aware cards but adds a dependency. Routing critical direct removes Notifiarr from the SPOF chain for incidents that genuinely require immediate attention; warning/info routes through Notifiarr where small delays don't matter.
- **Framework-first scope (with BGP as proof-of-concept) instead of BGP-only**: future alerts are inevitable. Framework Completion Criteria + Phasing make explicit when "framework done" is reached.
- **HITL via Discord buttons instead of fully autonomous or fully manual**: fully autonomous risks cascading failure; fully manual loses the speed advantage of codified runbooks. Discord buttons give a deliberate-but-fast path with a human in every loop. State machine + idempotence + replay protection make the contract precise enough to test.
- **Build-vs-buy for HITL receiver — pre-plan validation required**: Robusta is the canonical OSS Prometheus playbook engine, but its Discord interactive-component support is historically weaker than its Slack support. **Before /ce-plan, run a small spike to confirm Robusta vN supports verified Discord button callbacks (signature verification, interaction tokens). If yes, use Robusta. If no, scope a small custom receiver.** This decision is too consequential to defer to plan-time.
- **Secrets as `secretKeyRef` in AlertmanagerConfig, not envsubst**: webhook URLs may contain characters that conflict with Flux's `${VAR}` substitution. AlertmanagerConfig CRD natively supports `secretKeyRef`; that's the canonical reference.
- **Per-playbook ServiceAccounts (not a single shared one)**: a misconfigured BGP-recovery playbook should not be able to delete pods cluster-wide. Each playbook gets only the RBAC verbs/resources it explicitly needs. The BGP playbook needs only `Secret/get` for the UDM SSH credential — zero workload mutation verbs.
- **UDM SSH constrained at the OS level, not just RBAC**: `command=` restriction in `authorized_keys` + `known_hosts` pinning + dedicated unprivileged user. Cluster RBAC alone can't constrain SSH egress; OS-level constraint is the actual security boundary.
- **`info` severity does NOT route to Discord**: prevents notification fatigue. `info` lands in Loki/Grafana annotations only.
- **Deduplication strategy across Layer 2A and 2B**: when R5 ships, uptime-kuma's BGP probe scope shifts to TCP/179 reachability only (not session state). Layer 2B owns session-state alerting end-to-end. One outage → one notification stream.

---

## Outstanding Questions

### Resolved during brainstorm + review

- *Notifiarr or direct webhook?* → Both, severity-routed (mutually exclusive per R3).
- *BGP-only or framework?* → Framework with BGP as POC; Framework Completion Criteria documented.
- *Autonomous, manual, or HITL?* → HITL via Discord buttons, with explicit state machine.
- *Discord signature verification?* → Required (R8); public key in ConfigMap.
- *Replay protection?* → Required, ±60s window with NTP requirement (R9).
- *Robusta or custom receiver?* → Spike before /ce-plan; both paths defined for state durability (R14).
- *HITL endpoint exposure?* → Cloudflare Tunnel + signature-header WAF gate + rate-limit (R11).
- *UDM SSH credential shape?* → `command=` restricted, dedicated user, host-key pinned (R21).
- *Severity routing regression guard?* → CI amtool + kubectl --dry-run=server (R6).
- *Snooze duration?* → Fixed 1h, AM-silence-backed, explicit cancel-on-resolve (R15).
- *Audit schema?* → Required structured fields (R17).
- *Watchdog circular dependency?* → R18a uses sink-independent Pushover/ntfy path.
- *State durability across pod restart?* → CRD or Robusta state store (R14).
- *Public key in Secret or ConfigMap?* → ConfigMap (R8, R20).
- *Replay nonce mechanism?* → HMAC of fingerprint+timestamp, single-use (R22).
- *Routing exclusivity?* → No `continue: true` on Discord-receiver routes; CI-enforced (R3, R6).
- *Flapping?* → 4x in 30min downgrades severity one tier (R4).

### Deferred to planning

- **Robusta version + concrete Discord interactivity capability**: result of the pre-plan spike. If positive, plan picks Robusta and references its sink config; if negative, plan defines a small custom receiver pod.
- **Group-wait/repeat-interval fine-tuning**: defaults stated in R3 (30s/4h/12h); revisited after live noise feedback.
- **Robusta UI auth posture (if Robusta is chosen)**: Robusta's UI exposure decision deferred to planning, but constrained by R19 (must match operator-identity auth or not be exposed at all).

---

## Validation / Gameday

A minimum-viable gameday after Phase 3 lands. Pass criteria documented inline so the exercise is binary, not vibes-based.

**Sequence:**
1. Schedule a maintenance window.
2. Apply NetworkPolicy that blackholes egress to Notifiarr's endpoint IP (simulates Notifiarr down).
3. Inject a synthetic warning alert via Alertmanager API. **Expected:** alert is queued (or dropped per R3 design — confirm which), no critical-path impact, eventual logged failure visible in `NotifiarrDown` self-monitor (R18b) within 2-5min.
4. Inject a synthetic critical alert via Alertmanager API. **Expected:** Discord direct webhook delivers within `group_wait + jitter` (~30s); buttons posted by HITL receiver; sig-verification and timestamp checks pass.
5. Click Approve from operator-allowlisted user. **Expected:** state machine moves Pending → Approved; playbook runs; success → Succeeded; Loki audit log shows full lifecycle queryable by `fingerprint`.
6. Inject second concurrent critical alert. **Expected:** independent button correlation IDs; state isolated.
7. Click Approve twice rapidly on first alert. **Expected:** second click acknowledged "already executed", playbook NOT re-run.
8. Have a non-allowlisted Discord user click Approve. **Expected:** ephemeral "Not authorized" reply; Loki event with `outcome: rejected_unauthorized`; playbook NOT triggered.
9. Restore Notifiarr. **Expected:** queued warning alerts (if any) drain; meta-monitor `NotifiarrDown` resolves.
10. Restart the Alertmanager pod with an alert in `Pending` HITL state. **Expected:** silence persists (R1); buttons remain actionable.

If any expected outcome doesn't match, the framework is NOT done — investigate before declaring Phase 3 shipped.

---

## Sources & References

- Companion plan: `docs/plans/2026-05-05-002-feat-cilium-l2-announcements-plan.md` (Phase A / Cilium L2, of which this alerting layer is the monitoring follow-up)
- UDM persistence script (Layer 1 of defense pyramid): `docs/network/udm-se/15-cluster-bgp.sh`
- BGP setup doc (cluster side): `docs/network/udm-se-bgp.md`
- Cilium BGP metric exposed today (verified live): `cilium_bgp_control_plane_session_state`, scraped via `cilium-agent` ServiceMonitor in `kube-system`
- Existing TrueCharts pattern for SOPS Secrets: see any `*.secret.yaml` under `clusters/main/kubernetes/`
- Discord interaction signature verification spec: https://discord.com/developers/docs/interactions/receiving-and-responding#security-and-authorization
- Robusta upstream: https://docs.robusta.dev/
- Notifiarr running in cluster: `media/notifiarr` namespace
- Production-grade review findings (revision 2 driver): captured inline above as R6, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18, R21
- Production-grade re-review findings (revision 3 driver): WAF rule mechanism (R11), public key class (R8, R20), silence cancel-on-resolve (R15), watchdog sink independence (R18), state durability (R14), routing exclusivity (R3, R6), flap classification (R4), nonce mechanism (R22), NTP drift window (R9)
