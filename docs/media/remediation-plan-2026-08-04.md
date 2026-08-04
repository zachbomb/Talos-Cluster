# SQ-20 identity remediation — Phase 1 preview plan (2026-08-04)

**This document is a preview. Nothing in it has been executed.** It was produced under a
zero-write contract: every Radarr call used to build it was a `GET` (no `POST`/`PUT`/`DELETE`),
and no file on disk was created, moved, renamed, or deleted. Every action below is written
out exactly as Phase 2 would run it, so a human can read precisely what would happen before
anything happens.

Companion inputs:
- Verdicts: `docs/media/movie-identity-verdicts-2026-08-04.md` (commit `367934d94`)
- Audit: `docs/media/movie-identity-audit-2026-08-04.md` (commit `4e8e45570`)

Live snapshot taken 2026-08-04 (Radarr 6.4.1.10545 at `192.168.10.210:7878`, `/api/v3/`,
`X-Api-Key` from the radarr pod's `/config/config.xml`; disk listings via the `tdarr` pod,
which mounts the same `/media/media/movies` library). Root folder: `/media/media/movies`
(accessible, 66.3 TB free).

Radarr naming config (live, `GET /api/v3/config/naming`):
- `renameMovies: true`, `colonReplacementFormat: "delete"`, `replaceIllegalCharacters: true`
- folder: `{Movie CleanTitle} ({Release Year}) {tmdb-{TmdbId}}`
- file: `{Movie CleanTitle} {(Release Year)} {tmdb-{TmdbId}} {edition-{Edition Tags}} {[Custom Formats]}[Quality Full]…[-Release Group]`
- `CleanTitle` drops apostrophes and colons (evidenced live: `Bluebeard's` → `Bluebeards`).

---

## The 15 defects (enumeration)

No prior artifact numbers the defects; this plan fixes the enumeration explicitly. It is
every actionable defect in the verdicts doc: the 11 headline findings (counting the
JOUR DE FÊTE pair as one defect) plus the 4 actionable cohort-B items.

| # | Defect | Class |
|---|---|---|
| D1 | `Get Out (2016)` — record is *Get Out Alive* (tmdb 414530), file is *Get Out* (2017) | Radarr record wrong |
| D2 | `Hero (2002)` — record is *Hero* 2007 (tmdb 51550), file is Zhang Yimou's *Hero* 2002 | Radarr record wrong |
| D3 | `Bluebeard's 8th Wife (1938)` — record is the 1923 short (tmdb 535525), file is the 1938 Lubitsch feature | Radarr record wrong |
| D4 | `The House, 1984 (1984)` — record is *The House* (tmdb 628603), file is *Nineteen Eighty-Four* | Radarr record wrong |
| D5 | `The Creatures (1966)` — mispull, embedded title "5. MARRIED LIFE", true identity unknown | Mispull, human ID |
| D6 | `No Regret (1993)` — mispull, file is the 38-min Marlon Riggs *No Regret* (probable), not *No Regret, No Return* | Mispull, probable ID |
| D7 | `Ô saisons, ô châteaux (1958)` — file corrupted (invalid MKV magic) | Corrupted, re-acquire |
| D8 | `Fellini Satyricon (1969)` — file corrupted (invalid MKV magic) | Corrupted, re-acquire |
| D9 | `Monster Mash (1970)` — orphan folder actually containing M\*A\*S\*H | Duplicate (see drift) |
| D10 | `JOUR DE FÊTE DANS LES MONTS NAGA (1964)` + `(1995)` — suspected duplicate pair, no TMDB match | Duplicate, human research |
| D11 | `Joan the Maid (1993)` — both feature parts on disk, Radarr `hasFile=false` (2-part gap) | Structural |
| D12 | `First Cow (2020)` — orphan folder duplicating the tracked `First Cow (2019)` copy | Duplicate (see drift) |
| D13 | `Curious George 2 Follow That Monkey! (2009)` — orphan folder, byte-identical duplicate of the tracked copy | Duplicate (see drift) |
| D14 | `Secrets and Lies (1996)` — leftover folder next to the already-remediated tagged folder | Residue cleanup |
| D15 | `Samson and Delilah (1996)` — empty folder remnant | Residue cleanup |

The seven cohort-A3 stale-path records needing plain re-acquisition (Fallen Angels,
Je Tu Il Elle, Lumière & Company, Non Je Ne Regrette Rien, Room 666, WALL-E residue) were
already known from the audit and are not counted among the 15; they are listed in
Appendix A so nothing actionable is lost.

## Drift since the verdicts doc (verified live 2026-08-04)

The library moved between the SQ-20 snapshot and this plan. Three verdicts-doc remediations
are obsolete in their original form:

1. **M\*A\*S\*H already exists in Radarr** — id 870, tmdb 651, path `/media/media/movies/MASH (1970)`,
   holding a 7.2 GB `M-A-S-H (1970) {tmdb-651} [DSNP][WEBDL-1080p][EAC3 5.1][h264]-GPRS.mkv`
   (imported Jul 2025). D9 is therefore **not** "add Monster Mash to Radarr as M\*A\*S\*H";
   it is a duplicate-copy decision (the orphan folder holds a second, smaller 4.0 GB rip).
2. **Secrets & Lies already remediated** — id 2488, tmdb 11159, path
   `Secrets and Lies (1996) {tmdb-11159}` with a 36.9 GB feature file (movie.xml dated Jul 30).
   D14 reduces to cleaning the leftover un-tagged folder.
3. **First Cow / Curious George 2 have records** — the verdicts doc called their folders
   orphans, which is still true, but each is shadowed by a tracked sibling folder:
   record 501 (*First Cow*, tmdb 558582) tracks `First Cow (2019)` (22.9 GB copy), and record
   357 (*Curious George 2*, tmdb 23903) tracks `Curious George 2 - Follow That Monkey! (2009)`
   (with dash). D12/D13 are duplicate cleanups, not adds.
4. **Samson and Delilah folder is now completely empty** (was metadata-only) — D15 is a
   `rmdir` plus an optional re-acquisition decision.

## CRITICAL ordering constraint — SQ-25 must wait for D1–D6

Live `GET /api/v3/rename?movieId=` previews (Appendix B, verbatim) prove that Radarr's
pending renames would stamp **wrong-identity names onto six correct files** today:

| movieId | file today | Radarr would rename it to |
|---|---|---|
| 539 | `Get Out (2016).mkv` | `Get Out Alive (2016) {tmdb-414530} […].mkv` — WRONG film name |
| 2421 | `Hero.2002.CHINESE.DC….mkv` | `Hero (2007) {tmdb-51550} […].mkv` — WRONG year/film |
| 1895 | `Bluebeard's 8th Wife (1938).mkv` | `Bluebeards 8th Wife (1923) {tmdb-535525} […].mkv` — WRONG year/film |
| 1490 | `The House, 1984 (1984).mkv` | `The House (1984) {tmdb-628603} […].mkv` — WRONG film |
| 1398 | `The Creatures (1966).mkv` | `Terror-Creatures from the Grave (1965) {tmdb-63507} […].mkv` — WRONG film |
| 989 | `No Regret (1993).mkv` | `No Regret No Return (1993) {tmdb-261238} […].mkv` — WRONG film |

**Any library-wide rename (SQ-25) run before D1–D6 are fixed permanently bakes these wrong
identities into filenames.** Movie ids 539, 2421, 1895, 1490, 1398, 989 must be excluded
from bulk rename until their defects are closed.

## Conventions used below

- API base: `http://192.168.10.210:7878/api/v3`, header `X-Api-Key: <key>` on every call.
- Radarr cannot change a record's `tmdbId` in place. The identity fix is always:
  **delete the record (keeping files) → re-add with the correct `tmdbId` pinned to the
  existing folder → rescan**. Re-adding with an explicit `path` performs **zero file moves**.
- `DELETE /movie/{id}?deleteFiles=false&addImportExclusion=false` never touches disk.
- `DELETE /moviefile/{id}` **does** delete the physical file — it is used only in D7/D8
  where deleting the corrupted file *is* the remediation, and each such call carries an
  explicit before → after pair.
- Folder/file names marked *(predicted)* are derived from the live naming config; the
  authoritative preview must be re-run with `GET /rename?movieId=<newId>` after each
  re-add, before any rename is executed (that re-preview is step SQ-25/STAGE-1).
- Steps tagged **[HUMAN GATE]** stop the sequence until a person decides.

---

## D1 — `Get Out (2016)`: record *Get Out Alive* → *Get Out* (2017, tmdb 419430)

**Current state (live):** record id 539, tmdb 414530 (*Get Out Alive* 2016), profile 7,
`path=/media/media/movies/Get Out (2016)`, movieFileId 532 → `Get Out (2016).mkv` (60.5 GB,
WEBDL-2160p HDR10). Verdict: file is Jordan Peele's *Get Out* (2017), measured 104.08 min
vs TMDB 104. Target confirmed live: tmdb 419430 / tt5052448 / 104 min.

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/movie/539?deleteFiles=false&addImportExclusion=false`
2. `POST /api/v3/movie` body:
   ```json
   {"title":"Get Out","tmdbId":419430,"year":2017,"qualityProfileId":7,
    "path":"/media/media/movies/Get Out (2016)","monitored":true,
    "minimumAvailability":"announced","addOptions":{"searchForMovie":false}}
   ```
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":<id returned by step 2>}`
4. Verify: `GET /api/v3/movie/<newId>` shows `hasFile: true`, `movieFile.relativePath`
   = `Get Out (2016).mkv`. If the file did not auto-link, preview the link with
   `GET /api/v3/manualimport?folder=/media/media/movies/Get Out (2016)` and import via UI.

**Filesystem effect of D1: none.** Every path is unchanged:
- `/media/media/movies/Get Out (2016)/` → `/media/media/movies/Get Out (2016)/` (no move)
- `…/Get Out (2016)/Get Out (2016).mkv` → unchanged

**Deferred rename (SQ-25, after D1):** *(predicted)*
- folder `…/Get Out (2016)/` → `…/Get Out (2017) {tmdb-419430}/`
- file `Get Out (2016).mkv` → `Get Out (2017) {tmdb-419430} [WEBDL-2160p][HDR10][DTS-X 7.1][h265].mkv`
- side files (`.nfo`, artwork, `movie.xml`, `.DS_Store`) travel with the folder move.

## D2 — `Hero (2002)`: record *Hero* 2007 → Zhang Yimou's *Hero* (2002, tmdb 79)

**Current state (live):** record id 2421, tmdb 51550 (*Hero* 2007, Japanese), profile 13,
`minimumAvailability: tba`, `path=/media/media/movies/Hero (2002)`, movieFileId 7190 →
`Hero.2002.CHINESE.DC.1080p.BluRay.DDP5.1.x265.10bit-LAMA.mkv` (3.7 GB). This is an
**active misassignment** — the 2007 record's path points at the 2002 film's folder.
Target confirmed live: tmdb 79 / tt0299977 (TMDB runtime 99 = international cut; the file
is the Chinese director's cut, measured 109.35 min — consistent, not a red flag).

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/movie/2421?deleteFiles=false&addImportExclusion=false`
   (the *Hero* 2007 title simply leaves the library — its file was never present; re-add it
   separately later if actually wanted)
2. `POST /api/v3/movie` body:
   ```json
   {"title":"Hero","tmdbId":79,"year":2002,"qualityProfileId":13,
    "path":"/media/media/movies/Hero (2002)","monitored":true,
    "minimumAvailability":"announced","addOptions":{"searchForMovie":false}}
   ```
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":<newId>}`
4. Verify `hasFile: true` with the LAMA mkv linked.

**Filesystem effect of D2: none.** `/media/media/movies/Hero (2002)/` and its contents unchanged.

**Deferred rename (SQ-25, after D2):** *(predicted)*
- folder `…/Hero (2002)/` → `…/Hero (2002) {tmdb-79}/`
- file `Hero.2002.CHINESE.DC….mkv` → `Hero (2002) {tmdb-79} [Bluray-1080p][EAC3 5.1][x265]-LAMA.mkv`
  (optionally set `edition = Directors Cut` on the movie file first so the
  `{edition-…}` token captures the DC; decide at SQ-25 time).

## D3 — `Bluebeard's 8th Wife (1938)`: record 1923 short → 1938 Lubitsch feature (tmdb 31996)

**Current state (live):** record id 1895, tmdb 535525 (1923 short), profile 7,
`path=/media/media/movies/Bluebeard's 8th Wife (1938)`, movieFileId 1844 →
`Bluebeard's 8th Wife (1938).mkv` (16.7 GB). Folder also holds `Featurettes/`, `Trailers/`,
artwork, `.nfo`. Verdict: measured 85.53 min ≈ TMDB 85 for the 1938 film.
Target confirmed live: tmdb 31996 / tt0029929 / 85 min.

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/movie/1895?deleteFiles=false&addImportExclusion=false`
2. `POST /api/v3/movie` body:
   ```json
   {"title":"Bluebeard's 8th Wife","tmdbId":31996,"year":1938,"qualityProfileId":7,
    "path":"/media/media/movies/Bluebeard's 8th Wife (1938)","monitored":true,
    "minimumAvailability":"announced","addOptions":{"searchForMovie":false}}
   ```
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":<newId>}`
4. Verify `hasFile: true`.

**Filesystem effect of D3: none.**

**Deferred rename (SQ-25, after D3):** *(predicted)*
- folder `…/Bluebeard's 8th Wife (1938)/` → `…/Bluebeards 8th Wife (1938) {tmdb-31996}/`
  (apostrophe dropped by CleanTitle — evidenced by today's live preview)
- file `Bluebeard's 8th Wife (1938).mkv` → `Bluebeards 8th Wife (1938) {tmdb-31996} [WEBDL-1080p][PCM 1.0][h264].mkv`
- `Featurettes/`, `Trailers/`, artwork travel with the folder.

## D4 — `The House, 1984 (1984)`: record *The House* → *Nineteen Eighty-Four* (tmdb 9314)

**Current state (live):** record id 1490, tmdb 628603 (*The House*, 59-min TV film),
profile 7, `path=/media/media/movies/The House, 1984 (1984)`, movieFileId 1450 →
`The House, 1984 (1984).mkv` (31.6 GB) plus `-trailer.mkv`, `Behind the Scenes/`,
`Interviews/`. Verdict: embedded title "1984", measured 110.63 min vs TMDB 113.
Target confirmed live: tmdb 9314 / tt0087803 / 113 min.

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/movie/1490?deleteFiles=false&addImportExclusion=false`
2. `POST /api/v3/movie` body:
   ```json
   {"title":"Nineteen Eighty-Four","tmdbId":9314,"year":1984,"qualityProfileId":7,
    "path":"/media/media/movies/The House, 1984 (1984)","monitored":true,
    "minimumAvailability":"announced","addOptions":{"searchForMovie":false}}
   ```
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":<newId>}`
4. Verify `hasFile: true` with the 31.6 GB mkv linked.

**Filesystem effect of D4: none.**

**Deferred rename (SQ-25, after D4):** *(predicted)*
- folder `…/The House, 1984 (1984)/` → `…/Nineteen Eighty-Four (1984) {tmdb-9314}/`
- file `The House, 1984 (1984).mkv` → `Nineteen Eighty-Four (1984) {tmdb-9314} [WEBDL-1080p][PCM 1.0][h264].mkv`
- trailer + extras folders travel with the folder move.

## D5 — `The Creatures (1966)`: mispull, identity unknown **[HUMAN GATE]**

**Current state (live):** record id 1398, tmdb 63507 (*Terror-Creatures from the Grave*
1965), profile 13, `path=/media/media/movies/The Creatures (1966)`, movieFileId 1373 →
`The Creatures (1966).mkv` (18.3 GB). Verdict: embedded title **"5. MARRIED LIFE"** — a
chapter/episode label; the file is not the matched film and its true identity is unknown.
(The folder name suggests Varda's *Les Créatures* (1966) was intended, but that runs
~105 min vs 94.28 measured — unconfirmed either way.)

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** Identify the actual content (open the file / watch a sample — 94 min,
   chapter title "5. MARRIED LIFE"). Every subsequent step depends on the answer.
2. Detach the wrong identity regardless of the answer:
   `DELETE /api/v3/movie/1398?deleteFiles=false&addImportExclusion=false`
3. Branch on identification:
   - **Identified as X:** `POST /api/v3/movie` with X's `tmdbId` and
     `"path":"/media/media/movies/The Creatures (1966)"` (same zero-move re-add pattern as
     D1–D4), then `RescanMovie`; folder/file rename deferred to SQ-25.
   - **Unwanted content:** quarantine —
     `mv "/media/media/movies/The Creatures (1966)" "/media/media/movies/.quarantine/The Creatures (1966)"`
     before → after:
     `/media/media/movies/The Creatures (1966)/` → `/media/media/movies/.quarantine/The Creatures (1966)/`
   - **Want the originally-intended film:** additionally re-add that film (new empty
     folder, `searchForMovie: true`).

**Filesystem effect until the gate clears: none.**

## D6 — `No Regret (1993)`: file probably belongs to record 993 **[HUMAN GATE]**

**Current state (live):** three intertwined objects —
- record id 989, tmdb 261238 (*No Regret, No Return* 1993, Korean, runtime 94), profile 13,
  `path=/media/media/movies/No Regret (1993)`, movieFileId 975 → `No Regret (1993).mkv`
  (7.8 GB, measured **38:13**, embedded title "THE SIGNIFYIN' WORKS OF MARLON RIGGS - DISC 2")
- record id 993, tmdb 281084 (*No Regret* 1993, Marlon Riggs, runtime **38**), profile 7,
  `path=/media/media/movies/Non Je Ne Regrette Rien (No Regret) (1993)`, `hasFile: false`,
  folder empty on disk
- **New evidence this pass:** the mispulled file's 38:13 runtime matches record 993's
  expected 38 min exactly. The file sitting in 989's folder is very probably the Marlon
  Riggs *No Regret* — i.e. the film record 993 is waiting for.

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** Confirm the file is the Riggs film (38-min doc; the "DISC 2" tag means
   it was ripped from the Signifyin' Works compilation disc — verify it contains only
   *No Regret*, not several shorts).
2. If confirmed, move the file to record 993's folder:
   - before → after:
     `/media/media/movies/No Regret (1993)/No Regret (1993).mkv`
     → `/media/media/movies/Non Je Ne Regrette Rien (No Regret) (1993)/No Regret (1993).mkv`
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":993}` → record 993 gains the file.
4. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":989}` → record 989 drops to
   `hasFile: false` (its real film — *No Regret, No Return* — is genuinely missing).
5. **[HUMAN GATE]** Decide whether to re-acquire *No Regret, No Return* (tmdb 261238):
   `POST /api/v3/command` body `{"name":"MoviesSearch","movieIds":[989]}` — or unmonitor.
6. Cleanup of the now file-less `No Regret (1993)` folder's leftover artwork/nfo (which
   describe the Korean film): delete or leave for SQ-25's sweep; before → after pairs:
   `…/No Regret (1993)/No Regret (1993).nfo` → (deleted), fanart/poster likewise.
7. If step 1 DISCONFIRMS: fall back to quarantine —
   `/media/media/movies/No Regret (1993)/No Regret (1993).mkv`
   → `/media/media/movies/.quarantine/No Regret (1993)/No Regret (1993).mkv`, then step 4.

## D7 — `Ô saisons, ô châteaux (1958)`: corrupted file, re-acquire

**Current state (live):** record id 1000, tmdb 278727 (identity fine), profile 8,
movieFileId 6510 → `O.Saisons.O.Chateaux.1958.1080p.BluRay.x264-BiPOLAR.mkv` (3.4 GB,
invalid MKV magic bytes, unplayable), plus matching `.en.sdh.srt`.

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/moviefile/6510` — **deletes the corrupted file from disk** (intended):
   - before → after:
     `/media/media/movies/Ô saisons, ô châteaux (1958)/O.Saisons.O.Chateaux.1958.1080p.BluRay.x264-BiPOLAR.mkv` → (deleted)
2. Remove the orphaned sidecar sub:
   - `…/O.Saisons.O.Chateaux.1958.1080p.BluRay.x264-BiPOLAR.en.sdh.srt` → (deleted)
3. `POST /api/v3/command` body `{"name":"MoviesSearch","movieIds":[1000]}` — re-acquire.
4. Verify: new download imports into the same folder; `hasFile: true` with a new movieFileId;
   spot-check the new file opens (ffprobe via tdarr pod).

**Folder unchanged:** `/media/media/movies/Ô saisons, ô châteaux (1958)/` stays (rename to
`O Seasons O Castles (1958) {tmdb-278727}` *(predicted)* deferred to SQ-25).

## D8 — `Fellini Satyricon (1969)`: corrupted file, re-acquire

**Current state (live):** record id 490, tmdb 11163 (identity fine), profile 13,
movieFileId 6423 → `Fellini.s.Satyricon.1969.MULTi.1080p.BluRay.x264-CherryCoke.mkv`
(13.6 GB, invalid MKV magic), plus `.en.srt`, trailer, `Featurettes/`, `Interviews/`.

**Phase 2 actions (ordered):**
1. `DELETE /api/v3/moviefile/6423` — deletes the corrupted file from disk:
   - before → after:
     `/media/media/movies/Fellini Satyricon (1969)/Fellini.s.Satyricon.1969.MULTi.1080p.BluRay.x264-CherryCoke.mkv` → (deleted)
2. Remove the orphaned sidecar sub:
   - `…/Fellini.s.Satyricon.1969.MULTi.1080p.BluRay.x264-CherryCoke.en.srt` → (deleted)
3. `POST /api/v3/command` body `{"name":"MoviesSearch","movieIds":[490]}`.
4. Verify import + playable file as in D7. Trailer/Featurettes/Interviews are untouched.

## D9 — `Monster Mash (1970)`: duplicate copy of M\*A\*S\*H **[HUMAN GATE]**

**Current state (live):** orphan folder (no Radarr record points at it) containing
`Monster Mash (1970).mkv` (4.0 GB, embedded title "M\*A\*S\*H (1970)", 115.92 min) plus
`MASH (1970).nfo`, `M-A-S-H (1970).txt`, sample, trailer, artwork. Radarr **already tracks
M\*A\*S\*H** (id 870, tmdb 651) at `/media/media/movies/MASH (1970)` with a 7.2 GB
DSNP WEBDL-1080p copy — no pending rename (its file is already canonically named).

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** Confirm the 7.2 GB tracked WEBDL is the copy to keep (it is newer,
   larger, properly tagged). Cross-check the 4.0 GB rip against the SQ-8 household
   disc-rip preservation manifest before destroying it — if it is a household rip, archive
   instead of delete.
2. Delete (or archive) the orphan folder — before → after:
   - `/media/media/movies/Monster Mash (1970)/` → (deleted, all 16 items)
   - or archive variant: `/media/media/movies/Monster Mash (1970)/` → `<archive location per SQ-8>/Monster Mash (1970)/`
3. No Radarr call needed (no record involved).

## D10 — `JOUR DE FÊTE DANS LES MONTS NAGA` (1964) + (1995): duplicate pair **[HUMAN GATE]**

**Current state (live):** two orphan folders, no Radarr records, no TMDB match for either:
- `…/JOUR DE FÊTE DANS LES MONTS NAGA (1964)/JOUR DE FÊTE DANS LES MONTS NAGA (1964).mkv` — 9,148,026,450 bytes, 80.53 min
- `…/JOUR DE FÊTE DANS LES MONTS NAGA (1995)/JOUR DE FÊTE DANS LES MONTS NAGA (1995).mkv` — 9,159,735,511 bytes, 80.25 min
- identical embedded title "JOUR DE FÊTE"; files are near- but **not** byte-identical.

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** Research the film (likely an ethnographic documentary; neither year
   verifiable on TMDB) and diff the two files (e.g. ffprobe stream inventory + a few
   frame hashes via the tdarr pod — read-only) to establish whether one is a superior copy.
2. Keep exactly one folder; delete the other — before → after (choice pending):
   - `/media/media/movies/JOUR DE FÊTE DANS LES MONTS NAGA (<loser year>)/` → (deleted, ~9.1 GB freed)
3. Radarr: none (no TMDB entry exists, so it stays outside Radarr by design — same category
   as *World on a Wire*).

## D11 — `Joan the Maid (1993)`: split the 2-part film into two tracked records

**Current state (live):** record id 1905, tmdb 142373 (*Joan the Maid I: The Battles* 1994,
runtime 160), profile 8, `hasFile: false`, `path=/media/media/movies/Joan the Maid (1993)`.
The folder physically holds BOTH parts:
`Joan the Maid (1993) Part 1.mkv` (40.1 GB) and `Joan the Maid (1993) Part 2.mkv` (44.0 GB)
plus per-part nfo/posters. Part II confirmed live on TMDB: *Joan the Maid II: The Prisons*,
tmdb 142374 / tt0107260 / 176 min. Radarr models one movie per folder, so the shared folder
must be split. **Do not re-download anything — both files are already on disk.**

**Phase 2 actions (ordered):**
1. Create the two target folders and move each part (folder names follow the live naming
   scheme so SQ-25 has nothing left to do here) — before → after:
   - `…/Joan the Maid (1993)/Joan the Maid (1993) Part 1.mkv`
     → `…/Joan the Maid I The Battles (1994) {tmdb-142373}/Joan the Maid (1993) Part 1.mkv`
   - `…/Joan the Maid (1993)/Joan the Maid (1993) Part 1.nfo` → same folder as its mkv (with `-clearlogo.png`, `-fanart.jpg`, `-logo.png`, `-poster.jpg`)
   - `…/Joan the Maid (1993)/Joan the Maid (1993) Part 2.mkv`
     → `…/Joan the Maid II The Prisons (1994) {tmdb-142374}/Joan the Maid (1993) Part 2.mkv`
   - `…/Joan the Maid (1993)/Joan the Maid (1993) Part 2.nfo` → same folder as its mkv (with `-fanart.jpg`, `-poster.jpg`)
   - `…/Joan the Maid (1993)/` → (deleted once empty)
2. Repoint record 1905 at the Part I folder:
   `PUT /api/v3/movie/1905` with the record's JSON, `path` changed to
   `/media/media/movies/Joan the Maid I The Battles (1994) {tmdb-142373}` and
   `"moveFiles": false` (folder already final; nothing for Radarr to move).
3. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":1905}` → Part I links.
4. Add Part II: `POST /api/v3/movie` body:
   ```json
   {"title":"Joan the Maid II: The Prisons","tmdbId":142374,"year":1994,
    "qualityProfileId":8,
    "path":"/media/media/movies/Joan the Maid II The Prisons (1994) {tmdb-142374}",
    "monitored":true,"minimumAvailability":"announced",
    "addOptions":{"searchForMovie":false}}
   ```
5. `POST /api/v3/command` body `{"name":"RescanMovie","movieId":<newId>}` → Part II links.
6. Verify both records `hasFile: true`; file renames to canonical form defer to SQ-25.

## D12 — `First Cow (2020)`: orphan duplicate of the tracked copy **[HUMAN GATE]**

**Current state (live):** record id 501, tmdb 558582 tracks `…/First Cow (2019)/First Cow (2019).mkv`
(22.9 GB, WEBDL-2160p HDR10 per its pending-rename preview). Orphan folder
`…/First Cow (2020)/` holds a second copy `First Cow (2020).mkv` (9.6 GB, 1080p-class)
plus artwork/nfo. Same film, two encodes.

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** Confirm keeping the tracked 22.9 GB 2160p copy.
2. Delete the orphan folder — before → after:
   - `/media/media/movies/First Cow (2020)/` → (deleted, ~9.6 GB freed, 16 items)
3. Radarr: none now. Note for SQ-25: record 501's already-previewed rename will move
   `First Cow (2019).mkv` → `First Cow (2020) {tmdb-558582} [WEBDL-2160p][HDR10][AC3 5.1][h265].mkv`
   and the folder *(predicted)* `…/First Cow (2019)/` → `…/First Cow (2020) {tmdb-558582}/` —
   i.e. the tracked folder will take over the "(2020)" name after the orphan is gone
   (ordering note: delete the orphan **before** the SQ-25 rename to avoid a name collision).

## D13 — `Curious George 2 Follow That Monkey! (2009)`: byte-identical duplicate **[HUMAN GATE]**

**Current state (live):** record id 357, tmdb 23903 tracks
`…/Curious George 2 - Follow That Monkey! (2009)/Curious George 2 - Follow That Monkey! (2009).mkv`.
Orphan folder (same name **without** the dash) holds `Curious George 2 Follow That Monkey! (2009).mkv`
— **identical size (2,790,271,434 bytes) and identical mtime (Nov 4 2017)** to the tracked
copy: a pure duplicate.

**Phase 2 actions (ordered):**
1. **[HUMAN GATE]** (formality) Confirm deletion of the dashless orphan folder.
2. Delete — before → after:
   - `/media/media/movies/Curious George 2 Follow That Monkey! (2009)/` → (deleted, ~2.8 GB freed, 19 items)
3. Radarr: none. SQ-25 note: record 357's previewed rename retitles the tracked file to
   `Curious George 2 Follow That Monkey! (2009) {tmdb-23903} [WEBDL-1080p][EAC3 5.1][h264].mkv`
   (dashless form) — delete the orphan **before** that rename to avoid folder-name collision
   when the folder rename *(predicted)* lands on `Curious George 2 Follow That Monkey! (2009) {tmdb-23903}`.

## D14 — `Secrets and Lies (1996)`: leftover folder beside the remediated one

**Current state (live):** the remediation already happened (record 2488, tmdb 11159, tagged
folder `Secrets and Lies (1996) {tmdb-11159}` with the 36.9 GB feature, no pending rename).
The OLD folder `…/Secrets and Lies (1996)/` remains with only: `clearlogo.png`, `logo.png`,
`fanart.jpg`, `.DS_Store`, and an `Interviews/` extras dir.

**Phase 2 actions (ordered):**
1. Preserve the extras — before → after:
   - `/media/media/movies/Secrets and Lies (1996)/Interviews/`
     → `/media/media/movies/Secrets and Lies (1996) {tmdb-11159}/Interviews/`
2. Delete the residue — before → after:
   - `/media/media/movies/Secrets and Lies (1996)/` (remaining artwork + `.DS_Store`) → (deleted)
3. Radarr: none.

## D15 — `Samson and Delilah (1996)`: empty folder remnant **[HUMAN GATE on re-acquire]**

**Current state (live):** `/media/media/movies/Samson and Delilah (1996)/` is completely
empty (0 entries). No Radarr record. TMDB entry confirmed live: tmdb 1739328 / tt0117547
(runtime metadata sparse: 0).

**Phase 2 actions (ordered):**
1. Remove the empty folder — before → after:
   - `/media/media/movies/Samson and Delilah (1996)/` → (deleted, empty)
2. **[HUMAN GATE]** Decide whether the film is wanted. If yes:
   `POST /api/v3/movie` body:
   ```json
   {"title":"Samson and Delilah","tmdbId":1739328,"year":1996,"qualityProfileId":7,
    "rootFolderPath":"/media/media/movies","monitored":true,
    "minimumAvailability":"released","addOptions":{"searchForMovie":true}}
   ```
   (fresh folder created by Radarr as `Samson and Delilah (1996) {tmdb-1739328}` *(predicted)*).
   If no: done after step 1.

---

## Recommended execution order (Phase 2)

1. **D1 → D2 → D3 → D4** (pure identity fixes, zero file moves, no human gate)
2. **D6** steps 1–4 (one gated file move that immediately heals record 993)
3. **D5** (gated; at minimum step 2's detach can run with D1–D4)
4. **D7, D8** (corrupted-file delete + re-search; downloads then import on their own)
5. **D11** (structural split; biggest moves, still fully deterministic)
6. **D9, D12, D13** (duplicate deletions after one batched human confirmation; check D9
   against the SQ-8 manifest first)
7. **D14, D15** (residue cleanup)
8. **D10** (research task; no deadline pressure)
9. Only after 1–8: re-run `GET /rename?movieId=` for every touched record and proceed to
   SQ-25 STAGE 1 (library-wide rename preview). **SQ-25 must not start before step 1.**

## What the library looks like afterwards (net effect summary)

- 6 Radarr records carry the correct TMDB identity (419430, 79, 31996, 9314, plus D5/D6 outcomes); 0 files moved for D1–D4.
- Record 993 (*No Regret*, Riggs) gains its file; record 989 honestly reports its film missing.
- 2 corrupted files deleted and re-acquired into their unchanged folders (D7, D8).
- Joan the Maid: 1 shared folder becomes 2 canonical per-part folders, both tracked, no downloads.
- 3 duplicate folders deleted (~21.5 GB freed: Monster Mash 4.0 + First Cow 9.6 + Curious George 2.8 + samples/extras), 1 of the JOUR pair (~9.1 GB) after research.
- 2 residue folders gone (D14 after moving `Interviews/`, D15).
- All cosmetic folder/file renames (identity-tagged canonical names) remain deferred to SQ-25, which is unblocked only once D1–D6 close.

## Appendix A — Known re-acquisition records (not counted among the 15)

Pre-existing audit knowledge, unchanged by this plan; ordinary `MoviesSearch` candidates:

| id | title | tmdbId | path (all under `/media/media/movies/`) | on-disk |
|---|---|---|---|---|
| 469 | Fallen Angels (1995) | 11220 | `Fallen Angels (1998)` | trailer + extras only |
| 717 | Je Tu Il Elle (1974) | 93934 | `Je, Tu, Il, Elle (1976)` | extrathumbs only |
| 842 | Lumière & Company (1995) | 48336 | `Lumière and Company (1995)` | empty |
| 993 | No Regret (1993) | 281084 | `Non Je Ne Regrette Rien (No Regret) (1993)` | empty — **probably healed by D6 instead** |
| 2030 | Room 666 (1985) | 118257 | `Room 666 (1982)` | empty |
| 1802 | The Berlin Wall: Escape to Freedom (2006) | 211683 | `WALL-E (2008)` | extras only (2026-07-30 remediation residue; real *WALL·E* is fine at id 1803) |

## Appendix B — Live rename previews (verbatim, `GET /api/v3/rename?movieId=`)

Snapshot 2026-08-04. `existingPath`/`newPath` are relative to each movie folder.

```
movieId=539  : Get Out (2016).mkv -> Get Out Alive (2016) {tmdb-414530} [WEBDL-2160p][HDR10][DTS-X 7.1][h265].mkv   (WRONG identity — blocked by D1)
movieId=2421 : Hero.2002.CHINESE.DC.1080p.BluRay.DDP5.1.x265.10bit-LAMA.mkv -> Hero (2007) {tmdb-51550} [Bluray-1080p][EAC3 5.1][x265]-LAMA.mkv   (WRONG — blocked by D2)
movieId=1895 : Bluebeard's 8th Wife (1938).mkv -> Bluebeards 8th Wife (1923) {tmdb-535525} [WEBDL-1080p][PCM 1.0][h264].mkv   (WRONG — blocked by D3)
movieId=1490 : The House, 1984 (1984).mkv -> The House (1984) {tmdb-628603} [WEBDL-1080p][PCM 1.0][h264].mkv   (WRONG — blocked by D4)
movieId=1398 : The Creatures (1966).mkv -> Terror-Creatures from the Grave (1965) {tmdb-63507} [WEBDL-1080p][PCM 1.0][h264].mkv   (WRONG — blocked by D5)
movieId=989  : No Regret (1993).mkv -> No Regret No Return (1993) {tmdb-261238} [WEBDL-1080p][PCM 2.0][h264].mkv   (WRONG — blocked by D6)
movieId=1000 : O.Saisons.O.Chateaux.1958.1080p.BluRay.x264-BiPOLAR.mkv -> O Seasons O Castles (1958) {tmdb-278727} [Bluray-1080p]-BiPOLAR.mkv   (moot — file corrupted, D7 deletes it)
movieId=490  : Fellini.s.Satyricon.1969.MULTi.1080p.BluRay.x264-CherryCoke.mkv -> Satyricon (1969) {tmdb-11163} [MULTi][Bluray-1080p]-CherryCoke.mkv   (moot — D8)
movieId=357  : Curious George 2 - Follow That Monkey! (2009).mkv -> Curious George 2 Follow That Monkey! (2009) {tmdb-23903} [WEBDL-1080p][EAC3 5.1][h264].mkv   (correct identity — SQ-25 scope)
movieId=501  : First Cow (2019).mkv -> First Cow (2020) {tmdb-558582} [WEBDL-2160p][HDR10][AC3 5.1][h265].mkv   (correct identity — SQ-25 scope)
movieId=870  : (no pending rename — M*A*S*H file already canonical)
movieId=2488 : (no pending rename — Secrets & Lies file already canonical)
```

## Provenance / zero-write attestation

Data sources, all read-only:
- Radarr GETs: `/system/status`, `/movie` (full dump), `/rootfolder`, `/qualityprofile`,
  `/config/naming`, `/rename?movieId=` ×12, `/movie/lookup/tmdb?tmdbId=` ×5,
  `/movie/lookup?term=Joan the Maid`. No POST/PUT/DELETE was issued.
- Disk listings: `ls` via the `tdarr` pod on `/media/media/movies` (same physical library).
- API key read from the radarr pod's `/config/config.xml` (`-c radarr`; exportarr sidecar
  is distroless).
