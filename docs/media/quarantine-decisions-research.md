# Quarantine decisions research — the 7 gated items (2026-08-04)

Research pass over the seven `[HUMAN GATE]` items in `docs/media/remediation-plan-2026-08-04.md`
(D5, D6, D9, D10, D12, D13, D15), which trace back to `docs/media/movie-identity-verdicts-2026-08-04.md`.
Purpose: give whoever throws the gate the evidence and options, not a decision. **Zero writes.**

**Methodology.** Radarr `192.168.10.210:7878/api/v3` — GET only (`/movie/{id}`, `/movie/lookup`,
`/movie/lookup/tmdb`), no POST/PUT/DELETE. Disk reads via the `tdarr` pod (`ls`, `md5sum` — a
read, not a write). Deep `ffprobe -v quiet -print_format json -show_format -show_streams
-show_chapters` on every feature file in scope, beyond the shallow `-show_format -show_streams`
pass the verdicts doc used — this surfaces chapter titles, per-stream audio/subtitle languages,
all format tags (not just `title`), and video transfer characteristics (field order, pix_fmt,
color space). Two supplementary web searches for D5/D6/D10 provenance (Criterion box-set disc
contents, CFE ethnographic-film naming). No file was moved, renamed, or deleted; no Radarr record
was mutated. SQ-27 is concurrently mutating Radarr ids 539/2421/1895/1490/1905 — none of those
overlap this ticket's scope (1398, 989/993, 870, and five orphan folders with no Radarr record).

---

## D5 — `The Creatures (1966)` — mispull, identity unknown

**Radarr (live, GET /movie/1398):** record 1398, tmdb 63507 (*Terror-Creatures from the Grave*,
1965, Italian), profile 13, `monitored:false`, path `/media/media/movies/The Creatures (1966)`,
movieFileId 1373, size 18,296,773,522 bytes (18.30 GB). MediaInfo already on record: audio "fra",
1ch, PCM.

**Deep ffprobe — new findings not in the shallow pass:**
- **Format title tag: `"5. MARRIED LIFE"`** (confirmed, same as verdicts doc).
- **Audio stream language tag: `fra` (French), mono, `title: "Mono"`.** The video stream's own
  `language` tag reads `eng` (an artifact of how MakeMKV stamps the primary video track — not
  meaningful) but the **audio track people would actually hear is French**. *Terror-Creatures
  from the Grave* is an Italian/English co-production; a French-only mono track is inconsistent
  with it and consistent with a French film.
- **Chapters: 15, generically titled `Chapter 01`-`Chapter 15`** — no chapter-level titles, so
  chapters add nothing to identity beyond confirming a normal single-feature disc structure (not
  an anthology disc with per-title chapter markers).
- **All format tags:** `title`, `encoder: "libmakemkv v1.16.5 (1.3.10/1.5.2) darwin(arm64-release)"`,
  `creation_time: 2021-11-10T05:07:12Z`. No `comment`/`description`/`album`/`artist` — this is a
  clean MakeMKV remux (household disc rip), not a scene release with embedded metadata.
- **Video:** h264, 1920x1080, `field_order: progressive`, 23.976fps — a film-sourced transfer,
  consistent with a 1960s European theatrical feature (rules out a video-shot source).
- **Subtitles:** 1 PGS track, English, no forced/SDH flag.
- **Attachment:** 1 embedded `mjpeg` cover image (`cover.jpg`) — routine MakeMKV disc-cover
  capture, not identity evidence.
- **Folder context (disk `ls`, not previously checked):** `Featurettes/` holds
  `"Les Crèatures Introduction from 2012-featurette.mkv"` (248 MB) and
  `"Varda on Set-featurette.mkv"` (1.7 GB), both dated the same rip session (Nov 10 2021).
  These are bonus features **specifically for Agnès Varda's *Les Créatures*** — not generic
  filler, not present by coincidence.

**Web research — what "5. MARRIED LIFE" actually is:** Criterion's 2020 box set *The Complete
Films of Agnès Varda* groups its 39 films across 15 themed discs; one search result states the
disc titled **"Married Life" contains three films: *Le Bonheur* (1965), *Les Créatures* (1966),
and *Elsa la Rose* (1966)**. `"5. MARRIED LIFE"` is very plausibly that disc's own embedded
title (disc 5 of the set), not a chapter/segment label internal to a single film — MakeMKV often
inherits the disc-level title as the format `title` tag when a rip doesn't override it. TMDB
confirms: `The Creatures` / *Les Créatures* (1966), **tmdb=53026, imdb=tt0060263, runtime 94
min** — measured 94.28 min (1:34:17) is a near-exact match (+0.3%), a dramatically tighter fit
than Terror-Creatures from the Grave's TMDB runtime of 85 (measured delta was +9.3 min, already
flagged as suspicious in the verdicts doc).

**Convergent evidence for Les Créatures (tmdb 53026), not Terror-Creatures from the Grave
(tmdb 63507) and not an unknown film:**
1. Disc-title metadata matches Criterion's own "Married Life" disc name for the Varda box set.
2. Folder-adjacent bonus featurettes are Les Créatures-specific (Introduction 2012, Varda on Set).
3. Audio track is French — Varda's film is French-language; Terror-Creatures is Italian/English.
4. Measured runtime 94.28 min vs TMDB Les Créatures 94 min — near-exact; vs Terror-Creatures 85
   min the delta is +9.3 min, already a red flag in the original audit.
5. Progressive 23.976fps film transfer, consistent with a 1966 theatrical feature.

**Does this change the recommendation?** Yes, substantially. The remediation plan treated D5 as
"identity unknown, needs a human to watch a sample." The deeper probe plus the disc-title lookup
converges on a specific, checkable identity (tmdb 53026) with only routine confirmation left —
this is no longer a blind-viewing task.

**Options:**
1. **(Recommended)** Treat as identified: re-add with tmdb 53026 (*The Creatures* / *Les
   Créatures*, 1966) using the same zero-move re-add pattern as D1-D4 (`DELETE
   /movie/1398?deleteFiles=false` -> `POST /movie` with `tmdbId:53026`, same `path` -> `RescanMovie`).
   A human should still open the file for ~30 seconds to visually confirm (Varda's film is in
   French, black-and-white/color mix, has a distinctive island setting) before executing - cheap
   insurance given the file will get a "final" identity-tagged filename at SQ-25.
2. Treat the evidence as sufficient without a viewing spot-check and proceed directly to the
   re-add in option 1 - faster, marginally more risk if the disc-title inference is wrong.
3. If a human viewing disconfirms Les Créatures, fall back to the original D5 branch (quarantine
   to `.quarantine/The Creatures (1966)/` or identify some other film) - treat this as the
   low-probability branch given the convergent evidence above, not the default path.

---

## D6 — `No Regret (1993)`: file probably belongs to record 993

**Radarr (live):** record 989, tmdb 261238 (*No Regret, No Return*, 1993, Korean, expected 94
min), profile 13, path `/media/media/movies/No Regret (1993)`, movieFileId 975, size
7,842,118,912 bytes (7.84 GB). Record 993, tmdb 281084 (*No Regret*, Marlon Riggs, expected 38
min), profile 7, path `.../Non Je Ne Regrette Rien (No Regret) (1993)`, `hasFile:false`, folder
empty on disk (both confirmed live, unchanged from the plan doc).

**Deep ffprobe — new findings:**
- **Format title tag:** `"THE SIGNIFYIN' WORKS OF MARLON RIGGS - DISC 2"` (confirmed).
- **Audio: English, stereo PCM** — consistent with an American documentary, inconsistent with
  the matched Korean action film (which would be Cantonese/Mandarin audio).
- **Video: h264 1920x1080, `field_order: "tt"` (top-field-first, interlaced), 29.97fps.** This
  is the single strongest new signal: an **interlaced NTSC 29.97i transfer** is a broadcast/
  video-sourced fingerprint, exactly what's expected from a 1990s American documentary
  originated on video, and is inconsistent with a 35mm Korean theatrical feature (which would be
  a progressive 23.976fps film transfer, as seen on essentially every other film-sourced item in
  this library, e.g. D5 above).
- **Chapters: none (empty list).** No internal chapter markers exist to show whether the disc's
  "DISC 2" content beyond No Regret leaked into this rip.
- **All format tags:** `title`, `encoder: "libmakemkv v1.16.5..."`, `creation_time:
  2022-01-10T04:19:11Z`. No other descriptive tags.
- **Subtitles:** 1 PGS track, English.
- **Attachment:** 1 embedded `mjpeg` cover image, routine.

**Web research — what's actually on "Disc 2":** Criterion's *The Signifyin' Works of Marlon
Riggs* box set's disc 2 contains **three works**: *Color Adjustment* (1992, ~88 min), *Non, je ne
regrette rien (No Regret)* (1993, ~38 min), and *Black Is...Black Ain't* (1995, ~87 min) —
combined disc runtime would be well over 200 minutes. The ripped file here is **38:13**, matching
only the No Regret segment (TMDB runtime 38 min, delta +0.2 min — near-exact), not a combined
multi-title rip. This directly answers the plan doc's own step-1 gate question ("verify it
contains only No Regret, not several shorts") in the affirmative: the duration proves a
single-title extraction, not the full disc.

**Does this change the recommendation?** Sharpens it from "probable" to high confidence. Every
new signal (interlaced NTSC video, English audio, single-title-length duration matching only the
No Regret segment of a known multi-film disc) independently supports the plan doc's hypothesis
and directly answers its own verification gate.

**Options:**
1. **(Recommended)** Proceed with the plan doc's D6 sequence: move
   `No Regret (1993)/No Regret (1993).mkv` -> `Non Je Ne Regrette Rien (No Regret) (1993)/`,
   `RescanMovie` on 993 (gains file) and 989 (drops to `hasFile:false`), then decide whether to
   re-search *No Regret, No Return* (tmdb 261238) for record 989 or leave it unmonitored.
2. Still gate on a human spot-check before moving the file (open ~1 minute, confirm it's Riggs'
   poetic first-person documentary about being Black, gay, and HIV-positive, not a Korean
   action film) — marginal extra safety for a near-zero-risk move since `deleteFiles` is never
   invoked either way.
3. If a spot-check disconfirms: fall back to quarantine (`.quarantine/No Regret (1993)/...`) as
   the plan doc's step 7 already specifies — treat as the low-probability branch.

---

## D9 — `Monster Mash (1970)`: duplicate copy of M*A*S*H — the deep probe changes this one

**Current state (live disk `ls`):** orphan folder `/media/media/movies/Monster Mash (1970)/`
holds `Monster Mash (1970).mkv` (4,025,467,683 bytes / 4.03 GB) plus `MASH (1970).nfo`,
`M-A-S-H (1970).txt`, a sample and a trailer. Radarr tracks M*A*S*H separately: record 870,
tmdb 651, path `/media/media/movies/MASH (1970)/`, file
`M-A-S-H (1970) {tmdb-651} [DSNP][WEBDL-1080p][EAC3 5.1][h264]-GPRS.mkv` (7,200,489,310 bytes /
7.20 GB), confirmed live via `GET /movie/870`.

**Deep ffprobe comparison (full stream fingerprint, both files):**

| | Orphan `Monster Mash (1970).mkv` | Tracked `M-A-S-H ... -GPRS.mkv` |
|---|---|---|
| Duration | 6955.051 s (1:55:55) | 6950.944 s (1:55:51) — 4.1s apart |
| Size | 4.03 GB | 7.20 GB |
| Video codec | HEVC, Main 10 (10-bit), 1920x816 | h264 (8-bit), 1920x1080 |
| Audio | EAC3 5.1 "Dolby Digital Plus 5.1" + AAC 2.0 "Commentary with Robert Altman" | EAC3 5.1 only |
| Subtitles | PGS (eng, "PGS") + SRT (eng, "SRT") | SRT (eng, "SDH") only |
| Chapters | 40, titled `Chapter 1`-`40` | 0 |
| Format tags | Full metadata block: `TITLE`, `ARTIST` (full cast), `DIRECTOR: Robert Altman`, `PRODUCER`, `SCREENPLAY_BY`, `GENRE`, `SYNOPSIS`, `LAW_RATING`, `ENCODED_BY: Sartre` | `encoder` only (mkvmerge), no descriptive tags |
| Mux tool | `libebml v1.3.4 + libmatroska v1.4.5` (2017-06-22) | `libebml v1.4.5 + libmatroska v1.7.1` (source: Disney+ WEB-DL, muxed by mkvmerge v82) |

The two files agree on runtime (within 4 seconds, i.e. same cut of the film) but **diverge hard**
on codec, bitrate, resolution/crop, mux tooling, and — most importantly — **bonus content**: the
orphan carries a Robert Altman audio commentary track and 40 chapter markers; the tracked WEBDL
copy has neither. Per the standing guardrail (a genuinely different version must not be deleted
or consolidated as a "duplicate," only a truly redundant copy may go), **this is not a redundant
duplicate** — it is a Blu-ray-sourced encode with extras the currently-tracked streaming rip
lacks entirely.

**Does this change the recommendation?** Yes — this is the one item where the deeper probe
overturns rather than sharpens the plan doc's framing. The plan doc's D9 gate asked only
"confirm keeping the 7.2 GB tracked WEBDL, delete the orphan" (justified there as "newer, larger,
properly tagged"). The stream-level comparison shows the orphan is the one with the commentary
track and chapter navigation; "larger" reflected h264-vs-HEVC bitrate inefficiency, not more
content. Deleting the orphan under the original framing would destroy the only copy with the
Altman commentary.

**Evidence gap:** the plan doc's own D9 step 1 says to "cross-check the 4.0 GB rip against the
SQ-8 household disc-rip preservation manifest" before any deletion. No such manifest exists
under `docs/` in this repo (searched); it may live only in the SQ-8 ticket/board record, which
this GET-only, Radarr/tdarr-scoped research pass has no visibility into. That check is still
outstanding regardless of which option below is chosen.

> **RESOLVED 2026-08-06 — the gate is now clearable, and it confirms option 1.**
>
> The manifest did not exist anywhere, not just under `docs/`. The SQ-8 board record is a
> title and nothing else: no body, no description, no comments. Its claim of a "manifest
> complete (5,117 files)" was never persisted. It has now been built for real -
> `docs/media/preservation-manifest.md`, generated by
> `tools/media/build_preservation_manifest.py` from a library-wide `ffprobe` census.
>
> Running D9 against it **inverts the original framing**, independently of the commentary-track
> finding above:
>
> | File | Verdict | Why |
> |---|---|---|
> | tracked `M-A-S-H (1970) … [DSNP][WEBDL-1080p]…-GPRS.mkv` (7.20 GB) | `REPLACEABLE` | A Disney+ WEB-DL cannot be a rip of a disc anyone owns. Re-acquirable by definition. |
> | orphan `Monster Mash (1970).mkv` (4.03 GB) | `REVIEW` | No container title, no source token, no release group. Nothing establishes it can be re-obtained. |
>
> So the copy the plan proposed **deleting** is the one that cannot be replaced, and the copy it
> proposed **keeping** is the one that can. Option 1 was already recommended on commentary-track
> grounds; the manifest reaches the same place on replaceability grounds, which is a stronger
> argument because it does not depend on judging whether the commentary is wanted.

**Options:**
1. **(Recommended)** Do not delete either copy outright. Re-point Radarr's tracked file at the
   orphan's Blu-ray/commentary encode instead of the WEBDL (manual import of the 4.03 GB HEVC
   file onto record 870, replacing movieFileId — a Radarr-mediated file swap, not a raw
   filesystem delete), then remove the now-superseded WEBDL copy. Net effect: one tracked file,
   the better one, extras preserved. Still needs the SQ-8 manifest cross-check per the plan doc's
   own gate before anything is deleted.
2. Keep both: leave the WEBDL as Radarr's tracked file (no disruption to profile/quality-cutoff
   logic) but relocate the orphan's Blu-ray rip into the M*A*S*H folder as a manually-managed
   extra (e.g. `Featurettes/` or an edition-tagged second file) rather than deleting it — avoids
   a Radarr re-import but preserves the commentary track.
3. Revert to the plan doc's original framing (keep tracked WEBDL, delete orphan) only if a human
   determines the commentary/chapters aren't wanted and the SQ-8 manifest check clears the
   orphan as non-preservation-worthy — the least-recommended option given what the probe found.

---

## D10 — `JOUR DE FÊTE DANS LES MONTS NAGA (1964)` + `(1995)`: duplicate pair

**Current state (live disk `ls`):** two orphan folders, no Radarr records for either year, no
TMDB match for either (re-confirmed: no useful hit from `movie/lookup?term=` style web search
either — see below).
- `(1964)/JOUR DE FÊTE DANS LES MONTS NAGA (1964).mkv` — 9,148,026,450 bytes (9.148 GB)
- `(1995)/JOUR DE FÊTE DANS LES MONTS NAGA (1995).mkv` — 9,159,735,511 bytes (9.160 GB)
- Sizes differ by 11,709,061 bytes (+0.128%) — **not byte-identical**, so no MD5 was run (a
  checksum on non-equal-size files is guaranteed to differ and would burn ~10 min of pod I/O for
  no new information; size alone already rules out "identical file copied twice").

**Deep ffprobe comparison:**

| | `(1964).mkv` | `(1995).mkv` |
|---|---|---|
| Duration | 4831.868 s (1:20:32) | 4815.268 s (1:20:15) — 16.6s / 0.34% shorter |
| Video | h264, 1920x1080, 23.976fps | h264, 1920x1080, 23.976fps — identical config |
| Audio | AC3, 1ch (mono), French (`fra`) | AC3, 1ch (mono), French (`fra`) — identical config |
| Subtitles | 1 PGS, English | 1 PGS, English — identical config |
| Chapters | 11, generic `Chapter 01`-`11` | 11, generic `Chapter 01`-`11` — same count |
| Chapter boundary offsets | e.g. ch1 ends 464.09s, ch9 ends 4218.42s | e.g. ch1 ends 485.28s, ch9 ends 4177.17s — each boundary shifted by tens of seconds, proportionally consistent across all 11 chapters |
| Format title | `"JOUR DE FÊTE"` | `"JOUR DE FÊTE"` — identical |
| Rip timestamp | 2021-12-02T17:02:44Z | 2021-12-02T17:10:38Z — **8 minutes apart, same session** |
| Encoder | `libmakemkv v1.16.5...` | `libmakemkv v1.16.5...` — identical tool/version |

Both files were ripped back-to-back in the same MakeMKV session (8 minutes apart) with identical
audio/video/subtitle/chapter-count configuration and a proportionally-consistent (not random)
0.34% duration offset across all 11 chapter boundaries. This pattern — same title tag, same
technical fingerprint, same session, small but structured (not chapter-count-different) duration
delta — is much more consistent with **two rips of two physical discs carrying the same content**
(e.g. two pressings, or a disc ripped twice as a backup/verification pass) than with two distinct
works that happen to share a title. A genuinely different film would be far more likely to show a
different chapter count, different audio channel layout, or a materially different runtime, not a
uniform sub-1% offset across every chapter mark.

**NFO metadata is not usable evidence:** both folders' `.nfo` files were scraped by
tinyMediaManager to **Jacques Tati's unrelated 1949 comedy *Jour de Fête*** (tmdb 4595) — a pure
title-fuzzy-match error (scraped 2023-07-24 and 2023-07-26, two days apart), which also explains
why both folders carry byte-identical placeholder artwork. This confirms the plan doc's "no TMDB
match" finding but adds that the folders' own metadata is actively wrong and should not be relied
on by any future automated matching pass.

**Web research:** no source was found identifying "Jour de Fête dans les Monts Naga" by title
(checked general web search and the Comité du Film Ethnographique / CNRS ethnographic-film
context, which is a plausible fit for a French-titled documentary about a festival day in the
Naga hills of northeast India). The title remains genuinely unidentified via this pass.

**Does this change the recommendation?** Sharpens it. The plan doc already flagged this as a
"suspected duplicate," but "identical embedded title, near-identical runtime" alone doesn't rule
out two different cuts. The full stream/chapter fingerprint (same channel layout, same subtitle
config, same chapter count with proportional offsets, same rip session) is materially stronger
duplicate evidence, closer to the "two different encodes of the same content" pattern than to
"two different films."

**Options:**
1. **(Recommended)** Treat as a near-certain duplicate pair from the same underlying content;
   before deleting either, note the size and runtime signals actually disagree on which copy is
   "better" — `(1995)` is 11.7 MB larger while `(1964)` is 16.6s longer — which argues against a
   blind pick and for option 2 below.
2. Before deleting either, do a **read-only content check** (permitted under this ticket's
   evidence-gathering scope, not yet performed): pull a few matching-timestamp frame hashes or a
   short `ffmpeg -ss <t> -i <file> -frames:v 1` still-frame comparison between the two files at
   corresponding chapter marks, to see whether the 0.34% offset is a trimmed intro/outro (same
   footage, different edit boundary) or a genuine content divergence. This is the step the plan
   doc's own D10 action 1 calls for and it has not yet been done. In parallel, research the title
   itself (Comité du Film Ethnographique catalog, `film-documentaire.fr`, CNRS ethnographic film
   archive) to see whether "1964" and "1995" are both legitimate release/restoration years for
   the same underlying film — which would explain a title match with a small runtime delta
   without implying a wasteful duplicate rip.
3. Keep both indefinitely (no deletion) until the content-check in option 2 resolves — the safe
   default if nobody has bandwidth for the frame comparison soon; costs ~9.1 GB of shelf space,
   which the plan doc itself flags as "no deadline pressure."

---

## D12 — `First Cow (2020)`: orphan duplicate of the tracked copy

**Radarr (live, from the plan doc, re-confirmed via disk `ls`):** record 501 tracks
`First Cow (2019)/First Cow (2019).mkv`, 22,850,753,559 bytes (22.85 GB). Orphan
`First Cow (2020)/First Cow (2020).mkv`, 9,621,552,866 bytes (9.62 GB).

**Deep ffprobe comparison:**

| | Tracked `(2019)` (22.85 GB) | Orphan `(2020)` (9.62 GB) |
|---|---|---|
| Duration | 7306.752 s (2:01:47) | 7308.352 s (2:01:48) — 1.6s apart, i.e. same cut |
| Video | HEVC, 2876x2152, `bt2020nc` (HDR10-class color) | h264, 1440x1080 (non-standard reduced-width encode), `bt709` (SDR) |
| Audio | AC3 5.1, English | DTS 5.1, English (`title: "English"`) |
| Subtitles | 1 SRT, English (SDH) | 2 tracks: PGS English + PGS Spanish |
| Chapters | 0 | 16 |
| Format title | none | `"First Cow"` |
| Bitrate | ~25.0 Mbps | ~10.5 Mbps |

Runtime agrees to within 1.6 seconds (0.02%) — this is the coordinator's textbook "same film,
two encodes" signature: identical cut, wildly different bitrate/codec/resolution. This confirms
the plan doc's "same film, two encodes" framing rather than overturning it. However, the orphan
is not strictly inferior in every dimension: it carries a Spanish subtitle track and 16 chapter
markers that the tracked 2160p HDR copy lacks entirely.

**Does this change the recommendation?** Sharpens it with one addition: before deleting the
orphan, salvage the Spanish subtitle track (and optionally the chapter markers) onto the tracked
copy, since those aren't present anywhere else in the library for this title.

**Options:**
1. **(Recommended)** Keep the tracked 2160p HDR copy (unambiguously the better transfer: higher
   resolution, HDR10 color, 2.4x the bitrate). Before deleting the orphan, extract its embedded
   Spanish PGS subtitle track (a read/extract operation on the orphan, not a mutation of the
   tracked file) and place it alongside the tracked file as an external sidecar, or import it
   into the tracked mkv — then delete the orphan folder per the plan doc.
2. Delete the orphan as-is per the original plan doc, accepting the loss of the Spanish subtitle
   track and chapter markers — simplest, but discards content not replicated elsewhere.
3. Keep both (no deletion) if the ~9.6 GB is not a storage concern and the Spanish-subtitle
   salvage in option 1 isn't worth the effort — least likely to be worth it given 66.3 TB free on
   the root folder per the plan doc's live snapshot.

---

## D13 — `Curious George 2 Follow That Monkey! (2009)`: byte-identical duplicate

**Radarr (live):** record 357 tracks
`Curious George 2 - Follow That Monkey! (2009)/Curious George 2 - Follow That Monkey!
(2009).mkv` (with dash). Orphan folder (same title, no dash):
`Curious George 2 Follow That Monkey! (2009)/Curious George 2 Follow That Monkey! (2009).mkv`.

**Checksum comparison (definitive — the strongest evidence tier the ticket contract asks for):**

| | Tracked (with dash) | Orphan (no dash) |
|---|---|---|
| Size | 2,790,271,434 bytes | 2,790,271,434 bytes — identical |
| mtime | Nov 4 2017 | Nov 4 2017 — identical |
| MD5 | `99e73bb19569bafab40b08b880f9e217` | `99e73bb19569bafab40b08b880f9e217` — identical |

Both files hash to the same MD5 (`md5sum` run via the `tdarr` pod, read-only). This is not a
"probable" or "same content, different encode" duplicate — it is a byte-for-byte identical file
under two different folder names. No stream-level comparison is needed beyond this; identical
bytes trivially imply identical every ffprobe field.

**Does this change the recommendation?** No — it confirms the plan doc's D13 framing exactly
("byte-identical duplicate") and upgrades the evidence from "same size + same mtime" (already
strong) to a cryptographic hash match (conclusive). This is the one item in the set of seven with
no remaining uncertainty.

**Options:**
1. **(Recommended, formality only)** Proceed with the plan doc's D13 action: delete the dashless
   orphan folder. No further evidence-gathering is useful here.
2. N/A — there is no plausible alternative reading of an MD5-identical file pair; a second option
   would only be "keep both copies of literally the same bytes," which has no benefit.

---

## D15 — `Samson and Delilah (1996)`: empty folder remnant

**Current state (live disk `ls`):** `/media/media/movies/Samson and Delilah (1996)/` — 0 entries,
completely empty, confirmed unchanged from the plan doc. No Radarr record.

**TMDB lookup (live, `GET /movie/lookup/tmdb?tmdbId=1739328`) — new detail not in the plan doc:**
title "Samson and Delilah" (1996), **studio: "Best Hollywood"**, alternate title **"Sámson és
Delila"** (Hungarian), **runtime: 0** (TMDB has no runtime data at all for this entry), overview
empty, `tmdb.votes: 0`. "Best Hollywood" is a Hungarian production house associated with
low-budget, direct-to-video genre/biblical films — this is very likely a minor/hard-to-source TV
movie rather than a notable theatrical release. This is useful context specifically for the "is
it worth re-acquiring" branch of the plan doc's D15 gate: TMDB's own near-total lack of metadata
(zero runtime, zero votes, empty overview) for tmdb 1739328 is itself a signal this title may be
difficult to source and low household priority, distinct from e.g. the well-known 1949 DeMille or
2009 Warwick Thornton films that share the "Samson and Delilah" title.

**Does this change the recommendation?** Adds a data point relevant to the re-acquisition branch
only; the folder-removal branch (step 1 of the plan doc's D15) is unaffected and remains a pure
filesystem cleanup with no ambiguity.

**Options:**
1. **(Recommended)** Remove the empty folder now (zero risk, no Radarr record involved) — this
   part of the plan doc's D15 has no open question. Defer the re-acquisition decision separately.
2. On re-acquisition: given the sparse/dubious TMDB entry (0 runtime, "Best Hollywood" studio,
   Hungarian alt-title), do **not** default to `MoviesSearch` on tmdb 1739328 without confirming
   this is actually the title the household wants — verify against a definitive source (IMDb
   `tt0117547` cross-reference) that this is the intended 1996 film before adding, since the
   generic title collides with several unrelated "Samson and Delilah" productions.
3. Skip re-acquisition entirely (unmonitor / leave out of the library) given the low-confidence
   metadata — reasonable if nobody specifically remembers wanting this exact 1996 title.

---

## Summary table

| # | Item | Identity/duplicate confidence after deep probe | Recommendation |
|---|---|---|---|
| D5 | The Creatures (1966) | High — converges on Les Créatures (tmdb 53026) via disc-title + featurette + audio-language + runtime evidence | Re-add as tmdb 53026 (light spot-check optional) |
| D6 | No Regret (1993) | High — interlaced NTSC + English audio + single-title-length duration all corroborate Riggs' *No Regret* | Proceed with the file move to record 993 |
| D9 | Monster Mash (1970) | High duplicate-of-M*A*S*H confidence, but not a redundant duplicate — different edition with commentary/chapters | Do not delete outright; re-point Radarr at the better (orphan) encode, pending SQ-8 manifest check |
| D10 | JOUR DE FÊTE pair | Moderate-high duplicate-pattern evidence (same session, matching fingerprint, proportional chapter offset); title itself still unidentified | Keep both pending a frame-level content check; research the title separately |
| D12 | First Cow (2020) | High — confirmed same-cut, different-encode duplicate | Keep 2160p HDR copy; salvage Spanish subtitle before deleting orphan |
| D13 | Curious George 2 (dashless) | Conclusive — MD5-identical | Delete orphan, no further research needed |
| D15 | Samson and Delilah (1996) | N/A (empty folder) | Remove folder now; treat re-acquisition as a separate, lower-confidence decision |

## Provenance / zero-write attestation

- Radarr: `GET /system/status`, `GET /movie/{id}` x6 (1398, 989, 993, 870, 501, 357),
  `GET /movie/lookup/tmdb?tmdbId=` x2 (53026, 1739328), `GET /movie/lookup?term=` x1. No
  POST/PUT/DELETE issued.
- Disk: `ls -la` via the `tdarr` pod on the folders in scope; `ffprobe -show_format -show_streams
  -show_chapters` on every feature file in scope (The Creatures, No Regret, Monster Mash, tracked
  M*A*S*H, both JOUR DE FÊTE files, both First Cow files); `md5sum` on both Curious George 2
  files (the only pair where byte-identity was a live question and file sizes already matched).
  No file was moved, renamed, or deleted; no directory was created.
- API key read from the radarr pod's `/config/config.xml` (`-c radarr`), same method as prior
  SQ-20 artifacts.
- Web search: Criterion Varda box-set disc contents, Criterion Marlon Riggs box-set disc 2
  contents, and Comité du Film Ethnographique / Naga-hills context (no result for the JOUR DE
  FÊTE title itself).

---

## Operator decisions — 2026-08-04

Recorded after reading the research above. All four questions put to the operator were
answered with the recommended option.

| item | decision | status |
|---|---|---|
| **D5** `The Creatures (1966)` | Identified as Varda's *Les Créatures* (tmdb 53026). Re-add via the D1–D4 zero-move pattern. **Spot-check first.** | BLOCKED on viewing |
| **D6** `No Regret (1993)` | Move the file to `Non Je Ne Regrette Rien (No Regret) (1993)/`, rescan 993 and 989. **Spot-check first.** | BLOCKED on viewing |
| **D9** `Monster Mash` / M\*A\*S\*H | **Swap to the Blu-ray.** Manual-import the 4.03 GB Blu-ray/commentary encode onto record 870 replacing the WEBDL, then remove the superseded WEBDL. SQ-8 preservation-manifest check runs before any delete. | READY |
| **D10** `JOUR DE FÊTE` pair | **CORRECTED — two different CUTS, not duplicates.** Neither is deleted. Consolidate into one folder with `{edition-}` tags per SQ-26. See the correction section below. | KEEP BOTH |
| **D12** `First Cow (2020)` | **Salvage then delete.** Extract the Spanish PGS track from the orphan to a sidecar beside the tracked 2160p file, then delete the orphan folder (~9.6 GB). | READY |
| **D13** `Curious George 2` | Delete the dashless orphan. MD5-identical; formality. | READY |
| **D15** `Samson and Delilah (1996)` | **Remove the empty folder. Skip re-acquisition** — metadata is low-confidence and nobody specifically wants this title. | READY |

### What the operator needs to spot-check (D5, D6)

Two files, roughly a minute total. Both identifications are strong but inferential, and both
write a permanent identity into a filename at SQ-25, so the check is cheap insurance —
today already demonstrated that confident inference from metadata can point the wrong way.

- `/media/media/movies/The Creatures (1966)/…` — expect **Agnès Varda's *Les Créatures***
  (1966): French dialogue, island setting, Catherine Deneuve and Michel Piccoli, a
  colour/black-and-white mix. If it is instead an Italian gothic horror, it is
  *Terror-Creatures from the Grave* and the original Radarr record was right.
- `/media/media/movies/No Regret (1993)/No Regret (1993).mkv` — expect **Marlon Riggs'
  *No Regret*** (1993): a 38-minute poetic first-person documentary with five Black gay men
  living with HIV. If it is a Korean action film, it is *No Regret, No Return* and record
  989 was correct.

### Note on how the framing changed

This was originally scoped as "quarantine all seven, then decide." The research dissolved
most of that: D5 is a record correction rather than a mispull, D9/D12/D13 are swaps or
deletions with known keepers, and D15 is an empty directory. **Only D10 remains genuinely
unidentified**, and it is the one item where parking the content is the right move.

The deeper `ffprobe` pass (chapters, per-stream languages, all format tags) is what changed
D5, D9 and D12. Two of those three would otherwise have destroyed content: the M\*A\*S\*H
"duplicate" carries a commentary track the keeper lacks, and the First Cow "duplicate"
carries a Spanish subtitle track the keeper lacks. Both were queued for plain deletion.

---

## CORRECTION — D10 is NOT a duplicate pair. It is two different cuts.

**Raised by the operator, confirmed by measurement 2026-08-04.** The D10 analysis above is
wrong and its recommendation is withdrawn. Deleting either copy would have destroyed a
version, in direct violation of the standing library guardrail.

### The error

The analysis compared **total runtimes** (16.6 s / 0.34% apart) and **technical
configuration** (identical codec, channel layout, subtitle config, chapter count, rip
session) and concluded "two encodes of the same content." It also described the chapter
boundary offsets as "proportionally consistent across all 11 chapters." They are not — the
two boundaries it quoted already diverge in **opposite directions** (ch1: 1995 later by
21.2 s; ch9: 1995 earlier by 41.3 s), which the write-up did not reconcile.

### The measurement that settles it — per-chapter LENGTHS, not boundaries

| ch | length 1964 | length 1995 | delta |
|---|---|---|---|
| 1 | 464.09 | 485.28 | **+21.19** |
| 2 | 654.11 | 617.74 | **−36.37** |
| 3 | 406.70 | 407.24 | +0.54 |
| 4 | 693.57 | 645.56 | **−48.01** |
| 5 | 201.78 | 214.51 | +12.72 |
| 6 | 371.83 | 377.21 | +5.38 |
| 7 | 404.11 | 408.41 | +4.30 |
| 8 | 378.59 | 367.08 | −11.51 |
| 9 | 643.64 | 654.15 | +10.51 |
| 10 | 364.82 | 364.95 | +0.13 |
| 11 | 248.62 | 273.15 | **+24.52** |

Boundary deltas span **−62.6 s to +21.2 s with a sign change**. Aggregate absolute
difference is **~175 s — nearly three minutes of differing content** — netting to 16.6 s
only because gains and losses cancel.

Chapter 4 is 48 s shorter in the 1995 version; chapter 1 is 21 s longer. **No re-rip of one
disc redistributes content between chapters.** This is one work in two edits.

The identical technical fingerprint and shared rip session are consistent with this, not
against it: two titles pulled off the same physical disc 8 minutes apart — plausibly an
original and a later restoration, which is precisely what folders labelled 1964 and 1995
assert.

### Revised disposition

**Neither copy is deleted.** Per the guardrail carried from the 2026-07-30 version work:
multiple editions are intentional and must stay independently selectable; only a *redundant
duplicate* may be removed, never a *version*.

Correct treatment is the additive one from SQ-26: consolidate both into **one movie folder**
with consistent `{edition-}` tags so Plex groups them as selectable versions — e.g.
`{edition-1964}` and `{edition-1995}` pending better labels once the film is identified.
Both files stay; nothing is consolidated away.

The title itself remains unidentified (no TMDB entry, no catalogue hit; both folders' NFOs
are a tinyMediaManager fuzzy-match error pointing at Tati's unrelated 1949 *Jour de Fête*).
Identification is still open — but it is now a *cataloguing* question, not a
keep-or-delete one.

### Method note worth keeping

**Compare per-chapter lengths, not total runtime, when testing whether two files are the
same cut.** A re-edit that adds in one place and trims in another nets to almost nothing at
the total level while differing substantially throughout. Total runtime agreement is
necessary but nowhere near sufficient evidence of identical content.

### D10 refined — a 1995 recut of a 1964 film (operator reading, supported by the deltas)

Splitting the per-chapter deltas by position, rather than treating them as scatter, gives a
coherent editorial signature:

| position | chapters | delta |
|---|---|---|
| front | ch1 | **+21.19 s** |
| back | ch11 | **+24.52 s** |
| body | ch2–ch10 | **−62.31 s** |
| | | net **−16.60 s** |

**~46 seconds ADDED at the two ends; ~62 seconds TRIMMED out of the middle.**

That is what a recut looks like: new front matter (titles, re-release or restoration
credits) and new end matter, with the body tightened. It is *not* what a restoration looks
like — restorations preserve or restore runtime and reinstate lost footage; they do not cut
48 s from chapter 4 and 36 s from chapter 2 while padding the bookends. Editorial trimming
of the body on a later release is commonly driven by rights or clearance issues (music cues
especially) or by a director/distributor re-edit.

Combined with the folder labels, the reading is: **`(1964)` is the original; `(1995)` is a
later recut of it.** Both are legitimate versions of one work and both stay.

**Edition labels** for the SQ-26 consolidation — both files tagged, per the rule that a
folder must never have some features tagged and others bare:

```
JOUR DE FÊTE DANS LES MONTS NAGA (1964)/
  … (1964) {edition-1964 Original}.mkv
  … (1964) {edition-1995 Recut}.mkv
```

Folder year follows the original release (1964); the recut is carried as an edition inside
it, which is how Plex expects a later cut of an earlier film to be modelled. Labels can be
refined once the film is identified — the structure does not depend on knowing the title.

**Do not "pick the better copy."** The earlier size-and-runtime comparison implicitly framed
this as choosing a winner (1995 larger, 1964 longer). Once they are understood as two cuts,
that question dissolves: they are different works to preserve, not competing encodes of one.
