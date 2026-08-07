# Music / Lidarr Reconciliation Audit (SQ-52)

Date: 2026-08-07. Read-only audit — no Lidarr writes, no file moves, no deletions, no imports, no rescans were performed on any instance. All Lidarr access was HTTP GET; all disk access was read-only walks from the tunarr pod.

## Denominators (what was actually examined)

One `os.walk` per library root, executed in the tunarr pod, zero errors:

| Library | Root walked | Files examined | Dirs | Audio files (this audit's ext set) | Walk errors |
|---|---|---|---|---|---|
| Main | `/media/media/music/Main` | 41,620 | 14,441 | **41,505** (incl. 1,753 `.m4p`) | 0 |
| FLAC | `/media/media/music/FLAC` | 24,155 | 7,169 | **23,999** | 0 |
| Liz iTunes | `/media/media/music/Liz iTunes` | 48,628 | 8,980 | **47,505** | 0 |

Audio ext set: mp3 flac m4a aac ogg oga opus wma wav aif aiff ape wv mpc dsf dff m4p alac. Lidarr-side figures re-fetched live and matched the briefing exactly (Main 1,599 artists / 26,202 trackFiles; FLAC 1,600 / 21,012; Liz 1,088 / 22,877).

## Are the two counts comparable? Mostly yes — with two corrections

1. **Per-file counting is 1:1.** Spot check (Metric, Main): Lidarr reports 53 trackFiles; the disk folder holds 64 audio files; the 11-file delta is exactly the unmatched items (a CD single, an EP, an "Unknown Album" track, a 5-track compilation, and 2 stray tracks). Multi-disc and multi-version albums do not distort the comparison — trackFileCount counts physical files.
2. **The briefing's disk counts excluded `.m4p`** (DRM iTunes files). Audio-excluding-m4p from this walk: Main 39,752 (briefing said 39,751), FLAC 23,999 (23,998), Liz 47,462-ish (47,459). Agreement within ±1-46 files on a live share. Main's true audio count including DRM files is 41,505.
3. **For Liz the comparison was structurally invalid**: the 47,459 figure spans the whole `Liz iTunes` tree, but Lidarr's root folder is the subdirectory `Liz iTunes/Lidarr Apple Music`. 22,672 audio files (48% of the tree) were never inside Lidarr's root at all.

## Corrected gap figures

| Library | Disk audio | Lidarr trackFiles | Apparent gap | Real "Lidarr saw it but did not import it" gap |
|---|---|---|---|---|
| Main | 41,505 | 26,202 | 15,303 | **~10,300 net** inside owned artist folders (gross ~10,709) |
| FLAC | 23,999 | 21,012 | 2,987 | **~2,981** inside owned artist folders |
| Liz | 47,505 | 22,877 | 24,628 | **~248 gross** inside owned artist folders — the library is effectively fully imported; see below |

Arithmetic identities (verified exactly): Main 15,303 = 10,300 (unimported in owned folders, net) + 5,564 (orphan folders) − 561 (stale DB entries under artist folders that no longer exist). FLAC 2,987 = 2,981 + 29 − 23. Liz 24,628 = 22,672 (outside Lidarr root) + 2,796 (`--Completed` staging dump inside root) + 248 (gross unmatched) − 886 (DB overcounts) − 202 (stale under missing folders).

## Classification breakdown

### Main (apparent gap 15,303)

| Class | Files | Evidence |
|---|---|---|
| Unimported audio inside the 1,397 Lidarr-owned artist folders (net) | 10,300 | 35,941 on disk vs 25,641 tracked in those folders |
| — of which multi-artist folders Lidarr cannot map | 1,169 | `Compilations/` 620 + `Various Artists/` 549 (both exist as 0-trackFile Lidarr artists) |
| — of which duplicate encodings (same stem, 2+ audio exts in same dir) | 759 | e.g. `.flac` + `.mp3` of the same track |
| — of which DRM `.m4p` inside owned folders | 37 | unimportable |
| — remainder: unmatched albums/EPs/singles/tracks | ~8,700 | top: Elliott Smith 266, Sparks 214, Johnny Cash 196, Modest Mouse 186, Brian Eno 185, Green Day 176 (whole-album pattern, cf. Metric spot check) |
| Orphan folders (no Lidarr artist maps to them): 641 folders | 5,564 (42.9 GB) | |
| — `Main/Apple Music/` DRM dump | 1,711 | 1,710 of them `.m4p` — an iTunes-layout tree, permanently unimportable by Lidarr |
| — punctuation-variant duplicates of tracked artists (5 folders) | 439 | `AC_DC` (198) beside Lidarr's `AC+DC` (123 tf); also `R.E.M_`, `Dinosaur Jr_`, `Albert Hammond, Jr_`, `+_-` |
| — genuinely untracked artists (~635 folders) | ~3,414 | verified absent from the artist list: Cake (67), John Coltrane (66), Sleater Kinney (82); plus soundtrack composers (Trent Reznor and Atticus Ross 78, Mac Quayle 51) |
| Stale DB entries (Lidarr counts files that are not on disk) | 561 + 409 | 202 artists whose folders do not exist hold 561 trackFiles; 28 artists count 409 more files than their folders contain |
| Non-audio files in the tree | 115 | jpg/cue/log/nfo/m3u/mpg |

### FLAC (apparent gap 2,987) — the cleanest library

- 461 of 464 disk folders map to Lidarr artists; orphans are 3 folders / 29 files (`¥$`, `Patrick Watson`).
- The gap is almost entirely **whole unmatched albums inside owned folders**: Nine Inch Nails 225, Frank Sinatra 170, Depeche Mode 165, Coldplay 135, Death Cab for Cutie 110, Deep Purple 102.
- Zero duplicate-encoding pairs, zero `.m4p`, only 23 stale trackFiles, zero artists with negative deltas.
- 1,139 of 1,600 artists have no disk folder at all (1,147 have zero trackFiles) — artists added and monitored but never downloaded; not part of the file gap.

### Liz iTunes (apparent gap 24,628) — structural, not an import failure

Per-tree audio totals from the walk:

| Tree under `Liz iTunes/` | Audio files | Size |
|---|---|---|
| `Lidarr Apple Music/` (Lidarr's actual root) | 24,833 | 241.1 GB |
| `Server iTunes/Media.localized/Music/` | 22,664 | 192.1 GB |
| `Media/Apple Music/` | 8 | ~0 |
| `Music 1/`, `Previous iTunes Libraries/` | 0 | library DBs only |
| Loose at top level | — | `iTunes Library.itl`, `.itdb` files, `.DS_Store` |

Findings (report only; **no proposals for this library — strictly read-only per operator instruction**):

1. `Liz iTunes` is not a music library; it is a **container of at least three Music.app/iTunes library generations plus the Lidarr-managed copy**. Lidarr is pointed at `Lidarr Apple Music` only; 22,672 audio files (92% of the apparent gap) live in sibling trees Lidarr cannot see and was never configured to see.
2. `Server iTunes` holds 1,497 artist folders; only 541 share a name with the 711 folders under `Lidarr Apple Music`. It is an older, *broader* library, not a copy — 956 artist names exist only there. How much of its content is byte- or track-level duplicated into the Lidarr tree was **not measured**.
3. Inside the Lidarr root, coverage is effectively complete and slightly *over*-counted: matched folders hold 22,037 audio files on disk vs 22,877 tracked; 51 artists count 886 more files than exist and 378 artists (202 trackFiles) have no folder on disk — i.e. stale DB entries from deleted/moved files, not missing imports. Gross unmatched inside artist folders is only ~248 files (top: Joanna Newsom 35, Aphex Twin 30).
4. One orphan inside the Lidarr root: `--Completed/` with 2,796 audio files — a download-client staging dump (scene-release folder names, `-WEB-`, `-xpost`, split `.rar` parts).
5. iTunes-specific layout artifacts (`Media.localized`, `Music Library.musiclibrary`, `Compilations`, 641 extensionless files, `.musicdb`/`.itdb`/`.strings`) confirm these trees follow Apple's layout, which Lidarr does not parse; pointing Lidarr at them as-is would not map cleanly.

## Reconciliation plan — Main and FLAC only (NOT executed; for human approval)

Liz iTunes is excluded from every step below by operator instruction.

**Phase 0 — safety preconditions (both instances)**
- Set a recycle bin: `recycleBin` is currently **empty** on both — any upgrade-on-import would hard-delete the replaced file. Do not proceed without this.
- Snapshot both Lidarr DBs/PVCs (VolSync manual point-in-time or a copy of `lidarr.db`).
- Note `renameTracks=true` + `replaceIllegalCharacters=true` on both: imports will rename files to the naming spec. Expect mass mtime/path churn → VolSync backup volume spike and Plex/Emby rescan storms. Run mid-day (VolSync windows are 00:00–04:32) and consider suspending the music-related ReplicationSources during the import burst.
- `watchLibraryForChanges=true` and `rescanAfterRefresh=always` mean Lidarr has already seen everything below — the gap is match failures, so a plain rescan closes nothing. Do not expect "Rescan" to fix this.

**Phase 1 — clear stale DB entries (touches DB only, no files)**
Main: 202 folder-less artists (561 trackFiles) + 28 negative-delta artists (409 files). FLAC: 23 files. Per-artist Refresh; if counts persist, delete the specific trackfile records via API. Expected result: Main trackFiles drop by up to ~970 before rising again in Phase 3.

**Phase 2 — decide the metadata-profile question first**
The unmatched pattern (Metric's CD single + EP; whole albums for NIN/Sinatra/etc.) is consistent with releases absent from each artist's active metadata profile (EPs/singles/compilations excluded) or MB release-matching failures. Before mass manual import, sample ~10 top-offender albums in the Manual Import UI and record *why* each is unmatched. If the profile excludes EP/Single, importing them requires a profile change, which raises monitored-track counts and future search load — an explicit decision, not a default.

**Phase 3 — manual import of unmatched audio inside owned folders**
Scope: Main ~8,700 files (after excluding VA/Compilations 1,169, dup encodings 759, m4p 37), FLAC ~2,981. Work per-artist from the ranked lists (persisted in the session scratchpad `join_main.json` / `join_flac.json`; top-15s reproduced above). Use interactive Manual Import in place (files are already in final locations; no move). Wrong-match risk is highest for VA content and non-album tracks — skip anything ambiguous on the first pass.

**Phase 4 — orphan folders (Main only)**
- 5 punctuation-variant folders (439 files): merge into the canonical Lidarr folders (`AC+DC`, `R.E.M`, `Dinosaur Jr`, …). This is a file move — needs its own approved ticket and the Phase 0 backup.
- ~635 genuinely untracked artist folders (~3,414 files): produce an add/ignore decision list for the human; add chosen artists in Lidarr, then manual-import their folders. Some (soundtrack composers, jazz) may be deliberately untracked.

**Phase 5 — document the permanently-unimportable remainder (no action)**
Main: 1,747 DRM `.m4p` (the `Apple Music/` dump 1,710 + 37 in-folder), 1,169 Compilations/Various Artists, 759 duplicate encodings. These will always show as a disk-vs-Lidarr delta; record them as known-untracked (or relocate them out of the root in a separately approved ticket) so future audits do not rediscover them.

**What could go wrong**
- Upgrades during import deleting originals (mitigated by recycle bin — Phase 0).
- Rename churn triggering VolSync/Plex storms (mitigated by scheduling + suspend).
- Fingerprinting (`allowFingerprinting=newFiles`) hammering the NFS share during bulk import — throttle by doing one artist at a time.
- Mis-matches on VA/compilation content polluting artist discographies — excluded from scope in Phase 3.
- FLAC instance importing its 130 stray `.mp3`/24 `.wav` into a lossless profile — the quality profile will reject or flag these; leave them for the dedup/decision list.

**Expected end state if fully executed**: Main trackFiles 26,202 → ~34,000 (+ orphan-artist adds), FLAC 21,012 → ~23,970. Residual disk-vs-Lidarr delta after that: Main ~3,675 known-untracked + whatever the human declines; FLAC ~30.

## Verified vs inferred

**Verified by measurement this session**: every count and identity above (walk denominators with zero errors; live API totals matching the briefing exactly; the Metric 64-vs-53 file-level diff; `AC+DC`-vs-`AC_DC` duplicate trees; Liz root folder setting via `/api/v1/rootfolder`; `--Completed` contents sample; `Server iTunes` 1,497 dirs and 541-name overlap; media-management and naming configs on all three instances).

**Inferred, not verified**: the *cause* of unmatched albums (metadata profile vs MB matching — pattern-based; Phase 2 verifies it); the degree of content duplication between `Server iTunes` and `Lidarr Apple Music` (not measured); the briefing find's exact extension set (reconstructed from ±1-file agreement on Main/FLAC); `.m4p` being unimportable by Lidarr (documented Lidarr behavior, not tested here).

**Writes performed**: none, on any Lidarr instance or any media file. All API calls were GET; disk access was read-only; no rescan/refresh/import commands were issued.
