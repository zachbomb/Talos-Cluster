#!/bin/bash
# /data/on_boot.d/15-cluster-bgp.sh — installed on UDM-SE only
#
# Persists Cilium BGP peering with k8s-control-1 across UDM reboots and
# UniFi reprovisioning events. UniFi can wipe /etc/frr/{frr.conf,daemons}
# during firmware updates or settings applies, so this re-applies them.
#
# IMPORTANT: This script does NOT enable proxy_arp / proxy_arp_pvlan on br0.
# An earlier version did, but that was too broad — Linux's proxy ARP
# responds for ANY IP UDM has a route to (including the cluster node .89
# and VIP .167), which intercepted control-plane traffic and caused an
# outage during a Proxmox reboot. Cilium L2 Announcements (configured in
# the cluster) is now the correct mechanism: the cluster node answers
# ARP for LB IPs directly via eBPF, scoped per-IP.
#
# Companion to: docs/network/udm-se-bgp.md
# Plan: docs/plans/2026-05-05-002-feat-cilium-l2-announcements-plan.md

set -euo pipefail

# 1. Ensure bgpd is enabled (UniFi may reset /etc/frr/daemons)
sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons

# 2. Make sure FRR is running
if ! systemctl is-active --quiet frr; then
  systemctl start frr
  sleep 3
fi

# 3. Re-apply BGP config (idempotent — vtysh ignores no-op reconfigs)
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

# 4. Install cron healthcheck so this script self-heals if FRR crashes mid-day
#    or if /etc/frr/* gets wiped by a UniFi reprovisioning event between reboots.
#    Idempotent: the script does nothing when BGP is healthy, restores when it isn't.
#    /etc/cron.d/ may not persist across reboots, but on_boot.d re-creates it.
cat > /etc/cron.d/cluster-bgp-healthcheck <<'CRON'
# Auto-installed by /data/on_boot.d/15-cluster-bgp.sh
# Re-runs the BGP setup every 5 min. Idempotent — vtysh skips no-op
# reconfigs and systemctl skips already-running services.
*/5 * * * * root /data/on_boot.d/15-cluster-bgp.sh >/dev/null 2>&1
CRON
chmod 644 /etc/cron.d/cluster-bgp-healthcheck

logger -t cluster-bgp "BGP applied via on_boot.d (Cilium L2 handles ARP cluster-side); cron healthcheck installed"
