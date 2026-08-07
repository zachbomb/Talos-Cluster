#!/usr/bin/env python3
"""Media ENVIRONMENT dashboard - the whole media stack as one experience.

Every expr here was validated against live Prometheus before commit.

This is an environment board, not a service board: it aggregates the PURPOSE
metric of each member service to answer "is the media experience working",
rather than stacking per-pod CPU charts. Per-service drilldowns hang off it.

The library-gap panel is the point of the whole exercise. Those numbers -
thousands of missing episodes, cutoff-unmet movies, missing subtitles - were
in Prometheus the entire time and no dashboard showed them. A media stack can
have every pod Running, every probe green, and still be failing at its job.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import (  # noqa: E402
    Q1, Q2, Q3, Q4, alert_table, bargauge, dashboard, emit_configmap, gauge,
    row, stat, timeseries)

P = []

# ---------------------------------------------------------------- Q1: broken?
P += [
    row(Q1, 0),
    stat("CRITICAL in media",
         'count(ALERTS{alertstate="firing",severity="critical",namespace="media"}) or vector(0)',
         0, 1, bad_above=0),
    stat("Warnings in media",
         'count(ALERTS{alertstate="firing",severity="warning",namespace="media"}) or vector(0)',
         4, 1, bad_above=2),
    alert_table("Firing in media", 'ALERTS{alertstate="firing",namespace="media"}', 8, 1,
                desc="Scoped to the media namespace. Empty here is the good "
                     "case - the count tiles to the left always render, so an "
                     "empty table never means the panel is broken."),
    stat("Scrape targets down", 'count(up{namespace="media"} == 0) or vector(0)',
         0, 5, bad_above=0,
         desc="A down exporter makes every library-gap number below go stale "
              "while still displaying a confident value."),
    stat("Container restarts (1h)",
         'sum(increase(kube_pod_container_status_restarts_total{namespace="media"}[1h]))',
         4, 5, warn_above=2, decimals=1),
]

# ------------------------------------------------------ Q2: doing its job?
P += [
    row(Q2, 9),
    stat("Plex streams", "plex_active_streams_total", 0, 10,
         desc="The purpose metric for Plex. CPU can be near idle while every "
              "stream fails; this is the number that says it is serving."),
    stat("Plex transcoding", "plex_active_streams_transcode", 4, 10, warn_above=2,
         desc="Transcodes are where the CPU goes. Direct play is free, "
              "transcode is not - a rising ratio predicts saturation before "
              "the node graph does."),
    stat("Emby sessions", "sum(emby_session_active)", 8, 10),
    stat("Tunarr channels", "count(tunarr_channel_info)", 12, 10,
         desc="26 channels expected. A drop means the lineup failed to build, "
              "which looks identical to 'no one is watching' from the pod."),
    stat("Sonarr series", "sonarr_series_total", 16, 10),
    stat("Radarr movies", "radarr_movie_total", 20, 10),

    timeseries("Plex streams over time", [
        ("plex_active_streams_total", "total"),
        ("plex_active_streams_direct_play", "direct play"),
        ("plex_active_streams_transcode", "transcode"),
    ], 0, 14, w=12,
        desc="Watch the gap between total and direct play. That gap IS the "
             "transcode load."),

    bargauge("Library gaps - what the stack is failing to deliver", [
        ("sonarr_episode_cutoff_unmet_total", "Sonarr episodes below cutoff"),
        ("sonarr_episode_missing_total", "Sonarr episodes missing"),
        ("radarr_movie_cutoff_unmet_total", "Radarr movies below cutoff"),
        ("radarr_movie_missing_total", "Radarr movies missing"),
        ("sum(lidarr_albums_missing_total)", "Lidarr albums missing"),
        ("bazarr_subtitles_missing_total", "Bazarr subtitles missing"),
    ], 12, 14, w=12, warn=500, crit=3000,
        desc="THE panel this dashboard exists for. Every one of these was "
             "already in Prometheus and invisible. Cutoff-unmet is not "
             "cosmetic - cutoff drives storage growth, so a large number here "
             "is also a capacity forecast."),
]

# ----------------------------------------------------- Q3: keeping up?
P += [
    row(Q3, 22),
    stat("Queued across *arrs",
         'sum({__name__=~"(sonarr|radarr|lidarr|readarr)_queue_total"})',
         0, 23, warn_above=250,
         desc="Backlog the acquisition side has accepted but not finished. "
              "Steady growth means grabbing outpaces importing."),
    stat("SABnzbd queue", "sabnzbd_queue_length", 4, 23, warn_above=40),
    stat("SABnzbd remaining", "sabnzbd_remaining_bytes", 8, 23, unit="bytes"),
    stat("Pods not Running",
         'count(kube_pod_status_phase{namespace="media",phase=~"Pending|Failed|Unknown"} > 0) or vector(0)',
         12, 23, warn_above=3),

    timeseries("Download throughput", [
        ("deluge_download_rate", "deluge down"),
        ("deluge_upload_rate", "deluge up"),
        ("rate(nzbget_downloaded_total_bytes[5m])", "nzbget"),
    ], 0, 27, w=12, unit="Bps"),

    timeseries("Acquisition backlog", [
        ("sonarr_queue_total", "sonarr"),
        ("radarr_queue_total", "radarr"),
        ("lidarr_queue_total", "lidarr"),
        ("readarr_queue_total", "readarr"),
        ("sabnzbd_queue_length", "sabnzbd"),
    ], 12, 27, w=12),
]

# ------------------------------------------------- Q4: can it keep going?
P += [
    row(Q4, 35),
    gauge("Fullest media PVC",
          'max(kubelet_volume_stats_used_bytes{namespace="media"} / kubelet_volume_stats_capacity_bytes{namespace="media"})',
          0, 36, w=5, warn=0.85, crit=0.92),
    stat("Library free space", "max(sonarr_rootfolder_freespace_bytes)", 5, 36,
         unit="bytes",
         desc="Root folder free space as the *arrs see it - the NFS share, "
              "not a PVC. This is what actually stops imports."),
    stat("SABnzbd disk used", "sum(sabnzbd_disk_used_bytes)", 9, 36, unit="bytes"),
    stat("media memory",
         'sum(container_memory_working_set_bytes{namespace="media",container!=""})',
         13, 36, unit="bytes"),
    stat("media CPU",
         'sum(rate(container_cpu_usage_seconds_total{namespace="media",container!=""}[5m]))',
         17, 36, decimals=2,
         desc="Cores. Compare against transcode count above - if CPU climbs "
              "without transcodes climbing, something else is eating it."),

    timeseries("media namespace resource use", [
        ('sum(rate(container_cpu_usage_seconds_total{namespace="media",container!=""}[5m]))', "CPU cores"),
    ], 0, 40, w=12),
    timeseries("media namespace memory", [
        ('sum(container_memory_working_set_bytes{namespace="media",container!=""})', "working set"),
    ], 12, 40, w=12, unit="bytes"),
]

HEADER = """---
# Media ENVIRONMENT dashboard.
#
# Generated by tools/dashboards/gen_media_environment.py - edit that, not this.
#
# WHY THIS EXISTS: a 2026-08-06 audit of the 44 installed dashboards found the
# media stack - 18 scrape targets and ~250 metric families across sonarr,
# radarr, lidarr, readarr, bazarr, sabnzbd, nzbget, deluge, plex, emby and
# tunarr - represented by exactly ONE dashboard, titled "Sonarr v3", with 7
# panels. Meanwhile Prometheus already held 3,187 missing episodes, 7,580
# episodes below cutoff, 524 missing movies, 1,596 movies below cutoff and 77
# missing subtitles. None of it was on a screen anywhere.
#
# The layout follows the four-questions order defined in
# tools/dashboards/dashlib.py: broken -> doing its job -> keeping up -> can it
# keep going. That is the order an operator actually asks, as opposed to the
# CPU/memory/network grouping that imported dashboards inherit from whoever
# wrote the exporter.
#
# Every expr was validated against live Prometheus before commit; none render
# "No data". `or vector(0)` appears only on metrics confirmed to exist.
"""

if __name__ == "__main__":
    d = dashboard("Media - Environment", "media-environment", P,
                  tags=["media", "environment"])
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../../clusters/main/kubernetes/system/kube-prometheus-stack/app/"
        "grafana-dashboard-media-environment.yaml")
    open(os.path.abspath(out), "w").write(
        emit_configmap(d, "grafana-dashboard-media-environment",
                       "media-environment.json", HEADER))
    data = [p for p in P if p["type"] != "row"]
    print("wrote %s" % os.path.abspath(out))
    print("rows=%d data panels=%d" % (len(P) - len(data), len(data)))
    for p in data:
        for t in p.get("targets", []):
            print("  %-34s %s" % (p["title"][:34], t["expr"][:80]))
