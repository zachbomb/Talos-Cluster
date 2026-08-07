# Media Alignment - Dimension F: Cross-Service Identity, File Organisation and Interoperability Audit

- **Ticket:** SQ-44 (review-audit, read-only)
- **Audited:** 2026-08-07 05:00-05:30 UTC. Samples timestamped inline where they matter.
- **Posture:** GET-only against every service. Zero media files renamed/moved/deleted/retagged. Zero *arr mutations. Nothing restructured for Emby (4.9.5.0 version-grouping regression stands).
- **Live conditions during sampling:** Bazarr `series_full_scan_subtitles` re-index running (started ~04:5x UTC); TrueNAS scrub running on the backing pool. Both accounted for below.
- **Method:** full-population joins, not samples, unless stated: Radarr 2,472 movie records x Plex 1,914 movie items x Emby 2,210 movie items x 2,111 on-disk folders x 2,689 on-disk NFO/movie.xml files; Sonarr 152 series x Plex 143 shows x Emby 144 series x 145 on-disk show folders x 67 tvshow.nfo. IDs compared **within the same provider namespace only**; IMDB used as the cross-service join key.

---

## 1. Executive summary

1. **Identity agreement is high and the July fixes held.** TV identity is near-perfect (one genuine mismatch). Movies: 1,853/1,893 Radarr-vs-Plex folder joins agree on TMDB id; the "12 splits" defect class (mixed tagged/untagged versions in one folder) is now **zero**.
2. **The largest live identity defect is Emby-side, caused by stale TMM-era NFOs plus extras handling** - 256 extras files surface as first-class Emby movie items, 76 of them confidently misidentified as real films; 57 folders carry a TMM NFO whose TMDB id contradicts Radarr. Plex is immune (ignores NFO); Emby is not. This is the measured Plex/Emby divergence axis.
3. **The IP-drift class is mostly remediated but not extinct:** Bazarr and Overseerr now use cluster DNS names, but **all 33 *arr indexer entries and all 6 download-client entries are bare IPs**, including 192.168.10.10 (out-of-cluster Prowlarr) referenced 33 times while an in-cluster DNS abstraction (`prowlarr-external-service.media.svc`) exists and sits unused.
4. **TMM is currently pointed at nothing** - empty datasource list, empty 12KB databases, never scanned in this deployment. Every `.nfo` on disk is residue from a previous instance. As configured it detects no gaps and writes nothing; its historic writes are the ones poisoning Emby.
5. All 6 replacement searches from 2026-07-30 landed and pass the runtime-mismatch detector. The Plex-orphan list shrank 16 to 10. All 6 WANTED-EDITIONS remain absent (empty placeholder folders exist for several).

Ranking used throughout: (silent-failure risk) x (blast radius).

---

## 2. Identity reconciliation (centrepiece)

### 2.1 Namespace inventory (verified, not assumed)
| Service | Primary namespace | IMDB join-key coverage |
|---|---|---|
| Radarr | TMDB | 2,394/2,472 records have imdbId (78 missing - mostly obscure shorts/docs) |
| Sonarr | TVDB | 136/152 have imdbId (16 missing) |
| TMM NFO (residue) | TMDB uniqueid on movies; **mixed on TV** (about 25 of 67 tvshow.nfo carry a TMDB uniqueid in a TVDB-keyed tree; most also carry IMDB) | high |
| Plex | own agent, ignores NFO | 1,877/1,914 movie items have imdb guid (37 without = heuristically matched or unmatched) |
| Emby | reads NFO | ProviderIds present except where NFO absent/garbage |

### 2.2 Results by mismatch class

**Class 1 - provider mismatch (both valid, will diverge):**
- Movies: none found - folder tags, movie.xml and TMM NFOs all use TMDB(+IMDB), same as Radarr.
- TV: about 25/67 tvshow.nfo carry a **TMDB** uniqueid in the TVDB-keyed Sonarr tree (e.g. The Simpsons, Better Call Saul, Peep Show). Emby will happily key on these. Most also carry IMDB and/or TVDB so real divergence is limited, but several tvshow.nfo contain a bare `id` field that is neither (the value 310881 appears on **four different Bourdain-adjacent shows** - scraper-group garbage).

**Class 2 - value mismatch (same provider, different id = genuine misidentification), highest severity:**
- **Radarr vs Plex (both ids present):** 14 folders. Standouts: `The City (1999)` Radarr tmdb-125501 vs Plex **tmdb-9447 = Babe: Pig in the City**; `The Good German (2006)` matched by Plex as "Good"; `War and Peace (1966)` split by Plex into 4 per-part items with 4 different tmdb ids; plus Benediction, Bluebird, Eden (2014), No Regret, Seoul 1988, Sydney 2000, Ten Nights in a Bar Room, The Creatures, The Silence (1964), The Swindlers, The House 1984.
- **Radarr vs Emby (main-movie items only, extras excluded):** the same titles plus `American Woman` (2018)/(2019) - Emby has the two films' TMDB ids **swapped**, following two swapped TMM NFOs (measured: the NFO in the 2018 folder carries the 2019 film's ids).
- **Radarr vs on-disk TMM NFO:** 57 folders disagree on TMDB, 18 on IMDB (overlapping; a handful are extras-NFOs sitting at folder level, e.g. the War and Peace part-NFOs). These are the fuel for the Emby mismatches - Plex ignores them, Emby believes them.
- **Radarr vs its own movie.xml:** 1,887/1,893 agree; **1 stale**: `The City (1999)` movie.xml says tt0120595 (Babe: Pig in the City) while Radarr now says tt0208288. Both Plex and the stale XML independently point at Babe - the actual file identity needs a human eyeball before "fixing" either direction.
- **TV:** exactly **1**: Destination Flavour Japan - Emby tvdb-273435 vs Sonarr tvdb-261617. Mechanism measured: the `Destination Flavour (2012) {tvdb-261617}` folder contains a tvshow.nfo whose ids (tt3532078 / 273435) belong to the *Japan* series. Wrong NFO in the folder, Emby follows it. Folder-tag vs Sonarr DB mismatches: **0**.

**Class 3 - missing id (heuristic matching guaranteed):**
- Movie folder tags: only **77/2,111** folders carry `{tmdb-N}`; 2,019 are bare `Title (Year)`; 15 other. Radarr's folder-naming format DOES include the tag - it applies only to newly created folders, so the bulk of the library predates it. Consequence measured: 35 Plex items have no tmdb guid and 37 no imdb guid - and every Class-2 Plex mismatch above sits in an **untagged** folder.
- Concrete demonstration: `Get Out` sits in folder `Get Out (2016)` (wrong year - the film is 2017); Plex's item for it carries **no tmdb guid at all**.
- TV: 142/145 folders tagged `{tvdb-N}`; the 3 untagged are truncated names with trailing spaces (`VH1's I Love the `, `Julia Child - Cooking with Master Chefs `, `Top Chef (GR) `) from illegal-character stripping.
- 7 folder-level TMM NFOs contain no usable id at all.

**Class 4 - type disagreement (presents as orphan, actually unownable):**
- `World on a Wire (1973)` - TMDB classes it as a miniseries; still on disk, still unowned (in the current 10-orphan list).
- Same-class candidates from the orphan list: `Omnibus Monsieur Hulot's Work (1976)` (TV omnibus episode), `Kishi Bashi Live on Valentines Day (2013)` (concert film), `JOUR DE FETE DANS LES MONTS NAGA (1964)/(1995)` (ethnographic shorts, dubious TMDB presence), `Monster Mash (1970)`.
- TV: a `Twin Peaks (2017)` folder exists on disk containing **only** Featurettes and Behind-the-Scenes extras - no episodes (the S2017 episodes live under `Twin Peaks (1990) {tvdb-70533}`, which also contains its own nested `Twin Peaks (2017)` extras subfolder). Sonarr does not own it; **Emby lists it as a full series** (ghost, uniqueid tvdb-696307 from the residue NFO); Plex ignores it.

**Class 5 - split identity:**
- **Mixed tagged/untagged version files in one folder: 0 remaining** (down from the July "12 splits"; re-measured with trailers/extras excluded from the version set).
- 7 same-TMDB Plex item pairs remain (Apocalypse Now, The Big Sleep, The Gold Rush, Red River, Fanny and Alexander, Enter the Dragon, Scenes from a Marriage). All are **consistently edition-tagged files** - Plex creates one item per `{edition-}` by design, which is exactly the "independently selectable versions" requirement. **Not a defect. Do not consolidate.**
- Residual structural variance worth recording: editions live in ONE folder for 5 of the 7 (the target structure), but `Scenes from a Marriage` is split across two `{edition-}` folders (Theatrical owned by Radarr, Television unowned), and `The Killing of a Chinese Bookie` has its two actual files (both **untagged**) in an unowned `{tmdb-32040}` folder while Radarr owns the *empty* `{edition-1978 Re-edit}` folder and reports the movie missing.

**Class 6 - merged/crossed identity:**
- `Panda! Go Panda! (1972)` - two folders, tmdb-695839 vs tmdb-21036, same title+year: two adjacent works correctly separated in Plex, but a standing trap for anything matching on title+year. It is the only same-title+year different-tmdb pair in the entire Plex movie library.
- **Emby extras cross-merge (the big one):** 256 of Emby's 2,210 movie items are extras files (Featurettes/Trailers/interviews); **76 of them got matched to real provider ids**, e.g. "Deleted Scenes" = tmdb-120044 in three different movie folders, "Hui's Comedy: A Look Back" merged into items under **seven** unrelated folders, "Interviews with the Makers of Monsters" under four. Emby is scraping extras subfolders as movies; Plex correctly hides all of them.

### 2.3 Count consistency across services (movies)
2,111 disk folders (1,930 with a main video) / Radarr 2,472 records, 1,891 with file / Plex 1,914 items (includes the 7 edition-pair items, 10 orphan-folder items, 38 multi-version items) / Emby 2,210 items (about 1,900 real + 256 extras + ghosts). Emby also retains at least one deleted-content ghost (Twin Peaks 2017, TV side). Radarr-with-file but invisible-in-Plex: **0**.

---

## 3. File organisation

### 3.1 Movies (`/media/media/movies`, walked 05:03 UTC, 2,111 folders)
| Metric | Value |
|---|---|
| Folder name `Title (Year) {tmdb-N}` | 77 (3.6%) |
| `Title (Year)` no tag | 2,019 (95.6%) |
| Square-bracket `[tmdbid-N]` | **0** - no curly/square inconsistency exists; the library is uniformly curly-or-nothing. Tag FORMAT is a non-issue (Plex reads curly; Emby matches via NFO anyway); tag ABSENCE is the issue (Class 3). |
| Other names | 15 (9 are `{edition-}`-suffixed folders, plus: Pioneers of African American Cinema, "You Sing Loud, I Sing Louder ()", "Calgary '88- 16 Days of Glory", Zatoichi Supplements, .deletedByTMM) |
| Multi-version folders (extras excluded) | 43 |
| Mixed tagged/untagged versions | **0** |
| Folders with no main video | 181 total: 173 are Radarr-monitored-missing (122 fully empty, the rest artwork/extras awaiting the file), **8 unowned**: 6 empty `{edition-}` placeholders, `Secrets and Lies (1996)` (leftover after re-import into `Secrets and Lies (1996) {tmdb-11159}`), `.deletedByTMM` |
| Near-duplicate folder groups (normalised title+year) | 11 - incl. `WALL-E (2008)` (leftover, extras-only) vs the live folder with the unicode middle-dot, Curious George 2 with/without dash, the Secrets and Lies pair, plus the edition-folder families |
| Extras subdirs | 1,663 canonical (Featurettes/Trailers/...); other subdirs dominated by `.@__thumb` (869) and `extrathumbs` (698) QNAP/TMM junk; 11 `Versions/` dirs; nested movie-named dirs inside other movies' folders (The Gold Rush (1942), Where Is Kyra (2018), Ad Astra (2019), Ready Player One (2018), Adaptation (2002), Infamous (2006)) |
| Root-level strays | `.DS_Store` only |

### 3.2 TV (`/media/media/tv`, walked 05:04 UTC, 145 show folders)
| Metric | Value |
|---|---|
| `Show (Year) {tvdb-N}` | 142/145 (`Twin Peaks (2017)` extras-ghost, `.deletedByTMM`, 1 tag-truncated) |
| Season dirs zero-padded `Season XX` | 565. **Unpadded `Season N`: 257.** `Specials`: 9. `Season 00`: 0. Sonarr is configured `Season {season:00}` + `Specials`, so unpadded dirs are legacy. |
| Duplicate season dirs from padding drift | `Twin Peaks (1990)` has BOTH `Season 1` + `Season 01` AND `Season 2` + `Season 02`, with files split across them - the concrete harm of the padding split |
| Episode files | 8,192 videos; 6,194 match the Sonarr naming scheme; **about 1,998 scene-named** (dotted, no ` - SxxExx - ` pattern). `renameEpisodes: true` is set, so these are legacy imports Sonarr has never been asked to rename |
| Loose videos directly in show folders | 12 |
| Unowned folders | 2 (`.deletedByTMM`, `Twin Peaks (2017)`) |
| Sonarr series with no disk folder | 9 - all 0-file, list-added, never downloaded (correct) |

### 3.3 Share-root strays (`/media` level, outside both roots)
`CLAUDE.md`, `migrate_lossless.log`, `migrate_lossless_to_flac.sh`, **empty `tvshows/` dir**, `filler/` (Tunarr), `torrents/` and `usenet/` (download staging), `app_backups/`. None harmful; the empty `tvshows/` and the migrate script/log are finished-business leftovers.

### 3.4 `/media/media/rollout` - NOT FOUND
Checked from radarr, sonarr and plex pods at 05:12 UTC: no `rollout` at `/media/media/` or `/media/`. The share root maps to NFS `192.168.10.123:/mnt/Pibbs-Horde/media/data`. Either it was removed between the 2026-08-07 04:5x confirmation and this walk, or it lives on a TrueNAS path outside the `data` export and was observed via a different mount. **Flagged as unmeasurable from the cluster's mounts - not estimated.** Nothing references it (rootfolder APIs re-confirmed: Radarr owns `/media/media/movies` only, Sonarr `/media/media/tv` only).

---

## 4. Service interoperability

### 4.1 IP-drift class re-verification (every cross-service reference, sampled 05:10-05:15 UTC)
| Consumer / target | Configured value | Current truth | Verdict |
|---|---|---|---|
| Bazarr to Sonarr | `ip: sonarr`, port 8989 | sonarr.media.svc | **DNS, immune** |
| Bazarr to Radarr | `ip: radarr`, port 7878 | radarr.media.svc | **DNS, immune** |
| Overseerr to Sonarr/Radarr | hostname `sonarr` / `radarr` | correct; its activeDirectory values match the *arr root folders exactly | **DNS, immune** |
| Sonarr+Radarr to Deluge | **bare IP** 192.168.10.223:8112 | .223 correct today | latent drift instance |
| Sonarr+Radarr to NZBGet | **bare IP** 192.168.10.208:10057 | .208:10057 correct | latent |
| Sonarr+Radarr to SABnzbd | **bare IP** 192.168.10.207:10097 | .207:10097 correct | latent |
| Sonarr (16) + Radarr (17) indexers | **bare IP** `http://192.168.10.10:9696/{n}/`, 33 entries | Prowlarr, external host, answers 200 on /ping | **latent x33** - and `prowlarr-external-service.media.svc` (ClusterIP endpoint 192.168.10.10, defined in GitOps at `apps/media/prowlarr/app/helm-release.yaml`) already exists as the abstraction and is **unused** |
| Plex libraries | `/media/media/movies`, `/media/media/tv` | same as *arr roots | ok |
| Emby libraries | `/movies`, `/tv` mapped to NFS `/mnt/Pibbs-Horde/media/data/media/movies` and `.../tv` | same physical dirs | ok |
| Sonarr to Notifiarr webhook | external https | n/a | ok |

Note: the bare-IP entries are all CORRECT today, which is exactly what the 8-month Bazarr outage looked like on day one. Prowlarr is the worst case: one renumbering of the external host breaks 33 indexer entries across two apps while both UIs keep passing health checks, and the in-cluster DNS fix already exists. Because Prowlarr pushes these URLs on app-sync, the durable fix must be made on the Prowlarr side or sync will reinstate the IP.

### 4.2 Download-client wiring detail
- Field names verified: Radarr `movieCategory: "movies"`, Sonarr `tvCategory: "tv"` - set on the Deluge, NZBGet and SABnzbd entries. All enabled.
- **Deluge Label persistence trap: currently safe** - `core.conf` has `enabled_plugins: ["Label"]` persisted on the PVC and `label.conf` contains both `tv` and `movies`. A pod restart will not drop it as things stand.
- Not verified server-side: SABnzbd/NZBGet category tables (needs their API keys; out of scoped effort). Client-side config is consistent.

### 4.3 Metadata writers as an interop axis (verified live 05:08 UTC)
| Writer | State | Coverage on disk |
|---|---|---|
| Radarr Emby(Legacy) movie.xml | **enabled** (the only writer on) | 1,893/2,111 folders (89.7%); 1,887 agree with Radarr's IMDB, 1 stale, 2 lack IMDB |
| Radarr Kodi-NFO | off | - |
| Sonarr (all writers) | **all off** - writes nothing | 0 |
| TMM | **detached**: movieDataSource [], tvShowDataSource [], movies.db and tvshows.db 12,288 bytes each (empty), never scanned in this deployment; connector would be KODI / filename.nfo if attached | residue: 768 movie-folder .nfo (36%), 65/145 tvshow.nfo, 857 episode-level .nfo (about 10%) |
| Plex | ignores NFO (`tv.plex.agents.movie` / `.series` confirmed on both sections) | - |
| Emby | reads NFO | consumes all of the above, including the 57/18 conflicting NFOs and the extras NFOs |

The chain, measured end to end: **TMM (historic) wrote NFOs; some are wrong/swapped/stale; Emby believes NFO; Emby diverges from Radarr/Sonarr/Plex** (section 2.2). Radarr's movie.xml is near-perfectly synced and is NOT the divergence source (1 stale file). Sonarr writing nothing costs nothing today: Plex ignores NFO, and Emby's only TV error was caused by a *wrong* NFO, not a missing one.

### 4.4 Config that is NOT in GitOps (lost on PVC loss; silent-regression list)
| Config | Where it lives | What silently breaks on restore-from-old/loss |
|---|---|---|
| Bazarr everything (ignore_ass_subs, upstream DNS names, path mappings) | `/config/config/config.yaml` on PVC | subtitle pipeline reverts (guard off, or back to dead IPs) |
| Sonarr/Radarr API keys, indexer/client tables | `/config/config.xml` + SQLite on PVC | every consumer with an embedded key |
| Deluge enabled_plugins / labels | `/config/core.conf`, `label.conf` on PVC | Label plugin drops; *arr category assignment fails HTTP 400 |
| Overseerr service wiring | `/app/config/settings.json` on PVC | sonarr/radarr hookup |
| TMM datasources/settings/license | `/data/data/*.json`, `tmm.lic` on PVC | whatever role TMM is given next |

---

## 5. Embedded subtitle codec census (FULL library: n=10,014 items = 1,914 movies + 8,100 episodes; per-item Plex stream data; 0 fetch errors; run 05:18-05:22 UTC)

Counts of subtitle tracks (streamType 3). Embedded = stream without a `key` attribute; external sidecars listed separately.

| Codec class | Codec | Movies (embedded) | TV (embedded) |
|---|---|---|---|
| TEXT (losslessly extractable) | srt/subrip | 3,748 | 56,116 |
| | mov_text | 1 | 51 |
| | ass | 131 | 193 |
| | webvtt | 0 | 3 |
| | eia_608 (captions) | 14 | 575 |
| BITMAP (needs OCR; extraction attempts will structurally fail) | pgs | 5,232 | 463 |
| | vobsub | 86 | 16 |
| | dvb_subtitle | 2 | 10 |
| TEXT-based DVB (ccextractor territory; Bazarr support **not asserted**) | dvb_teletext | 0 | 10 |
| unmapped | "none" | 0 | 95 |
| **External sidecars** | srt | 486 | 432 |
| | idx | 2 | 0 |

Reading: the TV library is overwhelmingly text-first (56k embedded srt vs 489 bitmap tracks); the MOVIE library is bitmap-first (5,320 bitmap vs 3,894 text) - an extraction sweep will "fail" on most movie tracks for structural reasons, and those failures are not faults. dvb_teletext exists only on TV and only 10 tracks: the Weekly Wipe probe found a pocket, not a population. The 95 codec-"none" tracks are concentrated in ONE show - Come Dine with Me: The Professionals (2022) S01, ALL4 WEB-DLs, language English - Plex itself cannot name the codec. The Tunarr channel-6 fra+eng "none" pair could not be located in this census (different population: live-TV scan items are not library items); left unresolved rather than guessed, though the ALL4 concentration shows "probe fails to map a real stream" is the observed pattern for codec-none.

Sidecar naming (Plex/PMP compatibility): movies 477 srt sidecars - 476 language-suffixed, **1 bare**; TV 431/431 language-suffixed. `.ass/.ssa` sidecars: **0** in both roots (embedded ass exists: 324 tracks). PMP's external-srt-only constraint is satisfied by every sidecar except one bare-named file.

**Bazarr flags (read 05:07 UTC):** `ignore_ass_subs: true` - the TEMPORARY guard is still in place (also ignore_pgs_subs true, ignore_vobsub_subs true, single_language false, subfolder current, utf8_encode true, use_embedded_subs true, hi_extension sdh). The user's end-goal is all three formats once clients cope; removal of the guard belongs to that future decision, and the flag lives on the PVC (section 4.4), not in GitOps.

**Bazarr coverage:** wanted = 77 movies / 1,105 episodes at 05:02 UTC and **identical at 05:27 UTC** (re-sampled). Denominators at sample time: 1,891 movies-with-file gives 95.9%; 8,110 episode files gives 86.4% - but the episode figure is taken **mid-re-index** and is provisional until the running full-scan completes; the prior 94% baseline is not comparable at this instant.

---

## 6. Open items from the prior audit - status

1. **16 Plex orphans, now 10** (Plex items whose folders Radarr does not own): World on a Wire (type mismatch, unownable), Curious George 2 Follow That Monkey!, First Cow (2020), JOUR DE FETE x2, the Chinese Bookie `{tmdb-32040}` folder (Radarr owns the wrong sibling - section 2.2 class 5), Kishi Bashi Live, Omnibus Monsieur Hulot's Work, Monster Mash (1970), Scenes from a Marriage `{edition-Television}` folder. Genuinely unmanageable: World on a Wire, Omnibus (TV-class), likely both JOUR DE FETE shorts and Kishi Bashi (concert). Manageable but undecided: **First Cow** and **Curious George 2** (ordinary movies; add-or-ignore decision remains open).
2. **6 replacement searches (2026-07-30): ALL LANDED** - Ratcatcher, Heaven Can Wait (1943), Paddington 2, Secrets & Lies, Harry Potter PoA, Safe (1995), imported 07-30 per Radarr history. Runtime-mismatch detector re-run on ALL 8 imports since 07-28 (also Avengers Endgame 08-03, Heat 08-06): **0 mispulls, 0 corrupt, 0 samples**; worst deviation 1 minute. (The 08-04 movieFileDeleted events for Get Out / Bluebeard's 8th Wife / Joan the Maid II were upgrade cycles - all three have files now.)
3. **WANTED-EDITIONS: all 6 still absent.**
   - Fanny and Alexander theatrical 188m: empty `{edition-Theatrical}` placeholder exists; library has Full Length + TV Act I only.
   - Apocalypse Now theatrical 147m: the `{edition-Theatrical}` folder contains only a trailer; library has Redux + Final Cut.
   - Chinese Bookie 1978 re-edit 108m: Radarr's own `{edition-1978 Re-edit}` folder is empty (hasFile false); the 1976 cut files sit untagged in the unowned sibling folder.
   - LOTR theatrical x3: all three folders contain Extended only (single-file remux plus pt1/pt2 pairs).
4. **Bazarr coverage** - see section 5; re-index in flight, numbers stamped.

---

## 7. TMM's proper role: read-only gap detector feeding procurement

- **Current state:** detached - no datasources, empty DBs, last scan: never in this deployment. Its residue NFOs are today's largest identity-drift source (section 2.2). A stale TMM DB cannot mislead procurement right now because there is no DB at all - but there is also no gap detection.
- **Capability check on this image (v5.3.0):** export templates ARE present at `/app/templates` (ExcelXml, DataTablesHTML, ListAspectRatioCsv, ListExampleCsv/Xml, TvShowExampleCsv, and more) and the `/app/tinyMediaManager` launcher exists. TMM 5.x documents a headless CLI (update/scrape/export). **Actually executing a headless scan+export from THIS container was not tested** - running it would write databases and potentially NFOs, a mutation, out of scope. Unverified: whether this image runs the CLI without the web UI session, and whether export works without scraping first.
- **Why TMM detects gaps the *arrs cannot:** TMM enumerates the FILESYSTEM; the *arrs enumerate their own databases. Cases from this audit only a filesystem view catches: the unowned Chinese Bookie folder with real files, the empty edition placeholders, the Twin Peaks (2017) extras-ghost, 12 loose TV videos, nested movie folders inside other movies' folders. It can also cross-check subtitle absence independently of Bazarr's wanted list, and episodes-missing-per-scraped-metadata independently of Sonarr monitoring flags.
- **Recommendation (design only, nothing done): attach TMM strictly read-only.** Before any scan: NFO/connector writing OFF, artwork downloads OFF, renamer OFF (TMM's renamer collides head-on with the never-rename guardrail and with Radarr's own renamer). Use scan + export templates (CSV/XML) as the gap list; never let it write into the library again. Reversal: restore `/data/data/*.json` from a pre-change copy; nothing else is touched.

---

## 8. Staged remediation plan (nothing below was performed)

Ranked by (silent-failure risk) x (blast radius). SAFE = mechanical, config-only, no media files touched. JUDGEMENT = needs a human decision on a media library. Every step names its reversal.

**Stage 0 - kill the remaining IP-drift fuses (SAFE, highest rank)**
- 0a. Repoint Sonarr+Radarr download clients from bare IPs to cluster DNS (`deluge.media.svc:8112`, `nzbget.media.svc:10057`, `sabnzbd.media.svc:10097`). Change: 6 downloadclient rows via each UI. Reversal: restore the recorded IPs (preserved in section 4.1).
- 0b. Prowlarr: change its application/server URL settings so synced indexer entries carry `http://prowlarr-external-service.media.svc:9696/...` instead of 192.168.10.10, then re-sync apps and test one indexer per app. Reversal: set back to the IP and re-sync (all 33 entries revert automatically). Must be fixed at the Prowlarr end or app-sync will reinstate the IP.
- 0c. Add the five non-GitOps configs (section 4.4) to the backup/runbook inventory so a PVC restore has a diff baseline. Change: documentation/backup only. Reversal: none needed.

**Stage 1 - stop Emby drinking bad NFO (JUDGEMENT - every option touches identity)**
- 1a. Decide `The City (1999)`'s true identity by watching 60 seconds of the file. If it is Babe: Pig in the City, the Radarr record is the error (fix = re-map the movie in Radarr; movie.xml regenerates; reversal = remap back, both ids recorded in section 2.2). If it is the 1999 documentary, refresh the movie in Radarr so the stale movie.xml regenerates (reversal: none needed; the file is machine-generated).
- 1b. The 57-folder TMM-vs-Radarr NFO conflict list: per folder, a human confirms which id is right, then EITHER fix Radarr's mapping (reversal: remap) OR delete that one stale TMM .nfo (machine-generated residue; reversal: restore from snapshot). Do NOT bulk-delete: the American Woman pair proves some NFOs are right where the *other* NFO is wrong, and Plex-vs-NFO agreement (e.g. The City) sometimes sides against Radarr.
- 1c. `Destination Flavour (2012)` folder: its tvshow.nfo carries the Japan series' ids - same per-folder treatment. Reversal identical.
- 1d. Emby extras-as-movies (256 items, 76 misidentified): fixing this is Emby library configuration (extras handling), not restructuring - but per the guardrail nothing Emby-side is touched while the 4.9.5.0 grouping regression is live and untested against config changes. Recorded as KNOWN-DEFERRED with counts; revisit on a fixed Emby release.

**Stage 2 - Radarr/folder ownership repairs (JUDGEMENT, small blast radius each)**
- 2a. Chinese Bookie: Radarr points at the empty `{edition-1978 Re-edit}` folder while both actual files sit untagged in the unowned `{tmdb-32040}` folder; Radarr wrongly reports the film missing and could grab a duplicate. The correct end-state per the target structure needs renames/moves of 2 media files - **explicit operator approval required under the never-rename guardrail**. Interim SAFE step: unmonitor the movie in Radarr to prevent a duplicate grab; reversal: re-monitor.
- 2b. Scenes from a Marriage two-folder split: works today (both cuts selectable in Plex); folding into one folder is cosmetic conformance requiring a move - operator approval or leave as is.
- 2c. Empty leftovers (6 edition placeholders, `Secrets and Lies (1996)`, `WALL-E (2008)`, two `.deletedByTMM` dirs, empty `/media/tvshows`): contents verified empty or artwork-junk only. Removing them deletes no media file but IS deletion inside the library - operator sign-off, with this document as the inventory; recreating an empty dir is trivially reversible.
- 2d. Add-or-ignore: add First Cow (2020) and Curious George 2 to Radarr (reversal: remove from Radarr; files untouched). Put the unownable class (World on a Wire, Omnibus, etc.) on a recorded permanent-ignore list so they stop resurfacing as "orphans" every audit.
- 2e. `Get Out (2016)` wrong-year folder: renaming the folder would fix Plex's failed match but is a rename (operator approval). SAFE alternative: fix the match inside Plex (metadata match, no file touched; reversal: unmatch).

**Stage 3 - TV conformance debt (JUDGEMENT, widest blast radius, lowest silent-failure risk - nothing is failing because of it today)**
- 3a. Season-padding normalisation (257 unpadded dirs; Twin Peaks 1990 has live duplicate season dirs with files split across them) and the roughly 1,998 scene-named episode files: Sonarr's preview-rename covers both. Reversal: capture the preview JSON as the rename map before applying; Sonarr also logs old names. **Blocked on the never-rename guardrail - present to the operator as one batch with the preview diff; do not run opportunistically.** If anything is approved, Twin Peaks's duplicated season dirs go first.
- 3b. Sonarr metadata writers: leave OFF. Measured conclusion: with Plex ignoring NFO and Emby's only TV error caused by a WRONG NFO, enabling TV NFO writing buys no consumer anything today. TMM-on-TV likewise buys nothing as a writer; as a read-only gap detector it has value (section 7).

**Stage 4 - procurement (SAFE to search, JUDGEMENT to import)**
- Re-kick searches for the 6 absent wanted editions. On arrival, re-run the runtime-mismatch detector (thresholds: deviation over 25% AND over 10 min = mismatch; under 3 min = corrupt; "sample" in filename = sample) - this audit re-validated the detector on the last 8 imports.

---

## 9. Measured-vs-unmeasurable ledger

Could not measure (flagged, not estimated): `/media/media/rollout` (absent from all cluster mounts at sample time); SABnzbd/NZBGet server-side category tables; TMM headless CLI actually running on this image; the Tunarr channel-6 codec-"none" pair's true codec (population not addressable from the library); Bazarr per-language coverage percentages during the in-flight re-index (wanted counts stamped instead).

Everything else above is a direct count from Radarr/Sonarr/Bazarr/Plex/Emby APIs (GET only), pod-mounted filesystem walks, and on-disk NFO/XML reads, taken 2026-08-07 05:00-05:30 UTC.
