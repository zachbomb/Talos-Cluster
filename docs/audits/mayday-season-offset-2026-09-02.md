# Mayday / Air Crash Investigation — season-numbering offset

**Status: evidence gathered, NO files changed. Repair map pending completion of
subtitle extraction.**

## What the owner reported

"I've had issues in the past with this show grabbing the wrong files / episodes
being wrong when I watch it." Then, after Season 26 was confirmed scrambled:
"I think it's pervasive in the earlier seasons too."

Both correct. The second one contradicted my own working theory at the time.

## What it actually is

NOT random mispulls. **Whole seasons are shifted by one**, episode numbers preserved:

    S15E02 -> S16E02        S18E01 -> S19E01        S19E01 -> S20E03
    S15E03 -> S16E03        S18E02 -> S19E04        S19E02 -> S20E06
    S15E04 -> S16E04        S18E03 -> S19E03        S19E04 -> S20E02
    S20E03 -> S21E03        S22E01 -> S23E02
    S20E05 -> S21E05
    S20E06 -> S21E06

i.e. the file filed as SxxEnn contains S(xx+1)Enn's content.

**Why**: Mayday has genuinely different season boundaries across broadcasters
(Discovery Canada / National Geographic / UK). A release group numbering by one
convention imports one season out of step with TVDB, which is what Sonarr matches
against. Sonarr then matches on the SxxExx NUMBER, ignores the title, renames the
file to the expected name -- and destroys the evidence in the filename.

Affected so far: **S14, S15, S17, S18, S19, S20, S22, S25** (and S26 separately,
as an 8-episode closed rotation). Clean so far: **S21 (6/6), S23, S12**.

## Verdicts on the 80 episodes that had subtitles at the time of writing

    MATCH 10 · MISFILED 64 · WEAK 10 · (160 not yet extracted)

Per season, the striking part is that seasons are wholly bad or wholly clean:

    S15 10/10 misfiled    S19 10/10        S21 6 MATCH, 0 misfiled
    S17  9/10             S20  8/10        S23 2 MATCH
    S18  9/10             S25  8/11        S12 1 MATCH

Random errors do not cluster like that. Whole-block import does.

## Method, and its limits

Each Mayday episode covers ONE named air accident and the episode title names it,
so subtitle text can be scored against every episode's title terms library-wide.
The file's true identity is whichever episode's terms its dialogue actually matches.

Three corrections were needed to get here, each worth keeping:

1. **Byte-identical duplicate detection found NOTHING** (0 groups / 240 files) and
   is structurally blind to this: every file is a distinct, correct-length, real
   episode -- just filed under the wrong number. A clean duplicate check is NOT
   evidence of a clean library.
2. **Same-season comparison produced confident WRONG attributions.** The first
   version only compared within a season, on the assumption rotations stay local
   because Season 26's did. S19E02 disproved it: hand-read as Air Sweden 294, which
   is S20E06. Restricted to Season 19, the matcher named a plausible-but-wrong
   in-season candidate. Cross-season comparison raised its score 4 -> 9 and found
   the truth.
3. **A 45s bounded-extraction timeout produced FALSE "no subtitles"** under I/O
   contention (found by the audit agent, proven on S05E01). Some episodes marked
   unchecked are fine.

Outliers that are probably noise, not findings: S14E04->S11E13, S25E01->S02E01,
S17E01/03/04->S05E02. Generic titles score spuriously; the repair map needs a
confidence floor, not just "best match wins".

## Why NOT to re-download the show

Considered, and rejected on evidence:

* 734 GB, 8-33 hours depending on link speed.
* The library is already assembled from **8+ release groups** (HDCTV 69, playWEB 59,
  ADWeb 23, Kitsune 22, BLOOM 21, Dooky/NORViNE/FLIX 10 each). A re-grab does not
  fetch a canonical set; it fetches whatever those same indexers serve today, from
  the same groups whose numbering disagreement caused this.
* The defect is NUMBERING, not corruption. Sonarr would search S19E02, receive a
  release labelled S19E02 from a mis-numbered group, and re-import the same wrong
  content -- destroying the evidence again on rename.
* It discards files that are fine (10 confirmed MATCH so far).

The files are almost all present and intact. This is a metadata repair.

## Next

1. Finish extraction (all 240 get a sidecar; 80 done at time of writing).
2. Re-run the matcher on the full set.
3. Build the repair map with a confidence floor; treat low-score verdicts as
   UNCHECKED, never as findings.
4. Sonarr's rename-on-import is what destroyed the original evidence -- any repair
   has to correct Sonarr's database too, or it will re-break on the next scan.
   Plan that step; do not improvise it.
