# Bazarr PVC config — record of non-GitOps settings

> **DRIFT WARNING, read first.** Bazarr's settings live in `/config/config/config.yaml`
> on its PVC, **not in this repo**. Nothing here is applied by Flux. A PVC restore, a
> volume rebuild, or a fresh deploy reverts every value below to chart defaults, silently.
> If subtitle coverage ever regresses, **check these values before investigating anything
> else.** This file is the record, not the source of truth — the source of truth is the PVC.

Deployed version at time of record: **Bazarr 1.6.0** (`ghcr.io/home-operations/bazarr`,
digest `sha256:cd63bbd0…`). Changes require a pod restart to load.

## Current values and why each is what it is

| setting | value | rationale |
|---|---|---|
| `general.ignore_ass_subs` | `true` | **Keep true.** Gates the *indexer* only (bazarr v1.6.0 `series.py:59` / `movies.py:60`) — it decides whether an existing embedded ASS track counts as "already has subtitles". `true` marks ASS-embedded items as MISSING, making them eligible for the `embeddedsubtitles` provider, which extracts and converts them to external SRT. Flipping to `false` would suppress extraction on exactly the anime/foreign content we want. |
| `general.ignore_pgs_subs` | `true` | Flipped 2026-08-05 (was `false`). PGS is bitmap and cannot be extracted to SRT, so a PGS-embedded item counted as "covered" was neither extracted nor searched externally — invisible in `wanted` and unusable by the client. `true` makes them searchable against external providers, the only route that can serve them. |
| `general.ignore_vobsub_subs` | `true` | Flipped 2026-08-05 (was `false`). Same reasoning as PGS. |
| language profile `originalFormat` | **off** (profile 1 "English") | **This is the real guard** against `.ass` reaching a client that only accepts SRT — not any `ignore_*` flag. Bazarr converts all non-SRT to SRT via `pysubs2` in `subliminal_patch`'s `Subtitle.is_valid()` unless a profile enables "Use Original Format". **One enabled profile silently reopens the hole.** Verify after any profile change. |
| `general.enabled_providers` | includes `embeddedsubtitles` | Already enabled since 2026-07-30. Confirmed working — 59 deliveries in history (51 episode, 8 movie), first firing ~2026-07-31. |
| `opensubtitlescom.include_machine_translated` | `true` | Set 2026-07-30. The key lever for foreign-language shows — Bazarr was rejecting machine-translated English subs, which is most of what exists for Finnish/Greek/French content. |
| `general.enabled_providers` incl. `subf2m` | yes | Added 2026-07-30. Note `podnapisi` does NOT exist in 1.6.0 and is silently dropped on restart if added. |
| Sonarr/Radarr connection | cluster DNS (`sonarr`/`radarr`) | Set 2026-07-30 as **DNS not IPs** — deliberately immune to a future MetalLB renumber, which is what silently broke Bazarr for ~8 months. |

## Correction recorded 2026-08-05

A 2026-07-30 note described `ignore_ass_subs: true` as a **temporary guard** to stop
`.ass` reaching PMP, "to revisit once PMP handles ASS". **That rationale was wrong**, per a
source read of bazarr v1.6.0. The flag never controlled what is fetched or written — only
what the indexer counts as covered. The hazard it was guarding against is real, but is
controlled by `originalFormat`, a different setting entirely.

The belief was recorded honestly, with its reasoning, and was still wrong. It read as
authoritative *because* it explained itself. Keeping the correction visible here rather
than silently editing the old note.

## Baselines for the post-sweep re-census

Captured 2026-08-05, immediately before the PGS/VobSub flip took effect:

```
episodes wanting subs : 1112     (was 517 on 2026-07-30 — more than doubled, unexplained)
movies wanting subs   :   77     (was 114 on 2026-07-30)
external .srt on disk :  828     (422 tv + 406 movies)  ≈ 8% of ~10,000 media files
external .ass on disk :    0
```

**A RISING wanted count after the flip is the fix working**, not a regression —
previously-hidden bitmap-only titles surfacing. The indexer re-evaluates on the
`movies_sync` / `series_sync` cycle (60 min), so expect a lag.

Bazarr's own "coverage" percentage counts embedded tracks. Only the ~828 external sidecars
are consumable by the live-TV client chain — which is what the ~7% figure in the Route A
analysis refers to.

## Backup

Pre-flip config preserved in the pod at
`/config/config/config.yaml.bak-preflip-2026-08-05`. Revert = restore that file and
restart the deployment.

## Post-flip verification, 2026-08-05 (~2.5h after the flip)

| metric | pre-flip | +2.5h | verdict |
|---|---|---|---|
| movies wanting subs | 77 | **147** (+70) | flip working |
| episodes wanting subs | 1112 | **1112** (no change) | index stale — see below |

**Codec normalization is CONFIRMED WORKING.** The +70 movies are previously-hidden
bitmap-only titles surfacing, which means Bazarr's `hdmv_pgs_subtitle → pgs` and
`dvd_subtitle → vobsub` mapping is functional. That was the open caveat on SQ-221 and it is
now closed by observation rather than by a source read.

### But TV did not move, and it should have

ffprobe sample of 60 TV episodes:

```
bitmap-ONLY (PGS, no text track) : 15   (25%)
text track present               : 38
both text and bitmap             :  7
no subtitle streams              :  0
```

At ~25% of 8109 episode files, roughly **2000 episodes should have surfaced** as wanted.
Zero did.

Confirmed on a specific title: `Out 1` (Rivette, 8 episode files, every one
`hdmv_pgs_subtitle` only) still reports `episodeMissingCount: 0` in Bazarr.

**Cause: the subtitle index is not re-evaluated on the `series_sync` cycle.** Bazarr has
dedicated tasks for it:

```
series_full_scan_subtitles   "Index All Existing Episodes Subtitles"
movies_full_scan_subtitles   "Index All Existing Movies Subtitles"
```

The movies index evidently got re-evaluated; the series index did not. **The post-scrub
sweep must therefore explicitly run `series_full_scan_subtitles`** — a flag change alone
does not reach existing TV items, and waiting longer will not fix it.

This re-index is an ffprobe pass over ~8109 episodes on NFS
(`embedded_subtitles_parser: ffprobe`), so it is genuinely I/O-heavy and belongs in the
post-scrub window alongside the sweep, not before it.

### Why this check was worth running

Without it, the post-sweep census would have shown TV unchanged and the natural suspicion
would have been the codec normalization mapping — the exact caveat already flagged. The
mapping is fine. The real gap is a stale index needing an explicit re-scan. One is a
config/compatibility bug; the other is a missing step in the runbook.

### Instrument errors made and corrected during this check

1. **Task `lastExecution` read as `None` for every task** — read five minutes after
   restarting Bazarr. Post-restart scheduler state is not evidence about historical
   execution. The durable instrument was the *download history* (`/api/episodes/history`),
   which showed `embeddedsubtitles` had delivered 59 times starting ~2026-07-31.
2. **First ffprobe sample reported "577 episodes, 0 subtitle streams"** from a `head -40`.
   TV filenames contain spaces and an unquoted `$(find …)` in a `for` loop word-split each
   path into fragments; every fragment failed ffprobe and was counted as "no subtitles".
   A complete false negative. Corrected with `find | while IFS= read -r`. **A sample count
   that does not match the requested limit is the tell.**
