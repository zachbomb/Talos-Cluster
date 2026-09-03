# ch22 backfill gap: Tunarr cannot adopt re-keyed Plex episodes

**Date:** 2026-09-02/03
**Status:** channel healthy at 206/206; 33 backfilled episodes NOT addable via any API

## Where things stand

| | count |
|---|---|
| Mayday episodes in Plex | 239 |
| Programs on ch22 | 206 (all valid, 0 stale, all `state=ok`) |
| Backfilled episodes not on ch22 | 33 |

The channel works. This is an incompleteness, not a breakage.

## Why the 33 cannot be added

The backfill + repair renames caused Plex to **re-create** these episode items
under new ratingKeys (`72115`-`72147`, added 2026-09-02 20:26-22:49Z). Tunarr
has no program rows for those keys, and there is no API path that creates them:

1. **`ScanLibrariesTask` does not discover them.** It ran at 00:00:05Z on 09-03 —
   *after* all 33 items already existed in Plex (latest addedAt 22:49Z) — and the
   highest Plex `external_key` Tunarr knows is still `72114`. The timing rules out
   "the scan hasn't caught up"; a rescan is not the fix. Confirms the existing note
   in `tunarr-stale-plex-ratingkey-repair`: *rescan is source-driven and can't fix it*.
2. **`POST /api/channels/{id}/programming` rejects external ids.** The `content`
   lineup item's `id` is an unconstrained string (unlike `filler`, which enforces a
   uuid pattern), which suggests it might accept `plex|<sourceId>|<key>`. It does not:
   the POST returns `500 FOREIGN KEY constraint failed`. `id` must be an existing
   program uuid. **The failed POST rolled back cleanly — ch22 was verified undamaged.**
3. **`POST /api/programming/batch/lookup` is read-only.** Returns `{}` for absent keys.
   `GET /api/programming/plex|<src>|72118` returns 404. The `|` separator is correct —
   an `_` separator produces `Invalid sourceType`, proving the parser accepts the pipe form.

## The trap: Tunarr HAS `state=ok` rows for these episodes — and they are dead

Under the show grouping (`357f5dba-408f-48ac-816c-6106956eb0ce`) Tunarr holds
**518 rows: 240 `ok`, 278 `missing`**. All 33 gap episodes have an `ok` row — under
*old* ratingKeys (52620, 46524, 42628, 58709, ...). Those keys **do not resolve in
Plex** (verified individually: `NOT FOUND`), while the current key `72118` does.

**`state=ok` in Tunarr's DB is not evidence the program is playable.** Adding these
uuids to ch22 would look correct in every count and 404 on stream — reintroducing
exactly the defect the earlier pass removed. Do not select programs by `state`.

## Remaining options (need an owner decision)

* **Tunarr UI add-content flow** — the UI can demonstrably add new Plex content, so
  it uses a path not exposed in the OpenAPI spec. Would need browser automation.
* **Direct DB insert** — writing `program` rows against a 596MB production SQLite DB
  with UNIQUE indexes and FK constraints. Note the standing rule: never rewrite
  `external_key`.
* **Leave as-is** — 206 valid episodes; revisit if Tunarr upstream changes.

## Method notes worth keeping

* Join ch22 to Plex on `programs[].program.externalId` ↔ Plex `ratingKey`. There is no
  `externalKey` field on these objects; guessing that name produced a **false "0 matches
  / 239 missing"** result twice. Always run an overlap control on a known-good key before
  trusting a diff.
* `kubectl exec` returning *no output at all* under node load is the exec timing out,
  not the query failing. Distinguish before diagnosing.
* Unindexed `LIKE` scans on this DB (596MB) exceed 200s; `file_path` is NULL for
  Plex-sourced programs — query via `tv_show_uuid`.

## Separately: 27 duplicate episode numbers (pre-existing, NOT from this work)

27 episode numbers have two files each (~68.6 GB in the older copies). **Zero involve a
file touched in the last 24h** — dates run Jan/Feb/Jun/Jul/Dec of the prior year. Plex
merges them as extra media parts under one episode, which is why Plex reports 239
episodes and the filesystem 266 files (239 + 27). Unrelated cleanup; not backfill damage.
