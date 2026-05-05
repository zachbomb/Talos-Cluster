#!/bin/bash
# /data/on_boot.d/15-cluster-bgp.sh — installed on UDM-SE only
#
# Persists Cilium BGP peering with k8s-control-1 across UDM reboots and
# UniFi reprovisioning events. UniFi can wipe /etc/frr/{frr.conf,daemons}
# during firmware updates or settings applies, so this re-applies them.
#
# Companion to: docs/network/udm-se-bgp.md
# Plan: docs/plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md

set -euo pipefail

# 1. Ensure bgpd is enabled (UniFi may reset /etc/frr/daemons)
sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons

# 2. Make sure FRR is running
if ! systemctl is-active --quiet frr; then
  systemctl start frr
  sleep 3
fi

# 3. Same-subnet proxy ARP for BGP-learned /32 routes.
#    proxy_arp + proxy_arp_pvlan together let UDM respond to ARP for any
#    IP it has a route to via br0 (BGP-learned routes included).
sysctl -w net.ipv4.conf.br0.proxy_arp=1 >/dev/null
sysctl -w net.ipv4.conf.br0.proxy_arp_pvlan=1 >/dev/null

# 4. Re-apply BGP config (idempotent — vtysh ignores no-op reconfigs)
vtysh <<'EOF'
configure terminal
ip prefix-list CLUSTER-LB seq 10 permit 192.168.10.192/26 ge 32 le 32
ip prefix-list CLUSTER-LB seq 99 deny any
route-map FROM-CLUSTER permit 10
 match ip address prefix-list CLUSTER-LB
exit
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
exit
end
write memory
EOF

logger -t cluster-bgp "BGP + proxy_arp_pvlan applied via on_boot.d"
