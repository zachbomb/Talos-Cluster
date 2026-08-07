#!/usr/bin/env python3
"""Storage and Network ENVIRONMENT dashboards.

Same four-questions layout as Media. Both aggregate several services to answer
one question about the environment, rather than stacking per-component charts.

Q1 IS ONLY AS GOOD AS THE ALERT RULES BEHIND IT. Counting rules by domain
before building these found Storage with 38 and the ENTIRE network path with
3 - all three node-level NIC counters, nothing for Traefik, Blocky, MetalLB,
Cloudflared or CoreDNS. So prometheusrule-network.yaml was written alongside
this board; without it the Network Q1 row would have been structurally
incapable of ever showing anything.

TWO MEASUREMENT TRAPS FOUND WHILE BUILDING, both avoided here:

  truenas_pool_scan_percentage reads 101.17 during/after a scrub. A gauge with
  max=100 would clamp it to full-red and imply a problem. It is a stat.

  longhorn_volume_actual_size_bytes (886 GB) EXCEEDS
  longhorn_node_storage_capacity_bytes (411 GB) - they count different things
  (replicas vs node-local). Any used-vs-capacity panel built from that pair
  would be nonsense, so capacity is shown from PVC and TrueNAS metrics, which
  are internally consistent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import (  # noqa: E402
    Q1, Q2, Q3, Q4, alert_table, bargauge, dashboard, emit_configmap, gauge,
    row, stat, stat_floor, timeseries)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "../../clusters/main/kubernetes/system/"
                   "kube-prometheus-stack/app")

# =====================================================  STORAGE  ============
STORAGE = [
    row(Q1, 0),
    stat("TrueNAS pools unhealthy", "count(truenas_pool_healthy == 0) or vector(0)",
         0, 1, bad_above=0,
         desc="TrueNAS's OWN health verdict, which counts permanent data "
              "errors. It can read unhealthy while `zpool status` still says "
              "ONLINE - trust this one over the status string."),
    stat("Longhorn degraded", "count(longhorn_volume_robustness == 2) or vector(0)",
         4, 1, bad_above=0,
         desc="Robustness is encoded in the metric VALUE (0 unknown, 1 healthy, "
              "2 degraded, 3 faulted), ~4 series per volume."),
    stat("Longhorn faulted", "count(longhorn_volume_robustness == 3) or vector(0)",
         8, 1, bad_above=0),
    stat("PVCs over 85%",
         "count(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85) or vector(0)",
         12, 1, warn_above=0),
    stat("PVs failed",
         'count(kube_persistentvolume_status_phase{phase="Failed"} == 1) or vector(0)',
         16, 1, bad_above=0),
    alert_table("Firing storage alerts",
                'ALERTS{alertstate="firing",alertname=~"(Longhorn|TrueNAS|VolSync|PVC|KubePersistentVolume).*"}',
                0, 5, w=24,
                desc="38 storage rules exist, so this row is genuinely "
                     "populated - unlike the network board, which needed its "
                     "rules written before it could say anything."),

    row(Q2, 13),
    stat("Longhorn healthy volumes",
         "count(longhorn_volume_robustness == 1) or vector(0)", 0, 14),
    stat("PVCs protected by VolSync",
         "count(count by (obj_name,obj_namespace) (volsync_volume_out_of_sync))",
         4, 14,
         desc="Coverage, not health. A falling count means volumes stopped "
              "being backed up, which looks identical to backups succeeding."),
    stat("VolSync out of sync", "sum(volsync_volume_out_of_sync) or vector(0)",
         8, 14, bad_above=0),
    stat("TrueNAS scrub progress", "max(truenas_pool_scan_percentage)", 12, 14,
         unit="percent", decimals=1,
         desc="A STAT and not a gauge on purpose: this metric reads over 100 "
              "(101.17 observed) during and after a scrub, and a gauge capped "
              "at 100 would pin to full-red and imply a fault."),
    stat("TrueNAS vdev errors", "sum(truenas_vdev_errors_total)", 16, 14,
         warn_above=0,
         desc="Errors spread evenly across ALL members of one vdev, with the "
              "sibling clean, is a transport signature - six drives do not "
              "degrade in lockstep."),

    row(Q3, 18),
    timeseries("Longhorn volume health", [
        ("count(longhorn_volume_robustness == 1)", "healthy"),
        ("count(longhorn_volume_robustness == 2) or vector(0)", "degraded"),
        ("count(longhorn_volume_robustness == 3) or vector(0)", "faulted"),
    ], 0, 19, w=12),
    timeseries("VolSync backup drift", [
        ("sum(volsync_volume_out_of_sync) or vector(0)", "out of sync"),
    ], 12, 19, w=12),

    row(Q4, 27),
    gauge("Fullest PVC",
          "max(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes)",
          0, 28, w=6, warn=0.85, crit=0.92),
    gauge("TrueNAS pool used", "max(truenas_pool_used_ratio)", 6, 28, w=6,
          warn=0.80, crit=0.90),
    stat("TrueNAS free", "sum(truenas_pool_raw_free_bytes)", 12, 28, unit="bytes"),
    stat("Longhorn provisioned", "sum(longhorn_volume_capacity_bytes)", 16, 28,
         unit="bytes",
         desc="Provisioned, not consumed. Deliberately NOT compared against "
              "longhorn_node_storage_capacity_bytes - those two count "
              "different things and the ratio is meaningless."),
    stat("Longhorn actual on disk", "sum(longhorn_volume_actual_size_bytes)",
         20, 28, unit="bytes"),
    timeseries("Capacity trend", [
        ("max(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes)",
         "fullest PVC"),
        ("max(truenas_pool_used_ratio)", "TrueNAS pool"),
    ], 0, 32, w=24, unit="percentunit",
        desc="The slope is the point - it turns 'how full' into 'how long "
             "until full'. Now readable over 60 days rather than 14."),
]

# =====================================================  NETWORK  ============
NETWORK = [
    row(Q1, 0),
    stat("Cloudflare tunnel conns", "sum(cloudflared_tunnel_ha_connections)",
         0, 1, warn_above=None,
         desc="4 is healthy. Zero means all EXTERNAL access is down while "
              "internal access via Traefik is fine - which is why it can go "
              "unnoticed from inside the network entirely."),
    stat("Blocky blocking enabled", "blocky_blocking_enabled", 4, 1,
         desc="1 = blocking. Blocky can run healthy, pass every probe and "
              "answer every query with blocking switched OFF. No liveness "
              "check can see this; only this flag can."),
    stat("MetalLB config stale", "max(metallb_k8s_client_config_stale_bool)",
         8, 1, bad_above=0),
    stat("Traefik 5xx/sec",
         'sum(rate(traefik_service_requests_total{code=~"5.."}[5m])) or vector(0)',
         12, 1, warn_above=0, decimals=2),
    stat("CoreDNS SERVFAIL/sec",
         'sum(rate(coredns_dns_responses_total{rcode="SERVFAIL"}[5m])) or vector(0)',
         16, 1, warn_above=0, decimals=2),
    alert_table("Firing network alerts",
                'ALERTS{alertstate="firing",alertname=~"(Traefik|Blocky|MetalLB|Cloudflared|CoreDNS|NodeNetwork).*"}',
                0, 5, w=24,
                desc="Before 2026-08-06 this row could only ever have been "
                     "empty: the whole network path had 3 alert rules, all "
                     "node-level NIC counters. prometheusrule-network.yaml "
                     "was written alongside this board to give it something "
                     "to show."),

    row(Q2, 13),
    stat("Traefik requests/sec", "sum(rate(traefik_entrypoint_requests_total[5m]))",
         0, 14, decimals=2),
    stat("Blocky queries/sec", "sum(rate(blocky_query_total[5m]))", 4, 14,
         decimals=2),
    stat("CoreDNS requests/sec", "sum(rate(coredns_dns_requests_total[5m]))",
         8, 14, decimals=2),
    stat("Traefik open connections", "sum(traefik_open_connections)", 12, 14),
    stat("Blocky denylist entries", "sum(blocky_denylist_cache_entries)", 16, 14,
         desc="~1.2M domains. A sharp fall means a list failed to load rather "
              "than that the internet got cleaner."),
    timeseries("Request rates", [
        ("sum(rate(traefik_entrypoint_requests_total[5m]))", "traefik"),
        ("sum(rate(blocky_query_total[5m]))", "blocky DNS"),
        ("sum(rate(coredns_dns_requests_total[5m]))", "coredns"),
    ], 0, 18, w=24),

    row(Q3, 26),
    stat("Traefik p95 latency",
         "histogram_quantile(0.95, sum by (le) (rate(traefik_service_request_duration_seconds_bucket[5m])))",
         0, 27, unit="s", decimals=3),
    gauge("Blocky cache hit ratio",
          "sum(rate(blocky_cache_hits_total[10m])) / (sum(rate(blocky_cache_hits_total[10m])) + sum(rate(blocky_cache_misses_total[10m])))",
          4, 27, w=5, warn=0.5, crit=0.3,
          desc="Inverted meaning: HIGH is good. Thresholds are set so low hit "
               "rates colour, not high ones."),
    gauge("CoreDNS cache hit ratio",
          "sum(rate(coredns_cache_hits_total[10m])) / sum(rate(coredns_cache_requests_total[10m]))",
          9, 27, w=5, warn=0.5, crit=0.3),
    timeseries("Traefik latency percentiles", [
        ("histogram_quantile(0.50, sum by (le) (rate(traefik_service_request_duration_seconds_bucket[5m])))", "p50"),
        ("histogram_quantile(0.95, sum by (le) (rate(traefik_service_request_duration_seconds_bucket[5m])))", "p95"),
        ("histogram_quantile(0.99, sum by (le) (rate(traefik_service_request_duration_seconds_bucket[5m])))", "p99"),
    ], 14, 27, w=10, unit="s"),

    row(Q4, 35),
    gauge("MetalLB pool utilisation",
          "sum(metallb_allocator_addresses_in_use_total) / sum(metallb_allocator_addresses_total)",
          0, 36, w=6, warn=0.85, crit=0.95,
          desc="Pool is 192.168.10.193-254. Exhaustion does not degrade - the "
               "next LoadBalancer service simply stays Pending forever, with "
               "no error anywhere that names MetalLB."),
    stat("MetalLB IPs in use", "sum(metallb_allocator_addresses_in_use_total)",
         6, 36),
    stat("MetalLB IPs total", "sum(metallb_allocator_addresses_total)", 10, 36),
    stat_floor("Blocky list refresh age",
               "time() - max(blocky_last_list_group_refresh_timestamp_seconds)",
               14, 36, unit="s", warn_below=172800, crit_below=345600,
               desc="Low is good. Denylists that stop refreshing decay "
                    "silently - blocking keeps working against an ageing list."),
    stat("Blocky failed downloads (1h)",
         "sum(increase(blocky_failed_downloads_total[1h]))", 18, 36,
         warn_above=0, decimals=0),
    timeseries("MetalLB address allocation", [
        ("sum(metallb_allocator_addresses_in_use_total)", "in use"),
        ("sum(metallb_allocator_addresses_total)", "total"),
    ], 0, 40, w=24),
]

BOARDS = [
    ("Storage - Environment", "storage-environment", STORAGE,
     ["storage", "environment"], "grafana-dashboard-storage-environment",
     "storage-environment.json"),
    ("Network - Environment", "network-environment", NETWORK,
     ["network", "environment"], "grafana-dashboard-network-environment",
     "network-environment.json"),
]

HDR = """---
# %s
#
# Generated by tools/dashboards/gen_infra_environments.py - edit that, not this.
#
# Four-questions layout per tools/dashboards/dashlib.py. Every expr validated
# against live Prometheus from the built artifact; none render "No data".
"""

if __name__ == "__main__":
    for title, uid, panels, tags, cm, key in BOARDS:
        d = dashboard(title, uid, panels, tags=tags)
        p = os.path.abspath(os.path.join(OUT, cm + ".yaml"))
        open(p, "w").write(emit_configmap(d, cm, key, HDR % title))
        n = len([x for x in panels if x["type"] != "row"])
        q = sum(len(x.get("targets") or []) for x in panels)
        print("wrote %-44s panels=%-3d queries=%d" % (os.path.basename(p), n, q))
