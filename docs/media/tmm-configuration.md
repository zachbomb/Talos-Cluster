# TinyMediaManager configuration — SQ-53 (2026-08-07)

> **DRIFT WARNING, read first.** TMM's settings live in `/data/data/*.json` on the
> `tinymediamanager-data` PVC, **not in this repo**. Nothing here is applied by Flux.
> TMM **rewrites these JSON files on exit**, so a live edit gets clobbered — the only
> safe change procedure is: scale the deployment to 0, edit via a helper pod, scale
> back to 1 (see "Change procedure" below). This file is the record and the reasoning;
> the source of truth is the PVC. Pre-change snapshot:
> **`/data/config-snapshot-sq53-20260807/`** (on the PVC, covered by the nightly
> VolSync backup).

Deployed at time of record: **TMM 5.3.0** (`docker.io/tinymediamanager/tinymediamanager:5.3.0`,
TrueCharts chart 14.8.0), pod in `media`, UI at `https://tinymediamanager.${BASE_DOMAIN}/`
(noVNC). HTTP command API enabled, in-pod only (see below).

## What TMM is for here

TMM manages **on-disk presentation metadata and artwork** for the media library —
posters, fanart, and (for TV only) NFO metadata — and provides a workbench for
validating that every folder on disk is matched to the right title. It is **not** the
identity authority (Radarr/Sonarr are), it does **not** rename anything (Radarr/Sonarr
do), and it is **not** the gap tracker (Radarr/Sonarr `/wanted/missing` is).

## The ownership matrix (the central decision)

Two producers writing the same class of file to the same folders, with no declared
authority, is exactly how this estate accumulated 57 folders whose NFO TMDB id
contradicts Radarr, and 257 phantom "movies" in Emby promoted from extras sidecars.
Every row below therefore names **one** owner, on measured evidence:

| Surface | Owner | Evidence |
|---|---|---|
| Movie identity | **Radarr** | 2,478 records, corrected through the SQ-20 remediation; TMDB-keyed |
| TV identity | **Sonarr** | 152 series, TVDB-keyed, `{tvdb-N}` folder tags |
| File/folder naming | **Radarr / Sonarr** | see "Naming" below; TMM renamer disabled outright |
| Movie metadata on disk | **Radarr** (`movie.xml`) | Radarr's `Emby (Legacy)` consumer is enabled (`movieMetadata: True`) and writes continuously; present in ~89% of a 400-folder sample. TMM movie NFO writing **off** |
| TV metadata on disk | **TMM** (`tvshow.nfo` + `<episode>.nfo`) | **Every** Sonarr metadata consumer is disabled (verified `/api/v3/metadata` 2026-08-07) — TMM is the sole producer, so no conflict class exists |
| Movie artwork | **TMM** | Radarr's enabled consumer has **no image option at all** (verified: `Emby (Legacy)` exposes only `movieMetadata`) — no collision possible |
| TV artwork | **TMM** | Sonarr writes nothing (above) |
| Subtitles | **Bazarr** | Bazarr writes external SRT into the same media folders, converts non-SRT via `pysubs2`, and is governed by language profiles (`docs/media/bazarr-pvc-config-record.md`). TMM's subtitle scrapers are now `[]` in **both** files so the constraint is mechanical, not procedural — TMM wrote `Movie.eng.srt` (ISO3T) against Bazarr's 2-letter tags: two producers, two naming conventions, one folder |
| Gap tracking | **Radarr / Sonarr** | `/wanted/missing` already tracks monitored-but-missing; TMM adds nothing there and is not configured for it |

### Why Radarr keeps movie metadata (and TMM does not write movie NFOs)

1. **Radarr's file is live.** `movie.xml` is rewritten on every import, upgrade and
   edit, keyed to Radarr's (remediated) TMDB identity, with zero human intervention.
   A TMM-written NFO is a snapshot that goes stale until someone re-scrapes.
2. **A TMM NFO would be a second document, not a replacement.** TMM writes
   `<moviefile>.nfo`; Radarr writes `movie.xml`. Neither touches the other. On the
   measured sample that leaves 137/400 folders carrying two metadata files that can
   drift apart indefinitely — with Emby's `LocalMetadataReaderOrder` unpinned
   (`None`), so precedence between them is undefined. That is the exact preconditions
   of the original damage.
3. **Nothing would read it today.** Emby's NFO reader was disabled 2026-08-07
   (`DisabledLocalMetadataReaders: ["Nfo"]`) because the residue was untrustworthy;
   Plex has never read NFOs. Emby *does* read `movie.xml`.
4. **TMM's movie matching is the risky kind.** Movie folders carry no id tags
   (see Naming), so TMM must match ~1,889 films by title/year — the failure mode that
   produced the five wrong-film folders found 2026-08-07. Arming a writer on top of
   unvalidated matches bakes errors into 2,470 folders.

**Revisit trigger:** if Radarr's `Emby (Legacy)` consumer is ever turned off, movie
NFO writing in TMM becomes the natural replacement — re-arm `nfoFilenames` to
`[FILENAME_NFO]` (per-file naming, required for multi-version folders) and validate
identity first.

### Why TMM owns TV metadata

Sonarr writes no metadata at all, so there is no competing producer and no drift
class. The existing `tvshow.nfo` residue (from the dead TMM instance) includes ~25
files carrying a **TMDB** uniqueid inside this TVDB-keyed tree; TMM, correctly
configured (TVDB scraper, `writeCleanNfo: true`), is the tool that replaces that
residue with correct files. TV matching is also near-deterministic: every series
folder carries `{tvdb-N}`, which TMM parses for identity, so the mismatch risk that
blocks movie NFO writing barely exists for TV.

NFO generation itself is **SQ-54** (scrape → validate identity → fix misimports).
Nothing has been scraped or written to the media share in SQ-53.

## Axis 1 — Naming

**Radarr and Sonarr own naming, files and folders. TMM's renamer is disabled outright**
(`renamerFilenameEnabled`/`renamerPathnameEnabled` false for movies;
`renamerFilename/TvShowFoldername/SeasonFoldername-Enabled` false for TV;
`renameAfterScrape: false` in both). A TMM "Rename" click now changes nothing.

Grounds:

- **A rename outside the arrs orphans their databases.** Radarr does not detect
  externally renamed folders; a TMM folder rename would strand Radarr's path records
  for up to 2,470 movies. Renames must originate from the tool that tracks the paths.
- **The arrs already rename continuously** on import/upgrade. A second renamer with a
  different template fights the first indefinitely, and every rename churn invalidates
  Plex/Emby/Tunarr references (measured today: ~45 stale Tunarr program rows and a
  channel airing colour bars after renames).
- **The `{tmdb-}` gap is a Radarr enforcement gap, not a TMM job.** Radarr's
  configured `movieFolderFormat` already includes `{tmdb-{TmdbId}}`; folders lack it
  because Radarr only applies folder renames when explicitly asked (Movie Editor bulk
  rename). The TV tree, where Sonarr's `{tvdb-N}` convention *is* applied, has almost
  none of the identity defects movies have — strong evidence the fix is to make
  Radarr apply its own format. That is **SQ-25**, deliberately gated behind the
  identity defects D1–D6 (a bulk rename before those are fixed would stamp
  wrong-identity names onto six known-correct files — see
  `remediation-plan-2026-08-04.md`).
- Canonical formats (unchanged, per `id-tag-format-decision.md`): movies
  `Title (Year) {tmdb-N}` (target; suffix pending SQ-25), TV
  `Title (Year) {tvdb-N}/Season XX/`. The 62 alternate cuts
  (`{edition-…}`, `-bootlegcut`, `-alternate`) are intentional and must remain
  independently selectable — another reason no automatic renamer may touch them.

## Axis 2 — Information sources

| Setting | Value | Why |
|---|---|---|
| Movie scraper | `tmdb` | Must match Radarr's TMDB keying — one id namespace per library |
| TV scraper | `tvdb` | Must match Sonarr's TVDB keying; prevents re-seeding the TMDB-uniqueid-in-TVDB-tree hazard found in ~25 residue NFOs |
| Movie artwork providers | `tmdb`, `fanarttv` | fanart.tv adds curated high-res art TMDB lacks |
| TV artwork providers | `tmdb`, `tvdb`, `fanarttv` | TVDB is authoritative for season art |
| Ratings | IMDB (deduplicated; was `["IMDB","IMDB"]`) | single displayed source |
| Language / certification | `en` / `US` | matches library and player settings |
| Scraper fallback | off (movies) | a fallback provider answering in a different id namespace is how cross-namespace ids creep in |

`doNotOverwriteExistingData` stays `false`: when SQ-54 scrapes, TMM data should be
**replaced** by scraper truth, not merged over residue. Likewise `writeCleanNfo: true`
(both modules): unknown/junk tags parsed from the untrusted residue NFOs are dropped
rather than carried forward into newly written files.

## Axis 3 — Posters / artwork

TMM owns artwork in both libraries (no other producer exists — verified, see matrix).
Selected types and filenames:

| Type | Filename | Read by |
|---|---|---|
| Movie poster | `poster.jpg` (`POSTER`) | Plex ✔ Emby ✔ Kodi ✔ |
| Movie fanart | `fanart.jpg` (`FANART`) | Plex ✔ Emby ✔ Kodi ✔ |
| Show poster | `poster.jpg` | Plex ✔ Emby ✔ |
| Show fanart | `fanart.jpg` | Plex ✔ Emby ✔ |
| Season poster | `seasonXX-poster.jpg` (`SEASON_POSTER`) | Emby ✔ Kodi ✔ (Plex support uncertain — acceptable; Plex fetches its own) |

Changed from the previous `FILENAME_POSTER`/`FILENAME_FANART` (i.e.
`<moviefile>-poster.jpg`): Plex's local-asset reader wants the folder-level names;
Emby reads both. **Multi-version folders are safe:** in a folder holding several video
files TMM automatically switches to `<filename>`-prefixed artwork, keeping each
edition's art independently attached.

Rejected artwork types, all set to write nothing — banner, clearart, clearlogo,
discart, keyart, landscape/thumb, extrafanart, character art, season banner/fanart/thumb,
**episode thumbs**: no consumer in this estate reads them from disk (Plex and Emby
fetch what they need from their own providers), and episode thumbs alone would mean
~6,800 image writes for art the players generate themselves. Movie-set artwork and
set NFOs are also off — no `movieSetDataFolder` is configured and neither player
consumes Kodi movie-set files here.

Image sizes: `LARGE` poster / `LARGE` fanart (original-resolution variants preferred,
`imageScraperOtherResolutions` on, prefer language-free fanart).

**Nothing has been downloaded yet** — artwork fetches happen alongside SQ-54's scrape,
after identity validation.

## Axis 4 — Folder structure & datasources

- Datasources: exactly **`/movies`** and **`/tv`** (set in `movieDataSource` /
  `tvShowDataSource`). The broader `/media` mount stays out — it would double-index
  the same trees plus non-video categories.
- One movie per folder (`allowMultipleMoviesInSameDir: false` in the renamer profile,
  and the library is laid out that way); editions either as sibling files in the
  folder or `{edition-…}` folders.
- **Extras**: the 1,356 `Featurettes/Interviews/Trailers/…` directories are recognized
  by TMM's own classifier — folder names on its hardcoded extras list
  (`extras`, `featurettes`, `behind the scenes`, `interviews`, `deleted scenes`,
  `trailers`, …, verified in TMM 5.x source, `MediaFileHelper.java`) are typed
  `EXTRA`/`TRAILER` and attached to the parent movie. **TMM creates no library
  entries for them and writes no NFOs or artwork into them.** The existing per-extra
  `.nfo`/poster sidecars are residue (they are what Emby promoted into 257 phantom
  movies); TMM will neither maintain nor delete them. Their cleanup is a separate
  decision once Emby's handling is settled.
- `skipFoldersWithNomedia: true` and skip-folder `MAKEMKV` kept.

## Operational settings

| Setting | Value | Why |
|---|---|---|
| `renameAfterScrape` | `false` (both) | hard constraint; renamer is disabled anyway |
| `updateOnStart` | **`true` — temporary** (both) | see below: the only reliable headless trigger for "update data sources" found. **SQ-54 should revert to `false`** in its own maintenance window — a full datasource walk is real NFS metadata load over ~2,600+ folders and should not remain a side effect of every pod restart |
| `buildImageCacheOnImport` | `false` (both, was `true`) | building the image cache over ~1.9k movies risks filling the 2Gi `/data` PVC |
| `enableHttpServer` | `false` — **self-reverting, do not rely on it** | Setting it `true` worked exactly once (the API on `localhost:7878` accepted `{"action":"update"}` and started the first scan), but TMM held `false` in memory on subsequent boots and wrote `false` back to `tmm.json` on its next graceful exit — behavior consistent with license/Pro gating re-evaluated at startup. Until that is understood, the reliable triggers are the UI (noVNC) or `updateOnStart` |
| Trakt sync | off | not in use |
| Trailer/subtitle download | explicit-action only (no automatics) | writes into the media tree must be deliberate |

## What was applied and how (2026-08-07)

Procedure (the only safe one — TMM rewrites its JSON on exit):

1. `kubectl scale deploy tinymediamanager -n media --replicas=0`, wait for the pod to
   finish its graceful exit (takes >3 min — it saves state).
2. Helper pod (`busybox`) mounting PVC `tinymediamanager-data`.
3. Snapshot: `cp -a /data/data /data/config-snapshot-sq53-20260807`.
4. Configs pulled, edited **deterministically by script** (asserts preconditions,
   changes only intended keys), pushed back via `cat >` (preserves uid 568 ownership),
   md5-verified.
5. Helper pod deleted, deployment scaled back to 1, checksums re-verified after TMM
   startup, then a read-only **"update data sources"** run for both libraries (first
   via the HTTP API while it briefly worked, then re-run via `updateOnStart` after an
   external deployment bounce interrupted the MediaInfo phase). The scan populates
   TMM's database; it writes nothing to the media share. First-scan result: 24,822
   files walked under `/movies`, **1,952 movie entries created** (vs Radarr's 1,889
   movies-with-file — the delta is unmatched/multi-video material for SQ-54 to
   adjudicate).

Full changed-key list (old → new) for `movies.json`, `tvShows.json`, `tmm.json` is
reproduced in ticket SQ-53's submission; the semantic content is exactly the tables
above. Not run in this ticket: scrape, NFO/artwork writing, any rename/move/delete —
all deferred to SQ-54 (blocked on identity validation).

## Rejected defaults (and on what grounds)

| Default | Rejected because |
|---|---|
| Movie NFO writing armed (`FILENAME_NFO`, Kodi connector) | Radarr already maintains `movie.xml` live; second producer = drift; zero consumers for movie NFOs today |
| Kodi movie-set NFOs/artwork (`KODI_NFO` etc.) | no consumer, no set data folder |
| `<file>-poster.jpg` artwork naming | Plex wants folder-level `poster.jpg`/`fanart.jpg`; Emby reads both |
| Full artwork spread (banner/clearart/discart/keyart/thumb/…) | no on-disk consumer; pure clutter in 2,470 folders |
| Episode thumb writing | ~6,800 files the players generate themselves |
| TMM renamer enabled | naming belongs to the tools that track the paths (Radarr/Sonarr); external renames orphan their DBs and churn Plex/Emby/Tunarr |
| `buildImageCacheOnImport: true` | 2Gi PVC protection |
| Update-on-start as a *permanent* setting | NFS walk as restart side effect — currently `true` only as the interim scan trigger; SQ-54 reverts it |
| `writeCleanNfo: false` | would carry junk tags from untrusted residue into new files |

## What TMM can and cannot tell us about gaps

Radarr/Sonarr `/wanted/missing` remains the gap tracker for monitored-but-missing
items, and TMM is deliberately not configured as a gap detector (missing-episode /
missing-set-member display off). What TMM *uniquely* adds is the inverse direction:
**disk-first validation** — every folder/file on the share becomes a TMM entry that
can be checked against the arrs' databases for unmatched, duplicated, or
wrongly-identified items (the class Radarr's title-only folders make possible).
That is the SQ-54 workflow.

### Why subtitles needed a row (added 2026-08-08)

The matrix exists because *two producers writing the same class of file to the same
folders, with no declared authority* is how this estate accumulated 57 contradictory
NFO ids and 257 phantom Emby movies. Subtitles were exactly that shape and had no row:
Bazarr owned them in practice while TMM carried four subtitle scrapers and a different
language-tag style. Latent rather than active — TMM has no automatic-subtitle-download
setting, so those scrapers only fire on an explicit user action — but a gap in the
matrix is a gap regardless of whether it has bitten yet.

Surfaced by the SQ-59 full-settings audit (`docs/media/tmm-settings-audit.md`), which
walked all 318 keys after a keyword-filtered spot-check had wrongly reported the
configuration as verified.
