# Mayday repair — execution status (2026-09-02)

## Done and verified

| step | result |
|---|---|
| Sonarr unmonitored | series + all seasons, so it cannot act mid-repair |
| Files renamed | 71 episodes, 129 files including sidecars, two-phase, zero overwrites |
| Sonarr rescan | 0 files whose season folder disagrees with their name |
| Content spot-check | S16E03=Tenerife, S16E02=Pentagon, S20E06=Sweden 294, S16E05=Proteus 706 |
| Plex | scanned ITSELF (unprompted); 4/4 repaired slots correct, titles updated |
| Emby | already aligned, 236 episodes = filesystem exactly, 4/4 correct |
| TinyMediaManager | 0 .nfo files for this show — nothing to reconcile, TMM detached here |

## Cross-platform alignment

    filesystem  236 media files
    Sonarr      219 episodeFile records, 0 season/name disagreements
    Plex        209 episodes indexed, repaired slots correct
    Emby        236 episodes, paths current
    Tunarr      107 BROKEN paths in the ch22 pool  <-- NOT YET FIXED
    TMM         no NFOs; detached, nothing to fix

## NOT done — deliberately

1. **Tunarr ch22 pool** — 107 broken paths (73 mappable, 34 orphaned). A path patch
   is NOT the right fix: Tunarr caches each program's TITLE at add time, so
   re-pointing a path would play the right file under the wrong guide entry, which
   is the original bug recreated inside Tunarr. The pool must be rebuilt so Tunarr
   re-reads identity from the corrected library. Stopped here per the owner.
2. **5 files in `.repair-staging`** — their targets are held by AMBIGUOUS files.
   Placing them requires moving an ambiguous file OUT of the library into
   quarantine, which is a different risk class from renaming. Needs a decision.
3. **13 excluded collisions** — occupants were AMBIGUOUS / NO-SRT / themselves
   MISFILED, i.e. no confirmed-correct file was ever at risk. Left untouched.
4. **Sonarr still UNMONITORED** — correct until the above settle, or it will start
   grabbing replacements for episodes it now thinks are missing (22 by its count).

## Reversibility

`rename-undo.json` holds the exact inverse of every executed move, including
sidecars. `rename-excluded.json` records what was deliberately not touched.

## Sonarr's missing list after repair (22)

    S14:5  S16:1  S18:3  S19:2  S20:1  S22:8  S24:1  S25:1

These are genuine gaps exposed by correcting the numbering — episodes the library
never actually had, previously masked by a wrong file occupying the slot. They are
the backfill target, and Sonarr must stay unmonitored until someone decides to
fetch them deliberately.

---

# Phase 2 — ch22 fixed, backfill started (2026-09-02 14:0x)

## ch22 did NOT need a rebuild

The earlier "107 broken paths" figure was wrong — it counted the whole Tunarr DB
across all channels. ch22 itself had 191 programs, 17 with a stale path.

More importantly, **Tunarr's programs are keyed by Plex ratingKey, not file path**.
The stale paths are a local mirror Tunarr does not stream from. The check that
actually mattered was resolving every ratingKey against Plex:

    175 resolve and MATCH the guide entry
      0 resolve to a DIFFERENT episode   <-- no wrong-guide-entry risk existed
     16 dead ratingKey (Plex 404)

Zero stale guide entries means a full teardown would have destroyed 175 correct
programs and reshuffled the schedule to fix 16. A surgical edit was correct.

## What was done

    191 programs
    -16  dead (Plex item gone — these would have failed on air)
    +31  episodes present in Plex but absent from the pool
    = 206 programs, ALL 206 verified to resolve in Plex, 0 dead

Splitting removal from addition mattered: the combined POST failed with
`FOREIGN KEY constraint failed` because hand-built lineup entries referenced
program UUIDs Tunarr generates itself. Removal alone succeeded (200), leaving the
channel better than before; the additions then succeeded using Tunarr's OWN
existing program uuids. The failed combined POST rolled back cleanly — verified
programCount unchanged at 191 before retrying.

3 of the 34 candidate additions are not yet known to Tunarr and were skipped; they
will come in with the next source sync.

## Backfill: 31 genuine gaps, search running

    S11:1  S12:2  S14:5  S16:1  S18:7  S19:2  S20:1  S22:7  S24:1  S25:2  S26:2

These are episodes the library never actually had — previously masked by a wrong
file occupying the slot. Sonarr was re-monitored (series + seasons + exactly these
31 episodes) and an EpisodeSearch was triggered against them specifically, not a
blanket season search.

## Still outstanding

1. **Fix ch22 again once backfill lands** — new files will need adding to the pool.
2. **5 files in `.repair-staging`** — targets held by AMBIGUOUS occupants; placing
   them means moving a file OUT of the library. Needs a decision.
3. **13 excluded collisions** — occupants were AMBIGUOUS / NO-SRT / MISFILED, so no
   confirmed-correct file was at risk. Left untouched.
