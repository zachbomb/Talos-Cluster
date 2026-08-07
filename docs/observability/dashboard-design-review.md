# Grafana Dashboard Design Review and Content-Domain Media Reorganisation

**Ticket:** SQ-42 - design document, not code.
**Intended repo location:** `docs/observability/dashboard-design-review.md` (this executor is read-only; materialising the file is a one-step copy of this plan document).
**Basis:** `tools/dashboards/dashlib.py` (the design system and its measured rationale), `gen_media_environment.py`, `gen_media_services.py`, `gen_infra_environments.py`; the 2026-08-07 estate audit (52 dashboards, panel-type census); the verified metric inventory in the ticket. Grafana 13.0.2, only the four bundled Grafana apps installed, **no third-party panel plugins** - every shape proposed below is a core panel.

**Inherited hard constraints** (each exists for a measured incident, all honoured by every proposal here):

1. No panel may render "No data". `or vector(0)` only on metrics confirmed to exist.
2. No `$` anywhere in generated JSON. Fixed windows (`[5m]`, `[1h]`, `[24h]`), hardcoded datasource uid `prometheus`.
3. Never aggregate a per-entity metric with `max()`/`min()` across entities (the `truenas_pool_scan_percentage` lesson).
4. Emptiness propagates through arithmetic; unions via `{__name__=~"..."}`, and (extended below, section 2.0) no arithmetic across *different exporters* in one expr.
5. "Low is bad" metrics take inverted thresholds (start red, step up into green).

Anything below that needs a metric **not** in the verified inventory is flagged inline with **[NOT IN INVENTORY]** or **[VERIFY]** rather than assumed into existence. A consolidated list is in Appendix A.

---

## 1. The four-question system: an honest critique

### 1.1 What it genuinely gets right

Credit precisely, because the reorganisation in section 2 keeps the system:

- **The ordering is the operator's ordering, and it is backed by an incident.** Alerts-first exists because three CRITICALs ran ~9 hours while hand-picked "health" metrics read green. Q1 as scoped `ALERTS` is not a stylistic preference; it is the fix for a measured failure mode, and no imported dashboard in the estate has it.
- **Q2 - the purpose metric - is the real innovation.** "A dashboard that shows a service's CPU but not its purpose metric tells you the process is alive, not that it works" is the single best sentence in `dashlib.py`. It is what surfaced 3,187 missing episodes and 7,580 cutoff-unmet episodes that sat in Prometheus for months behind a 7-panel "Sonarr v3" board.
- **Fixed row titles are most of what "cohesive" means.** A reader learns the shape once. This also makes the system *portable across scopes* - which matters for section 2: the four questions survive re-scoping from pipeline-stage boards to content-domain boards without modification. That is evidence the rows are close to orthogonal to board scope, which is a strong property.
- **The no-"No data" rule and the two-kinds-of-empty distinction** (`noValue` on alert tables) encode real debugging cost into the library, where it cannot be forgotten.
- **Colour discipline** - background colour only for counts of bad things, plain values for inventory - keeps the boards from becoming the wall of green that trains people to stop looking. This matches the general dataviz rule that status colour is reserved and must *mean* state.

### 1.2 Where it is forced (with receipts from the shipped generators)

The system's weakness is that a fixed four-row template demands content for every row on every board, and when a service does not naturally have it, filler appears. The shipped boards contain the evidence:

- **Emby library counts live under Q4 "Can it keep going?" on the Streaming board.** `emby_movie_count`, `emby_series_count`, `emby_episode_count` are inventory, not capacity. They are there because Streaming's real Q4 content is thin (one PVC gauge) and the template demanded a row. The content-domain reorg fixes this honestly: those counts move to the Movies/TV boards' Q2, where they are reconciliation signals (section 2.3), and Streaming's Q4 shrinks to what is actually capacity.
- **"Grabs recorded" on the Acquisition board Q3** is a lifetime counter whose own description admits it is "not a health signal". That is template-filling. The honest shape is a rate: `increase(sonarr_history_total[24h])` - which section 2 uses.
- **`avg(tunarr_channel_duration_ms)` under Q4** is a health heuristic, not capacity - and an average over 26 channels arithmetically hides one collapsed channel (a 0-length lineup among 25 healthy ones moves the average ~4%). Section 2.3 replaces it with a count-below-threshold stat, which is the shape that actually answers "did a lineup fail to rebuild".
- **Q2 vs Q3 has a blurry boundary the generators already straddle.** Library gaps sit in Q2 on one board; queue depth in Q3; but a backlog is both "not doing its job yet" and "not keeping up". The system works anyway, but only because each author re-decides the boundary per board. Proposed boundary rule, to be added to `dashlib.py`'s docstring: **Q2 is the state of the promise to the user (is the delivered thing complete/correct/available now); Q3 is the flux of work in progress (is the machinery moving and is the backlog shrinking).** Under that rule: missing/cutoff counts are Q2, queues and grab rates are Q3, and the placement stops being per-author taste.
- **Q1 boilerplate is copy-pasted.** The same `ALERTS{namespace="media"}` table and exporter-up tiles appear on every media board. Consistency is the point, but three exporter-up stat tiles per board is vocabulary poverty: one state-timeline of `up{namespace="media"}` (section 4.3) answers the same question for *all* targets, with history, in one panel.

### 1.3 Q1 is only as good as the rule inventory behind it - and the layout cannot see that

`gen_infra_environments.py` already documents the trap: the Network board's Q1 was structurally incapable of showing anything until `prometheusrule-network.yaml` was written (3 rules for the whole network path vs 38 for storage). The four-question layout **presents** rule coverage but cannot **verify** it: a green Q1 over an un-ruled domain is a confident lie of omission. This is a process gap, not a panel gap: the honest mitigation is (a) the rule-count-by-domain audit that produced the network rules becomes a repeatable check alongside `promtool-tests/`, and (b) each domain board added in section 2 states in its Q1 panel description which rule files feed it. A per-domain "rules loaded" stat is only partially expressible (`prometheus_rule_group_rules` is per-group, not per-domain) - flagged as not solvable cleanly with current metrics.

### 1.4 Thresholds encode today's normal and will rot

`warn_above=250` on queue depth, `warn=500, crit=3000` on library gaps - these encode 2026-08 operating values. A library that grows 30% makes them fire meaninglessly or never. The system has no provenance convention for thresholds. Recommendation: every threshold in a generator carries a comment with the live value it was calibrated against and the date (several already do informally); re-calibration is an explicit checklist item whenever a board is regenerated. This costs nothing and prevents the "trained to ignore orange" decay that `stat_floor`'s docstring warns about.

### 1.5 A shipped violation of constraint 3, found during this review

`max(sonarr_rootfolder_freespace_bytes)` / `max(radarr_rootfolder_freespace_bytes)` (Acquisition Q4, Environment Q4) aggregate a **per-entity** metric (per root folder) with `max()`. This is the `truenas_pool_scan_percentage` failure shape exactly: with more than one root folder, `max()` of *free space* systematically reports the emptiest folder and structurally hides the full one - and imports stop on the folder a given series/movie maps to, not on the emptiest one. If there is exactly one root folder per app today, the panel is accidentally correct and silently becomes wrong the day a second folder is added. Section 2.3 replaces these with per-entity bargauges (`radarr_rootfolder_freespace_bytes` legend `{{path}}` **[VERIFY label name]**). This is the strongest argument that constraint 3 belongs in a lint in `emit_configmap` (grep for `max(`/`min(` over metrics known to be per-entity), not only in a docstring.

---

## 2. The content-domain media reorganisation

### 2.0 Where the domain cut is real - and where the metrics refuse it

The proposed cut is Movies / TV / Music / Books, across services. Before the board list, the honest structural finding:

**The domain cut is real exactly where metrics carry content identity, and impossible where they do not.**

| Pipeline stage | Content identity in metrics? | Consequence |
|---|---|---|
| Acquisition (*arrs) | **Yes, by construction** - each *arr is single-domain (Radarr=movies, Sonarr=TV, Lidarr=music, Readarr=books), Bazarr splits `movie_subtitles_missing_total` vs `subtitles_missing_total` | This is where the reorg has teeth. The old "Acquisition" board dissolves into four domain boards. |
| Library serving (Emby) | **Partially** - `emby_movie_count`, `emby_series_count`, `emby_episode_count` are content-typed; `emby_session_active` is not. No music/book counts exist. | Emby *inventory* joins the domain boards as reconciliation panels; Emby *sessions* cannot. |
| Live sessions (Plex, Emby, Tunarr streams) | **No.** `plex_active_streams_*`, `plex_bandwidth_*`, `plex_transcode_*`, `emby_session_active` carry no media-type or library label in the verified inventory. | **A content-domain split of streaming cannot be built with current metrics. Stated plainly, not solved.** See 2.4. |
| Transport (SABnzbd, NZBGet, Deluge) | **No** - queue lengths and byte rates are content-blind. | Downloaders stays a shared board (2.5). The *domain-visible* view of downloading is each *arr's own `queue_total`, which lands on each domain board. |

So the reorganisation is: **four new domain boards replace the Acquisition board; Streaming and Downloaders are retained as explicitly content-agnostic shared-stage boards; Environment stays on top and gains a cross-domain comparability panel.** Anything else would be pretending the metrics say things they do not.

One rule is added to the design system, generalising constraint 4:

> **Cross-exporter reconciliation is drawn as overlaid series, never as arithmetic in one expr.** `radarr_movie_downloaded_total - emby_movie_count` returns empty if *either* exporter is down (constraint 4), and the resulting "No data" is indistinguishable from a broken query. Two independent targets on one timeseries degrade independently: if one exporter dies, the other series still renders and the gap becomes visibly one-sided. Same-exporter arithmetic (e.g. `sum(lidarr_songs_downloaded_total) / sum(lidarr_songs_total)`) shares a single failure domain with its own metrics and remains allowed.

### 2.1 Board list (after)

| Board | uid | Fate |
|---|---|---|
| Media - Environment | `media-environment` | kept, revised (2.6) |
| Media - Movies | `media-movies` | **new** |
| Media - TV | `media-tv` | **new** |
| Media - Music | `media-music` | **new** (thin - honestly so, see note) |
| Media - Books | `media-books` | **new** (thin) |
| Media - Streaming | `media-streaming` | kept; content-agnostic by necessity; loses the Emby-inventory Q4 filler |
| Media - Downloaders | `media-downloaders` | kept; content-agnostic transport |
| Media - Acquisition | `media-acquisition` | **retired** - contents redistributed to the four domain boards |

On thinness: Music and Books get full boards rather than being merged, for one reason - **navigational uniformity is the four-question system's core asset** (1.1). A half-board would be the only place in the estate where the reader's learned shape breaks. The cost is two boards of ~10 panels instead of one of ~20; the panels are not padded to hide the thinness, and each board says in its description that music/books have no serving-side or per-title depth because Emby/Plex export none for them.

Tags: domain boards are tagged `["media", "domain"]`. `dashboard()` builds the "Related" dropdown from `tags[:1]` = `media`, so all eight boards interlink with no extra work - the existing mechanism already does the navigation.

### 2.2 Grid conventions

24-column grid, dashlib geometry: stat/gauge h=4 (stat w=4, gauge w=5), timeseries/bargauge/table h=8 w=12 unless noted, alert table w=16 h=8. Positions below are `(x, y, w, h)`. Row headers occupy y=0, 9, 22, 31 as in the shipped boards.

### 2.3 Board specs

#### Media - Movies (`media-movies`)

*Radarr owns acquisition, Bazarr owns movie subtitles, Emby provides the served-library count. Plex per-title serving does not exist in metrics (2.4).*

**Row 1 - Is it broken right now?** (y=0)

| Panel | Pos | Expr | Why it earns the slot |
|---|---|---|---|
| stat_floor "Radarr exporter" | (0,1,4,4) | `count(radarr_movie_total) or vector(0)` | Stale-zero guard: with the exporter down, every number below freezes at a plausible value. `vector(0)` legal - metric confirmed. crit_below=1. |
| stat_floor "Bazarr exporter" | (4,1,4,4) | `count(bazarr_movie_subtitles_missing_total) or vector(0)` | Same guard for the subtitle numbers. crit_below=1. |
| alert_table "Firing in media" | (8,1,16,8) | `ALERTS{alertstate="firing",namespace="media"}` | Namespace is the finest alert scope that exists today; a movies-only Q1 would need `domain:` labels added to the media PrometheusRules (flagged: rule change, not a metric gap - worth doing when rules are next touched). |

**Row 2 - Is it doing its job?** (y=9) - the movie library's promise: complete, at cutoff, subtitled, actually served.

| Panel | Pos | Expr | Why |
|---|---|---|---|
| stat "Movies missing" | (0,10,4,4) | `radarr_movie_missing_total` | The domain's headline gap. warn_above=600 (calibrated: 524 on 2026-08-07 - colour means *drift above normal*, not judgment of the backlog's existence). |
| stat "Movies below cutoff" | (4,10,4,4) | `radarr_movie_cutoff_unmet_total` | warn_above=1800 (now 1,596). Cutoff drives storage growth - this stat is also a capacity forecast (established repo finding). |
| stat "Movie subtitles missing" | (8,10,4,4) | `bazarr_movie_subtitles_missing_total` | Bazarr's movie-scoped series - this is the cross-service panel the domain cut exists for. warn_above=50. |
| stat "Movie library" | (12,10,4,4) | `radarr_movie_total` | Inventory - plain value, no colour (dashlib rule). 2,472 now. |
| stat "Emby indexed movies" | (16,10,4,4) | `emby_movie_count` | The served-side count, beside the manager-side count. Plain. |
| stat "Monitored" | (20,10,4,4) | `radarr_movie_monitored_total` | Denominator context for the gap numbers. Plain. |
| timeseries "Movie library gaps" | (0,14,12,8) | `radarr_movie_missing_total` ("missing"), `radarr_movie_cutoff_unmet_total` ("below cutoff") | The stats show level; this shows direction - whether acquisition is winning. The thing a stat cannot express (1.2). |
| timeseries "Radarr vs Emby reconciliation" | (12,14,12,8) | `radarr_movie_downloaded_total` ("radarr downloaded"), `emby_movie_count` ("emby indexed") | Overlaid, never subtracted (2.0). The absolute offset is expected (editions, non-Radarr content); the signal is the gap *changing* - a widening gap means imports or library scans broke, which no single service's board can see. |

**Row 3 - Is it keeping up?** (y=22)

| Panel | Pos | Expr | Why |
|---|---|---|---|
| stat "Radarr queue" | (0,23,4,4) | `radarr_queue_total` | Domain-visible view of the shared transport layer. warn_above=100. |
| stat "Grabs (24h)" | (4,23,4,4) | `increase(radarr_history_total[24h])` | Replaces the admitted-useless lifetime stat with a rate. Caveat: history purges look like counter resets and inflate `increase()` briefly - acceptable for a trend tile, noted in desc. |
| timeseries "Queue depth" | (8,23,8,8) | `radarr_queue_total` | Backlog trajectory. |
| timeseries "Grabs per hour" | (16,23,8,8) | `increase(radarr_history_total[1h])` | Movement. Queue flat + grabs zero for a day = the pipeline is stuck even though nothing is red. |

**Row 4 - Can it keep going?** (y=31)

| Panel | Pos | Expr | Why |
|---|---|---|---|
| bargauge "Root folder free space" | (0,32,12,8) | `radarr_rootfolder_freespace_bytes` legend `{{path}}` **[VERIFY label name against live series]** | Per-entity, replacing the shipped `max()` (1.5). Needs the inverted-threshold bargauge variant (4.3) - free space is low-is-bad. |
| stat "Movie library on disk" | (12,32,4,4) | `radarr_movie_filesize_total` | unit=bytes, plain. |
| timeseries "Movie storage growth" | (16,32,8,8) | `radarr_movie_filesize_total` | The slope turns "how big" into "how long until full", read against the root-folder bars. |

#### Media - TV (`media-tv`)

*Sonarr + episode-scoped Bazarr + Emby series/episode counts + Tunarr - live TV channels are a TV-domain experience built from the TV library.*

**Row 1** (y=0): stat_floor "Sonarr exporter" (0,1,4,4) `count(sonarr_series_total) or vector(0)`; stat_floor "Bazarr exporter" (4,1,4,4) `count(bazarr_subtitles_missing_total) or vector(0)`; stat_floor "Tunarr exporter" (0,5,4,4) `count(tunarr_channel_info) or vector(0)`; stat "Scrape targets down" (4,5,4,4) `count(up{namespace="media"} == 0) or vector(0)` bad_above=0; alert_table (8,1,16,8) as on Movies.

**Row 2** (y=9):

| Panel | Pos | Expr | Why |
|---|---|---|---|
| stat "Episodes missing" | (0,10,4,4) | `sonarr_episode_missing_total` | warn_above=3500 (now 3,187). |
| stat "Episodes below cutoff" | (4,10,4,4) | `sonarr_episode_cutoff_unmet_total` | warn_above=8000 (now 7,580). Capacity forecast, as with movies. |
| stat "Episode subtitles missing" | (8,10,4,4) | `bazarr_subtitles_missing_total` | **[VERIFY]** that this series is episode-scoped (vs all-content) - the name pairs with `movie_subtitles_missing_total`; confirm the split on live data before commit. warn_above=100. |
| stat "Series" | (12,10,4,4) | `sonarr_series_total` | Inventory, plain (152). |
| stat "Emby indexed episodes" | (16,10,4,4) | `emby_episode_count` | Served-side count. Plain. |
| stat_floor "Tunarr channels" | (20,10,4,4) | `count(tunarr_channel_info)` | warn_below=26 (26 expected). A drop means lineup build failure, which from the pod looks identical to "no one is watching". |
| timeseries "TV library gaps" | (0,14,12,8) | `sonarr_episode_missing_total` ("missing"), `sonarr_episode_cutoff_unmet_total` ("below cutoff") | Direction. |
| timeseries "Sonarr vs Emby reconciliation" | (12,14,12,8) | `sonarr_episode_downloaded_total` ("sonarr downloaded"), `emby_episode_count` ("emby indexed") | Same overlay rule and rationale as Movies. |

**Row 3** (y=22): stat "Sonarr queue" (0,23,4,4) `sonarr_queue_total` warn_above=100; stat "Grabs (24h)" (4,23,4,4) `increase(sonarr_history_total[24h])`; stat "Monitored seasons" (8,23,4,4) `sonarr_season_monitored_total` plain; timeseries "Queue depth" (12,23,12,8) `sonarr_queue_total`.

**Row 4** (y=31):

| Panel | Pos | Expr | Why |
|---|---|---|---|
| bargauge "Root folder free space" | (0,32,12,8) | `sonarr_rootfolder_freespace_bytes` legend `{{path}}` **[VERIFY label]** | Per-entity, replacing `max()` (1.5). |
| stat "Channels with thin lineups" | (12,32,4,4) | `count(tunarr_channel_duration_ms < 43200000) or vector(0)` | Replaces `avg(tunarr_channel_duration_ms)` (1.2): counts channels under 12h of programming - the stale-lineup signature from the Tunarr runbook - instead of an average that hides one collapsed channel among 26. warn_above=0. `vector(0)` legal: metric confirmed; empty here means "no channel is thin", which must render as green 0. |
| timeseries "Root folder free trend" | (16,32,8,8) | `sonarr_rootfolder_freespace_bytes` legend `{{path}}` | Slope per folder. |

*Note: there is no sonarr filesize metric in the verified inventory - TV's on-disk footprint cannot be shown per-domain today. **[NOT IN INVENTORY: sonarr series/episode filesize]**. See 5.6.*

#### Media - Music (`media-music`)

*Lidarr only. No serving-side metrics exist for music (Emby exports no music counts; Plex sessions are unlabelled) - said in the board description, not papered over. The library is majority-holes by construction (full discographies monitored: 33,675 albums missing), so missing-counts get NO threshold colour - a permanently red tile trains people to ignore red (dashlib's own reasoning, applied honestly).*

**Row 1** (y=0): stat_floor "Lidarr exporter" (0,1,4,4) `count(lidarr_artists_total) or vector(0)`; stat "Lidarr health issues" (4,1,4,4) `sum(lidarr_system_health_issues)` bad_above=0 (the only *arr exporting its own health-check count); alert_table (8,1,16,8).

**Row 2** (y=9):

| Panel | Pos | Expr | Why |
|---|---|---|---|
| stat "Artists" | (0,10,4,4) | `sum(lidarr_artists_total)` | Inventory, plain. (`sum()` follows the shipped boards - **[VERIFY: confirm the label dimension being summed]**.) |
| stat "Albums" | (4,10,4,4) | `sum(lidarr_albums_total)` | Plain. |
| stat "Albums missing" | (8,10,4,4) | `sum(lidarr_albums_missing_total)` | Plain, deliberately uncoloured (see board note above). |
| stat "Songs downloaded" | (12,10,4,4) | `sum(lidarr_songs_downloaded_total)` | Plain. |
| gauge "Song completeness" | (16,10,5,4) | `sum(lidarr_songs_downloaded_total) / sum(lidarr_songs_total)` | Same-exporter ratio (allowed, 2.0). Needs the inverted-good gauge variant (4.3): high is good here. The ratio is the honest health signal for a majority-holes library - the *count* of missing albums is policy, the *direction of the ratio* is operations. |
| timeseries "Albums missing trend" | (0,14,12,8) | `sum(lidarr_albums_missing_total)` | Is the hole shrinking, static, or growing faster than acquisition. |
| table "Artists by genre" | (12,14,12,8) | `topk(15, sum by (genre) (lidarr_artists_genres_total))` **[VERIFY label name `genre`]** | "Which ones" question - table, not pie (4.5): 15+ classes of anything is a table by rule. Optional panel; drop before shipping if label verification fails. |

**Row 3** (y=22): stat "Lidarr queue" (0,23,4,4) `lidarr_queue_total` warn_above=100; timeseries "Queue depth" (8,23,16,8) `lidarr_queue_total`.

**Row 4** (y=31): stat "Music on disk" (0,32,4,4) `sum(lidarr_artists_filesize_bytes)` unit=bytes, plain. **[NOT IN TICKET INVENTORY: `lidarr_rootfolder_freespace_bytes`]** - the shipped Acquisition board queries it (and claims build-time validation), but it is outside the ticket's verified inventory; re-verify against live Prometheus before carrying it here. If absent, music Q4 rests on filesize plus the shared NFS free-space visibility on the Movies/TV boards.

#### Media - Books (`media-books`)

*Readarr only; same serving-side absence as Music. 137 of 176 books missing - the standout the shipped boards already call out: a small library that is mostly holes is a different problem from a large one with a few.*

**Row 1** (y=0): stat_floor "Readarr exporter" (0,1,4,4) `count(readarr_book_total) or vector(0)` crit_below=1; stat "Scrape targets down" (4,1,4,4) `count(up{namespace="media"} == 0) or vector(0)` bad_above=0; alert_table (8,1,16,8).

**Row 2** (y=9):

| Panel | Pos | Expr | Why |
|---|---|---|---|
| stat "Books" | (0,10,4,4) | `readarr_book_total` | Plain (176). |
| stat "Books missing" | (4,10,4,4) | `readarr_book_missing_total` | Plain, uncoloured - same majority-holes reasoning as Music (137/176). |
| stat "Authors" | (8,10,4,4) | `readarr_author_total` | Plain. |
| stat "Books downloaded" | (12,10,4,4) | `readarr_book_downloaded_total` | Plain. |
| gauge "Book completeness" | (16,10,5,4) | `readarr_book_downloaded_total / readarr_book_total` | Same-exporter ratio; inverted-good gauge (4.3). At ~22% today, the gauge's job is direction, so thresholds sit at "worse than now" (crit below 0.15, warn below 0.22) rather than aspirational values that would read red forever. |
| timeseries "Books missing trend" | (0,14,12,8) | `readarr_book_missing_total` | Direction. |

**Row 3** (y=22): stat "Readarr queue" (0,23,4,4) `readarr_queue_total` warn_above=50; stat "Books grabbed" (4,23,4,4) `readarr_book_grabbed_total` **[VERIFY semantics: lifetime counter vs current-grab gauge - shape the panel (increase vs raw) only after confirming]**; timeseries "Queue depth" (8,23,16,8) `readarr_queue_total`.

**Row 4** (y=31): stat "Books on disk" (0,32,4,4) `readarr_author_filesize_bytes` unit=bytes, plain.

### 2.4 The Streaming problem, stated plainly

**A content-domain split of live streaming cannot be built from the current metrics.** `plex_active_streams_total` and its direct-play/direct-stream/transcode variants, `plex_bandwidth_*`, `plex_transcode_*_sessions`, and `emby_session_active` carry no media-type, library, or title label in the verified inventory. There is no expr - clever or otherwise - that attributes a stream to Movies vs TV vs Music. Every option that "solves" this manufactures data.

What would make it solvable: session metrics labelled by media type - e.g. a Tautulli-class Plex exporter that emits per-session media-type labels, or an upgraded Emby exporter with per-library session counts. That is a new/changed exporter deployment, i.e. out of scope for a dashboard reorg and explicitly **not assumed** here.

Consequences, honestly drawn:

- **Media - Streaming survives as a shared-stage board**, unchanged in role: delivery to a human, whatever the content. Its panels (stream composition, transcode breakdown, bandwidth, namespace CPU) are already the right ones for that role.
- Changes to it: the Emby inventory stats leave Q4 for the domain boards (fixing the 1.2 forcing), and "Tunarr avg channel length" is replaced by the TV board's thin-lineup count. Q4 keeps the fullest-PVC gauge and gains nothing artificial - a shorter honest row beats a padded one.
- Each domain board's description carries one sentence: "Live playback of this content is on Media - Streaming; sessions cannot be attributed to a content domain with current metrics."

### 2.5 Downloaders

Transport is content-blind (SABnzbd/NZBGet/Deluge queues and rates carry no domain), so **Media - Downloaders stays as-is** - its panels are sound, including the deliberately-absent Deluge free-space panel and its in-code rationale. The *domain-visible* face of downloading is each *arr's `queue_total` and grab rate, which the domain boards now carry (Q3). That is the correct seam: "is transport healthy" is one shared question; "is MY domain's stuff moving" is four scoped ones. No rename needed; the board description gains the seam sentence.

### 2.6 Media - Environment revision

The Environment board keeps its role (aggregate the purpose metrics; answer "is the media experience working") with three changes:

1. **The mixed-scale bargauge gets fixed.** The shipped "Library gaps" bargauge puts 33,675 (Lidarr albums) next to 77 (subtitles) on one linear scale - the smallest bars render as zero-pixel slivers, so the panel only ever *shows* Lidarr and Sonarr. Counts also are not comparable across domains (an episode is not an album). Replace with **bargauge "Library completeness by domain"** - four same-exporter ratios on a shared 0-1 scale, which is what bargauge is actually for (ranked comparison of like quantities):
   - `sonarr_episode_downloaded_total / sonarr_episode_total` ("TV episodes")
   - `radarr_movie_downloaded_total / radarr_movie_total` ("Movies")
   - `sum(lidarr_songs_downloaded_total) / sum(lidarr_songs_total)` ("Music songs")
   - `readarr_book_downloaded_total / readarr_book_total` ("Books")
   Inverted-good thresholds (4.3), unit=percentunit. Caveat in desc: downloaded/total approximates completeness where unmonitored items exist; the per-domain boards carry the exact counts.
2. **Books joins the board.** The shipped Environment Q2 has no Readarr presence at all; the ratio bar above adds it, and the raw gap counts stay on the domain boards where their scale is local.
3. **Links.** The Related dropdown already picks up the new boards via the `media` tag; the board description's drill-down order becomes Environment -> domain -> shared stage.

Everything else on Environment (alert counts, exporter guards, streams, queue/backlog, capacity row) stands - it already follows the rules.

### 2.7 Migration and uid hygiene

- New uids `media-movies`, `media-tv`, `media-music`, `media-books`; existing `media-environment`, `media-streaming`, `media-downloaders` retained so saved links and the Related dropdown survive.
- `media-acquisition` is retired **after** the four domain boards ship (one commit: add four ConfigMaps + regenerate environment/streaming, delete acquisition ConfigMap and its kustomization entry). Generator layout: a new `gen_media_domains.py` (four boards, shared helpers); `gen_media_services.py` shrinks to Streaming + Downloaders.
- Every expr above goes through the standing gate: validated against live Prometheus before commit; `emit_configmap`'s dollar-refusal already enforces constraint 2 mechanically.

### 2.8 Consolidated flags for this section

Needs live verification before commit (in addition to the standing validate-every-expr gate): root-folder label name (`path` vs `folder`) on sonarr/radarr `rootfolder_freespace_bytes`; episode-scoping of `bazarr_subtitles_missing_total`; lidarr sum dimension; `lidarr_artists_genres_total` label name; `readarr_book_grabbed_total` semantics; `lidarr_rootfolder_freespace_bytes` existence. Does not exist / not solvable now: per-content-type session metrics (2.4); sonarr filesize (TV disk attribution, 5.6); domain-labelled ALERTS (needs rule edits, 2.3).

---

## 3. Estate cleanup plan - the 44 imported boards

### 3.1 What the 44 actually are

Two distinct populations with different owners and different fixes:

- **~34 chart-bundled boards** from kube-prometheus-stack (`grafana.defaultDashboardsEnabled: true` in `helm-release.yaml`): the k8s mixin set (apiserver, kubelet, namespace/pod resources, etcd, prometheus, alertmanager...), plus node-exporter boards **including the AIX and macOS ones the audit flagged** - those ship with the chart, they were not hand-imported. `k8s-coredns` at 47% (pre-1.7 metric names) is also this population.
- **~10 hand-imported ConfigMaps** in `clusters/main/kubernetes/system/kube-prometheus-stack/app/`: blocky, cloudflared, dcgm-gpu, exportarr ("Sonarr v3"), nginx-ingress, proxmox, smartctl, unpoller, plus two already converted to generated boards (cluster-overview, uptime-kuma - the "Solar PV System" ConfigMap has already been replaced by `gen_uptime_kuma.py`, and the crowdsec/"Rclone" and graphite/"Environment" wrong-content ConfigMaps are already gone from the repo).

### 3.2 Hand-imported ConfigMaps: keep / fix / delete

| Board | Verdict | Reasoning |
|---|---|---|
| `grafana-dashboard-exportarr.yaml` ("Sonarr v3", 7 panels) | **DELETE** now | Fully superseded by the media boards; it is the artifact of the exact gap the generated system was built to close. Keeping it invites the old habit back. |
| `grafana-dashboard-smartctl.yaml` (11% queries alive) | **DELETE** now | The exporter is not deployed; 89% of the board can never render. Re-import (current revision) only if a smartctl exporter ever ships on the Talos nodes. Disk health today comes via the TrueNAS exporter; note the Talos-node-disk gap explicitly rather than keeping a dead board as a placeholder. |
| `grafana-dashboard-nginx-ingress.yaml` | **DELETE** now | The controllers are legacy-pending-decommission, serving one Flux webhook. Ingress observability lives on the Network board (Traefik). A board for a system being removed is negative signal - it implies the system matters. |
| `grafana-dashboard-blocky.yaml` | **DELETE**, folded | The generated Network board already carries Blocky's purpose metrics (blocking enabled, qps, cache ratio, list freshness, failed downloads). A second, imported Blocky board splits attention and rots independently. If a drilldown proves necessary, generate it. |
| `grafana-dashboard-cloudflared.yaml` | **DELETE**, folded | Same reasoning: tunnel connections are on the Network board Q1. |
| `grafana-dashboard-dcgm-gpu.yaml` | **KEEP** (pin + re-import current) | Vendor-maintained (NVIDIA), complex domain, GPU is real (RTX A4000 for ollama). Exactly the case where importing beats generating. Verify it post-Angular (3.4) and record the imported revision in the ConfigMap header. |
| `grafana-dashboard-unpoller.yaml` | **KEEP** (pin + re-import current, trim) | UniFi is a vendor domain with a maintained upstream board family; regenerating would be re-doing UnPoller's work badly. Also the most likely home of legacy graph/piechart panels - re-import the current revision and delete panels targeting hardware not present. |
| `grafana-dashboard-proxmox.yaml` | **KEEP** (pin + re-import current) | The hypervisor is outside repo control (established constraint) - this board is the only in-cluster visibility into it. Same Angular re-import treatment. |
| `grafana-dashboard-cluster-overview.yaml`, `grafana-dashboard-uptime-kuma.yaml` | **KEEP** | Already generated, already compliant. |

### 3.3 Chart-bundled boards

Options, in order of preference:

1. **Per-component flags first.** Where kube-prometheus-stack gates a dashboard behind its component flag, dead boards should fall out of honest component config (e.g. CoreDNS dashboard settings). This fixes `k8s-coredns` (47% alive) the right way - or, if the flag granularity disappoints, case 2 applies.
2. **HelmRelease `postRenderers`** (kustomize patches over rendered chart output - the supported Flux mechanism for exactly this) to drop the specific dead ConfigMaps: the AIX and macOS node boards on an all-Talos cluster, and `k8s-coredns` if not handled above, replaced by the CoreDNS panels already on the generated Network board. Note: plain `kustomization.yaml` patches cannot touch these - HelmRelease output does not pass through the app kustomization.
3. **Do NOT flip `defaultDashboardsEnabled: false`.** The k8s mixin boards (apiserver, kubelet, scheduler, workload resources) are the best-maintained imports in the estate and upstream keeps them current with metric renames - the all-or-nothing switch would trade ~4 dead boards for ~30 good ones.

### 3.4 The Angular problem (measured: 33 `graph`, 6 `singlestat`, 2 `table-old`, 1 `grafana-piechart-panel`)

Angular support was removed in Grafana 12; on 13.0.2 the core Angular panels (`graph`, `singlestat`, `table-old`) are force-migrated to React at load, and migrations drop config (thresholds, legends, axis options) silently. `grafana-piechart-panel` is worse: a third-party Angular plugin that is **not installed** - that panel renders as a broken panel *today*. All 42 of these live in the imported population (generated boards emit only current core types). Plan: for each KEPT import (dcgm, unpoller, proxmox), re-import the current upstream revision - upstream has largely re-authored these in React - rather than trusting force-migration output; the single `grafana-piechart-panel` instance is located during that re-import and removed or replaced with a core panel. For DELETEd boards the problem removes itself. Acceptance check per kept board after re-import: zero panels of type `graph`/`singlestat`/`table-old`/`grafana-piechart-panel` (a one-line grep over the ConfigMap), and >=80% of queries returning data live.

### 3.5 Standing policy (so this audit does not need re-doing from scratch)

- **Three tiers:** generated (owned by `tools/dashboards/`, full rule compliance); vendor-imported (allowed only for complex external domains - GPU, UniFi, Proxmox - pinned to a recorded upstream revision, >=80% query-liveness, no Angular types); everything else is not installed.
- **Liveness is measurable, so measure it:** the audit that produced the 11%/47% numbers becomes a small script in `tools/dashboards/` (walk ConfigMap JSON, extract exprs, query Prometheus, report % returning data), run whenever boards change and quarterly otherwise. The 2026-08 audit found wrong-content ConfigMaps installed "long enough that nobody remembered"; a number on a schedule is the cure for that class.

---

## 4. Panel-type strategy

### 4.1 The job picks the shape

Form first, colour second (the dataviz method: decide what the reader must *do* with the data). For this estate:

| Reader's job | Right shape | Estate examples |
|---|---|---|
| Read one current value against a meaning threshold | **stat** (background colour only when the count is of *bad* things) | alert counts, queue depth, paused flags |
| Read one current value whose *direction* matters | **stat + sparkline** (`graphMode: "area"`) - see 4.3 | missing counts, queue depth |
| Compare like quantities across named entities, "which is worst" | **bargauge** | completeness by domain (2.6), root-folder free space (2.3), per-*arr backlog |
| Identify *which ones* (identity, many classes) | **table** | firing alerts, artists by genre (55 language / many genre classes are far past the ~7-class colour ceiling) |
| Trend, rate, or two-series relationship over time | **timeseries** | gaps trend, reconciliation overlays, throughput |
| A bounded ratio against a limit | **gauge** | PVC fullness, completeness ratios (with 4.3's inverted variant) |
| Discrete state over time - "what happened overnight" | **state-timeline** (core panel, currently used ZERO times in 52 boards) | exporter up/down history, paused-flag history, per-volume Longhorn robustness, ALERTS over 24h |
| Distribution over time | **heatmap** | only genuine candidate is Traefik's latency histogram (network board); **no media metric in the inventory is a histogram**, so no media heatmap is proposed - one would require exporter changes |

### 4.2 What 282 timeseries + 179 stat actually means

The census reads like taste over-reliance; it is mostly **vocabulary ceiling**. `dashlib.py` offers exactly seven shapes (stat, stat_floor, gauge, timeseries, bargauge, table, alert_table), so generated boards *cannot* use anything else; the imported boards contribute the legacy tail (33 graph, 14 pie, 6 singlestat). The fix is not "use more variety" as a value - it is extending the library where a question is currently answered by the wrong shape, and deleting the imports that carry the legacy shapes (section 3).

### 4.3 Concrete dashlib additions (small, each earns its place)

1. **`state_timeline(title, expr, x, y, ...)`** - the one genuinely missing shape. First uses: (a) `up{namespace="media"}` per target - replaces N copy-pasted exporter-up stat tiles per board with one panel that also answers "did it flap overnight", which no stat can; (b) firing-alert history (5.1). Value mappings 0->red / 1->green with text labels; `spanNulls` false so scrape gaps stay visible.
2. **Sparkline flag on `stat`** (`graph_mode="area"`): for Q2/Q3 stats whose direction matters (missing counts, queues). Costs nothing; the stat-tile form is value + trend for exactly this reason.
3. **`bargauge_floor` / `gauge_floor`** - inverted-threshold variants (start red, step up through orange to green), required by 2.3 (root-folder free space) and 2.6 (completeness ratios). Mechanically identical to `stat_floor`'s threshold trick, inheriting its documented "getting this backwards trains people to ignore red" rationale.
4. **A constraint-3 lint in `emit_configmap`**: refuse `max(`/`min(` over a list of known per-entity metrics (rootfolder_freespace, pool_scan_percentage, channel_duration). The 1.5 finding shows the docstring alone did not prevent recurrence.

Explicitly rejected: **piechart** (all 14+1 instances are imports; part-to-whole at one instant is better served by bargauge or the numbers; close values are unreadable in a pie; the plugin-based instance is already dead); **heatmap in media** (no histogram metrics exist - the panel would require inventing data, which constraint 1 exists to prevent); **nodeGraph/flow panels** (5.2 - no data model exists in Prometheus here to feed them).

### 4.4 Wrong-shape instances in the current estate (fix list)

| Where | Today | Should be | Why |
|---|---|---|---|
| Acquisition/Environment Q4 | `max(*_rootfolder_freespace_bytes)` stat | per-entity bargauge_floor | constraint-3 violation; hides the full folder (1.5) |
| Acquisition Q3 | "Grabs recorded" lifetime stat | `increase(..._history_total[24h])` stat | lifetime counters answer "has it ever worked", not "is it working" |
| Streaming Q4 | `avg(tunarr_channel_duration_ms)` stat | count-below-threshold stat (2.3) | average across 26 channels hides one collapsed channel |
| Environment Q2 | mixed-scale gaps bargauge (33,675 next to 77) | ratio bargauge (2.6) | linear shared scale renders small bars as zero pixels; counts are not cross-domain comparable |
| Every media board Q1 | 2-3 exporter-up stat tiles per board | one `up` state-timeline | same information + history, less boilerplate |
| Imported boards | 33 graph / 6 singlestat / 2 table-old / 1 dead piechart | re-import or delete (3.4) | Angular removed in 12; migrations drop config; the plugin one is broken now |

### 4.5 Colour and accessibility (aligning dashlib with the dataviz rules it mostly already follows)

- **Status colours stay reserved.** Green/orange/red appear only where they mean ok/degraded/broken (thresholds); series identity in timeseries stays on `palette-classic`. dashlib already separates these - keep it that way; never colour a series red "for visibility".
- **Colour is never the only channel.** Threshold tiles carry the number; state-timelines get value mappings with text labels; the alert table's severity colour sits beside the severity word. Already house style (the `noValue` text) - state it as a rule so it survives new panel types.
- **Class ceilings:** past ~7 meaningful colour classes, use a table (bazarr's 55 languages, lidarr genres, radarr's 17 quality tiers - if per-quality distribution is ever panelled from `radarr_movie_quality_total`, it is a sorted table or single-hue bargauge, never 17 hues).
- **One axis, one scale.** No dual-axis panels exist in the generated estate; keep it that way - the queue-vs-rate pairs in 2.3 are deliberately separate panels rather than one twin-scale chart.
- Threshold provenance comments (1.4) double as the accessibility story for "why is this orange": the desc explains the calibration, so colour is interpretable, not folklore.

---

## 5. What the four-question layout cannot show, and what would be needed

The four questions are a **present-tense state model of one scope**. Five real question families fall outside it:

### 5.1 "What happened overnight?" - state history

Q1 is instantaneous: an alert that fired for 40 minutes at 03:00 leaves no trace by morning. Structure needed: a **history strip** - state-timeline of `ALERTS` (and `up`) over 24h - either as a fifth element inside Q1's row or on the Environment boards only. Possible today with core panels (4.3); no new metrics needed. This is the highest-value gap: it converts the boards from "current status" to "shift handover".

### 5.2 Pipeline causality - "where is it stuck?"

The media stack is a pipeline (wanted -> grabbed -> queued -> downloaded -> imported -> indexed -> served), and the four questions cannot express flow between stages; each board sees one segment. A true flow view (Sankey / node graph) has no data to feed it: Prometheus here has no item-level or edge-level metrics, and no suitable flow panel arrangement exists without them. What IS approximable today: a fixed **pipeline reading order** per domain board - the ordered stats already specified in 2.3 (missing -> queue -> grabs/24h -> downloaded -> emby-indexed) read left-to-right as stage counters; a stuck stage shows as a stalled number with moving neighbours. The causality stays in the reader's head; the layout can at least put the stages in causal order. Anything more requires per-item event data (logs/traces, not these metrics).

### 5.3 "Is tonight normal?" - baselines and seasonality

A stat says 4 streams; nothing says whether that is a lot for a Tuesday. Expressible today without structural change, using PromQL `offset`: add `plex_active_streams_total offset 1w` ("same time last week") as a second, visually muted series on the Streaming composition panel. Fixed offset, no dollar sign, metric confirmed. The layout has no *home* for baselines - by convention they live in Q2 as context series, never as their own row.

### 5.4 Windowed conformance - "what fraction of the last 30d was X true?"

The layout has no place for SLO-shaped questions (exporter uptime %, hours-with-zero-missing, backup-freshness conformance). Structure needed: recording rules (e.g. `avg_over_time(up[30d])` is too heavy ad hoc; precompute) plus either a fifth row ("How has it been?") or a dedicated conformance board. Recommendation: **do not** bolt a fifth row onto every board - the four-question shape's value is its fixedness (1.1). If SLO reporting is ever wanted, it is one board, fed by recording rules, and a separate design exercise. Flagged as future work, not designed here.

### 5.5 Content-attributed streaming

Covered in 2.4: not solvable with current metrics; requires media-type-labelled session metrics from a different/upgraded exporter. Named here because it is the one gap that blocks part of the ticket's ask itself.

### 5.6 Cross-domain capacity attribution - "who is eating the disk?"

Q4 shows how full things are, not which domain filled them. Partially possible today: `radarr_movie_filesize_total`, `sum(lidarr_artists_filesize_bytes)`, `readarr_author_filesize_bytes`, `bazarr_subtitles_filesize_total` support a four-bar "on-disk by domain" bargauge on Environment Q4 - except **TV, the largest consumer, has no filesize metric in the inventory [NOT IN INVENTORY]**, so the panel would silently omit the biggest slice and mislead. Per constraint-1 thinking (a confident partial answer is worse than none), the cross-domain disk panel is **not proposed** until a sonarr filesize metric exists; the per-domain boards carry what exists.

### 5.7 Event correlation - "what changed?"

Every generated board has an empty `annotations` list; CPU spikes and gap-trend kinks float free of causes. Possible today: a Prometheus annotation query on `increase(kube_pod_container_status_restarts_total{namespace="media"}[5m]) > 0` marks restarts on every media board's time axis (metric already used by the Environment board, hence confirmed). NOT possible: Flux reconcile/deploy annotations from `gotk_resource_info` - that metric is **confirmed absent** in this cluster (it is the ticket's own cautionary example); a Flux-event annotation source would need verification of which `gotk_*` series actually exist here first.

### Summary

| Gap | Needs | Possible today? |
|---|---|---|
| State history / handover | state-timeline of ALERTS + up | **Yes** - core panel |
| Pipeline flow | ordered stage row (approx.) / item-level events (real) | Approximation yes; real flow no |
| Baselines | `offset 1w` context series | **Yes** |
| Windowed SLO | recording rules + separate board | Future work |
| Streaming by content | labelled session metrics | **No - exporter change required** |
| Disk by domain | sonarr filesize metric | **No - metric missing (TV)** |
| Event annotations | restart-based annotation query | **Yes** (restarts only; Flux events unverified) |

---

## Appendix A - metric grounding

Every expr in section 2 uses only: (a) ticket-verified inventory metrics (sonarr_*, radarr_*, lidarr_*, readarr_*, bazarr_*, plex_*, emby_*, tunarr_*, sabnzbd_*, nzbget_*, deluge_*), (b) exprs already shipped in the generated boards and therefore live-validated at their build time (`ALERTS`, `up{namespace="media"}`, `kube_pod_container_status_restarts_total`, `kubelet_volume_stats_*`, `container_cpu/memory_*`), or (c) items explicitly flagged. Flags: **[VERIFY]** = exists but label/semantics unconfirmed (root-folder label name; bazarr episode scoping; lidarr sum dimension; genre label; readarr grabbed semantics; lidarr rootfolder metric). **[NOT IN INVENTORY]** = do not build until it exists (sonarr filesize; per-content-type session labels; domain-labelled ALERTS; gotk_resource_info). Standing gate unchanged: every expr is run against live Prometheus before any generated board is committed.

## Appendix B - implementation sequencing (for the follow-up ticket, not this document)

1. dashlib additions (4.3): `state_timeline`, sparkline flag, `bargauge_floor`/`gauge_floor`, constraint-3 lint. 2. `gen_media_domains.py` (four boards, 2.3) + Environment revision (2.6) + Streaming Q4 slim-down (2.4); retire `media-acquisition` in the same commit; run the live-validation gate on every expr including the [VERIFY] items. 3. Estate deletions (3.2), then chart-default handling via component flags / postRenderers (3.3), then Angular re-imports (3.4). 4. Liveness-audit script + policy (3.5).