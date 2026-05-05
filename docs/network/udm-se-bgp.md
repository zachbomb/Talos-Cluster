# UDM-SE BGP Configuration

**Companion to:** [Cilium BGP migration plan](../plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md) (Phase A, U2)

## Topology

```
UDM-SE (192.168.10.1, AS 64513)  ⇄ TCP/179 ⇄  k8s-control-1 (192.168.10.89, AS 64512)
                                                       │
                                                Cilium BGP control plane
                                                       │
                                          advertises LoadBalancer service IPs as /32
```

UDM-SE peers with the cluster's Cilium BGP speaker; cluster advertises its
MetalLB-allocated LoadBalancer IPs (192.168.10.193-254) as /32 routes.
UDM-SE installs them in its routing table and forwards traffic from clients
that route via the gateway (off-subnet clients, BGP-aware peers).

## FRR config to upload to UDM-SE

Paste this in **UniFi Network → Settings → Routing → BGP** (firmware ≥ 4.1.13).

```frr
! UDM-SE BGP config — peer with Cilium on k8s-control-1
! AS 64513 (UDM) ↔ AS 64512 (cluster)

ip prefix-list CLUSTER-LB seq 10 permit 192.168.10.192/26 ge 32 le 32
ip prefix-list CLUSTER-LB seq 99 deny any

route-map FROM-CLUSTER permit 10
 match ip address prefix-list CLUSTER-LB

router bgp 64513
 bgp router-id 192.168.10.1
 no bgp ebgp-requires-policy
 neighbor 192.168.10.89 remote-as 64512
 neighbor 192.168.10.89 description k8s-cilium
 neighbor 192.168.10.89 timers 10 30
 neighbor 192.168.10.89 timers connect 12

 address-family ipv4 unicast
  neighbor 192.168.10.89 activate
  neighbor 192.168.10.89 route-map FROM-CLUSTER in
  neighbor 192.168.10.89 soft-reconfiguration inbound
  maximum-paths 1
 exit-address-family
```

### What each block does

- **`ip prefix-list CLUSTER-LB`**: filter that only accepts /32 routes within
  192.168.10.192/26 (covers .192-.255, a superset of the MetalLB pool .193-.254).
  Anything else from the cluster is dropped.
- **`route-map FROM-CLUSTER permit 10`**: applies the prefix-list to inbound
  routes from the cluster.
- **`no bgp ebgp-requires-policy`**: FRR ≥7.4 requires explicit route-map for
  eBGP. We do have one inbound, but disabling the global requirement makes
  troubleshooting easier (no unexpected drops if route-map is mistyped).
- **`timers 10 30`**: keepalive 10s, holdtime 30s. Tighter than default
  (60/180) so failover from a flapping cluster is sub-minute.
- **`timers connect 12`**: 12s between dial attempts when session is down.
- **`soft-reconfiguration inbound`**: keeps a copy of received routes
  pre-policy, so `show bgp neighbor 192.168.10.89 received-routes` works.
- **`maximum-paths 1`**: single-node cluster — only one ECMP path, prevents
  half-baked load balancing if the field is left at default.

## Verification (from UDM-SE SSH)

```bash
ssh root@192.168.10.1
# session state should reach Established within ~30s
vtysh -c "show bgp summary"
# should list a /32 route per active LoadBalancer service
vtysh -c "show bgp ipv4 unicast"
# inspect the neighbor specifically
vtysh -c "show bgp neighbors 192.168.10.89"
```

## Verification (from cluster)

```bash
CILIUM_POD=$(kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n kube-system "$CILIUM_POD" -c cilium-agent -- cilium-dbg bgp peers
# Session should be 'established'
kubectl exec -n kube-system "$CILIUM_POD" -c cilium-agent -- cilium-dbg bgp routes advertised ipv4 unicast
# Should list every active LB service IP as a /32
```

## Persistence note

UniFi-applied BGP config persists across `forgetool talos` operations
because it lives on the UDM-SE side (FRR `/etc/frr/bgpd.conf`), not on the
cluster nodes. Talos firmware operations only touch cluster nodes.

## Rollback

Either:
- **UI**: clear the BGP config in Settings → Routing → BGP and apply.
- **SSH**: `vtysh -c "configure terminal" -c "no router bgp 64513"`

The cluster side will revert to MetalLB L2 advertisements (still active
through Phase A — they're not removed until U5).
