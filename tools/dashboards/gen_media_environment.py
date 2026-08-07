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
    Q1, Q2, Q3, Q4, alert_table, bargauge_floor, dashboard, emit_configmap,
    gauge, row, stat, state_timeline, timeseries)

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
              "while still displaying a confident value. The strip below "
              "shows WHICH target, and whether it flapped overnight."),
    stat("Container restarts (1h)",
         'sum(increase(kube_pod_container_status_restarts_total{namespace="media"}[1h]))',
         4, 5, warn_above=2, decimals=1),
    # One strip of every media scrape target replaces the per-exporter
    # stat-tile boilerplate the service boards used to carry: same
    # information, plus the history a stat cannot show. spanNulls=false, so
    # a flappy exporter (bazarr sat at 81% presence when this was built)
    # reads as a gappy strip, not a solid green lie.
    state_timeline("Media exporters - up/down history",
                   'up{namespace="media"}', 0, 9, w=24,
                   legend="{{pod}} {{probe}}",
                   desc="Every media scrape target. Gaps are scrape gaps - "
                        "they are shown on purpose; a gappy exporter's "
                        "numbers elsewhere on this board are going stale "
                        "between appearances."),
]

# ------------------------------------------------------ Q2: doing its job?
P += [
    row(Q2, 17),
    stat("Plex streams", "plex_active_streams_total", 0, 18,
         desc="The purpose metric for Plex. CPU can be near idle while every "
              "stream fails; this is the number that says it is serving."),
    stat("Plex transcoding", "plex_active_streams_transcode", 4, 18, warn_above=2,
         desc="Transcodes are where the CPU goes. Direct play is free, "
              "transcode is not - a rising ratio predicts saturation before "
              "the node graph does."),
    stat("Emby sessions", "sum(emby_session_active)", 8, 18),
    stat("Tunarr channels", "count(tunarr_channel_info)", 12, 18,
         desc="26 channels expected. A drop means the lineup failed to build, "
              "which looks identical to 'no one is watching' from the pod."),
    stat("Sonarr series", "sonarr_series_total", 16, 18),
    stat("Radarr movies", "radarr_movie_total", 20, 18),

    timeseries("Plex streams over time", [
        ("plex_active_streams_total", "total"),
        ("plex_active_streams_direct_play", "direct play"),
        ("plex_active_streams_transcode", "transcode"),
    ], 0, 22, w=12,
        desc="Watch the gap between total and direct play. That gap IS the "
             "transcode load."),

    # Replaces the mixed-scale gaps bargauge: 33,675 missing albums next to
    # 77 missing subtitles on one linear scale rendered the small bars as
    # zero pixels, so the panel only ever showed lidarr and sonarr - and an
    # episode is not an album, so the counts were never comparable anyway.
    # Ratios share a 0-1 scale, which is what a bargauge is actually for.
    # Per-domain floors, calibrated to live values on 2026-08-07 (TV 0.574,
    # movies 0.765, music 0.124, books 0.256): colour means "worse than
    # normal", not judgment of the backlog's existence - music and books are
    # majority-holes BY POLICY (full discographies/bibliographies monitored),
    # and a permanently red bar trains people to ignore red.
    bargauge_floor("Library completeness by domain", [
        ("sonarr_episode_downloaded_total / sonarr_episode_total",
         "TV episodes"),
        ("radarr_movie_downloaded_total / radarr_movie_total", "Movies"),
        ("sum(lidarr_songs_downloaded_total) / sum(lidarr_songs_total)",
         "Music songs"),
        ("readarr_book_downloaded_total / readarr_book_total", "Books"),
    ], 12, 22, w=12, unit="percentunit", decimals=1,
        floors={"TV episodes": (0.45, 0.55),
                "Movies": (0.60, 0.72),
                "Music songs": (0.08, 0.11),
                "Books": (0.15, 0.22)},
        desc="Same-exporter ratios on a shared 0-1 scale. Approximates "
             "completeness where unmonitored items exist - the per-domain "
             "boards carry the exact counts. Thresholds are calibrated to "
             "2026-08 operating values per domain, so colour means drift "
             "below normal, not an aspiration."),
]

# ----------------------------------------------------- Q3: keeping up?
P += [
    row(Q3, 30),
    stat("Queued across *arrs",
         'sum({__name__=~"(sonarr|radarr|lidarr|readarr)_queue_total"})',
         0, 31, warn_above=250, graph_mode="area",
         desc="Backlog the acquisition side has accepted but not finished. "
              "Steady growth means grabbing outpaces importing - the "
              "sparkline is the point."),
    stat("SABnzbd queue", "sabnzbd_queue_length", 4, 31, warn_above=40,
         graph_mode="area"),
    stat("SABnzbd remaining", "sabnzbd_remaining_bytes", 8, 31, unit="bytes"),
    stat("Pods not Running",
         'count(kube_pod_status_phase{namespace="media",phase=~"Pending|Failed|Unknown"} > 0) or vector(0)',
         12, 31, warn_above=3),

    timeseries("Download throughput", [
        ("deluge_download_rate", "deluge down"),
        ("deluge_upload_rate", "deluge up"),
        ("rate(nzbget_downloaded_total_bytes[5m])", "nzbget"),
    ], 0, 35, w=12, unit="Bps"),

    timeseries("Acquisition backlog", [
        ("sonarr_queue_total", "sonarr"),
        ("radarr_queue_total", "radarr"),
        ("lidarr_queue_total", "lidarr"),
        ("readarr_queue_total", "readarr"),
        ("sabnzbd_queue_length", "sabnzbd"),
    ], 12, 35, w=12),
]

# ------------------------------------------------- Q4: can it keep going?
P += [
    row(Q4, 43),
    gauge("Fullest media PVC",
          'max(kubelet_volume_stats_used_bytes{namespace="media"} / kubelet_volume_stats_capacity_bytes{namespace="media"})',
          0, 44, w=5, warn=0.85, crit=0.92),
    stat("SABnzbd disk used", "sum(sabnzbd_disk_used_bytes)", 5, 44, unit="bytes"),
    stat("media memory",
         'sum(container_memory_working_set_bytes{namespace="media",container!=""})',
         9, 44, unit="bytes"),
    stat("media CPU",
         'sum(rate(container_cpu_usage_seconds_total{namespace="media",container!=""}[5m]))',
         13, 44, decimals=2,
         desc="Cores. Compare against transcode count above - if CPU climbs "
              "without transcodes climbing, something else is eating it."),

    # Replaces `max(sonarr_rootfolder_freespace_bytes)` - a constraint-3
    # violation: max() of FREE space reports the emptiest folder and hides
    # the full one, and imports stop on the folder a title maps to, not on
    # the emptiest. Live check 2026-08-07: sonarr 1 folder, radarr 1,
    # lidarr THREE - so the aggregate was already wrong, not just fragile.
    # Floors carried over from the retired stat_floor tiles (200GB/1TB).
    bargauge_floor("Root folder free space (as the *arrs see it)", [
        ("sonarr_rootfolder_freespace_bytes", "tv {{path}}"),
        ("radarr_rootfolder_freespace_bytes", "movies {{path}}"),
        ("lidarr_rootfolder_freespace_bytes", "music {{path}}"),
    ], 0, 48, w=8, unit="bytes", decimals=1,
        crit_below=200e9, warn_below=1e12,
        desc="The NFS shares, not PVCs - this is what actually stops "
             "imports. One bar per root folder; the emptiest folder can no "
             "longer hide the full one."),
    timeseries("media namespace resource use", [
        ('sum(rate(container_cpu_usage_seconds_total{namespace="media",container!=""}[5m]))', "CPU cores"),
    ], 8, 48, w=8),
    timeseries("media namespace memory", [
        ('sum(container_memory_working_set_bytes{namespace="media",container!=""})', "working set"),
    ], 16, 48, w=8, unit="bytes"),
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
                  tags=["media", "environment"],
                  desc="Aggregates the purpose metrics of the media stack: "
                       "is the experience working. Drill-down order: "
                       "Environment -> domain (Movies/TV/Music/Books) -> "
                       "shared stage (Streaming/Downloaders).")
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../../clusters/main/kubernetes/system/kube-prometheus-stack/app/"
        "grafana-dashboard-media-environment.yaml")
    # Render BEFORE opening the file: emit_configmap refuses bad output by
    # raising, and open(path, "w") truncates immediately - the naive
    # open().write(emit(...)) order deletes the previous good artifact on a
    # lint failure.
    text = emit_configmap(d, "grafana-dashboard-media-environment",
                          "media-environment.json", HEADER)
    open(os.path.abspath(out), "w").write(text)
    data = [p for p in P if p["type"] != "row"]
    print("wrote %s" % os.path.abspath(out))
    print("rows=%d data panels=%d" % (len(P) - len(data), len(data)))
    for p in data:
        for t in p.get("targets", []):
            print("  %-34s %s" % (p["title"][:34], t["expr"][:80]))
