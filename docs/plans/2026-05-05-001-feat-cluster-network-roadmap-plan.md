---
title: "feat: Cluster network + observability roadmap (BGP, LAG, SonarQube, blocklists)"
type: feat
status: active
date: 2026-05-05
---

# feat: Cluster network + observability roadmap (BGP, LAG, SonarQube, blocklists)

## Summary

Four sequenced phases hardening the cluster's networking and adding SAST coverage: (A) **Cilium native BGP migration** to preserve client source IPs and unblock the IP-allowlist middleware deferred from the May 5 lockdown plan; (B) **STP/LAG repatch + LAG config** to eliminate the recurring SFP+ blocked-port events seen Apr 8/11/23/27; (C) **SonarQube self-host** with the official SonarSource Helm chart + CNPG; (D) **Pi-hole blocklist refresh** swapping the 3 dead URLs for working alternatives. Phase A gates the security finalization; B-D are independent and lower risk.

---

## Problem Frame

Four pieces of partial work accumulated across recent sessions:

1. **No real-IP visibility at Traefik**: with MetalLB L2 + Cilium kubeProxyReplacement + `externalTrafficPolicy: Cluster`, every LAN/VPN client is SNAT'd to a node IP (`172.16.x.x`) before Traefik sees it. The IP-allowlist middleware created for internal services in `docs/plans/internal-vs-external-services-lockdown.md` (Phase 3) cannot distinguish trusted internal clients from cloudflared-tunnel traffic. proxyProtocol was attempted and reverted (MetalLB L2 doesn't reliably inject PROXY headers in this stack).
2. **Recurring STP storms**: 4 SFP+ ports on Pro 48 PoE + EnterpriseXG remain in `discarding` state. Topology mapped via LLDP (6 DAC cables Aggregation↔access switches, no LAG configured, Aggregation-side ports non-sequential). `scripts/unifi-lag-config.sh` is queued for D1 (4-port LAG + 2-port LAG) but blocked on physical re-patch.
3. **No SAST coverage**: `sonarqube-cli` was installed during `/sonarqube:sonar-integrate` but the user deferred backend selection ("self-host or skip"). Triparr-bot, `scripts/`, and other code currently get no static analysis.
4. **Pi-hole gravity errors visible**: 3 inaccessible blocklist URLs flagging on the diagnosis page (osint.digitalside.it/Threat-Intel — global timeout; dbl.oisd.nl — global timeout; zerodot1.gitlab.io/CoinBlockerLists — 302 redirect Pi-hole's downloader doesn't follow).

Cilium BGP wasn't on the table when the cluster was first stood up (memory note: deployment via `clustertool flux bootstrap`); it now is.

---

## Requirements

- R1. After Phase A, Traefik must see the real LAN/VPN client IP, not a SNAT'd node IP — verified by checking `X-Forwarded-For` lookups in CrowdSec logs and Traefik access logs.
- R2. After Phase A, the deferred `internal-secure-chain` middleware (already created at `clusters/main/kubernetes/core/traefik/app/middleware-internal-secure-chain.yaml`) can be applied to internal-service ingresses without breaking LAN access.
- R3. After Phase B, no SFP+ port reports `stp_state: discarding` for ≥24 hours under normal load. LAG bonded interfaces show traffic distributed across member ports.
- R4. After Phase C, SonarQube admin UI loads at `https://sonarqube.sf.wethecommon.com` (LAN/VPN only — split-horizon DNS), backed by CNPG, persists data across pod restart, and `/sonarqube:sonar-integrate` `4.a` flow completes.
- R5. After Phase C, a baseline scan of `scripts/` reports its findings to the SonarQube project.
- R6. After Phase D, `kubectl logs -n networking pihole-k8s` and the Pi-hole admin diagnosis page show zero "list inaccessible during last gravity run" errors.
- R7. No service downtime > 30s during any phase. (Phase A is the only realistic risk; rollback plan must be inline.)
- R8. All changes must follow the repo's GitOps model — declarative manifests in `clusters/main/kubernetes/`, Flux reconciliation, SOPS for secrets per `.sops.yaml`. No imperative `kubectl apply` for persistent state.

---

## Scope Boundaries

- **In scope**: Cilium BGP control plane, MetalLB L2 → Cilium BGP cutover, internal-allowlist Traefik middleware finalization, UniFi LAG via existing API script, SonarQube cluster app, Pi-hole blocklist URL refresh.
- **Not in scope**: re-architecting the WAN failover (current dual-WAN setup remains as-is), MoCA topology rationalization (memory `project_unifi_stp_research_2026_04` flags this as a future project), Talos node multi-homing or HA control plane (single-node remains), full SonarCloud migration (we self-host).

### Deferred to Follow-Up Work

- **MetalLB removal**: keep MetalLB installed (but no L2Advertisement) as a fallback for one week post-Phase A. Removal is its own follow-up PR after BGP stability is confirmed.
- **Sonar scans of triparr-bot, ollama, and other custom code**: only `scripts/` baseline is in scope here. App-by-app scan integration is per-app follow-up work.
- **MoCA Bedroom Desk path decision** (EnterpriseXG p20 down vs p16 active): inherited open question from `project_unifi_stp_research_2026_04.md`; not blocking Phase B.

---

## Context & Research

### Relevant Code and Patterns

- **HelmRelease + Flux Kustomization**: every cluster app follows `clusters/main/kubernetes/<layer>/<app>/{ks.yaml, app/{kustomization.yaml, helm-release.yaml, namespace.yaml, ...}}`. See `clusters/main/kubernetes/system/goodmem/` for the freshest example (CNPG + ingress + secret + namespace).
- **CNPG cluster pattern**: 3 working examples — `clusters/main/kubernetes/apps/triparr-bot/app/cnpg-cluster.yaml`, `clusters/main/kubernetes/apps/ollama/app/cnpg-cluster.yaml`, `clusters/main/kubernetes/system/goodmem/app/cnpg-cluster.yaml`. Use `pgvector/pgvector:pg17` only via `imageName` workarounds (goodmem uses `tensorchord/cloudnative-vectorchord:18-1.1.1`); for SonarQube the default CNPG postgres image is fine — no vector extension needed.
- **MetalLB current**: TrueCharts `metallb-config` chart at `clusters/main/kubernetes/core/metallb-config/app/helm-release.yaml`. Single L2Advertisement covers all 53 services in pool `192.168.10.193-254`.
- **Cilium current**: deployed via `clusters/main/kubernetes/system/cilium/` with kubeProxyReplacement enabled. **No BGP CRDs configured yet** — clean greenfield for Phase A.
- **Internal-allowlist middleware**: already written at `clusters/main/kubernetes/core/traefik/app/middleware-internal-allowlist.yaml` (created during Phase 2 of lockdown plan, not yet applied to ingresses).
- **Internal-secure-chain middleware**: at `clusters/main/kubernetes/core/traefik/app/middleware-internal-secure-chain.yaml` — bouncer + internal-allowlist.
- **Pi-hole API auth**: established pattern from `internal-vs-external-services-lockdown.md` execution log — `PIHOLE_BARE_METAL_PASS` from `clusterenv.yaml`, POST `/api/auth`, then PUT `/api/config/dns/hosts/<entry>` or DELETE for blocklists.
- **UniFi LAG script**: `scripts/unifi-lag-config.sh` (gitignored; lives locally) — supports `check | d1 [--apply] | d2 [--apply]`. D1 = 4+2-port LAG with sequential-port verification. D2 = pull redundant cables, single uplink only.

### Institutional Learnings

- **Talos rebooted unexpectedly** during the GoodMem deploy on Apr 27 (memory `project_unifi_stp_research_2026_04`); BGP migration could similarly cause control-plane flap if BGP holdtime is set too aggressively. Mitigation: use BGP graceful restart; verify Talos's apid/kubelet survive cluster API blip.
- **CNPG webhook rejects pgvector image tags starting with non-numeric chars** (memory + this session's GoodMem deploy chase). SonarQube uses standard postgres → no risk here, but the pattern is documented.
- **Cilium + `externalTrafficPolicy: Local`** breaks on single-node Talos (CLAUDE.md memory). Cilium BGP doesn't require Local — kubeProxyReplacement preserves source IP via eBPF datapath. Verify before Phase A.
- **proxyProtocol attempt + revert** (this session): MetalLB L2 mode + Cilium kubeProxyReplacement combination doesn't reliably inject PROXY headers. Cilium BGP path is expected to obviate the need entirely.
- **TrueCharts `metallb-config` chart**: holds L2Advertisements + ipAddressPools. After Phase A migration, this can be reduced to just ipAddressPools (Cilium owns advertisement) or fully removed in the deferred follow-up.

### External References

- [Cilium BGP Control Plane docs (current)](https://docs.cilium.io/en/latest/network/bgp/) — covers `CiliumBGPClusterConfig`, `CiliumBGPPeerConfig`, `CiliumBGPAdvertisement` CRDs (the current API; older `CiliumBGPPeeringPolicy` is being phased out).
- [BGP with Cilium and UniFi (Stonegarden, 2025-11)](https://blog.stonegarden.dev/articles/2025/11/bgp-cilium-unifi/) — concrete walkthrough of Cilium BGP peering with UDM/UDM-SE.
- [UniFi BGP support (Ubiquiti Help Center)](https://help.ui.com/hc/en-us/articles/16271338193559-UniFi-Border-Gateway-Protocol-BGP) — UDM-SE 4.1.13+ supports BGP via FRR config upload. Current UDM is on `5.0.16.30692` ✓.
- [Configure BGP on a UDM-SE (chrisdooks.com)](https://chrisdooks.com/2022/10/25/get-bgp-working-on-udm-se-v3-0-10-or-later/) — older but FRR config syntax is stable.
- [SonarSource/helm-chart-sonarqube](https://github.com/SonarSource/helm-chart-sonarqube) — official chart, latest 2026.1.0 (SonarQube Community Build 26.1.0).
- [SonarQube Helm chart docs — external DB setup](https://docs.sonarsource.com/sonarqube-community-build/server-installation/on-kubernetes-or-openshift/customizing-helm-chart) — drop the embedded postgres, point at CNPG.

### Slack Context

- Not available in this environment; not searched.

---

## Key Technical Decisions

- **Cilium native BGP, not MetalLB BGP**: drop a layer. Cilium's BGP Control Plane is mature in 2026, integrates with kubeProxyReplacement, and removes the MetalLB-Cilium impedance issue that broke proxyProtocol earlier in this session. MetalLB and Cilium BGP are mutually exclusive — choose one.
- **MetalLB stays installed during cutover, gets disarmed gradually**: avoid dual-advertisement. Disable L2Advertisement before enabling Cilium BGPAdvertisement on the same pool. Keeps a quick rollback path (re-enable L2) for one week.
- **Single AS, eBGP with UDM-SE**: pick AS 64512 for cluster, AS 64513 for UDM (private 16-bit ASNs). Single peer (UDM is single router). Direct connect (no route reflectors).
- **Advertise ipAddressPool `main` via Cilium**: same `192.168.10.193-254` range. UDM accepts the route, advertises into LAN VLAN 10. Source IPs preserved end-to-end.
- **Phase A test cutover via least-critical service**: pick a non-load-bearing LB service (uptime-kuma or grafana) to flip first. Verify session establishment + reachability + source IP preservation before mass cutover.
- **Phase B uses D1 strategy** (4+2 LAG): user already approved this in the prior STP research session. D2 (pull redundant cables) is fallback if re-patch is impractical.
- **SonarQube via official SonarSource chart, not TrueCharts wrapper**: the SonarSource chart is purpose-built and maintained by the vendor; TrueCharts doesn't have a sonarqube wrapper. Pattern departs from the rest of the repo (which is mostly TrueCharts) but matches the goodmem pattern (vendor-direct deployment).
- **Sonar uses CNPG, not embedded PG**: matches existing pattern (triparr/ollama/goodmem). External database also explicitly recommended by the SonarSource chart docs.
- **SonarQube is internal-only**: hostname `sonarqube.sf.wethecommon.com` joins the 35 internal services from the lockdown plan — Cloudflare A 192.168.10.196 unproxied, Pi-hole + Blocky local override, **NOT** in the cloudflared tunnel ingress allowlist. Standard internal-host pattern.
- **Pi-hole blocklist replacements**:
  - List 85 (osint.digitalside.it threat intel) → drop entirely; the host has been offline globally for weeks. Closest active alternative: ThreatFox (`https://threatfox.abuse.ch/downloads/hostfile/`).
  - List 97 (zerodot1 CoinBlockerLists) → tag still works but downloader doesn't follow the 302. Update URL to the redirect target (current canonical is `https://gitlab.com/ZeroDot1/CoinBlockerLists/-/raw/master/hosts_browser`).
  - List 101 (oisd.nl bare apex) → use the canonical Pi-hole-format URL `https://big.oisd.nl/dnsmasq` (or `https://small.oisd.nl/` for less aggressive). The plain `https://dbl.oisd.nl/` was deprecated.

---

## Open Questions

### Resolved During Planning

- **Cilium BGP vs MetalLB BGP** — chose Cilium native (user-confirmed).
- **Phase ordering** — BGP first (user-confirmed). Risk-tolerance choice; user wants the foundational unblock done first.
- **SonarQube database backend** — CNPG, matches repo pattern.
- **SonarQube exposure** — internal-only, follows lockdown plan rules.

### Deferred to Implementation

- **Talos apid behavior during BGP session establishment**: monitor at execution time; if cluster API flaps, narrow Cilium BGP advertise list before retrying.
- **Exact UDM FRR config syntax** for accepting cluster routes: vary per UniFi firmware revision. Verify against the actual UI at execution and adjust.
- **Whether to drop MetalLB entirely**: deferred to follow-up after one-week stability window post-Phase A.
- **SonarQube admin password generation**: generate at execution time (random, ≥24 chars); store in clusterenv as `SONARQUBE_ADMIN_PASS`.
- **SonarQube initial token for `sonar` CLI**: created post-bootstrap inside the SonarQube UI; `sonar integrate claude` writes it to system keychain.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Phase A network topology (before/after)

```
BEFORE (current state):

  LAN client (192.168.10.50)
        ↓ ARP
  MetalLB L2 (192.168.10.196)
        ↓ kube-proxy SNAT
  Traefik pod (sees source = node IP 172.16.x.x)
        ↓
  internal-allowlist middleware: LOOKS LIKE LOCAL — can't distinguish
  cloudflared (172.16.0.62) from real LAN. Allowlist must include
  172.16/16, defeating the purpose.

AFTER (Cilium BGP):

  LAN client (192.168.10.50)
        ↓ BGP-advertised /32 route via UDM
  UDM-SE forwards 192.168.10.196 → Talos node IP (BGP next-hop)
        ↓ Cilium eBPF datapath (no SNAT)
  Traefik pod (sees source = 192.168.10.50 — REAL CLIENT IP)
        ↓
  internal-allowlist middleware: DISTINGUISHES correctly.
  cloudflared still sees 172.16.0.62 source; LAN sees real IPs.
  Allowlist scoped to LAN/VPN/Travel; pod CIDR excluded.
```

### Phase B cabling (target state)

```
                Aggregation switch (USL8A, 8x SFP+)
                ┌──────────────────────────────────────┐
                │ p1 ─┐                                │
                │ p2 ─┼─ 4-port LAG ─┐                 │
                │ p3 ─┤              │                 │
                │ p4 ─┘              │                 │
                │                    ↓                 │
                │ p5 ─┐         Pro 48 PoE p49-52     │
                │ p6 ─┴─ 2-port LAG ─┐                 │
                │                    ↓                 │
                │                EnterpriseXG p25-26   │
                │ p7 → UDM (uplink)                    │
                │ p8 → Video Recorder Pro              │
                └──────────────────────────────────────┘

  Currently non-sequential on Aggregation side (p1,3,4,6 to Pro48; p2,5 to EXG).
  Re-patch makes them sequential as shown above.
```

### Phase C deployment shape

```
clusters/main/kubernetes/system/sonarqube/
├── ks.yaml
└── app/
    ├── namespace.yaml
    ├── cnpg-cluster.yaml          # standard pg17, 5Gi, no extensions
    ├── cnpg-barman.yaml           # daily backup at 03:00 → s3://cnpg-sonarqube/
    ├── helm-release.yaml          # SonarSource/sonarqube, externalDB pointed at CNPG
    ├── ingress.yaml               # Traefik websecure, secure-chain (NOT internal-secure-chain yet — apply post-Phase A)
    ├── sonarqube-secret.secret.yaml   # SOPS — admin password
    └── kustomization.yaml
```

---

## Output Structure

```
docs/plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md   # this plan
clusters/main/kubernetes/system/sonarqube/                        # new — Phase C
├── ks.yaml
├── README.md
└── app/
    ├── namespace.yaml
    ├── cnpg-cluster.yaml
    ├── cnpg-barman.yaml
    ├── helm-release.yaml
    ├── ingress.yaml
    ├── sonarqube-secret.secret.yaml
    └── kustomization.yaml
clusters/main/kubernetes/system/cilium/app/                       # modified — Phase A
├── helm-release.yaml                                              # add bgpControlPlane.enabled: true
├── bgp-cluster-config.yaml                                        # new
├── bgp-peer-config.yaml                                           # new
├── bgp-advertisement.yaml                                         # new
└── kustomization.yaml                                             # add 3 new resources
clusters/main/kubernetes/core/metallb-config/app/                 # modified — Phase A cutover
└── helm-release.yaml                                              # remove L2Advertisements section
```

Other Phases (B, D) modify existing files in place — no new directory structure.

---

## Implementation Units

### Phase A — Cilium BGP migration

- U1. **Enable Cilium BGP control plane**

**Goal:** Set `bgpControlPlane.enabled: true` in Cilium values so the BGP datapath is loaded; no peer or advertisement yet — quiescent state.

**Requirements:** R1, R7, R8

**Dependencies:** None.

**Files:**
- Modify: `clusters/main/kubernetes/system/cilium/app/helm-release.yaml`

**Approach:**
- Add `bgpControlPlane: { enabled: true }` to values block.
- Confirm Cilium chart version supports the current CRD set (`CiliumBGPClusterConfig`, etc., not the legacy `CiliumBGPPeeringPolicy`).
- Reconcile via Flux; verify Cilium agents restart cleanly without reporting BGP config errors (no peer is configured yet, so they should start idle).

**Patterns to follow:**
- Existing `clusters/main/kubernetes/system/cilium/app/helm-release.yaml` value structure.

**Test scenarios:**
- Happy path: `kubectl get pods -n kube-system -l k8s-app=cilium` shows all pods Ready after Helm reconcile.
- Edge case: `cilium status` reports `BGP Control Plane: enabled` but no peers.
- Verification (no behavioral change yet): no service traffic disrupted; Traefik LB still answers via existing MetalLB L2.

**Verification:**
- Cilium pods restart cleanly.
- `cilium status --verbose` mentions BGP control plane is on.
- All existing LB services continue to answer.

---

- U2. **Configure UDM-SE BGP peer for cluster**

**Goal:** UDM accepts BGP session from Talos node, AS 64513 (UDM) ↔ AS 64512 (cluster), with route policy that accepts the cluster's `192.168.10.193/26` (or full `/24`) advertisement and re-advertises it into LAN VLAN.

**Requirements:** R1, R7

**Dependencies:** U1.

**Files:**
- No repo file. The UDM FRR config lives on the gateway itself — uploaded via UniFi UI (Settings → Routing → BGP) or via SSH `/etc/frr/frr.conf` on the UDM (firmware-dependent).

**Approach:**
- Use UniFi Network app's BGP config upload UI. Upload an FRR config snippet:
  - `router bgp 64513`
  - `neighbor <talos-node-ip> remote-as 64512`
  - `address-family ipv4 unicast` → `neighbor <talos-node-ip> activate`
  - Optional: `redistribute connected` to inject UDM's interface routes back (likely already present).
- Confirm BGP session attempt is logged on UDM; expect "active/idle" state until Cilium peer is configured in U3.

**Test scenarios:**
- Happy path: UniFi Settings → Routing → BGP shows the peer config saved without parser error.
- Edge case: UDM logs (`/var/log/frr/bgpd.log`) show repeated "Connection refused" on port 179 to Talos node — that's expected before U3, confirms UDM is trying.
- Error path: UI rejects the config (syntax error in FRR file) → revise.

**Verification:**
- BGP configuration persists on the UDM across `forgetool talos` operations.
- UDM's `vtysh -c "show bgp summary"` (via SSH) lists the cluster as a configured neighbor.

---

- U3. **Add Cilium BGP CRDs (cluster + peer + advertisement)**

**Goal:** Cilium establishes BGP session with UDM and advertises the MetalLB ipAddressPool range. Sessions Up; routes are learned but not yet preferred over L2 (MetalLB still wins ARP).

**Requirements:** R1, R7

**Dependencies:** U1, U2.

**Files:**
- Create: `clusters/main/kubernetes/system/cilium/app/bgp-cluster-config.yaml` (`CiliumBGPClusterConfig` referencing AS 64512 and a node selector that matches the Talos control-plane node)
- Create: `clusters/main/kubernetes/system/cilium/app/bgp-peer-config.yaml` (`CiliumBGPPeerConfig` for the UDM neighbor)
- Create: `clusters/main/kubernetes/system/cilium/app/bgp-advertisement.yaml` (`CiliumBGPAdvertisement` selecting Service objects with `type=LoadBalancer` and advertising assigned IPs as `/32`)
- Modify: `clusters/main/kubernetes/system/cilium/app/kustomization.yaml` (add the 3 new resources)

**Approach:**
- Reference Stonegarden's UDM walkthrough for the CRD shape; verify against current Cilium docs.
- Initial advertisement is **passive parallel** with MetalLB — Cilium learns/advertises but MetalLB L2 still answers ARP for the IPs. Linux prefers BGP-learned routes only after L2 entries age out OR after L2 advertisement is removed.

**Test scenarios:**
- Happy path: `cilium bgp peers` shows the UDM peer with `Session: established`.
- Happy path: `cilium bgp routes advertised` lists every LB-pool IP that has an active service.
- Edge case: peer flaps — check `cilium bgp peers` output. If holdtime expires, increase to 90s.
- Integration: from UDM `vtysh -c "show bgp ipv4 unicast"`, confirm the cluster's advertised /32 routes appear.

**Verification:**
- BGP session: Established.
- Advertised routes match the LB IPs in use.

---

- U4. **Pilot cutover: switch one service from MetalLB L2 to Cilium BGP**

**Goal:** Verify end-to-end (LAN client → BGP → Cilium → Traefik) on a single non-load-bearing service. Confirm source IP preserved.

**Requirements:** R1, R2, R7

**Dependencies:** U3.

**Files:**
- Modify: `clusters/main/kubernetes/core/metallb-config/app/helm-release.yaml` — add a per-service or per-IP exclusion from L2Advertisement scope. (Current chart syntax may not support per-IP; if not, fall back to temporarily moving the test IP into a separate ipAddressPool that's only Cilium-advertised.)

**Approach:**
- Pilot service: `monitoring/uptime-kuma` (uptime.sf — internal, low-traffic, easy to test).
- Two paths depending on metallb-config chart capability:
  1. Add a separate ipAddressPool with a single IP that's BGP-only (Cilium advertisement) and reassign uptime-kuma's service to it.
  2. Disable L2Advertisement entirely for the existing pool (riskier — affects all 53 services); only do this in U5 after pilot proves out.
- Verify from a LAN client browser → uptime.sf, then check Traefik access logs for `X-Forwarded-For` and the actual remoteAddr.

**Test scenarios:**
- Happy path: `dig uptime.sf.wethecommon.com` resolves; browser loads UI; Traefik access log shows real LAN client IP (not 172.16.x.x).
- Edge case: cellular-VPN client → same — works AND shows real VPN-side IP (192.168.3.x).
- Error path: BGP session drops mid-test → MetalLB L2 should still serve via L2 fallback. Verify by manually flapping Cilium agent.

**Verification:**
- Real LAN IP visible in Traefik logs for the pilot service.
- Service stays reachable through a forced BGP session restart.

---

- U5. **Mass cutover: disable MetalLB L2Advertisement, all services via Cilium BGP**

**Goal:** Single switchover where MetalLB stops advertising; Cilium BGP is the only path. Brief (<5s) ARP/route reconvergence expected.

**Requirements:** R1, R7

**Dependencies:** U4 (pilot success).

**Files:**
- Modify: `clusters/main/kubernetes/core/metallb-config/app/helm-release.yaml` — remove the `L2Advertisements:` section.

**Approach:**
- Time the change for low-traffic window.
- Pre-warm: ensure Cilium has advertised every active LB IP (cross-check with `kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.namespace}/{.metadata.name}: {.status.loadBalancer.ingress[0].ip}{"\n"}{end}'`).
- Push the helm-release change; Flux reconciles MetalLB; L2 announcements stop within ~30s; Cilium BGP routes take over.
- Curl every public + critical internal service immediately after.

**Test scenarios:**
- Happy path: `arp -an` on a LAN client shows MetalLB no longer responding for the LB IPs; routes now via UDM (BGP next-hop).
- Edge case: a service with active long-lived connection (Plex stream, n8n webhook) — verify it survives the cutover or auto-reconnects within seconds.
- Error path: Cilium agent crashes mid-cutover → all LB services unreachable. Rollback by re-enabling L2Advertisements (re-add to helm-release values, force flux reconcile).

**Verification:**
- 0 service failures in `scripts/cluster-status` for ≥5 minutes after cutover.
- MetalLB controller logs show no active speaker.
- Real client IPs visible in CrowdSec logs cluster-wide.

---

- U6. **Apply internal-secure-chain middleware to internal services**

**Goal:** Finalize the security work deferred from `internal-vs-external-services-lockdown.md`. Each of the 29 internal-service ingresses now uses the `traefik-internal-secure-chain@kubernetescrd` middleware annotation. The IP allowlist is finally effective because Traefik sees real client IPs.

**Requirements:** R2, R8

**Dependencies:** U5.

**Files:**
- Modify (each is a TrueCharts helm-release `values.ingress.main.integrations.traefik.middlewares` block): the 29 internal services across `clusters/main/kubernetes/{apps,core,system,networking}/`. See `docs/plans/internal-vs-external-services-lockdown.md` for the full enumeration.
- Modify: `clusters/main/kubernetes/core/traefik/app/middleware-internal-allowlist.yaml` — confirm `ipStrategy.depth: 1` is correct now that real IPs are visible.

**Approach:**
- Programmatic: write a small script (`scripts/apply-internal-chain.sh`) that, for each internal-service helm-release.yaml, ensures `middlewares: [{name: internal-secure-chain, namespace: traefik}]` is set. Or do manually (~30 files).
- Test on one service first (longhorn — easy admin UI to validate).
- After each change, verify from LAN browser that the UI loads (allowlist accepts) and from cellular-no-VPN that it returns 403 (allowlist rejects).

**Patterns to follow:**
- Existing `goodmem`'s ingress already uses `traefik-secure-chain@kubernetescrd`. Same shape, different middleware name.

**Test scenarios:**
- Happy path: LAN client → longhorn.sf → loads.
- Happy path: cellular client → longhorn.sf → 403 (allowlist rejects external).
- Edge case: VPN client (192.168.3.x) → longhorn.sf → loads.
- Error path: middleware reference typo → Traefik logs `middleware does not exist`; ingress 502s. Catch in pilot.

**Verification:**
- All 29 internal services accessible from LAN/VPN, blocked from cellular-no-VPN.
- CrowdSec ban list still enforces (banned IPs blocked even if from LAN — bouncer runs first in the chain).

---

### Phase B — STP/LAG repatch

- U7. **Confirm cabling layout + plan repatch**

**Goal:** Re-verify current LLDP map matches what we mapped Apr 27, then plan the exact cable moves on the Aggregation side to make ports sequential per D1 strategy.

**Requirements:** R3, R8

**Dependencies:** None (independent of Phase A).

**Files:**
- No repo file. Output is a written cable-move list (live notes) confirming: which DAC cable currently plugged in `Aggregation pX` should move to `Aggregation pY`.

**Approach:**
- Run `./scripts/unifi-lag-config.sh check` and capture output to a temp file.
- Compare against expected D1 layout (Aggregation p1↔Pro48 p49, p2↔Pro48 p50, p3↔Pro48 p51, p4↔Pro48 p52, p5↔EXG p25, p6↔EXG p26).
- Identify the minimum move set (likely: swap Aggregation p3↔p4 cables, and EXG cable from p5→p6 or vice versa — depends on current).

**Test scenarios:**
- Verification only: LLDP table from `./scripts/unifi-lag-config.sh check` matches what we documented in the prior session.

**Verification:**
- Fresh check confirms 6 DAC cables, current STP-blocked ports unchanged.

---

- U8. **Physical re-patch**

**Goal:** Aggregation switch SFP+ port assignments are sequential per D1.

**Requirements:** R3

**Dependencies:** U7.

**Files:** None (physical work).

**Approach:**
- User performs at the rack. Move one cable at a time; expect STP reconvergence after each move (known noisy behavior already accepted).
- Order matters: move the cable that makes the smallest path-cost change first to minimize blackholes.

**Execution note:** Coordinate with low-traffic window. Each cable swap may trigger ~15s of STP convergence on connected switches.

**Test scenarios:**
- Happy path: after each move, `./scripts/unifi-lag-config.sh check` shows the expected new LLDP entry within 60s.
- Edge case: a swapped cable goes into a port that's misconfigured (e.g., Pro48 p52 still has Camera-VLAN access config from prior session) — STP may be slow to converge. Check `port_overrides` and clear any per-port stale config before swapping.
- Error path: cable damaged during swap → swap to a known-good DAC; verify with `sfp_found`/`sfp_compliance` API field.

**Verification:**
- LLDP shows: Agg p1↔Pro48 p49, p2↔Pro48 p50, p3↔Pro48 p51, p4↔Pro48 p52, p5↔EXG p25, p6↔EXG p26.

---

- U9. **Apply LAG via API + verify STP clears**

**Goal:** D1 strategy applied — 4-port LAG between Pro 48 PoE and Aggregation, 2-port LAG between EnterpriseXG and Aggregation. STP converges with ZERO ports in `discarding` because the LAG looks like one logical link.

**Requirements:** R3, R8

**Dependencies:** U8.

**Files:**
- Run: `scripts/unifi-lag-config.sh d1 --apply` (script is local; confirm latest version checked in).

**Approach:**
- Script verifies LLDP matches expected layout before applying.
- Reset Pro 48 PoE p52's port_overrides as part of the run (script handles).
- Wait 30-60s for LACP negotiation.
- Run `./scripts/unifi-lag-config.sh check` → expect zero `stp_state: discarding`.

**Test scenarios:**
- Happy path: zero discarding ports, all 6 SFP+ links forwarding, LAG bonded correctly (LACP partner state visible in UniFi UI).
- Edge case: cable on one LAG member is a different vendor/spec → LACP fails on that port. Script should surface in dry-run output.
- Error path: API rejects port_overrides batch (e.g., webhook validation) → script reports per-port; rollback by re-running script with no `--apply` to inspect what would be sent.
- 24-hour soak: no new STP block events.

**Verification:**
- `for mac in <EXG> <Pro48> <Agg>; do API call; done` shows no discarding ports.
- UniFi UI shows two LAG groups (4-port + 2-port) on Aggregation.

---

### Phase C — SonarQube self-host

- U10. **Create CNPG cluster + S3 backup secret for SonarQube**

**Goal:** Postgres 17 cluster `sonarqube-db` ready for SonarQube to consume. Daily Barman backup to MinIO.

**Requirements:** R4, R8

**Dependencies:** None (independent of A and B).

**Files:**
- Create: `clusters/main/kubernetes/system/sonarqube/app/cnpg-cluster.yaml`
- Create: `clusters/main/kubernetes/system/sonarqube/app/cnpg-barman.yaml`
- Create: `clusters/main/kubernetes/system/sonarqube/app/namespace.yaml`

**Approach:**
- Copy `clusters/main/kubernetes/system/goodmem/app/cnpg-cluster.yaml` as template; change name to `sonarqube-db`, drop the pgvector image (use default `ghcr.io/cloudnative-pg/postgresql:17.5-bookworm`).
- DB owner `sonarqube_user`, database `sonarqube`, postInitSQL: `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"` (SonarQube uses UUIDs).
- Storage 10Gi (SonarQube's own data is in PVC, just the metadata is in Postgres).
- Backup `s3://cnpg-sonarqube/`, daily 03:30 (avoid 03:00 collision with goodmem).

**Patterns to follow:**
- `clusters/main/kubernetes/system/goodmem/app/cnpg-{cluster,barman}.yaml`
- `clusters/main/kubernetes/apps/triparr-bot/app/cnpg-{cluster,barman}.yaml`

**Test scenarios:**
- Happy path: `kubectl get cluster.postgresql.cnpg.io -n sonarqube sonarqube-db` reports phase `Cluster in healthy state`.
- Edge case: Longhorn volume provisioning slow → CNPG initdb pod retries; expected per memory `project_longhorn_1_11_recovery`.
- Error path: image pull fails → verify image name + tag.

**Verification:**
- `kubectl exec -n sonarqube goodmem-db-1 -- psql -U postgres -c "\l"` lists `sonarqube` database.

---

- U11. **HelmRelease: SonarSource SonarQube chart with external CNPG**

**Goal:** SonarQube Community Build pod up and connected to `sonarqube-db-rw.sonarqube.svc.cluster.local`. Admin password from SOPS secret.

**Requirements:** R4, R8

**Dependencies:** U10.

**Files:**
- Create: `clusters/main/kubernetes/system/sonarqube/ks.yaml` (Flux Kustomization, points to `app/`)
- Create: `clusters/main/kubernetes/system/sonarqube/app/helm-release.yaml`
- Create: `clusters/main/kubernetes/system/sonarqube/app/sonarqube-secret.secret.yaml` (SOPS-encrypted; contains `SONARQUBE_ADMIN_PASS`)
- Create: `clusters/main/kubernetes/system/sonarqube/app/kustomization.yaml`
- Modify: `clusters/main/kubernetes/system/kustomization.yaml` — add `- sonarqube/ks.yaml`

**Approach:**
- HelmRepository: add `https://SonarSource.github.io/helm-chart-sonarqube` to flux-system if not present.
- Chart: `sonarqube` version `2026.1.0` or latest minor.
- Values:
  - `community.enabled: true` (Community Build, free)
  - `postgresql.enabled: false` (drop embedded)
  - `jdbcOverwrite.enabled: true`, `jdbcUrl: jdbc:postgresql://sonarqube-db-rw.sonarqube.svc.cluster.local:5432/sonarqube`
  - `jdbcOverwrite.jdbcUsername` from CNPG-managed `sonarqube-db-app` secret
  - `monitoringPasscode: <ref-to-sops-secret>`
  - `sonarProperties: {}` keep defaults
  - Resources: `requests: { cpu: 500m, memory: 2Gi }` `limits: { cpu: 2, memory: 4Gi }` — SonarQube needs ~3GB headroom.
- Keep `service.type: ClusterIP` — Traefik handles external access in U12.

**Patterns to follow:**
- `clusters/main/kubernetes/system/goodmem/app/helm-release.yaml` (vendor-direct chart + envFrom secret pattern)
- `clusters/main/kubernetes/core/ddns-cloudflare/app/ddns-secret.secret.yaml` (SOPS secret pattern)

**Test scenarios:**
- Happy path: `kubectl rollout status deploy -n sonarqube sonarqube-sonarqube --timeout=300s` succeeds. Pod ready.
- Edge case: SonarQube Java initial heap fails (OOM) → bump memory limits to 6Gi.
- Edge case: Postgres connection rejected → check JDBC URL syntax + CNPG auth user.
- Error path: chart adds an `ingress-nginx` dependency by default in 2026.x — disable explicitly (`ingress.enabled: false` from chart, we use Traefik via separate Ingress in U12).

**Verification:**
- Pod ready; `curl -s http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000/api/system/status` returns `{"status":"UP"}`.

---

- U12. **Ingress + DNS for sonarqube.sf.wethecommon.com**

**Goal:** Internal-only SonarQube admin UI at `https://sonarqube.sf.wethecommon.com`. LAN/VPN clients reach Traefik directly; tunnel returns 404.

**Requirements:** R4, R8

**Dependencies:** U11.

**Files:**
- Create: `clusters/main/kubernetes/system/sonarqube/app/ingress.yaml`
- Modify: Pi-hole `.3` via API (add A record `192.168.10.196 sonarqube.sf.wethecommon.com`)
- Modify: `clusters/main/kubernetes/core/blocky/app/helm-release.yaml` — add to customDNS mapping
- Modify: Cloudflare DNS — add A `sonarqube.sf.wethecommon.com` → `192.168.10.196` unproxied (split-horizon)

**Approach:**
- Ingress uses `traefik-secure-chain@kubernetescrd` middleware initially (existing chain that Phase 1 lockdown plan uses for goodmem). After Phase U6 lands, can swap to `internal-secure-chain` for the IP-allowlist behavior.
- cert-manager: same `wethecommon-prod-cert` issuer as everything else.
- Tunnel ingress allowlist (`docs/plans/internal-vs-external-services-lockdown.md` final state): **do not add sonarqube.sf to the list** — confirm via `cf-internal-lockdown.py` style audit that catch-all 404 still applies.

**Patterns to follow:**
- `clusters/main/kubernetes/system/goodmem/app/ingress.yaml` (recently created, same internal-only pattern)

**Test scenarios:**
- Happy path: `dig @192.168.10.3 +short sonarqube.sf.wethecommon.com` → `192.168.10.196`.
- Happy path: LAN browser → `https://sonarqube.sf.wethecommon.com` → SonarQube login.
- Cellular without VPN: `curl https://sonarqube.sf.wethecommon.com` → connection timeout (split-horizon DNS returns 192.168.10.196, unroutable from internet).
- Edge case: cert-manager DNS-01 challenge stalls (Cloudflare TXT record creation rate-limited) → expected on first deploy; should self-heal within minutes.

**Verification:**
- `dig @1.1.1.1 +short sonarqube.sf.wethecommon.com` returns `192.168.10.196` (CF authoritative answer).
- LAN access works, external doesn't.
- TLS cert valid (cert-manager Ready).

---

- U13. **Bootstrap admin + wire SonarQube CLI integration**

**Goal:** First login → reset default admin password → generate token → `sonar integrate claude` finishes step 4.a from earlier `/sonarqube:sonar-integrate` work.

**Requirements:** R4, R5

**Dependencies:** U12.

**Files:**
- No repo file. Manual user step + a written runbook entry in `clusters/main/kubernetes/system/sonarqube/README.md` documenting the bootstrap path.

**Approach:**
- Open `https://sonarqube.sf.wethecommon.com` from LAN, log in `admin/admin`, change to the SOPS-stored admin password.
- Settings → Security → Generate user token (User Token, name: `claude-cli`).
- Run `sonar auth login -s https://sonarqube.sf.wethecommon.com` — opens browser flow → token stored in macOS Keychain.
- Run `sonar integrate claude --non-interactive` (project-only flow, since we're inside the Talos-Cluster repo).

**Test scenarios:**
- Happy path: `sonar auth status` reports the connected server.
- Happy path: `/sonarqube:sonar-list-projects` (MCP) returns at least the no-projects-yet response.
- Error path: token rejected → SonarQube clock skew; verify pod time vs UDM time.

**Verification:**
- `sonar auth status` shows authenticated.
- `~/.claude/settings.json` (or per-project `.claude/settings.json`) has SonarQube MCP server registered.
- Secrets-scanning hook is wired (per `sonar integrate claude` output).

---

- U14. **First scan: `scripts/` baseline**

**Goal:** SonarQube reports its first findings against the `scripts/` directory (Python, Bash). Establishes a baseline so future work has comparison data.

**Requirements:** R5

**Dependencies:** U13.

**Files:**
- Create: `scripts/sonar-project.properties` (project key `talos-cluster-scripts`, sources path `.`)
- (Optional) Modify: `.gitignore` — already has `scripts/` ignored, so the properties file lives outside git. Or check it in by removing the gitignore entry for that one file with `!scripts/sonar-project.properties`.

**Approach:**
- `cd scripts/ && sonar scan` (uses local CLI to push to the cluster instance).
- Triage initial findings via `/sonarqube:sonar-list-issues` MCP tool. Decide which to fix vs accept.

**Execution note:** First scan baseline; not addressing findings here — that's per-PR follow-up work.

**Test scenarios:**
- Happy path: `scripts/` project visible in SonarQube UI with N issues, M coverage.
- Edge case: gitignored files cause empty scan → adjust `sonar.sources` to `.` and `sonar.exclusions` for noise.

**Verification:**
- `/sonarqube:sonar-quality-gate -p talos-cluster-scripts` returns a status (pass or fail with reasons).

---

### Phase D — Pi-hole blocklist refresh

- U15. **Identify replacement URLs + apply via Pi-hole API**

**Goal:** Three new working URLs replace or augment the dead ones. Pi-hole `.3` admin shows zero "list inaccessible" warnings on next gravity run.

**Requirements:** R6, R8

**Dependencies:** None (independent).

**Files:**
- No repo file (Pi-hole config is API-managed; not in GitOps).
- Update reference: optionally add a docs/runbook entry under `docs/runbooks/pihole-blocklists.md` listing the chosen blocklists for future re-evaluation.

**Approach:**
- Use the same auth pattern as `cf-internal-lockdown.py`-era Pi-hole work (`PIHOLE_BARE_METAL_PASS` from clusterenv).
- Disable list 85 (osint.digitalside.it — dead, no good replacement; remove rather than replace).
- Update list 97 URL to `https://gitlab.com/ZeroDot1/CoinBlockerLists/-/raw/master/hosts_browser` (the actual file, not the redirect-prone shortlink).
- Replace list 101 URL with `https://big.oisd.nl/dnsmasq` (canonical Pi-hole-format alternative to deprecated `dbl.oisd.nl/`).

**Test scenarios:**
- Happy path: After update, manual gravity run via API or UI completes with 0 warnings on the diagnosis page.
- Edge case: New URL returns 200 but has unexpected format → Pi-hole reports parse error. Catch in pre-check via `curl -I` before applying.
- Error path: replacement URL also dead at apply time → pause and pick a different alternative.

**Verification:**
- `kubectl logs -n networking pihole-k8s` shows 0 "WARNING: List with ID … was inaccessible" entries on subsequent gravity run.
- Diagnosis page in admin UI is clean.

---

- U16. **Sync to pihole-k8s (.244) + verify nebula-sync**

**Goal:** The .3 changes propagate to .244 within one nebula-sync cycle. Both Pi-holes show the same blocklist set.

**Requirements:** R6

**Dependencies:** U15.

**Files:**
- No repo file. Trigger nebula-sync via `kubectl rollout restart deployment -n networking nebula-sync`.

**Approach:**
- After U15, restart nebula-sync to force an immediate sync.
- Confirm `.244` admin UI's adlist page matches `.3`.

**Test scenarios:**
- Happy path: `kubectl logs -n networking nebula-sync-...` shows successful sync.
- Edge case: nebula-sync auth fails because `PIHOLE_K8S_PASS` rotated — out of scope; flag and defer.

**Verification:**
- `kubectl exec -n networking pihole-k8s-... -- curl -s http://localhost/admin/api.php?action=getCustomDNS` (or v6 equivalent) shows the same lists as .3.

---

## System-Wide Impact

- **Interaction graph:** Phase A is the highest blast radius — touches every LB service. Phases B-D are bounded.
- **Error propagation:** Phase A failure (Cilium agent crash, BGP misconfig) takes down all LB services. Mitigation: pilot service U4, parallel-advertise U1-U3 before mass cutover U5, MetalLB stays installed for one-week rollback window.
- **State lifecycle risks:**
  - Phase A: stale ARP entries in client devices for the LB IPs; `arp -d` to flush if connectivity issues persist post-U5.
  - Phase C: SonarQube first-run schema migration on the CNPG database — irreversible. Snapshot before migration to allow rollback.
- **API surface parity:** Phase U6 changes the Traefik middleware annotation on 29 ingresses. Ensure no service accidentally drops the bouncer (CrowdSec) — `internal-secure-chain` includes both bouncer + allowlist.
- **Integration coverage:**
  - Phase A: end-to-end path test with real client IP visible across cellular VPN, LAN, and pod-to-LB. Unit tests don't prove the SNAT removal.
  - Phase C: SonarQube → CNPG → backup → restore drill (deferred to Operational Notes; not blocking).
- **Unchanged invariants:**
  - Phase 1 (DNS lockdown) split-horizon stays exactly as-is. Internal hostnames continue to resolve to 192.168.10.196 from public DNS, locally to the same.
  - Cloudflare tunnel ingress allowlist (22 hosts) unchanged. SonarQube does NOT get added to it.
  - Cloudflare Access policies on tools/search/pdf/paperless unchanged.
  - DDNS CronJob unchanged.

---

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Cilium BGP misconfig blackholes all LB traffic | Medium | High | Pilot U4 first; MetalLB L2 stays disarmable for rollback; cutover during low-traffic window |
| UDM-SE BGP firmware quirks | Low | Medium | Verify session establishes in U2 before U3 advertisement; have FRR config ready to revert |
| Talos control-plane API blip during Cilium agent restart | Low | Medium | Cilium agent restarts in rolling fashion; BGP graceful restart configured; U1 verifies pod readiness before proceeding |
| Physical re-patch causes wrong-port swap | Low | Medium | One cable at a time; LLDP verifies after each move (~60s convergence) |
| LAG breaks if Aggregation switch firmware lacks LACP support for these ports | Very Low | High | All three switches confirmed LAG-capable in prior session research |
| SonarQube needs more than 4Gi RAM | Medium | Low | Resource limits are easy to bump; not blocking |
| Pi-hole blocklist URLs go dead again | Medium | Very Low | Re-runs of this Phase are cheap; consider a periodic check via cron |

---

## Phased Delivery

### Phase A — Cilium BGP migration (Deep, foundational)

Sequential dependencies: U1 → U2 (parallelizable) → U3 → U4 (pilot) → U5 (mass cutover) → U6 (security finalization).

Estimated wall-clock: 3-4 hours, ideally during a maintenance window with rollback runway.

### Phase B — STP/LAG repatch (Standard, physical)

Sequential: U7 → U8 (physical, requires user at rack) → U9.

Estimated wall-clock: 30-60 minutes once at the rack. Can happen in parallel to Phase C if user is comfortable with two changes.

### Phase C — SonarQube self-host (Standard, isolated)

Sequential: U10 → U11 → U12 → U13 → U14.

Estimated wall-clock: 1-2 hours active + 24h Renovate cycle for chart updates.

### Phase D — Pi-hole blocklist refresh (Lightweight)

Sequential: U15 → U16.

Estimated wall-clock: 15 minutes.

---

## Documentation Plan

- After U6, update `docs/plans/internal-vs-external-services-lockdown.md` to mark Phase 3 (IP allowlist middleware) as ✅ DONE and link to this plan's U6.
- After C, write `clusters/main/kubernetes/system/sonarqube/README.md` capturing the bootstrap procedure (admin password reset + token + `sonar integrate claude`).
- After Phase A, update memory note `project_unifi_optimization.md` (or create a new memory file) with the new BGP-based architecture so future sessions know not to re-suggest proxyProtocol.

---

## Operational / Rollout Notes

- **Phase A maintenance window**: pick a low-traffic time. Family/streaming usage = avoid evenings. Early morning weekend recommended. Set Uptime Kuma to a maintenance pause to suppress noise alerts.
- **Phase A rollback**: re-add `L2Advertisements:` to `metallb-config/app/helm-release.yaml`, force flux reconcile. Cilium BGP can stay enabled (it's parallel-advertising); MetalLB regains L2 ARP authority within ~60s.
- **Phase B cabling pause**: while at the rack, also document any other cabling weirdness for future cleanup (e.g., MoCA Bedroom Desk path decision from prior memory).
- **Phase C SonarQube version pin**: Renovate is enabled per repo convention; pin the chart version with a `# renovate: ...` comment to control upgrades.
- **Phase D periodic review**: blocklist URLs rot. Add a quarterly review item to `memory/project_ongoing_maintenance.md`.

---

## Sources & References

- Origin context: this session's conversation thread following `internal-vs-external-services-lockdown.md` completion.
- Prior plans: [`docs/plans/internal-vs-external-services-lockdown.md`](../plans/internal-vs-external-services-lockdown.md) (Phase 3 deferred from there is finalized in U6 here).
- Prior research: `~/.claude/plans/smooth-napping-steele.md` (Apr 27 STP research; superseded by this plan).
- Existing patterns: `clusters/main/kubernetes/system/goodmem/`, `clusters/main/kubernetes/apps/triparr-bot/`, `clusters/main/kubernetes/core/traefik/app/middleware-*.yaml`.
- External: [Cilium BGP docs](https://docs.cilium.io/en/latest/network/bgp/), [Stonegarden BGP+UniFi walkthrough](https://blog.stonegarden.dev/articles/2025/11/bgp-cilium-unifi/), [Ubiquiti BGP support](https://help.ui.com/hc/en-us/articles/16271338193559-UniFi-Border-Gateway-Protocol-BGP), [SonarSource Helm chart](https://github.com/SonarSource/helm-chart-sonarqube), [SonarQube external DB customization](https://docs.sonarsource.com/sonarqube-community-build/server-installation/on-kubernetes-or-openshift/customizing-helm-chart).
- Local script: `scripts/unifi-lag-config.sh` (D1 strategy implementation, gitignored).
