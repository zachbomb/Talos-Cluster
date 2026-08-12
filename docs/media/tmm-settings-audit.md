# TinyMediaManager 5.3.0 — full settings audit (318 keys)

**SQ-59. Audit only. Nothing was scraped, scanned, renamed, written to the media share,
or changed by this ticket.** All cluster access was read (`kubectl exec … cat`, `ls`,
kubelet metrics). Intended repo path `docs/media/tmm-settings-audit.md` was **not
written** — this dispatch was prepared read-only; materialise this document there.

## Provenance and a drift warning

| capture | when (UTC) | source |
|---|---|---|
| **T1** baseline | 2026-08-08 ~08:14 | pod `tinymediamanager-6dbf6c44f8-t2bkv`, `/data/data/*.json` |
| **T3** authoritative | 2026-08-08 ~08:27 | pod `tinymediamanager-6dbf6c44f8-lw889`, after the SQ-59 change window |

**Every "current" value in this document is T3.** Key counts at both T1 and T3:
`tmm.json` 75 + `movies.json` 124 + `tvShows.json` 119 = **318**. No key was added or
removed by the change window — only values changed.

The config was **actively mutated while this audit ran** (deployment cycled 0→1 three
times; `tmm.json` mtime 08:20:12, `movies.json`/`tvShows.json` 08:25:11). Pre-change
backup is on the PVC at `/data/config-snapshot-sq59-20260808-081757/`. TMM rewrites
these files on graceful exit, so this audit has a short shelf life — re-diff before
acting on it.

### Stale premises in the ticket, corrected against measurement

| ticket said | measured |
|---|---|
| `tvshows.db 12,288 bytes` — TV never scanned | **TV is imported.** `tvshows.db` 8,093,696 B. Log: `TvShowUpdateDatasourceTask` — files 12,917, **TV shows 143, episodes 8,137**, completed 08:45 local |
| `/tv 144 series` | 144 series **directories**; 143 imported |
| `httpApiKey` present / port 7878 / auto-update on / `ignoreSSLProblems` on | all four already remediated in the change window (see §2) |

`movies.db` is 4,198,400 B at T3 (down from 10,887,168) — H2 compaction on shutdown,
not data loss; movie entry count is unchanged.

### The change window: 14 keys, not 13

The coordinator briefing listed 13. The measured T1→T3 diff is **14** — it omits
`movies.releaseDateCountry "" → "US"`. Full verified diff:

| file | key | T1 | T3 |
|---|---|---|---|
| tmm | `enableAutomaticUpdate` | true | **false** |
| tmm | `httpApiKey` | `<uuid>` | **`""`** |
| tmm | `httpServerPort` | 7878 | **7880** |
| tmm | `ignoreSSLProblems` | true | **false** |
| movies | `runtimeFromMediaInfo` | false | **true** |
| movies | `useMediainfoMetadata` | false | **true** |
| movies | `nfoWriteArtworkUrls` | true | **false** |
| movies | `releaseDateCountry` | `""` | **`"US"`** ← *not in the briefing list* |
| movies | `scraperMetadataConfig` | 31 entries | **29** (−EXTRAFANART, −EXTRATHUMB) |
| movies | `renamerProfiles.Default.renamerPathname` | `${title} (${year})` | **`… {tmdb-${tmdbid}}`** |
| tv | `useMediainfoMetadata` | false | **true** |
| tv | `nfoWriteArtworkUrls` | true | **false** |
| tv | `tvShowScraperMetadataConfig` | 38 | **35** (−EXTRAFANART, −CHARACTERART, −THEME) |
| tv | `renamerProfiles.Default.renamerTvShowFoldername` | `${showTitle} (${showYear})` | **`… {tvdb-${tvdbid}}`** |

Twelve of the fourteen are **correct and endorsed**. Two are challenged in §1.

---

## §0 — Settings that affect IDENTITY resolution

These are the only settings that can *corrupt* the library rather than merely look
wrong. Everything else is cosmetic, throughput, or file-layout.

| key | file | current | identity role | verdict |
|---|---|---|---|---|
| `movieScraper` | movies | `tmdb` | the id namespace movie identity is written in; must equal Radarr's | **KEEP** |
| `scraper` | tv | `tvdb` | must equal Sonarr's keying; wrong value re-seeds the TMDB-uniqueid-in-TVDB-tree defect | **KEEP** |
| `scraperFallback` | movies | `false` | a fallback provider answers in a *different* id namespace → cross-namespace ids | **KEEP false** |
| `scraperThreshold` | movies | `0.75` | **the single most identity-critical movie key.** Movie folders carry no `{tmdb-}` tag, so identity is decided by title/year string score. 0.75 is TMM's default, tuned for id-tagged libraries | **RAISE — operator decision** (§1-C) |
| `useMediainfoMetadata` | movies **and** tv | `true` | seeds entity metadata **incl. title** from embedded container tags when no NFO exists | **CHALLENGED — revert movies** (§1-A) |
| `movieDataSource` / `tvShowDataSource` | | `["/movies"]` / `["/tv"]` | scope of what gets identified at all | **KEEP** |
| `doNotOverwriteExistingData` | both | `false` | scraper truth replaces residue rather than merging over it — correct, but it also means a *wrong* match overwrites a right one | **KEEP false**, gate behind threshold |
| `nfoFilenames` | movies | `[]` | TMM writes no movie NFO ⇒ a wrong TMM match cannot reach disk | **KEEP `[]` — this is the load-bearing safety** |
| `nfoFilenames` / `episodeNfoFilenames` | tv | `["TV_SHOW"]` / `["FILENAME"]` | TMM *is* the TV NFO producer ⇒ a wrong TV match **does** reach disk | KEEP, but gate on SQ-58 |
| `renameAfterScrape` + 4 `renamer*Enabled` | both | all `false` | a rename outside the arrs orphans their path records | **KEEP false — hard constraint** |
| `writeCleanNfo` | both | `true` | drops junk tags parsed from untrusted residue instead of carrying them forward | **KEEP** |
| `certificationCountry` / `scraperLanguage` / `nfoLanguage` | | `US` / `en` / `en` | selects which localized title the match is scored against | **KEEP** |

**Measured identity anchors (this audit):**
- movies: 150-folder sample → **31 (20.7%) have any `.nfo`**, **130 (86.7%) have `movie.xml`**. Consistent with SQ-53's ~89%.
- tv: 144 dirs → **143 (99.3%) carry `{tvdb-N}`**, 65 (45%) have `tvshow.nfo`.
- **One TV directory has no `{tvdb-}` tag** — the single TV identity gap. SQ-58 territory; not acted on here.

---

## §1 — Findings requiring a verdict

### 1-A. HIGH — `useMediainfoMetadata: true` is not the runtime setting, and it is identity-affecting on movies

The briefing groups this under *"both libraries now derive runtime from the FILE"*. That
benefit is delivered entirely by **`runtimeFromMediaInfo`**, a separate key.
`useMediainfoMetadata` is documented as:

> *"Extract meta data (via mediainfo) on update data sources **if no NFO is available**"*
> — tinyMediaManager v5 Movie/TV Show settings docs

That is embedded **container-tag** extraction — title and other fields, not just runtime.

Why it matters here specifically:
1. **79% of movie folders have no NFO** (measured, above). TMM does not read Radarr's
   `movie.xml` as an NFO, so `movie.xml` does not suppress this. The condition is true
   for roughly **1,540 of 1,952** movie entries — the common case, not a corner case.
2. Movie identity in this estate is decided by **title/year string matching** (no
   `{tmdb-}` folder tags). Anything that changes the title TMM holds changes the search
   term identity is scored on.
3. Embedded titles in scene releases/remuxes are routinely absent, wrong, or
   release-group junk.
4. `doNotOverwriteExistingData: false` means already-populated entries are replaced.
5. **`updateOnStart: true` means this fires on the next pod restart with no further
   human action** — and the deployment cycled three times during this audit alone.

Proof the two keys are distinct: **TV already had `runtimeFromMediaInfo: true` before
the change window.** Setting `useMediainfoMetadata: true` on TV therefore delivered
**zero** runtime benefit — only embedded-metadata extraction.

**UNKNOWN (stated, not guessed):** I could not establish from the v5.3 docs whether the
extracted title actually feeds the *scraper search term* versus only populating display
fields, nor whether UDS-time extraction respects `doNotOverwriteExistingData`.

**Recommendation:** revert `movies.useMediainfoMetadata` → `false` pending confirmation;
keep `runtimeFromMediaInfo: true` (that is the setting that was actually wanted). TV may
stay `true` — `{tvdb-N}` anchors identity there — but it buys nothing, so `false` is the
cheaper default. **Decide before the next restart.**

### 1-B. MEDIUM — `updateOnStart: true` (both) is still the interim value SQ-53 said to revert

`docs/media/tmm-configuration.md` records this as **"`true` — temporary … SQ-54 should
revert to `false`"**: a full datasource walk is real NFS metadata load over 2,600+
folders as a side effect of *every* pod restart. It is still `true`. The audit window
alone triggered three restarts, and the just-completed walk took ~1h58m for movies plus
~10m for TV. It is also the delivery mechanism for 1-A. **Revert to `false`** once a
deliberate trigger exists.

### 1-C. MEDIUM — `scraperThreshold: 0.75` is the default, on the one library with no id tags

0.75 on title/year matching over ~1,952 entries is how the five wrong-film folders found
2026-08-07 happen. Raising it (0.85–0.90) converts "confidently wrong" into "unmatched",
which is recoverable; unmatched items surface in TMM's own missing-metadata view.
**Operator decision** — it trades coverage for correctness. TV has no equivalent key.

### 1-D. LOW — the artwork trim was partial

The change window removed only the *subfolder-creating* types. Still present in the
scrape configs with **empty filename lists**, i.e. scraped but never written:

- movies (6): `BANNER CLEARART THUMB CLEARLOGO DISCART KEYART`
- tv (9): `BANNER CLEARART THUMB CLEARLOGO DISCART KEYART SEASON_FANART SEASON_BANNER SEASON_THUMB`
- episode (1): `THUMB` (`episodeThumbFilenames: []`)

Now that `nfoWriteArtworkUrls` is `false`, these no longer reach the NFO either, so the
only remaining cost is **scrape-time provider calls** — a throughput cost on a
CPU-constrained node across 1,952 movies + 143 shows. **UNKNOWN:** whether TMM downloads
the image bytes or only the URLs when no filename is configured; the v5.3 docs do not
say. Trimming makes the question moot at zero risk. **Safe-now.**

### 1-E. LOW — `tvShowScraperMetadataConfig` contains `TAGLINE` twice

Positions 6 and 35 of the 35-entry list. Same defect class as the `["IMDB","IMDB"]`
SQ-53 deduplicated, and as `universalFilterFields` (§1-F). Survived the change window.
**Safe-now: deduplicate.**

### 1-F. COSMETIC — `universalFilterFields` is fully duplicated in *both* files

All 12 entries listed twice (24 total), identically in `movies.json` and `tvShows.json`.
UI filter scope only. **Safe-now: deduplicate.**

### 1-G. MEDIUM (gap in the ownership matrix) — subtitles have no declared owner

`docs/media/bazarr-pvc-config-record.md` establishes **Bazarr owns subtitles**: it writes
external SRT into the same media folders, converts non-SRT via `pysubs2`, and is governed
by language profiles. The SQ-53 ownership matrix has **no Subtitles row**.

TMM currently carries subtitle scrapers — movies `["opensubtitles2","opensubtitles","yify","subdl"]`,
tv `["opensubtitles2","opensubtitles","subdl"]` — and `subtitleLanguageStyle: ISO3T`
(`Movie.eng.srt`) where Bazarr's profile writes 2-letter tags. Two producers, two naming
conventions, same folders: exactly the drift class the matrix exists to prevent.

Latent, not active: TMM has no automatic-subtitle-download setting; these fire only on an
explicit user action. **Recommendation:** add a *Subtitles → Bazarr* row to
`tmm-configuration.md`, and set `subtitleScrapers: []` in both files to make the
constraint mechanical rather than procedural. **Safe-now** (no automatic behaviour changes).

### 1-H. MEDIUM — image cache sizing against a 2 GiB PVC

Measured now: capacity **2,040,373,248 B**, used **384,348,160 B (18.8%)**, free
**1,639,247,872 B**, **inodes used 90** — i.e. the image cache is effectively *empty*
today because nothing has been scraped and `buildImageCacheOnImport: false`.

Documented meanings: `imageCacheSize: BIG` = scale to **1000 px long side**
(`SMALL` = 400 px, `ORIGINAL` = no scaling); `imageCacheType: ULTRA_QUALITY` = the
highest-quality (slowest) scaler. Artwork files themselves land on the NFS media share;
**only the cache lands on this PVC.**

**UNKNOWN:** I will not fabricate a GB projection. The bounded statement: on first
artwork scrape the cache goes from ~0 to one 1000-px derivative per displayed image
across ~1,952 movies + 143 shows + seasons (roughly 4,200+ images), against 1.64 GB free
on a volume SQ-53 already protected by disabling `buildImageCacheOnImport`. Add the
observed log growth (`trace-*.log` was **30.7 MB** and growing).
**Recommendation:** before SQ-54's artwork run, either drop to `imageCacheSize: SMALL` +
`imageCacheType: QUALITY`, or grow the PVC — and re-read
`kubelet_volume_stats_used_bytes` during the run. `ULTRA_QUALITY` also costs CPU on a
constrained node for no on-disk benefit. **Operator decision.**

### 1-I. LOW (latent) — `cleanupFileType` would delete files from media folders

`[".html$", ".sfv$", ".txt$", ".url$"]`. Inert today: `renamerCleanupUnwanted: false`
in both renamer profiles and the renamer is off. If cleanup were ever enabled these are
**deletions inside media folders**. Record as a latent hazard tied to the renamer lock.

### 1-J. Verdicts explicitly requested by the ticket

| # | item | verdict |
|---|---|---|
| 1 | `httpApiKey` residue | **RESOLVED** — now `""`. Correct: a credential for a disabled service is pure residue. Endorsed. |
| 2 | port 7878 vs Radarr | **RESOLVED** — now 7880. *Correction to the framing:* there was **never a live conflict.* TMM has `hostNetwork` unset and no container port declared; Radarr is a separate pod reached via `svc/radarr` 192.168.10.210:7878. The two ports live in different network namespaces. The change is still right — it removes a documentation/ops trap and any future `hostNetwork`/NodePort exposure. 7880 collides with nothing (`upnpPort` is 7879; `svc/radarr-metrics` is also 7879 but likewise namespaced). |
| 3 | `enableAutomaticUpdate` / interval 1 | **RESOLVED for the flag** — now `false`. **Evidence it was live:** `tmm.prop` carried `lastUpdateCheck=1786078830938` (2026-08-07), so the check was really running. Correct call — a self-updating container defeats the Flux-pinned image. **Residual:** `automaticUpdateInterval` is still `1`; inert while the flag is false, but set it to 0 or document it. **Also:** the JSON flag is not the strongest control — the Docker-supported control is JVM opt **`-Dtmm.noupdate=true`** in `launcher-extra.yml`, which survives a config rewrite. Recommend adding it. |
| 4 | `ignoreSSLProblems` | **RESOLVED** — now `false`. Correct and it was a real exposure: it disabled certificate verification for **the metadata fetches identity is derived from**. `proxyHost` is null, so no proxy justified it. Endorsed. |
| 5 | the four identical secrets | **Encrypted empty values, not a shared secret.** `traktAccessToken`, `traktRefreshToken`, `mdbListApiKey`, `kodiPassword` are byte-identical, 24 base64 chars ending `==` → **16 raw bytes = exactly one AES block**, which is what PKCS-padded *empty* plaintext produces under TMM's fixed key (identical plaintext → identical ciphertext). A real Trakt token is 64 hex chars and could not fit in one block (~108 base64 chars). Corroborated in-config: `syncTrakt: false`, `kodiHost: ""`, `kodiUsername: ""`, Kodi ports at defaults. **No action; no secret is present.** Values are not reproduced here. |
| 6 | `writeMediaInfoXml` / cache sizing | `writeMediaInfoXml: false` — **KEEP false.** It writes `<file>-mediainfo.xml` **into the media tree**, a new producer of sidecar files in 2,113 folders, and this estate already had 257 phantom Emby "movies" promoted from sidecars. The rescan-speed benefit does not justify re-arming that class. Cache sizing → §1-H. |

### Change list

**Safe now (low risk, no behaviour surprise)**
1. Trim scrape configs to the artwork types that actually have filenames (§1-D).
2. Deduplicate `tvShowScraperMetadataConfig` `TAGLINE` (§1-E).
3. Deduplicate `universalFilterFields` in both files (§1-F).
4. `subtitleScrapers: []` in both files (§1-G).
5. `automaticUpdateInterval: 0`, and add `-Dtmm.noupdate=true` to `launcher-extra.yml` (§1-J #3).
6. Add a *Subtitles → Bazarr* row to `docs/media/tmm-configuration.md` (§1-G).

**Needs operator decision**
1. `movies.useMediainfoMetadata` → `false` (§1-A) — **decide before the next restart.**
2. `updateOnStart` → `false` both (§1-B).
3. `scraperThreshold` 0.75 → 0.85–0.90 (§1-C).
4. `imageCacheSize`/`imageCacheType`, or grow the 2 GiB PVC (§1-H).
5. `seasonArtworkFallback` false → true (§4).
6. `movies.fetchAllRatings` true vs `tv.fetchAllRatings` false — resolve the asymmetry (§3/§4).

**Blocked / do not act**
- No TV scrape until SQ-58's identity work completes. TV is the library where a wrong
  match **does** reach disk (`nfoFilenames: ["TV_SHOW"]`, `episodeNfoFilenames: ["FILENAME"]`).
  Noted per the ticket, not acted on.

---

## §2 — `tmm.json` (75 keys) — General / System / Advanced

Legend: **K** keep · **C** change recommended · **D** operator decision · **?** UNKNOWN.
"Inert" = the value has no effect in the current configuration.

### 2.1 Automatic Ratio Detection (Advanced → ARD) — 17 keys, feature OFF

`ardEnabled: false` gates all of it. ARD decodes sample frames to detect true aspect
ratio: enabling it over 24,822 movie files would be a very large CPU + NFS read cost on
a constrained node. **All 17: KEEP as-is; keep `ardEnabled: false`.**

| key | current | note |
|---|---|---|
| `ardEnabled` | `false` | **K — master gate. Do not enable.** High CPU/IO |
| `ardMode` | `DEFAULT` | K inert (selects the sample profile below) |
| `ardSampleSettings` | `{FAST:{1,1800,4}, DEFAULT:{2,900,6}, ACCURATE:{2,900,30}}` | K inert — duration/maxGap/minNumber per profile |
| `ardDarkLevelPct` / `ardDarkLevelMaxPct` | `7` / `13` | K inert — letterbox black thresholds |
| `ardIgnoreBeginningPct` / `ardIgnoreEndPct` | `2` / `8` | K inert — skip credits regions |
| `ardMFMode` / `ardMFThresholdPct` | `0` / `6` | K inert — multi-format handling |
| `ardPlausiWidthPct` / `ardPlausiWidthDeltaPct` | `50` / `1.5` | K inert — plausibility bounds |
| `ardPlausiHeightPct` / `ardPlausiHeightDeltaPct` | `60` / `2` | K inert |
| `ardRoundUp` / `ardRoundUpThresholdPct` | `false` / `4` | K inert |
| `ardSecondaryDelta` | `0.15` | K inert |
| `customAspectRatios` | 14 ratios `1.33…2.76` | K — stock list, manual selection only |

### 2.2 File types (Settings → File types) — 4 keys

| key | current | verdict |
|---|---|---|
| `videoFileType` | 50 ext | **K** — stock. Includes `.iso .img .bin .ifo .bdmv .disc .vob .strm`, which is why disc-image folders import; relevant to the 1,952-vs-1,889 delta SQ-54 adjudicates |
| `audioFileType` | 35 ext | K — stock |
| `subtitleFileType` | 21 ext | K — stock; includes `.srt .ass .sub .sup .vtt`, so Bazarr's output is recognised |
| `allSupportedFileTypes` | 114 ext | K — union of the three plus image/`.nfo` types. Verified consistent: no image or `.nfo` extension leaks into `videoFileType` |

### 2.3 Update / version — 4 keys

| key | current | verdict |
|---|---|---|
| `enableAutomaticUpdate` | `false` | **K — endorsed** (§1-J #3) |
| `automaticUpdateInterval` | `1` | **C** → `0`; inert but misleading |
| `version` | `"5.3.0"` | K — informational |
| `currentVersion` | `true` | K — "running the newest known build" flag; informational |

### 2.4 HTTP API / UPnP / remote — 6 keys

| key | current | verdict |
|---|---|---|
| `enableHttpServer` | `false` | **K false — hard constraint.** SQ-53 records it as self-reverting; do not rely on it staying true |
| `httpApiKey` | `""` | **K — endorsed** (§1-J #1) |
| `httpServerPort` | `7880` | **K — endorsed** (§1-J #2) |
| `upnpShareLibrary` | `false` | K — no UPnP listener |
| `upnpRemotePlay` | `false` | K |
| `upnpPort` | `7879` | K inert; pod-namespaced, no conflict |

### 2.5 Network / security — 6 keys

| key | current | verdict |
|---|---|---|
| `ignoreSSLProblems` | `false` | **K — endorsed** (§1-J #4) |
| `proxyHost` / `proxyPort` / `proxyUsername` / `proxyPassword` | all `null` | K — direct egress; nothing justified the SSL bypass |
| `maximumDownloadThreads` | `2` | **K** — conservative, correct for NFS + a constrained node. Do not raise for the SQ-54 artwork run |

### 2.6 External services — 8 keys

| key | current | verdict |
|---|---|---|
| `traktAccessToken` / `traktRefreshToken` | encrypted-empty | K — not configured (§1-J #5) |
| `traktDateField` | `DATE_ADDED` | K inert (`syncTrakt: false` in both libraries) |
| `mdbListApiKey` | encrypted-empty | K — not configured |
| `kodiHost` / `kodiUsername` / `kodiPassword` | `""` / `""` / encrypted-empty | K — Kodi push not configured; TMM docs mark it experimental |
| `kodiHttpPort` / `kodiTcpPort` | `8080` / `9090` | K inert (2 keys) |
| `wolDevices` | `[]` | K — Wake-on-LAN unused |

### 2.7 Media framework / trailers — 6 keys

| key | current | verdict |
|---|---|---|
| `useInternalMediaFramework` | `true` | K — bundled ffmpeg; avoids a host dependency |
| `mediaFramework` | `""` | K inert (external ffmpeg path) |
| `ffmpegPercentage` | `50` | K inert — frame position for extracted thumbs; no thumbs are written |
| `useInternalYtDlp` | `true` | K |
| `externalYtDlpPath` | `""` | K inert |
| `ytDlpParams` | `""` | K inert — arbitrary CLI args; keep empty (injection surface) |
| `mediaPlayer` | `""` | K — no external player; headless container |

### 2.8 Image cache — 4 keys

| key | current | verdict |
|---|---|---|
| `imageCache` | `true` | K — needed for a usable UI over NFS artwork |
| `imageCacheSize` | `BIG` (1000 px) | **D** → `SMALL` (400 px) (§1-H) |
| `imageCacheType` | `ULTRA_QUALITY` | **D** → `QUALITY` (§1-H) — also CPU |
| `imageChooserUseEntityFolder` | `false` | K — UI file-chooser start dir |

### 2.9 Trash / files — 4 keys

| key | current | verdict |
|---|---|---|
| `enableTrash` | `true` | **K — safety.** Deletions go to `.deletedByTMM` instead of vanishing |
| `deleteTrashOnExit` | `false` | **K** — keeps the undo window across restarts |
| `writeMediaInfoXml` | `false` | **K false** (§1-J #6) |
| `cleanupFileType` | `.html$ .sfv$ .txt$ .url$` | K inert — **latent deletion hazard** (§1-I) |

### 2.10 UI / locale / display — 16 keys, all cosmetic, all KEEP

`language` `en` · `theme` `Light` · `fontFamily` `Dialog` · `fontSize` `12` ·
`dateFormatStyle` `NATIVE` · `timeFormatStyle` `NATIVE` · `dateField` `DATE_ADDED` ·
`fileSizeBase10` `true` · `fileSizeDisplayHumanReadable` `true` · `showMemory` `true` ·
`storeWindowPreferences` `true` · `titlePrefix` (21 articles — used only for sortable
titles, which are off) · `configFilename` `tmm.json` (internal).
No on-disk or identity effect. *(Window geometry and table columns live in `tmm.prop`,
not in the 318.)*

---

## §3 — `movies.json` (124 keys)

### 3.1 Data source & folder handling — 5

| key | current | verdict |
|---|---|---|
| `movieDataSource` | `["/movies"]` | **K** — `/media` deliberately excluded (would double-index) |
| `skipFolder` | `["MAKEMKV"]` | K |
| `skipFoldersWithNomedia` | `true` | K — honours `.nomedia` |
| `badWord` | `[]` | K — no title-based exclusions |
| `configFilename` | `movies.json` | K internal |

### 3.2 Scraper — identity — 8

| key | current | verdict |
|---|---|---|
| `movieScraper` | `tmdb` | **K** (§0) |
| `scraperFallback` | `false` | **K** (§0) |
| `scraperThreshold` | `0.75` | **D — raise** (§1-C) |
| `scraperLanguage` | `en` | K |
| `certificationCountry` | `US` | K |
| `certificationStyle` | `LARGE` | K — display form of the rating |
| `releaseDateCountry` | `"US"` | **K — endorsed.** Was `""`; pins which country's release date is used. Benign, and consistent with `certificationCountry` |
| `doNotOverwriteExistingData` | `false` | **K** (§0) |

### 3.3 Scrape defaults — 3

| key | current | verdict |
|---|---|---|
| `scraperMetadataConfig` | 29 entries | **C — trim 6 unwritable artwork types** (§1-D) |
| `movieCheckMetadata` | `ID TITLE YEAR PLOT RATING RUNTIME CERTIFICATION GENRES ACTORS` | K — drives the completeness badge; this is SQ-54's validation lever |
| `movieCheckArtwork` | `POSTER FANART` | K — matches the two types actually written |

### 3.4 Ratings — 4

| key | current | verdict |
|---|---|---|
| `ratingSources` | `["imdb"]` | K — deduplicated by SQ-53 |
| `fetchAllRatings` | `true` | **D** — asymmetric with TV's `false` (§4) |
| `fetchRatingSources` | `["IMDB"]` | K |
| `useTrailerPreference` | `true` | K inert (no automatic trailer download) |

### 3.5 NFO — 12. **`nfoFilenames: []` makes this whole block inert on disk**

Radarr's `movie.xml` is authoritative; TMM writes no movie NFO. These values matter only
if the SQ-53 revisit trigger ever fires (Radarr's Emby-Legacy consumer turned off).

| key | current | verdict |
|---|---|---|
| `nfoFilenames` | `[]` | **K `[]` — the load-bearing constraint** (§0) |
| `movieConnector` | `KODI` | K inert — NFO dialect |
| `nfoWriteArtworkUrls` | `false` | **K — endorsed.** Local artwork is authoritative |
| `writeCleanNfo` | `true` | K |
| `nfoLanguage` | `en` | K inert |
| `nfoWriteDateAdded` | `true` | K inert |
| `nfoDateAddedField` | `DATE_ADDED` | K inert |
| `nfoWriteFileinfo` | `true` | K inert — streamdetails |
| `nfoWriteLockdata` | `false` | **K false** — `<lockdata>true</lockdata>` blocks Emby refresh; Emby must stay free to read `movie.xml` |
| `nfoWriteSingleStudio` | `false` | K inert |
| `nfoWriteTrailer` | `true` | K inert |
| `nfoDiscFolderInside` | `true` | K inert — NFO placement for BDMV/VIDEO_TS |

### 3.6 Outline / titles — 9. `createOutline`/`outlineFirstSentence` inert (no NFO)

| key | current | verdict |
|---|---|---|
| `createOutline` | `true` | K inert |
| `outlineFirstSentence` | `false` | K inert |
| `capitalWordsInTitles` | `false` | K — documented master toggle ("capitalize first letter of every word"), **off** |
| `title` `true` · `originalTitle` `true` · `englishTitle` `true` · `sortTitle` `false` · `sortableTitle` `false` · `sortableOriginalTitle` `false` | | **? UNKNOWN (6 keys).** The v5.3 docs describe only the single master checkbox and do not document these per-field booleans. Assessed impact: cosmetic — no movie NFO is written, and the master toggle is off. **Reported as UNKNOWN rather than guessed.** |

### 3.7 Artwork — 22

| key | current | verdict |
|---|---|---|
| `artworkScrapers` | `["tmdb","fanarttv"]` | K |
| `posterFilenames` | `["POSTER"]` → `poster.jpg` | K — folder-level, per SQ-53 (Plex needs it; Emby reads both). Multi-video folders auto-switch to `<file>-poster.jpg` |
| `fanartFilenames` | `["FANART"]` → `fanart.jpg` | K |
| `bannerFilenames` `clearartFilenames` `clearlogoFilenames` `discartFilenames` `keyartFilenames` `thumbFilenames` `extraFanartFilenames` | all `[]` | **K `[]` (7 keys)** — no on-disk consumer; writing them = clutter in 2,470 folders |
| `imagePosterSize` / `imageFanartSize` | `LARGE` / `LARGE` | K |
| `imageScraperLanguages` | `["en"]` | K |
| `defaultImageScraperLanguage` | `en` | K |
| `imageScraperOtherResolutions` | `true` | K — try other resolutions if the preferred one is missing |
| `imageScraperFallback` | `true` | **K — and note the naming trap.** This is *"Fallback: try to get any image"*, an **artwork** fallback. It is **not** `scraperFallback` and carries **no** identity risk. The two must not be conflated |
| `imageScraperPreferFanartWoText` | `true` | K — text-free fanart |
| `scrapeBestImage` | `true` | K — auto-pick in unattended scrape |
| `imageExtraFanart` / `imageExtraThumbs` | `false` / `false` | **K false (2)** — these create `extrafanart`/`extrathumbs` **subfolders**; re-arms the phantom-movie class |
| `imageExtraFanartCount` `imageExtraThumbsCount` `imageExtraThumbsResize` `imageExtraThumbsSize` | `5` `5` `true` `300` | K inert (4) |
| `showArtworkTypes` | `["POSTER","FANART","THUMB"]` | K — details-view display only, no disk effect |
| `extractArtworkFromVsmeta` | `false` | K — Synology vsmeta; N/A |

### 3.8 Renamer — 2 keys (+ profile). **Locked off**

| key | current | verdict |
|---|---|---|
| `renameAfterScrape` | `false` | **K — hard constraint** |
| `renamerProfiles.Default` | `renamerPathnameEnabled: false`, `renamerFilenameEnabled: false`, `renamerCleanupUnwanted: false`, `renamerNfoCleanup: false`, `allowMultipleMoviesInSameDir: false`, `renamerCreateMoviesetForSingleMovie: false` | **K — verified all-disabled.** Pathname now `${title} (${year}) {tmdb-${tmdbid}}` — **endorsed**: the old pattern would have *stripped* the id tag on an accidental run. Filename pattern `${title}${ - ,edition,} (${year}) ${videoFormat} ${audioCodec}` carries no id, which is correct — the id convention is folder-level per `id-tag-format-decision.md`, and `${ - ,edition,}` preserves the 62 alternate cuts |

### 3.9 Movie sets — 20 keys, entirely inert (`movieSetDataFolder: ""`, no consumer)

`movieSetNfoFilenames` `[]` · `movieSetConnector` `EMBY` · `movieSetDataFolder` `""` ·
`movieSetPosterFilenames` `movieSetFanartFilenames` `movieSetBannerFilenames`
`movieSetClearartFilenames` `movieSetClearlogoFilenames` `movieSetDiscartFilenames`
`movieSetThumbFilenames` all `[]` · `movieSetCheckMetadata` `[ID,TITLE,PLOT]` ·
`movieSetCheckArtwork` `[POSTER,FANART]` · `movieSetDisplayAllMissingMetadata` `false` ·
`movieSetDisplayAllMissingArtwork` `false` · `movieSetAppendTmdbId` `false` ·
`movieSetTitleCharacterReplacement` `"_"` · `movieSetPostProcess` `[]` ·
`scrapeBestImageMovieSet` `true` · `movieSetUiFilters` `[]` · `movieSetUiFilterPresets` `{}` ·
`displayMovieSetMissingMovies` `false` · `storeMovieSetUiFilters` `false`.
**All KEEP.** `COLLECTION` remains in `scraperMetadataConfig`, so set *membership* is
recorded in TMM's DB — nothing is written to disk.

### 3.10 Trailers — 6

| key | current | verdict |
|---|---|---|
| `automaticTrailerDownload` | `false` | **K — the gate.** No writes into the media tree |
| `trailerFilenames` | `["FILENAME_TRAILER"]` | K inert |
| `trailerScrapers` | `["tmdb","hd-trailers"]` | K inert |
| `trailerSource` | `YOUTUBE` | K inert |
| `trailerQuality` | `HD_720` | K inert |
| `useYtDlp` | `true` | K inert |
| `trailerDiscFolderInside` | `true` | K inert |

### 3.11 Subtitles — 5

| key | current | verdict |
|---|---|---|
| `subtitleScrapers` | `["opensubtitles2","opensubtitles","yify","subdl"]` | **C → `[]`** (§1-G) — Bazarr owns subtitles |
| `subtitleScraperLanguage` | `en` | K |
| `subtitleLanguageStyle` | `ISO3T` (`.eng.srt`) | K — but note the naming mismatch with Bazarr's 2-letter tags (§1-G) |
| `subtitleForceBestMatch` | `false` | K |
| `subtitleWithoutLanguageTag` | `false` | K |

### 3.12 MediaInfo / runtime — 3

| key | current | verdict |
|---|---|---|
| `runtimeFromMediaInfo` | `true` | **K — endorsed.** Real runtime beats the scraper's claim, and it helps SQ-54 spot wrong-film matches |
| `useMediainfoMetadata` | `true` | **C → `false` — HIGH** (§1-A) |
| `includeExternalAudioStreams` | `false` | K — external audio in streamdetails; inert (no movie NFO) |

### 3.13 Automatic tasks / UI state — 11

| key | current | verdict |
|---|---|---|
| `updateOnStart` | `true` | **D → `false`** (§1-B) |
| `buildImageCacheOnImport` | `false` | **K — 2 GiB PVC protection** |
| `resetNewFlagOnUds` | `true` | K — "new" flag cleared by update-data-sources |
| `postProcess` | `[]` | **K `[]` — arbitrary command execution surface; keep empty** |
| `writeActorImages` | `false` | **K** — would create `.actors/` folders with thousands of images |
| `movieDisplayAllMissingMetadata` / `movieDisplayAllMissingArtwork` | `false` / `false` | K — tooltip verbosity |
| `showMovieTableTooltips` / `showMovieSetTableTooltips` | `true` / `true` | K cosmetic |
| `storeUiFilters` | `false` | K |
| `uiFilters` | `[]` | K |
| `movieUiFilterPresets` | `{}` | K |
| `universalFilterFields` | 12 fields **listed twice** | **C — deduplicate** (§1-F) |
| `version` | `5201` | K — config schema version, not the app version |

---

## §4 — `tvShows.json` (119 keys)

**Gate:** TV is the library where a wrong match reaches disk. No TV scrape until SQ-58
completes. Recorded, not acted on.

### 4.1 Data source & identity — 8

| key | current | verdict |
|---|---|---|
| `tvShowDataSource` | `["/tv"]` | K |
| `scraper` | `tvdb` | **K** (§0) — matches Sonarr's keying |
| `scraperLanguage` | `en` | K |
| `certificationCountry` / `certificationStyle` | `US` / `LARGE` | K (2) |
| `releaseDateCountry` | `""` | **? minor asymmetry** — movies was set to `"US"`, TV was not. Low impact (TV uses `AIRED`); align for consistency |
| `doNotOverwriteExistingData` | `false` | K |
| `skipFolder` / `skipFoldersWithNomedia` | `["MAKEMKV"]` / `true` | K (2) |
| `badWord` | `[]` | K |
| `configFilename` | `tvShows.json` | K |

*No `scraperThreshold` exists for TV — identity comes from the `{tvdb-N}` folder tag
(measured: 143/144).*

### 4.2 Scrape defaults — 6

| key | current | verdict |
|---|---|---|
| `tvShowScraperMetadataConfig` | 35 entries | **C — trim 9 unwritable artwork types AND deduplicate `TAGLINE`** (§1-D, §1-E) |
| `episodeScraperMetadataConfig` | `TITLE ORIGINAL_TITLE ENGLISH_TITLE PLOT SEASON_EPISODE AIRED RATING TAGS RUNTIME ACTORS CREW THUMB` | **C — drop `THUMB`** (`episodeThumbFilenames: []`, ~8,137 pointless lookups) |
| `tvShowCheckMetadata` | `ID TITLE PLOT YEAR STATUS GENRES ACTORS` | K — completeness badge |
| `tvShowCheckArtwork` | `POSTER FANART` | K — matches what is written |
| `episodeCheckMetadata` | `SEASON_EPISODE TITLE ACTORS` | K |
| `episodeCheckArtwork` | `[]` | K — no episode artwork written |
| `seasonCheckArtwork` | `["SEASON_POSTER"]` | K — matches `seasonPosterFilenames` |
| `episodeSpecialsCheckMissingArtwork` / `episodeSpecialsCheckMissingMetadata` | `false` / `false` | K (2) — specials excluded from completeness |

### 4.3 NFO — 15. **This block is live: TMM is the sole TV NFO producer**

| key | current | verdict |
|---|---|---|
| `nfoFilenames` | `["TV_SHOW"]` → `tvshow.nfo` | **K** |
| `episodeNfoFilenames` | `["FILENAME"]` → `<episode>.nfo` | **K** |
| `seasonNfoFilenames` | `[]` | K — no consumer |
| `tvShowConnector` | `KODI` | K — Emby reads Kodi-format `tvshow.nfo` |
| `writeCleanNfo` | `true` | **K** — drops junk tags from the untrusted residue (65/144 shows carry a `tvshow.nfo` today, ~25 with a **TMDB** uniqueid in a TVDB tree) |
| `nfoWriteArtworkUrls` | `false` | **K — endorsed** |
| `nfoWriteEpisodeguide` | `true` | K — Kodi/Emby episode ordering |
| `nfoWriteNewEpisodeguideStyle` | `true` | K — v5 style; correct for a current Emby |
| `nfoWriteAllActors` | `false` | **K** — avoids repeating the full cast into 8,137 episode NFOs |
| `nfoWriteDateEnded` | `false` | K — `<enddate>` for ENDED shows; optional |
| `nfoWriteFileinfo` | `true` | K — streamdetails; pairs with `runtimeFromMediaInfo: true` |
| `nfoWriteLockdata` | `false` | **K false** — do not block Emby refresh |
| `nfoWriteDateAdded` / `nfoDateAddedField` | `true` / `DATE_ADDED` | K (2) |
| `nfoWriteSingleStudio` | `false` | K |
| `nfoWriteTrailer` | `true` | K — URL only, no download |
| `nfoLanguage` | `en` | K |

### 4.4 Outline / titles — 7

`createOutline` `false` · `outlineFirstSentence` `false` · `capitalWordsInTitles` `false`
— **K (3)**, and note TV writes no `<outline>` while movies would; harmless.
`title` `false` · `originalTitle` `true` · `englishTitle` `true` · `node` `false` —
**? UNKNOWN (4 keys)**, same undocumented group as §3.6 (`node` additionally appears as a
tree-column name in `tmm.prop`, suggesting UI scope). Master toggle is off; assessed
cosmetic. **Reported as UNKNOWN rather than guessed.**

### 4.5 Artwork — 24

| key | current | verdict |
|---|---|---|
| `artworkScrapers` | `["tmdb","tvdb","fanarttv"]` | K — TVDB is authoritative for season art |
| `posterFilenames` / `fanartFilenames` | `["POSTER"]` / `["FANART"]` | K (2) |
| `seasonPosterFilenames` | `["SEASON_POSTER"]` → `seasonXX-poster.jpg` | K |
| `seasonBannerFilenames` `seasonFanartFilenames` `seasonThumbFilenames` `bannerFilenames` `clearartFilenames` `clearlogoFilenames` `discartFilenames` `keyartFilenames` `characterartFilenames` `thumbFilenames` `extraFanartFilenames` `episodeThumbFilenames` | all `[]` | **K `[]` (12 keys)** — no on-disk consumer. `episodeThumbFilenames: []` alone avoids ~8,137 image writes |
| `seasonArtworkFallback` | `false` | **D → `true`** — with it off, a season with no dedicated art gets nothing; falling back to show art is usually better. Operator decision |
| `imagePosterSize` / `imageFanartSize` / `imageThumbSize` | `LARGE` / `LARGE` / `MEDIUM` | K (3); thumb size inert |
| `imageScraperLanguages` / `defaultImageScraperLanguage` | `["en"]` / `en` | K (2) |
| `imageScraperOtherResolutions` / `imageScraperFallback` / `imageScraperPreferFanartWoText` | `true` `true` `true` | K (3) — artwork-only fallbacks, **no identity risk** |
| `imageEpisodeScrapeAllSources` | `false` | K — avoids querying every provider for 8,137 episodes; throughput-relevant |
| `scrapeBestImage` | `true` | K |
| `imageExtraFanart` | `false` | **K** — subfolder creator |
| `imageExtraFanartCount` | `5` | K inert |
| `extractArtworkFromVsmeta` | `false` | K |
| `showTvShowArtworkTypes` `showSeasonArtworkTypes` `showEpisodeArtworkTypes` | `[POSTER,FANART,BANNER]` / `[SEASON_POSTER,SEASON_THUMB,SEASON_BANNER]` / `[THUMB]` | K (3) — details-view display only, no disk effect |

### 4.6 Renamer — 2 (+ profile). **Locked off**

`renameAfterScrape: false` — **K, hard constraint.**
`renamerProfiles.Default`: `renamerTvShowFoldernameEnabled` `false`,
`renamerSeasonFoldernameEnabled` `false`, `renamerFilenameEnabled` `false`,
`renamerCleanupUnwanted` `false` — **K, verified all-disabled.** Show pattern now
`${showTitle} (${showYear}) {tvdb-${tvdbid}}` — **endorsed**, the old pattern would have
stripped the `{tvdb-N}` anchor that 143/144 shows depend on. `specialSeason: true`,
`renamerMultiEpisodeStyle: REPEAT`, `createMissingSeasonItems: false` — K inert.

### 4.7 Trailers — 6

`automaticTrailerDownload` `false` (**K — the gate**) · `trailerFilenames`
`["TVSHOW_TRAILER"]` · `trailerScrapers` `["tmdb","imdb","tvdb"]` · `trailerSource`
`YOUTUBE` · `trailerQuality` `HD_720` · `useYtDlp` `true` · `useTrailerPreference` `true`
— **K, all inert.**

### 4.8 Subtitles — 4

`subtitleScrapers` `["opensubtitles2","opensubtitles","subdl"]` → **C `[]`** (§1-G) ·
`subtitleScraperLanguage` `en` K · `subtitleLanguageStyle` `ISO3T` K ·
`subtitleForceBestMatch` `false` K.

### 4.9 Ratings — 4

| key | current | verdict |
|---|---|---|
| `ratingSources` | `["imdb"]` | K |
| `fetchAllRatings` | `false` | **D** — asymmetric with movies' `true`; TV NFOs will carry only the TVDB rating |
| `fetchRatingSources` | `[]` | **D** — pairs with the above |

### 4.10 MediaInfo — 2

| key | current | verdict |
|---|---|---|
| `runtimeFromMediaInfo` | `true` | K — was already `true` before the change window |
| `useMediainfoMetadata` | `true` | **C → `false`** (§1-A). Lower risk than movies (`{tvdb-N}` anchors identity) but **zero benefit** — the runtime win was already delivered by the key above |

### 4.11 Trakt / automatic tasks / UI — 15

| key | current | verdict |
|---|---|---|
| `syncTrakt` | `false` | K — master gate |
| `syncTraktCollection` / `syncTraktRating` / `syncTraktWatched` | `true` ×3 | K inert (3) |
| `updateOnStart` | `true` | **D → `false`** (§1-B) |
| `buildImageCacheOnImport` | `false` | **K** — PVC protection |
| `resetNewFlagOnUds` | `true` | K |
| `postProcessTvShow` / `postProcessEpisode` | `[]` / `[]` | **K `[]` (2) — command execution surface** |
| `writeActorImages` | `false` | **K** — no `.actors/` folders across 143 shows |
| `displayMissingEpisodes` / `displayMissingNotAired` / `displayMissingSpecials` | `false` ×3 | **K (3)** — Sonarr `/wanted/missing` is the gap tracker |
| `tvShowDisplayAllMissingMetadata` / `tvShowDisplayAllMissingArtwork` / `seasonDisplayAllMissingArtwork` / `episodeDisplayAllMissingMetadata` / `episodeDisplayAllMissingArtwork` | `false` ×5 | K (5) — tooltip verbosity |
| `showTvShowTableTooltips` | `true` | K |
| `storeUiFilters` / `uiFilters` / `uiFilterPresets` | `false` / `[]` / `{}` | K (3) |
| `universalFilterFields` | 12 fields **listed twice** | **C — deduplicate** (§1-F) |
| `version` | `5202` | K — config schema version |

---

## §5 — UNKNOWN register

Reported as UNKNOWN rather than guessed, per the ticket's constraint.

| # | subject | what could not be established | why it is safe to leave unresolved |
|---|---|---|---|
| U1 | `title` `originalTitle` `englishTitle` `sortTitle` `sortableTitle` `sortableOriginalTitle` (movies) + `title` `originalTitle` `englishTitle` `node` (tv) — **10 keys** | v5.3 docs document only the single master checkbox ("capitalize first letter of every word in title and original title"); the per-field booleans are undocumented | master toggle `capitalWordsInTitles` is `false` in both files; no movie NFO is written. Assessed cosmetic |
| U2 | artwork type selected in `scraperMetadataConfig` but with an **empty** `*Filenames` list | whether TMM downloads the image bytes or only records the URL | either way **no file is written**. `nfoWriteArtworkUrls: false` now blocks the NFO path too. The §1-D trim makes it moot at zero risk |
| U3 | `useMediainfoMetadata` interaction with `doNotOverwriteExistingData` | whether UDS-time extraction overwrites already-populated entries, and whether the extracted title feeds the *scraper search term* | drives the §1-A recommendation to revert **pending confirmation** rather than on certainty |
| U4 | image-cache growth in bytes | no measured baseline exists — the cache is empty (90 inodes) and nothing has been scraped | §1-H gives the mechanism and the bound (1.64 GB free, ~4,200+ images) and asks for measurement during the run instead of a fabricated projection |
| U5 | whether `enableAutomaticUpdate: false` alone fully suppresses the in-app updater in this Docker image | the JSON flag vs. the documented `-Dtmm.noupdate=true` JVM opt | recommendation is to add the JVM opt as well — belt and braces |

## §6 — Coverage

| file | keys | audited |
|---|---|---|
| `tmm.json` | 75 | 75 |
| `movies.json` | 124 | 124 |
| `tvShows.json` | 119 | 119 |
| **total** | **318** | **318** |

## §7 — Constraints honoured

- No scrape, no scan, no rename, no NFO write, no artwork write initiated by this ticket.
- Renamer not enabled; verified all 7 `*Enabled` flags plus both `renameAfterScrape` are `false`.
- Movie NFO writing not enabled; `nfoFilenames` remains `[]`.
- HTTP server not enabled; `enableHttpServer` remains `false`.
- The SQ-58 gate on TV scraping is recorded, not acted on.
- No secret value is reproduced in this document.
- The in-progress `update data sources` run observed in `/data/logs/tmm.log` was started
  by a prior ticket, not by this audit.