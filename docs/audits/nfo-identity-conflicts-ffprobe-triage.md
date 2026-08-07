# NFO-vs-Radarr identity conflicts — ffprobe triage

**Generated:** 2026-08-07, SQ-44 follow-up. **Nothing was mutated to produce this.**

Runtime is the discriminator because it is independent of every metadata source: if the file is 83 minutes and one candidate ID is a 12-minute work, the file has already answered.
Tolerance: match if |actual - claimed| <= max(3 min, 10%).

TMM is DETACHED in this deployment (no datasources, empty DBs, never scanned), so **no NFO here has a living writer** — all are residue from a previous instance. They matter only because Emby reads NFO and Plex ignores it.

## Verdict counts

- **AMBIGUOUS** — 21
- **NFO_STALE** — 13
- **NO_VIDEO** — 11
- **RADARR_WRONG** — 6
- **NEITHER** — 2

## RADARR_WRONG — Radarr's mapping is the error (runtime gap too large to be coincidence)

| title | actual | radarr | nfo | radarr tmdb | nfo tmdb | movieId |
|---|---|---|---|---|---|---|
| Agnès Varda: From Here to There | 47.5 | 235 | 47 | 745698 | 6817 | 86 |
| Awaken | 82.7 | 12 | 82 | 715365 | 468085 | 159 |
| No Regret, No Return | 38.2 | 94 | 38 | 261238 | 281084 | 989 |
| Sydney 2000 Olympics Closing Ceremony | 116.2 | 157 | 117 | 716098 | 471051 | 1307 |
| Terror-Creatures from the Grave | 94.3 | 85 | 92 | 63507 | 53026 | 1398 |
| War and Peace | 96.6 | 422 | 98 | 29266 | 149465 | 1806 |

## NFO_STALE — Radarr is right; the NFO is dead residue

| title | actual | radarr | nfo | nfo file |
|---|---|---|---|---|
| A Woman | 23.8 | 23 | None | `A Woman (1915) Bluray-1080p.nfo` |
| Cronos | 92.5 | 94 | 18 | `Guillermo del Toro-interview.nfo` |
| Heaven Can Wait | 112.8 | 112 | 15 | `Heaven-Bound Travelers (1935).nfo` |
| L'Atalante | 88.2 | 88 | None | `Les Voyages de L'atalante-featurette.nfo` |
| Men with Guns | 128.1 | 127 | 89 | `Men with Guns (1997) DVD.nfo` |
| Night Gallery | 98.4 | 98 | 50 | `Night Gallery (1969).nfo` |
| River of Grass | 76.3 | 76 | None | `River of Grass (1994).nfo` |
| Say Hey, Willie Mays! | 98.6 | 98 | None | `Say Hey, Willie Mays! (2022).nfo` |
| The Four Horsemen of the Apocalypse | 147.0 | 153 | 81 | `The Four Horsemen of the Apocalypse (1962) DVD.nfo` |
| The Suicide | 20.5 | 20 | None | `The Suicide (1978) Bluray-720p.nfo` |
| Tongues Untied | 54.9 | 55 | None | `Tongues Untied (1989).nfo` |
| Bleeding Love | 102.4 | 96 | None | `Bleeding Love (2024) WEBDL-1080p.nfo` |
| Nineteen Eighty-Four | 110.6 | 113 | 59 | `The House, 1984 (1984).nfo` |

## AMBIGUOUS — runtime cannot discriminate; needs content/title check

| title | actual | radarr | nfo | radarr tmdb | nfo tmdb |
|---|---|---|---|---|---|
| Seven Rooms, Kitchen, Bathroom, for Sale | 28.5 | 28 | 29 | 251004 | 2309192 |
| A Couch in New York | 104.3 | 104 | 104 | 47434 | 1137 |
| Alice in the Cities | 113.3 | 110 | 113 | 2204 | 5266 |
| Allez Oop | 20.7 | 21 | 21 | 51374 | 8635 |
| American Woman | 111.9 | 111 | 111 | 339976 | 567969 |
| At War with the Army | 92.4 | 93 | 92 | 23325 | 4299 |
| Between the Lines | 101.7 | 101 | 102 | 175924 | 11512 |
| Children | 46.7 | 47 | 47 | 48142 | 143088 |
| Holiday | 91.0 | 91 | 95 | 104219 | 16274 |
| Les 3 Boutons | 11.5 | 11 | 11 | 358341 | 1505705 |
| Life, and Nothing More… | 95.4 | 95 | 95 | 83761 | 930120 |
| No Fear, No Die | 93.0 | 93 | 93 | 97041 | 4812 |
| Rainbow over Seoul | 139.4 | 128 | 139 | 436611 | 471042 |
| Smash His Camera | 90.1 | 87 | 90 | 47912 | 3032482 |
| The Adventures of Robin Hood | 101.9 | 102 | 102 | 10907 | 8724 |
| The Balloonatic | 22.3 | 22 | 22 | 45807 | 8635 |
| The Big Mouth | 107.4 | 107 | 107 | 99377 | 3663 |
| The Big Shave | 5.8 | 6 | 6 | 48714 | 1986703 |
| The Bigamist | 79.5 | 80 | 80 | 74122 | 3360 |
| The High Sign | 20.0 | 21 | 20 | 46510 | 8635 |
| The Bakery Girl of Monceau | 23.4 | 23 | 23 | 81399 | 23393 |

## NEITHER / NO_VIDEO

`NEITHER` is not a failure of the test — `War and Peace` returns it because Radarr holds the whole work's runtime (422 min, Bondarchuk's four parts) while the folder holds a single part. A binary classifier would have been forced to pick and been wrong either way.

| title | actual | radarr | nfo | class |
|---|---|---|---|---|
| Death and Transfiguration | None | 27 | 26 | NO_VIDEO |
| His New Job | None | 29 | 29 | NO_VIDEO |
| His Regeneration | None | 15 | None | NO_VIDEO |
| La chambre | None | 11 | None | NO_VIDEO |
| Madonna and Child | None | 29 | None | NO_VIDEO |
| Peyton Place | None | 157 | 157 | NO_VIDEO |
| Stage Struck | None | 95 | 94 | NO_VIDEO |
| Sunnyside | None | 33 | 30 | NO_VIDEO |
| The Neon Bible | None | 92 | None | NO_VIDEO |
| The Tramp | None | 26 | None | NO_VIDEO |
| Toute une nuit | None | 90 | 91 | NO_VIDEO |
| War and Peace | 96.6 | 422 | 147 | NEITHER |
| War and Peace | 96.6 | 422 | 81 | NEITHER |

## Caveats

- **AMBIGUOUS is not 'fine'.** Runtime cannot separate near-identical cuts or shorts. `A Woman` and `His New Job` share NFO tmdb 13848 — one ID across multiple folders is the extras-cross-merge signature, not genuine ambiguity.
- **NO_VIDEO folders** are Radarr-monitored-missing; there is no identity to resolve until content arrives.
- **Remapping Radarr is not a field edit.** Radarr does not permit changing `tmdbId` on an existing movie — the operation is remove (keeping files) then add the correct movie at that path then manual-import, i.e. the July rescue flow. More invasive than 'fix a field'.
- Do NOT bulk-delete NFOs: `American Woman` is a case where the other NFO is right, and `The City (1999)` is one where Plex and the NFO both side against Radarr.

