# ID-tag folder format — decision (SQ-21, 2026-08-04)

## Verdict

**No format change needed.** The tags already in use — `{tmdb-N}` for movies,
`{tvdb-N}` for TV — are parsed correctly by every consumer that matters here. The
square-bracket divergence the ticket flagged as "known" **does not apply to the Emby
version actually running**.

Current config, confirmed live and left unchanged:

```
Radarr  movieFolderFormat   {Movie CleanTitle} ({Release Year}) {tmdb-{TmdbId}}
        standardMovieFormat {Movie CleanTitle} {(Release Year)} {tmdb-{TmdbId}} {edition-{Edition Tags}} ...
Sonarr  seriesFolderFormat  {Series TitleYear} {tvdb-{TvdbId}}
```

## Per-consumer verdicts

| consumer | verdict | basis |
|---|---|---|
| Radarr | confirmed | current `config/naming`, live |
| Sonarr | confirmed | current `config/naming`, live |
| Plex | confirmed | `{tmdb-28}` -> `Guid tmdb://28`; `{tvdb-79488}` -> `tvdb://79488` |
| **Emby 4.9.5.0** | **confirmed — overturns the assumption** | 544 of 545 tagged items match Emby's own resolved `ProviderIds.Tmdb` |
| TMM 5.3.0 | documentary only | changelog v4.2.8 / v4.3.13; no REST API (GUI/VNC-only) |

TMM is the one verdict not directly observed. Its changelog states ID parsing from
file/folder names in the form `tmdb-xxxxx`, which is on point and versioned, but a GUI
spot-check would close it properly.

## Two corrections to the reasoning that produced this ticket

### 1. The IMDB dual-tag argument is much weaker than it was filed as

The ticket argued for adding `{imdb-}` alongside `{tmdb-}` because IMDB is the one ID
every downstream consumer understands. Measured against the live Emby library:

```
Emby movie items                 2209
  with an Imdb id anyway         2006   (90%)
```

**Emby resolves the IMDB ID itself for 90% of items with no `imdb` tag anywhere in the
path.** It derives it from the TMDB match. The same is true of Plex. So dual-tagging buys
far less than claimed — it would be adding a redundant token to 2000+ paths to supply
something the consumers already compute.

Recommendation: **drop the dual-tag proposal** unless a specific consumer is identified
that needs IMDB in the path and cannot derive it. The 78 Radarr records missing an
`imdbId` remain a real gap for *matching quality*, but they are not a *naming* problem.

### 2. The gap is COVERAGE, not FORMAT — and the tag is mostly in FILENAMES

The audit counted folder tags and concluded the movie library was 96% non-conformant.
That framing was misleading. Radarr's `standardMovieFormat` writes `{tmdb-}` into the
**filename**, and only `movieFolderFormat` writes it into the **folder**:

```
FILENAME carries {tmdb-}   535
FOLDER   carries {tmdb-}    69
```

So a substantial set of movies already carry a correct machine-readable ID that Plex and
Emby are demonstrably using, even though the folder looks untagged. Example:

```
/movies/500 Days of Summer (2009)/500 Days of Summer (2009) {tmdb-19913} [...].mkv
        ^ folder: no tag                                    ^ file: tagged
```

Emby matched that to `Tmdb 19913` correctly. Any remediation must count **file-or-folder**
tags, not folder tags alone, or it will rename files that are already working.

## Tag accuracy where tags exist

```
tagged items                     545
  tag == Emby's resolved Tmdb    544
  mismatch                         1
```

The single mismatch is instructive rather than alarming:

```
folder  Scenes from a Marriage (1974) {tmdb-133919} {edition-Television}
file    Scenes from a Marriage (1973).mkv
Emby    tmdb-617958   imdb=tt0070644
```

Bergman's work exists as a 1973 TV miniseries and a 1974 theatrical cut. Folder year,
file year, path tag and Emby's resolution disagree — four sources, three answers, one
work. This is the same class as `World on a Wire`, where TMDB classes the work as a TV
miniseries that Radarr structurally cannot own. Not a mispull; a modelling limit.

## What this changes downstream

- **SQ-23 (TMM scoping)** is unblocked: TMM should be configured to read `{tmdb-N}` /
  `{tvdb-N}`, and its renamer stays off. No format decision pending.
- **The mass rename** loses most of its urgency. Its remaining justification is
  consistency and folder-level matching, not "the tools cannot identify the content" —
  for a large share of the library they demonstrably can.
- **SQ-20** should count file-or-folder tags when assessing remediation scope.

## Sources

Live APIs on this cluster: Radarr `config/naming` (`192.168.10.210:7878`), Sonarr
`config/naming` (`192.168.10.211:8989`), Plex `/library/metadata/{id}`
(`192.168.10.203:32400`), Emby `/emby/Items?Fields=Path,ProviderIds`
(`192.168.10.204:10079`, 2209 items). TMM changelog v4.2.8 / v4.3.13
(tinymediamanager.org/changelog-v4/).
