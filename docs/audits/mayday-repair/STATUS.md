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
