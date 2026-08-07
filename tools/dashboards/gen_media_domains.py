#!/usr/bin/env python3
"""Content-domain media boards: Movies, TV, Music, Books.

These four boards REPLACED the pipeline-stage "Media - Acquisition" board.
The domain cut is real exactly where metrics carry content identity, and
impossible where they do not:

    Acquisition (*arrs)   YES by construction - each *arr is single-domain
                          (Radarr=movies, Sonarr=TV, Lidarr=music,
                          Readarr=books). This is where the reorg has teeth.
    Emby inventory        PARTIALLY - movie/series/episode counts are
                          content-typed and join these boards as
                          reconciliation signals; sessions are not.
    Live sessions         NO - plex/emby session metrics carry no media-type
                          or library label. Streaming stays a shared-stage
                          board; no expr can attribute a stream to a domain,
                          and every option that "solves" it manufactures data.
    Transport             NO - downloader queues are content-blind. The
                          domain-visible face of downloading is each *arr's
                          own queue and grab rate, which lives HERE (Q3).

RULE (generalising constraint 4): cross-exporter reconciliation is drawn as
OVERLAID SERIES, never subtraction. `radarr_movie_downloaded_total -
emby_movie_count` returns empty if EITHER exporter dies, and that "No data"
is indistinguishable from a broken query. Two independent targets on one
timeseries degrade independently: if one exporter dies the other still
renders and the gap becomes visibly one-sided. Same-exporter arithmetic
(completeness ratios) shares one failure domain with its own metrics and
remains allowed.

Music and Books get full boards rather than a merged one for one reason:
navigational uniformity is the four-question system's core asset. A
half-board would be the only place in the estate where the reader's learned
shape breaks. The panels are not padded to hide the thinness; each board
says in its description what does not exist for its domain.

All exprs validated against live Prometheus before commit (2026-08-07):
  * `path` IS the root-folder label on {sonarr,radarr,lidarr}
    _rootfolder_freespace_bytes; sonarr=1 series, radarr=1, lidarr=3
    (Main/FLAC/Liz instances) - which is why max() over them was already
    reporting the emptiest folder and hiding the full one.
  * lidarr runs as THREE separate instances distinguished by pod/url; the
    only extra dimension under sum() is the instance, so sum() means
    "across all three libraries".
  * bazarr_subtitles_missing_total is byte-identical to
    bazarr_movie_subtitles_missing_total over 7d (diff min=max=0 while the
    value moved 77->147): the un-prefixed family is NOT episode-scoped, so
    the TV board carries NO subtitle panel rather than a mislabelled one.
  * The bazarr exportarr target is flappy (81% presence over 6h, 9.3s
    scrape duration), so bazarr exprs are bridged with
    last_over_time(...[1h]); the Q1 up-strip shows the gaps honestly.
  * radarr/sonarr_history_total are monotonic-growing gauges;
    increase() over them is a usable grab rate. History purges look like
    counter resets and briefly inflate it - noted on the panels.
  * readarr_book_grabbed_total is a GAUGE (current grabbed-not-imported),
    not a lifetime counter - panelled raw, not wrapped in increase().
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import (  # noqa: E402
    Q1, Q2, Q3, Q4, alert_table, bargauge_floor, dashboard, emit_configmap,
    gauge_floor, row, stat, stat_floor, state_timeline, table, timeseries)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../../clusters/main/kubernetes/system/"
                         "kube-prometheus-stack/app")

SEAM = ("Live playback of this content is on Media - Streaming; sessions "
        "cannot be attributed to a content domain with current metrics.")

ALERT_DESC = ("Namespace is the finest alert scope that exists today; a "
              "domain-scoped Q1 would need domain labels added to the media "
              "PrometheusRules (a rule change, not a metric gap).")

UP_DESC = ("Every media scrape target, replacing per-exporter guard tiles: "
           "if a strip goes red or gappy, that exporter's numbers on this "
           "board are stale. Gaps are scrape gaps, shown on purpose.")


def q1(extra=None):
    """Shared Q1: one up-strip for all media targets + the scoped alert
    table. `extra` is an optional board-specific health tile at (8,1,4,8)."""
    panels = [
        row(Q1, 0),
        state_timeline("Media exporters - up/down history",
                       'up{namespace="media"}', 0, 1, w=8,
                       legend="{{pod}} {{probe}}", desc=UP_DESC),
    ]
    if extra is not None:
        panels.append(extra)
        panels.append(alert_table(
            "Firing in media", 'ALERTS{alertstate="firing",namespace="media"}',
            12, 1, w=12, desc=ALERT_DESC))
    else:
        panels.append(alert_table(
            "Firing in media", 'ALERTS{alertstate="firing",namespace="media"}',
            8, 1, w=16, desc=ALERT_DESC))
    return panels


# ======================================================  MOVIES  ============
MOVIES = q1() + [
    # -- Q2: the movie library's promise: complete, at cutoff, subtitled,
    #    actually served.
    row(Q2, 9),
    stat("Movies missing", "radarr_movie_missing_total", 0, 10,
         warn_above=600, graph_mode="area",
         desc="The domain's headline gap. Threshold calibrated against 524 "
              "on 2026-08-07: colour means drift above normal, not judgment "
              "of the backlog's existence."),
    stat("Movies below cutoff", "radarr_movie_cutoff_unmet_total", 4, 10,
         warn_above=1800, graph_mode="area",
         desc="Calibrated: 1,596 on 2026-08-07. Cutoff drives storage "
              "growth, so this is also a capacity forecast."),
    stat("Movie subtitles missing",
         "last_over_time(bazarr_movie_subtitles_missing_total[1h])", 8, 10,
         warn_above=150, graph_mode="area",
         desc="Bazarr's movie-scoped series - the cross-service panel the "
              "domain cut exists for. last_over_time bridges the flappy "
              "bazarr exporter (81% presence when built); staleness is "
              "visible on the Q1 strip. Calibrated: 77-147 over the 7d "
              "before 2026-08-07."),
    stat("Movie library", "radarr_movie_total", 12, 10,
         desc="Inventory - plain value, no colour. 2,472 when built."),
    stat("Emby indexed movies", "emby_movie_count", 16, 10,
         desc="The served-side count, beside the manager-side count. "
              "2,210 when built."),
    stat("Monitored", "radarr_movie_monitored_total", 20, 10,
         desc="Denominator context for the gap numbers."),
    timeseries("Movie library gaps", [
        ("radarr_movie_missing_total", "missing"),
        ("radarr_movie_cutoff_unmet_total", "below cutoff"),
    ], 0, 14, w=12,
        desc="The stats show level; this shows direction - whether "
             "acquisition is winning."),
    timeseries("Radarr vs Emby reconciliation", [
        ("radarr_movie_downloaded_total", "radarr downloaded"),
        ("emby_movie_count", "emby indexed"),
    ], 12, 14, w=12,
        desc="Overlaid, never subtracted: subtraction returns empty if "
             "either exporter dies, indistinguishable from a broken query. "
             "The absolute offset is expected (editions, non-Radarr "
             "content); the signal is the gap CHANGING - a widening gap "
             "means imports or library scans broke, which no single "
             "service's board can see."),

    # -- Q3: is acquisition moving?
    row(Q3, 22),
    stat("Radarr queue", "sum(radarr_queue_total) or vector(0)", 0, 23,
         warn_above=100, graph_mode="area",
         desc="Domain-visible view of the shared transport layer. "
              "vector(0) is legal: metric confirmed live; empty means an "
              "empty queue, which must render as 0."),
    stat("Grabs (24h)", "increase(radarr_history_total[24h])", 4, 23,
         graph_mode="area",
         desc="Replaces the lifetime history stat with a rate. Caveat: "
              "history purges look like counter resets and briefly inflate "
              "increase() - acceptable for a trend tile."),
    timeseries("Queue depth", [
        ("sum(radarr_queue_total) or vector(0)", "queued"),
    ], 8, 23, w=8, desc="Backlog trajectory."),
    timeseries("Grabs per hour", [
        ("increase(radarr_history_total[1h])", "grabs/h"),
    ], 16, 23, w=8,
        desc="Movement. Queue flat + grabs zero for a day = the pipeline "
             "is stuck even though nothing is red."),

    # -- Q4: capacity.
    row(Q4, 31),
    bargauge_floor("Root folder free space", [
        ("radarr_rootfolder_freespace_bytes", "{{path}}"),
    ], 0, 32, w=12, unit="bytes", decimals=1,
        crit_below=200e9, warn_below=1e12,
        desc="Per root folder - imports stop on the folder a movie maps "
             "to, not on the emptiest one, which is why this is never "
             "aggregated with max()."),
    stat("Movie library on disk", "radarr_movie_filesize_total", 12, 32,
         unit="bytes"),
    timeseries("Movie storage growth", [
        ("radarr_movie_filesize_total", "on disk"),
    ], 16, 32, w=8, unit="bytes",
        desc="The slope turns 'how big' into 'how long until full', read "
             "against the root-folder bars."),
]

# ======================================================  TV  ================
TV = q1() + [
    # NOTE: no episode-subtitle panel. Verified 2026-08-07 that
    # bazarr_subtitles_missing_total tracks bazarr_movie_subtitles_missing_
    # total exactly (identical over 7d) - it is not episode-scoped, and a
    # mislabelled panel is worse than a missing one.
    row(Q2, 9),
    stat("Episodes missing", "sonarr_episode_missing_total", 0, 10,
         warn_above=3500, graph_mode="area",
         desc="Calibrated: 3,187 on 2026-08-07."),
    stat("Episodes below cutoff", "sonarr_episode_cutoff_unmet_total", 4, 10,
         warn_above=8000, graph_mode="area",
         desc="Calibrated: 7,578 on 2026-08-07. Capacity forecast, as with "
              "movies."),
    stat("Series", "sonarr_series_total", 8, 10,
         desc="Inventory, plain. 152 when built."),
    stat("Emby indexed episodes", "emby_episode_count", 12, 10,
         desc="Served-side count. 8,246 when built."),
    stat_floor("Tunarr channels", "count(tunarr_channel_info)", 16, 10,
               warn_below=26,
               desc="26 expected. A drop means a lineup failed to build, "
                    "which from the pod looks identical to 'no one is "
                    "watching'. Live TV is a TV-domain experience built "
                    "from this library."),
    timeseries("TV library gaps", [
        ("sonarr_episode_missing_total", "missing"),
        ("sonarr_episode_cutoff_unmet_total", "below cutoff"),
    ], 0, 14, w=12, desc="Direction: is acquisition winning."),
    timeseries("Sonarr vs Emby reconciliation", [
        ("sonarr_episode_downloaded_total", "sonarr downloaded"),
        ("emby_episode_count", "emby indexed"),
    ], 12, 14, w=12,
        desc="Overlaid, never subtracted - see the Movies board for the "
             "full rationale. A widening gap means imports or library "
             "scans broke."),

    row(Q3, 22),
    stat("Sonarr queue", "sum(sonarr_queue_total) or vector(0)", 0, 23,
         warn_above=100, graph_mode="area",
         desc="vector(0) legal: metric confirmed; empty queue must render "
              "as 0."),
    stat("Grabs (24h)", "increase(sonarr_history_total[24h])", 4, 23,
         graph_mode="area",
         desc="History purges look like counter resets and briefly "
              "inflate increase()."),
    stat("Monitored seasons", "sonarr_season_monitored_total", 8, 23),
    timeseries("Queue depth", [
        ("sum(sonarr_queue_total) or vector(0)", "queued"),
    ], 12, 23, w=12),

    row(Q4, 31),
    bargauge_floor("Root folder free space", [
        ("sonarr_rootfolder_freespace_bytes", "{{path}}"),
    ], 0, 32, w=12, unit="bytes", decimals=1,
        crit_below=200e9, warn_below=1e12),
    stat("Channels with thin lineups",
         "count(tunarr_channel_duration_ms < 43200000) or vector(0)", 12, 32,
         warn_above=0,
         desc="Channels under 12h of programming - the stale-lineup "
              "signature from the Tunarr runbook. Replaces an average over "
              "26 channels that arithmetically hid one collapsed lineup "
              "(a 0-length lineup moves the mean ~4%). vector(0) legal: "
              "empty means no channel is thin, which must render green."),
    timeseries("Root folder free trend", [
        ("sonarr_rootfolder_freespace_bytes", "{{path}}"),
    ], 16, 32, w=8, unit="bytes", desc="Slope per folder."),
]

# ======================================================  MUSIC  =============
MUSIC = q1(extra=stat(
    "Lidarr health issues", "sum(lidarr_system_health_issues) or vector(0)",
    8, 1, w=4, h=8, bad_above=0,
    desc="Lidarr is the only *arr exporting its own health-check count "
         "(summed across the three instances). Non-zero means it is "
         "telling you something in its UI. vector(0) legal: metric "
         "confirmed; empty means no issues, which must render green.")) + [
    # The library is majority-holes BY CONSTRUCTION (full discographies
    # monitored), so missing-counts get NO threshold colour - a permanently
    # red tile trains people to ignore red. The completeness RATIO is the
    # honest health signal: the count of missing albums is policy, the
    # direction of the ratio is operations.
    row(Q2, 9),
    stat("Artists", "sum(lidarr_artists_total)", 0, 10,
         desc="Summed across the three lidarr instances (Main, FLAC, Liz) "
              "- verified 2026-08-07 that the instance is the only "
              "dimension under the sum."),
    stat("Albums", "sum(lidarr_albums_total)", 4, 10),
    stat("Albums missing", "sum(lidarr_albums_missing_total)", 8, 10,
         graph_mode="area",
         desc="Deliberately uncoloured: majority-holes by policy. "
              "33,670 when built; the sparkline's direction is the signal."),
    stat("Songs downloaded", "sum(lidarr_songs_downloaded_total)", 12, 10),
    gauge_floor("Song completeness",
                "sum(lidarr_songs_downloaded_total) / sum(lidarr_songs_total)",
                16, 10, w=5, warn_below=0.11, crit_below=0.08,
                desc="Same-exporter ratio. Thresholds sit at 'worse than "
                     "now' (12.4% on 2026-08-07), not aspirational values "
                     "that would read red forever."),
    timeseries("Albums missing trend", [
        ("sum(lidarr_albums_missing_total)", "missing"),
    ], 0, 14, w=12,
        desc="Is the hole shrinking, static, or growing faster than "
             "acquisition."),
    table("Artists by genre",
          "topk(15, sum by (genre) (lidarr_artists_genres_total))", 12, 14,
          w=12, exclude={"Value": False},
          desc="'Which ones' - a table, because 15+ classes is far past "
               "the ~7-class colour ceiling. Label verified live."),

    row(Q3, 22),
    stat("Lidarr queue", "sum(lidarr_queue_total) or vector(0)", 0, 23,
         warn_above=100, graph_mode="area",
         desc="72 when built. vector(0) legal: metric confirmed."),
    timeseries("Queue depth", [
        ("sum(lidarr_queue_total) or vector(0)", "queued"),
    ], 4, 23, w=20),

    row(Q4, 31),
    stat("Music on disk", "sum(lidarr_artists_filesize_bytes)", 0, 32,
         unit="bytes"),
    bargauge_floor("Root folder free space", [
        ("lidarr_rootfolder_freespace_bytes", "{{path}}"),
    ], 4, 32, w=12, unit="bytes", decimals=1,
        crit_below=200e9, warn_below=1e12,
        desc="THREE root folders across the lidarr instances - the reason "
             "max() over this metric was already wrong the day it shipped: "
             "it reported the emptiest folder and hid the full one."),
    timeseries("Root folder free trend", [
        ("lidarr_rootfolder_freespace_bytes", "{{path}}"),
    ], 16, 32, w=8, unit="bytes"),
]

# ======================================================  BOOKS  =============
BOOKS = q1() + [
    row(Q2, 9),
    stat("Books", "readarr_book_total", 0, 10,
         desc="176 when built."),
    stat("Books missing", "readarr_book_missing_total", 4, 10,
         graph_mode="area",
         desc="Deliberately uncoloured - same majority-holes reasoning as "
              "Music (137 of 176 when built): a small library that is "
              "mostly holes is a different problem from a large one with "
              "a few."),
    stat("Authors", "readarr_author_total", 8, 10),
    stat("Books downloaded", "readarr_book_downloaded_total", 12, 10),
    gauge_floor("Book completeness",
                "readarr_book_downloaded_total / readarr_book_total",
                16, 10, w=5, warn_below=0.22, crit_below=0.15,
                desc="Same-exporter ratio. At ~26% (2026-08-07) the "
                     "gauge's job is direction, so thresholds sit at "
                     "'worse than now', not aspirational values that "
                     "would read red forever."),
    timeseries("Books missing trend", [
        ("readarr_book_missing_total", "missing"),
    ], 0, 14, w=12, desc="Direction."),

    row(Q3, 22),
    stat("Readarr queue", "sum(readarr_queue_total) or vector(0)", 0, 23,
         warn_above=50, graph_mode="area",
         desc="vector(0) legal: metric confirmed."),
    stat("Books grabbed now", "readarr_book_grabbed_total", 4, 23,
         desc="Verified 2026-08-07: a GAUGE of currently-grabbed books "
              "(not a lifetime counter), so it is shown raw, not wrapped "
              "in increase()."),
    timeseries("Queue depth", [
        ("sum(readarr_queue_total) or vector(0)", "queued"),
    ], 8, 23, w=16),

    row(Q4, 31),
    stat("Books on disk", "readarr_author_filesize_bytes", 0, 32,
         unit="bytes"),
]


def hdr(title, why):
    return ("---\n# %s\n#\n# Generated by tools/dashboards/"
            "gen_media_domains.py - edit that, not this.\n#\n# %s\n#\n"
            "# Four-questions layout per tools/dashboards/dashlib.py. Every\n"
            "# expr validated against live Prometheus; none render \"No data\".\n"
            % (title, why))


BOARDS = [
    ("Media - Movies", "media-movies", MOVIES,
     "grafana-dashboard-media-movies", "media-movies.json",
     "Radarr owns acquisition, Bazarr owns movie subtitles, Emby provides\n"
     "# the served-library count. Per-title serving does not exist in\n"
     "# metrics - sessions carry no content label.",
     "The movie library's promise: complete, at cutoff, subtitled, served. "
     "Radarr + Bazarr (movies) + Emby inventory. " + SEAM),
    ("Media - TV", "media-tv", TV,
     "grafana-dashboard-media-tv", "media-tv.json",
     "Sonarr + Emby series/episode counts + Tunarr - live TV channels are\n"
     "# a TV-domain experience built from the TV library. No episode-scoped\n"
     "# bazarr series exists (verified identical to the movie series), and\n"
     "# no sonarr filesize metric exists, so TV's on-disk footprint cannot\n"
     "# be shown per-domain today.",
     "The TV library's promise, plus live TV (Tunarr). Sonarr + Emby "
     "inventory + Tunarr. No episode-scoped subtitle metric and no sonarr "
     "filesize metric exist - absent, not papered over. " + SEAM),
    ("Media - Music", "media-music", MUSIC,
     "grafana-dashboard-media-music", "media-music.json",
     "Lidarr only (three instances: Main, FLAC, Liz - summed). No\n"
     "# serving-side metrics exist for music: Emby exports no music counts\n"
     "# and sessions are unlabelled. The library is majority-holes by\n"
     "# construction, so missing-counts are deliberately uncoloured and the\n"
     "# completeness ratio carries the health signal.",
     "Lidarr only (Main + FLAC + Liz instances, summed). No serving-side "
     "music metrics exist (Emby exports no music counts); this board is "
     "honestly thin rather than padded. Missing-counts are uncoloured: the "
     "library is majority-holes by policy. " + SEAM),
    ("Media - Books", "media-books", BOOKS,
     "grafana-dashboard-media-books", "media-books.json",
     "Readarr only; same serving-side absence as Music. 137 of 176 books\n"
     "# missing when built - a small library that is mostly holes is a\n"
     "# different problem from a large one with a few.",
     "Readarr only. No serving-side book metrics exist; this board is "
     "honestly thin rather than padded. Missing-counts are uncoloured: "
     "majority-holes by policy. " + SEAM),
]

if __name__ == "__main__":
    total = 0
    for title, uid, panels, cm, key, why, desc in BOARDS:
        d = dashboard(title, uid, panels, tags=["media", "domain"], desc=desc)
        path = os.path.abspath(os.path.join(OUT, cm + ".yaml"))
        # Render before open(): open() truncates immediately, and a lint
        # failure inside emit_configmap must not delete a good artifact.
        text = emit_configmap(d, cm, key, hdr(title, why))
        open(path, "w").write(text)
        n = len([p for p in panels if p["type"] != "row"])
        q = sum(len(p.get("targets") or []) for p in panels)
        total += q
        print("wrote %-42s panels=%-3d queries=%d" % (os.path.basename(path), n, q))
    print("total queries: %d" % total)
