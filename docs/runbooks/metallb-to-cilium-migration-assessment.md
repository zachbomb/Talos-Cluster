# MetalLB → Cilium LB-IPAM migration — impact assessment

Deep audit performed 2026-06-10 to decide whether to remove MetalLB and consolidate
LoadBalancer IP management on Cilium, and to assess blast radius before doing so.

## TL;DR

**Decision: Cilium is correct.** For a single-node cluster, MetalLB is redundant —
Cilium already does L2 announcement (sole announcer) AND BGP. MetalLB is reduced to
**IP allocation (IPAM) only**, and its `frr-k8s`/`speaker` pods are dead weight
(the source of the 427-restart churn).

**But the migration is NOT trivial:** 45 LoadBalancer services carry MetalLB-specific
annotations that must be converted, including 2 shared-IP groups that use a different
mechanism in Cilium. It's a planned, staged operation — not a quick swap.

**Risk: LOW-to-MEDIUM, well understood.** The riskiest part (L2 announcement) is
*already on Cilium and stable*. The remaining work is IPAM cutover + annotation
conversion, both reversible.

## What the audit found

### MetalLB's actual role (much smaller than it looks)

| Component | What it does | Status |
|---|---|---|
| `metallb-controller` | **IPAM** — allocates IPs from pools to services with the pin annotation | The only load-bearing MetalLB function |
| `metallb-speaker` | L2/ARP announcement | **Announces NOTHING** — no `L2Advertisement` exists (removed 2026-05-05) |
| `metallb-frr-k8s` | BGP speaker backend | **100% dead** — 0 BGPPeers/Advertisements, `vtysh` → "BGP instance not found". Source of the 427 restarts. |

IPAddressPools: `main` (192.168.10.193-254) + `bgp-pilot` (.192), both `autoAssign: false`
(pin-only — services get an IP only via `metallb.io/loadBalancerIPs`).

### Cilium already owns announcement + BGP

- **L2 announcement** — `enable-l2-announcements: true`, `default-l2-policy`
  (serviceSelector `app.kubernetes.io/managed-by=Helm`), per-service
  `cilium-l2announce-*` leases (some 20 days old), all 43 LB services covered.
  **This is the sole, working announcer.**
- **BGP** — `CiliumBGPClusterConfig` (udm-bgp → UDM-SE at 192.168.10.1, ASN 64512→64513),
  `CiliumBGPAdvertisement` (lb-services, advertises LoadBalancerIP for Helm services),
  `CiliumBGPPeerConfig`. **NOTE: the BGP session is currently DOWN** (state "active",
  0 routes advertised). This is NOT load-bearing — LB IPs (.193-254) are in the UDM's
  directly-connected LAN subnet, so the UDM reaches them via ARP/L2 regardless of BGP.
  BGP would only matter for an off-subnet LB CIDR, which this cluster doesn't have.
  (Worth a separate look at why the session is "active"/not-established, but it does
  not block this migration and isn't breaking access today.)

### Migration scope (the work)

- **43 helm-releases** set `metallb.io/loadBalancerIPs: ${APP_IP}` → convert to
  `lbipam.cilium.io/ips: ${APP_IP}`
- **2 shared-IP groups (4 services)** use `metallb.io/allow-shared-ip` → convert to
  `lbipam.cilium.io/sharing-key`:
    - deluge + deluge-torrent share .223 (key "deluge"), ports 8112 + 6881
    - ollama + ollama-api share .202 (key "ollama"), ports 10686 + 11434
- **Remove** `system/metallb` (operator) + `core/metallb-config` (IPAM config)
- **clustertool/forgetool embed MetalLB in their base template** (`metallb` +
  `metallb-config` components, `${METALLB_RANGE}`). A future `clustertool init` would
  reintroduce it — but that's a manual bootstrap action, not something that runs on
  `genconfig`/Flux. Document the divergence; don't let a re-init silently re-add it.

## What could break (honest risk table)

| Risk | Severity | Mitigation |
|---|---|---|
| L2 announcement stops | **None** — already 100% on Cilium, unchanged by removing MetalLB | n/a |
| Dual-IPAM contention during cutover (both MetalLB + Cilium try to allocate) | Medium | Add CiliumLoadBalancerIPPool, then migrate annotations service-by-service (or batch), THEN remove MetalLB last. Or disable MetalLB controller before mass-converting. |
| Shared-IP services (deluge, ollama) break | Medium | Cilium uses `lbipam.cilium.io/sharing-key` + requires matching `lbipam.cilium.io/ips`. Test deluge first (least critical). Note: Cilium sharing has stricter rules (same sharing-key services must not have port conflicts — deluge-torrent has 6881 twice, verify). |
| A service silently loses its pinned IP (esp. DNS .195 blocky, Traefik .196) | Medium | Convert + verify one at a time for the critical IPs; confirm `lbipam.cilium.io/ips` honored via service status condition `io.cilium/lb-ipam-request-satisfied`. |
| clustertool re-init re-adds MetalLB | Low | Manual action only; document the intentional removal. |
| Cilium past issues recur | Low | Past issues were `externalTrafficPolicy: Local` (use Cluster on single-node — already applied), NetworkPolicy enforcement, and EPERM transients — **none about L2/LB-IPAM reliability**, which has run stably as sole announcer. |

## Migration plan (staged, when ready — NOT urgent)

**Phase 0 — quick win (optional, kills the churn without migrating):**
Disable MetalLB `speaker` + `frr-k8s` in `system/metallb` helm values (they announce
nothing; Cilium does). Keep the controller for IPAM. Removes the 427-restart source.
Verify metallb chart 0.16.1 supports `speaker.enabled: false` / controller-only.

**Phase 1 — stand up Cilium IPAM (no cutover yet):**
- Add `CiliumLoadBalancerIPPool` with `blocks: [{start: 192.168.10.192, stop: 192.168.10.254}]`
- Leave MetalLB running; services still pinned via metallb annotations (Cilium pool
  won't fight because services already satisfied)

**Phase 2 — migrate services in batches (low-risk first):**
- Convert `metallb.io/loadBalancerIPs` → `lbipam.cilium.io/ips` per helm-release
- Order: a throwaway/non-critical app → media *arr apps → shared-IP (deluge, ollama)
  → DNS-critical LAST (blocky .195, Traefik .196)
- After each: confirm the service keeps its exact IP + `io.cilium/lb-ipam-request-satisfied=True`

**Phase 3 — remove MetalLB:**
- Delete `system/metallb` + `core/metallb-config` helm-releases + namespaces
- Remove `${METALLB_RANGE}` from clusterenv (or leave as harmless var)
- Note the clustertool-base-template divergence

**Rollback at any phase:** revert the annotation change(s); MetalLB controller
re-allocates from its pool. Keep MetalLB installed until Phase 3 is verified.

## Recommendation

Do **Phase 0** as a safe quick win whenever (kills the churn, ~5 min). Treat
**Phases 1-3** as a planned maintenance operation — the work is mechanical but touches
DNS-critical IPs, so it deserves a focused window with the rollback path ready, not a
tail-end-of-a-long-session change. The architecture decision (Cilium) is sound and
low-risk; the execution just needs care on the 45 annotation conversions + 2 shared-IP
groups.
