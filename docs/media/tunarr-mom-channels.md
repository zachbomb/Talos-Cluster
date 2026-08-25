# Tunarr "Masters of the Month" Channels

Ten Tunarr channels (27-36) built from the Karagarga `MoM: *` Plex collections
(see `kg-mom-catalog.json` / `kg-mom-coverage.json` in this directory). Created
2026-08-25 (SQ-134).

## THE BIG CAVEAT: Plex collections are SNAPSHOTTED, not tracked

Tunarr copies a collection's membership at programming time (Tunarr issue #15,
slated for Milestone 2.0). **Adding a film to a `MoM:` collection in Plex later
does NOT put it on the channel.** To pick up new films, re-run the programming
step for that channel (see "Re-programming a channel" below).

## Channel configuration (identical for all ten)

| Setting | Value | Why |
|---|---|---|
| Transcode config | `c007fc05-42a0-464f-ae8b-8d2648471b89` (H264-VAAPI) | QSV pins output to 24.000 fps (SQ-130); VAAPI does not |
| Stream mode | `hls` | matches the 26 existing channels |
| Subtitles | `subtitlesEnabled: false` | shared-anchor subtitle defect; sparse-dialogue arthouse is the worst case |
| Group title | `Masters of the Month` | separates from the dizqueTV-migrated channels in the guide |
| Schedule | Random Slots, one `movie` slot, **fixed 2 h duration**, shuffle, uniform, Pad Slot @ 30 min, flex distributed, 7 days precalculated | Time Slots' "Max Lateness" can truncate an over-running feature; Random Slots never truncate — a film longer than its slot is scheduled whole and the clock just advances (`RandomSlotsService.ts`, "Program longer than we have left? Add it and move on") |
| On demand / stealth | both off | normal linear channels |

`programCount` on `/api/channels` counts *scheduled plays* in the precalculated
lineup (e.g. 75 for a 23-film channel over 7 days), not distinct films. Distinct
films = `GET /api/channels/{id}/programs` total, which matches the Plex
collection's childCount at build time.

## API recipe (what actually works — port 8000, not 12321)

The endpoints that exist (from `GET /openapi.json`, Tunarr 1.3.13):

1. **Browse collections**: `GET /api/plex/{mediaSourceId}/libraries/{plexSectionKey}/collections`
   — uses the Plex section key (`1` for Movies), *not* Tunarr's library uuid.
   NB: this call proxies a heavy Plex query and can 60 s-timeout; going to Plex
   directly (`/library/sections/1/collections`) is faster for discovery.
2. **Collection children**: `GET /api/plex/{mediaSourceId}/items/{ratingKey}/children?parentType=collection`
   — returns Tunarr-enriched media items. **The `uuid` on these items is a
   media-item id, NOT a Program id — do not feed it to programming.**
3. **Map to Program uuids**: `POST /api/programming/batch/lookup` with
   `{"externalIds": ["plex|<mediaSourceId>|<ratingKey>", ...]}`.
4. **Create channel**: `POST /api/channels` `{type:"new", channel:{...}}` with a
   client-generated uuid. (A programming POST immediately after create can 404 —
   small create/read race; retry after a couple of seconds.)
5. **Program + schedule in one shot**: `POST /api/channels/{id}/programming`
   `{type:"random", programs:[<Program uuids>], schedule:{type:"random", flexPreference:"distribute", maxDays:7, padMs:1800000, padStyle:"slot", randomDistribution:"uniform", slots:[{id:<uuid>, type:"movie", order:"shuffle", cooldownMs:0, weight:100, durationSpec:{type:"fixed", durationMs:7200000}}]}}`
   — the server generates the lineup and persists the schedule.

## Re-programming a channel (after adding films to a MoM collection)

Re-run steps 2-3 for the collection's ratingKey to get the updated Program uuid
list, then step 5 against the existing channel id. The schedule is regenerated
from scratch (new shuffle); that is fine for these channels.

## Channels

ratingKeys are the Plex collection ids in the Movies section (library key 1) of
Pibbs-Horde (`ae077270-d82a-4010-abbc-fd96463df172`). "Films" = distinct
programs on the channel = the collection's childCount at build time
(2026-08-25). "Plays/7d" = scheduled plays in the precalculated week
(`programCount` in the channel list).

| Ch | Name | Plex collection ratingKey | Films | Plays/7d | Tunarr channel id |
|---:|---|---|---:|---:|---|
| 27 | Frederick Wiseman | 71951 | 23 | 75 | `68c3beaf-81d5-4d1a-9009-d268ba6a5b49` |
| 28 | Deleuze's Images | 71957 | 90 | 96 | `43fb6d2c-bbda-4d0f-aac9-532428c9942f` |
| 29 | Queer Cinema(s) | 71958 | 75 | 93 | `2c948f46-d813-4c6a-802d-05fd86336d1c` |
| 30 | The Birth of Cinema | 71959 | 64 | 493 | `49cc8003-9575-4b88-ba4a-fb9ec591eaf4` |
| 31 | The Olympics | 71960 | 40 | 81 | `8b8c03fa-f66b-46fe-801b-62d9fe30cc3b` |
| 32 | Frank Tashlin & Jerry Lewis | 71961 | 37 | 98 | `09467470-fec9-4a20-89e5-d8a55d66ad9e` |
| 33 | Sidney Lumet | 71954 | 34 | 88 | `bb27f064-4163-4f74-b116-0b8499cbae06` |
| 34 | Ingmar Bergman | 71962 | 32 | 96 | `f02736ba-600d-4982-9ce1-ded9efa81fd0` |
| 35 | Rainer Werner Fassbinder | 71952 | 31 | 102 | `fdf2dfeb-15c4-4e72-a830-54c9d08b25ee` |
| 36 | Jacques Demy & Agnès Varda | 71953 | 30 | 137 | `b402e8ba-0707-45be-bce3-8728b4271265` |

Every channel verified at build: distinct programs == collection childCount,
every scheduled play's duration equals a full film runtime (no truncation —
including 349 min *Near Death* on ch27), tune test served HLS video on ch27 and
ch30 with `/.transcode` staying at ~2% of 4.9 G.

## Operational notes

- The lineup precalculates 7 days. Tunarr extends the schedule automatically
  (`data.schedule` is persisted in the channel's lineup file); if a channel ever
  runs dry, re-POST the programming per the recipe above.
- The `plex|...` browse proxy (`/api/plex/.../collections`) issues a heavy Plex
  query and can 500/timeout when the node is loaded; the direct-Plex +
  batch-lookup recipe above is the reliable path.
- Do not switch these channels to the HEVC-HLS config
  (`18ac6c88-340d-485b-9c21-7935b02b20e0`): it is QSV and pins output to
  24.000 fps.
