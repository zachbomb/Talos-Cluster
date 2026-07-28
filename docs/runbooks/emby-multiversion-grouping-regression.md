# Emby Multi-Version Grouping — Broken by Upstream Regression (HOLD)

**Status:** ⏸️ **BLOCKED ON UPSTREAM — hold until Emby ships a fix.** No action to take on our
side; nothing in our library or naming is wrong.
**Affects:** Emby Server (our instance `192.168.10.204:10079`, version **4.9.5.0**).
**Investigated:** 2026-07-28. **Recheck trigger:** any Emby Server update (esp. 4.10.x stable).

---

## TL;DR

Emby does not group multiple versions/editions of a movie into one selectable item. This is
a **known Emby regression introduced in 4.9.1.80 and still present in the current stable
4.9.5.0** — dev-acknowledged, unresolved, no working workaround. **Plex groups the exact same
files correctly.** So version selection works in Plex today; Emby will catch up when the bug
is fixed. **Do not restructure the library for Emby — it would not help on this version.**

## Symptom

- A movie with multiple versions (editions, aspect ratios, resolutions) shows as **multiple
  separate movies in Emby** instead of one movie with a version picker.
- `EnableMultiVersionByFiles` and `EnableMultiVersionByMetadata` are both **True** on the
  Movies library, yet nothing groups.

## Root cause — Emby 4.9.x regression (not our files)

- The multi-version grouping feature **broke as of Emby 4.9.1.80** and remains broken through
  **4.9.5.0** (the latest stable — there is no 4.9.6/4.9.7). Emby dev "Luke" acknowledged it;
  the suggested workaround ("disable *Merge the contents of the top level folders* + rescan")
  did **not** hold.
- **Empirically reproduced on our 4.9.5.0** (2026-07-28), three independent ways:
  1. **Correct naming didn't group.** Renamed *On the Waterfront (1954)*'s 3 files to Emby's
     exact documented convention `Folder Name - Label.ext` (filename prefix identical to the
     folder name). Emby freshly discovered them (new item IDs) and **still created 3 separate
     items.** Reverted afterward.
  2. **Auto-grouping by metadata didn't fire** even though all 3 files correctly matched the
     same movie (`tmdb=654`, `imdb=tt0047296`, 1954) in the same folder.
  3. **`MergeVersions` API is a no-op.** `POST /Videos/MergeVersions?Ids=a,b,c` (verified as
     the correct signature via the instance's own `openapi.json`) returns **HTTP 204** but
     does nothing — no `PrimaryVersionId`, no `MediaSourceCount`, still 3 items.
- **Plex, on the identical files, groups them correctly** (one movie, N versions — proven on
  On the Waterfront). So the files are fine; Emby is broken.

## What is NOT the problem — the correct unified structure (for Plex now, Emby later)

Both Plex and Emby (when working) share one convention — **one folder per movie, no versions
subfolder, all versions as files inside:**

```
Movie Title (Year) {tmdb-NNNN}/
   Movie Title (Year) {tmdb-NNNN} - Theatrical.mkv
   Movie Title (Year) {tmdb-NNNN} - Director's Cut.mkv
   Featurettes/ , Trailers/            # extras subfolders (both recognize)
```

- **Emby rule (when not regressed):** each version filename must begin **exactly** with the
  folder name (year + id included), then ` - Label` (space-hyphen-space). Same folder only.
- **Plex:** name-agnostic — any files in one movie folder group as versions; `{edition-Name}`
  in the filename gives labeled editions; separate `{edition-}` folders also work (both cuts
  must be tagged, else Plex splits them).
- **Adopt this structure regardless** — it is correct and future-proof: Plex groups it *now*,
  and Emby will *once the regression clears*.

## Disposition / hold

1. **Version selection = Plex-primary.** Zero effort; works today. Emby is the secondary
   player; it showing versions as separate entries is cosmetic until Emby is fixed.
2. **Do NOT** mass-rename or restructure the library for Emby, **downgrade** below 4.9.1.80
   (strands us on an old stable, loses 4.9.2–4.9.5 fixes), or chase `MergeVersions` scripting.
3. **When an Emby update lands (watch 4.10.x):** re-run the validation below before assuming
   anything changed.

## Re-test procedure (run when a new Emby version ships)

1. Pick a real multi-version movie already in one folder (e.g. *On the Waterfront (1954)* — 3
   files in `/movies/On the Waterfront (1954)/`).
2. Ensure each file's name begins exactly with the folder name + ` - Label` (rename in place;
   record originals to revert).
3. Trigger an Emby library scan: `POST /emby/Library/Refresh?api_key=$EMBY_API`.
4. Read back: `GET /emby/Items?IncludeItemTypes=Movie&Recursive=true&Fields=MediaSources,
   PrimaryVersionId&NameStartsWith=<title>&api_key=$EMBY_API`.
   - **Fixed** = 1 item with N MediaSources (or `PrimaryVersionId` linking the others).
   - **Still broken** = N separate items, 1 source each.
5. Also retry `POST /emby/Videos/MergeVersions?Ids=<id1,id2,...>&api_key=$EMBY_API` → check
   for a non-204/effect. Split/undo = `DELETE /emby/Videos/{Id}/AlternateSources`.
6. Revert filenames if renamed. (`$EMBY_API` = `kubectl get secret cluster-secrets -n
   flux-system -o jsonpath='{.data.EMBY_API}' | base64 -d`.)

## References

- Emby community — [Question About Multi Version Grouping](https://emby.media/community/topic/143050-question-about-multi-version-grouping/)
  (dev-acknowledged, 4.9.1.80+, workaround didn't hold, unresolved)
- Emby community — [Multi-version TV Series not merging](https://emby.media/community/topic/133994-multi-version-tv-series-not-merging/)
  (pre-regression naming rule: filename prefix must equal folder name)
- Emby docs — [Movie Naming](https://emby.media/support/articles/Movie-Naming.html)
- Emby community — [New Emby Server Release 4.9.5.0](https://emby.media/community/topic/147798-new-emby-server-release-4950/)
- Version reference — [Emby 4.9.5.0 / 4.10.0.20 beta](https://www.videohelp.com/software/Emby)
- Related session memory: `project_media_content_validation_audit.md` (full audit context,
  including the unified structure, Plex behavior, and the download-client / mispull findings).
