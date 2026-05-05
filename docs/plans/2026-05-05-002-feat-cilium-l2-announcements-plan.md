---
title: Cilium L2 Announcements migration (U5b)
status: draft
date: 2026-05-05
parent: docs/plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md
---

# Cilium L2 Announcements — Phase A Completion

## Why this exists

Phase A's primary goal was **preserve real LAN client IPs at Traefik** so the
internal-allowlist + CrowdSec bouncer can enforce per-IP policy. The original
plan (U1-U5) attempted:

> Cilium BGP advertises LB /32s to UDM-SE → UDM proxy_arp_pvlan answers ARP for
> same-subnet LAN clients → traffic routes UDM→.89→Cilium eBPF → real IP preserved

The U4 pilot **proved the concept works** — uptime-kuma at `192.168.10.192`
saw real LAN client IP `192.168.10.154` in its logs. But U5 mass-cutover
exposed an architecture flaw: Linux's `proxy_arp + proxy_arp_pvlan` is
all-or-nothing — UDM started answering ARP for ANY IP it had a route to via
br0, including the cluster node IP `192.168.10.89` and VIP `192.168.10.167`.
After a Proxmox host reboot took the cluster VM offline, UDM kept claiming
those IPs (because BGP routes to them existed even though the next-hop was
down), making the cluster API unreachable from LAN.

**U5 was rolled back.** MetalLB L2 is currently re-enabled. Real client IPs
are NOT preserved at Traefik (kube-proxy SNAT path). U6 is blocked.

The fix: **Cilium L2 Announcements** — Cilium agent answers ARP for
LB IPs from the cluster node itself (not from UDM proxy ARP). This:

- Scopes ARP responses to **only** the IPs Cilium is configured to announce
  (via `CiliumL2AnnouncementPolicy`), never the node/VIP IPs.
- Integrates with `kubeProxyReplacement: true` so eBPF datapath handles the
  packet without SNAT (when `externalTrafficPolicy: Local`).
- Replaces MetalLB L2 cleanly. MetalLB IPAM (the `IPAddressPool`) can stay or
  be migrated to `CiliumLoadBalancerIPPool` — orthogonal decision.
- Coexists with the existing Cilium BGP advertisement (for off-subnet/VPN
  clients that route via UDM).

Reference: [Cilium docs — Layer 2 Announcements](https://docs.cilium.io/en/stable/network/l2-announcements/)

## Pre-requisites (already in place)

- ✅ Cilium 1.18.6 with `kubeProxyReplacement: true`
- ✅ BGP control plane enabled + UDM-SE peering established
- ✅ MetalLB L2 currently active (rollback safety net)
- ✅ UDM-SE `/data/on_boot.d/15-cluster-bgp.sh` only enables BGP/proxy ARP for
  the BGP-only direction; same-subnet ARP for LB IPs comes from MetalLB today

## High-level steps

### Phase A.bis (this plan): switch from MetalLB L2 → Cilium L2

1. **U5b.1** Enable Cilium L2 announcements in helm-release values
2. **U5b.2** Create `CiliumL2AnnouncementPolicy` selecting LB services
3. **U5b.3** Verify Cilium answers ARP from `.89` for at least uptime-kuma
4. **U5b.4** Disable MetalLB `L2Advertisements` (mass cutover redux)
5. **U5b.5** Verify all LB services reachable + real client IPs preserved
6. **U5b.6** Set `externalTrafficPolicy: Local` on Traefik (the IP-preservation
   linchpin) — this is the single change that actually makes real IPs visible
7. **U5b.7** Re-attempt U6 (internal-secure-chain on 29 ingresses)

## Key Cilium configuration (proposed)

### Helm-release additions to `clusters/main/kubernetes/kube-system/cilium/app/helm-release.yaml`

```yaml
values:
  # ... existing ...
  l2announcements:
    enabled: true
    # tighter leaseDuration for fast failover (we're single-node so leader
    # election is essentially a no-op, but the field is required)
    leaseDuration: 15s
    leaseRenewDeadline: 5s
    leaseRetryPeriod: 2s
  k8sClientRateLimit:
    qps: 50
    burst: 100
  # required for L2 announcements to work
  externalIPs:
    enabled: true
```

### New CRD: `CiliumL2AnnouncementPolicy`

```yaml
---
apiVersion: cilium.io/v2alpha1
kind: CiliumL2AnnouncementPolicy
metadata:
  name: default-l2-policy
  namespace: kube-system
spec:
  # Match all helm-managed LoadBalancer services (same selector as our
  # CiliumBGPAdvertisement so L2 + BGP cover the same set)
  serviceSelector:
    matchLabels:
      app.kubernetes.io/managed-by: Helm
  nodeSelector:
    matchLabels:
      kubernetes.io/hostname: k8s-control-1
  interfaces:
    - eth0   # ← needs verification — Talos VM bond/bridge name
  externalIPs: false
  loadBalancerIPs: true
```

### Coordination with existing BGP

Both `CiliumBGPAdvertisement` (already in place) and `CiliumL2AnnouncementPolicy`
match the same Service set via the same `app.kubernetes.io/managed-by: Helm`
label. They cover different network paths:

| Path | Mechanism | Use case |
|------|-----------|----------|
| Same-subnet LAN client | Cilium L2 ARP from `.89` | LAN browser → uptime.sf |
| Off-subnet (VPN, multi-LAN) | UDM-SE BGP route via `.89` | WireGuard client → uptime.sf |

After U5b lands, both work simultaneously without conflict (BGP route is more
specific than the LAN /24 connected route, but same-subnet clients ARP first).

## Failure modes + rollbacks

| Failure | Symptom | Rollback |
|---------|---------|----------|
| L2 announcement doesn't fire | LAN client times out on LB IP after L2 disabled | re-add `L2Advertisements:` block to metallb-config helm-release |
| ARP responder picks wrong interface | Some clients reach LB IP, others don't | adjust `interfaces:` in the policy |
| Real client IP NOT preserved despite L2 | Traefik logs still show 172.16.x.x | flip Traefik service to `externalTrafficPolicy: Local`; if Local breaks per CLAUDE.md gotcha, set `loadBalancer.algorithm: maglev` and `loadBalancer.dsrDispatch: opt` for DSR mode |
| Cilium agent CrashLoop after L2 enabled | Pods unschedulable | suspend HelmRelease, scale agent to 0, fix config, resume |

The MetalLB L2 path can be re-enabled in <30 seconds by re-adding the
`L2Advertisements` block. Keep that rollback documented and ready.

## Pre-flight checks before executing

1. Confirm node interface name (`eth0` is a guess; could be `bond0` or `cilium_host`)
2. Confirm BGP session uptime > 1 day (stable baseline)
3. Audit any service NOT labeled `app.kubernetes.io/managed-by: Helm` —
   should be zero (was zero on 2026-05-05) but recheck before cutover
4. Take a `flux suspend` snapshot of metallb-config so the rollback path
   is `flux suspend` → re-edit values → `flux resume`

## Implementation Units

### U5b.1 — Enable Cilium L2 announcements

**Goal:** `cilium-config.enable-l2-announcements=true` in ConfigMap, agent
restarts cleanly, no service traffic disrupted (MetalLB L2 still active in
parallel).

**Files:** Modify `clusters/main/kubernetes/kube-system/cilium/app/helm-release.yaml`

**Verification:**
- `kubectl get cm cilium-config -n kube-system -o jsonpath='{.data.enable-l2-announcements}'` → `true`
- `kubectl get pods -n kube-system -l k8s-app=cilium` shows Cilium agent restarted, Ready 1/1
- `cilium-dbg config get | grep -i l2` shows L2 announcement settings
- All LB services still reachable (MetalLB is doing the work right now)

### U5b.2 — Add `CiliumL2AnnouncementPolicy`

**Goal:** policy applied, Cilium picks it up, but ARP responses don't yet take
effect because MetalLB is still answering first. Useful as dry-run setup.

**Files:**
- Create `clusters/main/kubernetes/kube-system/cilium/app/l2-announcement-policy.yaml`
- Modify `clusters/main/kubernetes/kube-system/cilium/app/kustomization.yaml`

**Verification:**
- `kubectl get ciliuml2announcementpolicy -A` shows the policy
- `cilium-dbg statedb l2-announcements` shows the matched services
- `cilium-dbg shell -- db/show l2-announce` lists active announcements

### U5b.3 — Verify Cilium L2 path on the pilot service

**Goal:** Confirm Cilium answers ARP for the bgp-pilot pool's `.192` (uptime-kuma's
old pilot IP) when MetalLB doesn't.

**Approach:** uptime-kuma is currently on `.245` in the L2-advertised pool. To
test, temporarily move it back to `.192` (BGP-only pool, no L2Advertisement).
With Cilium L2 + bgp-pilot pool, the same end-to-end test from U4 should work
**without** the UDM proxy_arp_pvlan workaround.

**Verification:**
- LAN client → `arp -d 192.168.10.192; curl http://192.168.10.192:3001/`
- ARP table shows `.192` mapped to **cluster node MAC** (not UDM's MAC)
- uptime-kuma logs show real LAN client IP

If verification fails, fix policy/interface before proceeding.

### U5b.4 — Disable MetalLB L2 (mass cutover redux)

**Goal:** Same as the original U5 — remove `L2Advertisements:` block from
metallb-config helm-release. This time Cilium L2 is the safety net, not UDM
proxy ARP.

**Files:** Modify `clusters/main/kubernetes/core/metallb-config/app/helm-release.yaml`

**Verification:**
- `kubectl get l2advertisements.metallb.io -A` empty
- All LB services still reachable from LAN (Cilium is now answering ARP)
- ARP table on a LAN client shows cluster node MAC for ALL LB IPs
- Traefik logs still show real client IPs (with `externalTrafficPolicy: Cluster`
  on a single-node cluster — this is the Phase A behavior we observed in U4)

### U5b.5 — Optional: flip Traefik to `externalTrafficPolicy: Local`

**Goal:** Belt-and-suspenders for IP preservation. CLAUDE.md says Local breaks
single-node — but the gotcha was specifically about MetalLB L2 + Local
combination. With Cilium L2, this pairing might work and is the canonical
"preserve client IP" config.

**Approach:** Test first by patching just Traefik. Verify with:
- LAN client → `https://uptime.sf.wethecommon.com` → Traefik logs show real IP
- Off-subnet/VPN client → same — works

If breaks, leave Traefik as `Cluster` and rely on the single-node-no-SNAT
behavior we observed in U4.

### U5b.6 — Apply internal-secure-chain to 29 internal ingresses (was U6)

Same as the deferred U6 — replace `<app>-tc-basic-secure-headers` with
`traefik-internal-secure-chain@kubernetescrd` on the 29 internal-only
ingresses. With real client IPs preserved, the IP allowlist + CrowdSec bouncer
finally enforce per-IP policy.

## Open questions

1. **Interface name** — Is the cluster node's primary NIC `eth0`, `bond0`, or
   something else from a Talos perspective? Check `kubectl get nodes -o yaml |
   grep -A2 addresses` and `cilium-dbg shell -- ip a`.
2. **DSR vs. eTP=Local** — both can preserve client IPs. Which matches the
   single-node-cluster reality better?
3. **Same selector for L2 and BGP?** — using
   `app.kubernetes.io/managed-by: Helm` for both is simplest. Alternative:
   different label per intent (e.g., L2 for "needs-LAN-reach", BGP for
   "needs-VPN-reach"). Probably overkill.

## Out of scope

- MetalLB → CiliumLoadBalancerIPPool migration (IPAM swap; orthogonal)
- Decommissioning MetalLB entirely (leave it running for IPAM only)
- Multi-node cluster considerations (single-node now; revisit when expanding)

## Estimated effort

- U5b.1 + U5b.2 + U5b.3: 30 min (config changes + verification)
- U5b.4: 10 min (one-line removal + reconcile + verify)
- U5b.5: 15 min (test + decide)
- U5b.6: 60-90 min (29 ingresses, programmatic apply via script)

Total: ~2 hours when executed end-to-end.

## Status

- 2026-05-05: Plan drafted post-U5 rollback.
- TODO: Verify pre-flight check #1 (interface name) before executing.
