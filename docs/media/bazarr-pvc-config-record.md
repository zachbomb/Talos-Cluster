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
