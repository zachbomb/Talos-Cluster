# Movie library identity audit — 2026-08-04

Radarr `/api/v3/movie` cross-referenced against on-disk folder names under `/movies`
(= `/media/media/movies`). **Regenerate before acting — the library moves.**

## Headline

Neither the folder name nor the Radarr record is authoritative, and BOTH the title and
the year vary by metadata source. TMDB dates from the earliest global/festival release,
IMDB from the primary national release; titles vary by translation, alternate release
title, subtitle inclusion, `&` vs `and`, and diacritics. **Only an ID is a stable join
key between tools.**

| cohort | count |
|---|---|
| on-disk movie folders | 2110 |
| already `{tmdb-}` tagged | 85 |
| untagged, title+year agree — mechanical rename | 1836 |
| untagged, +/-1yr same title — TMDB/IMDB year drift | 93 |
| untagged, **title-variant** (likely same film) | 44 |
| untagged, **hard suspect** (needs adjudication) | 31 |
| untagged, **stale path** (hasFile=false, wrong-named folder) | 7 |
| untagged, no parseable year | 3 |
| untagged, **orphaned** (no Radarr record) | 11 |

Radarr ID coverage: tmdbId 2471/2471, imdbId 2393/2471

## Cohort A1 — HARD SUSPECTS (adjudicate first)

Title has no containment relationship with the Radarr title. Some are real mispulls
(`Alien3`->`Aliens`, `Blade Runner 2049`->`Blade Runner`, `A. K.`->`A View to a Kill`),
others are alternate/translated release titles (`Redes`->`The Wave`,
`Invention for Destruction`->`The Fabulous World of Jules Verne`). **Runtime via ffprobe
is the discriminator** — an alternate title has matching runtime, a mispull does not.

| disk folder | Radarr title | year | imdbId | tmdbId |
|---|---|---|---|---|
| `7p., cuis., s. de b., … à saisir (1984)` | Seven Rooms, Kitchen, Bathroom, for Sale | 1984 | tt0159938 | 251004 |
| `Ater Hours (1985)` | After Hours | 1985 | tt0088680 | 10843 |
| `Blow Up My Town (1968)` | Saute ma ville | 1968 | tt0063551 | 49479 |
| `Deathdream (1974)` | Dead of Night | 1974 | tt0068457 | 38996 |
| `Dr. Strange and the Multiverse of Madness (2022)` | Doctor Strange in the Multiverse of Madness | 2022 | tt9419884 | 453395 |
| `Fast and Furious (2009)` | Fast & Furious | 2009 | tt1013752 | 13804 |
| `Fearless Hyena II (1983)` | Fearless Hyena 2 | 1983 | tt0085864 | 18741 |
| `Fists of Fury (1972)` | Fist of Fury | 1972 | tt0068767 | 11713 |
| `Five Deadly Venoms (1978)` | The Five Venoms | 1978 | tt0077559 | 13481 |
| `Ganja and Hess (1973)` | Ganja & Hess | 1973 | tt0068619 | 83096 |
| `Hans Brinker and the Silver Skates (1958)` | Hans Brinker or the Silver Skates | 1958 | tt0394610 | 925508 |
| `Invention for Destruction (1958)` | The Fabulous World of Jules Verne | 1958 | tt0052374 | 19759 |
| `Kamikaze 1989 (1982)` | Kamikaze '89 | 1982 | tt0084191 | 12607 |
| `La Grande Illusion (1937)` | Grand Illusion | 1937 | tt0028950 | 777 |
| `Lady Snowblood Love Song of Vengeance (1974)` | Lady Snowblood 2: Love Song of Vengeance | 1974 | tt0072157 | 18818 |
| `Lucia (1968)` | Lucía | 1968 | tt0064609 | 88591 |
| `Mission Impossible 2 (2000)` | Mission: Impossible II | 2000 | tt0120755 | 955 |
| `Mission Impossible 3 (2006)` | Mission: Impossible III | 2006 | tt0317919 | 956 |
| `Prisioneros de la Tierra (1939)` | Prisoners of the Land | 1939 | tt0176049 | 335367 |
| `Redes (1936)` | The Wave | 1936 | tt0028165 | 195522 |
| `Salt Lake City 2002- Bud Greenspan's Stories of Olympic Glory (2003)` | Salt Lake City 2002: Stories of Olympic Glory | 2003 | tt0414472 | 55454 |
| `Salut les Cubains (1963)` | Hello Cubans | 1963 | tt0057466 | 144599 |
| `Seoul 1988 (1989)` | Rainbow over Seoul | 1989 | tt4146418 | 436611 |
| `Sydney 2000- Stories of Olympic Glory (2001)` | Sydney 2000 Olympics Closing Ceremony | 2000 | — | 716098 |
| `Teorema (1968)` | Theorem | 1968 | tt0063678 | 5335 |
| `The Creatures (1966)` | Terror-Creatures from the Grave | 1965 | tt0060049 | 63507 |
| `The Fiancés of Macdonald Bridge (1961)` | Fiancés on the Bridge | 1962 | tt1086289 | 54464 |
| `The Fire Within Requiem for Katia and Maurice Krafft (2022)` | The Fire Within: A Requiem for Katia and Maurice Krafft | 2024 | tt19383190 | 977341 |
| `The Olympic Games Held at Chamonix in 1924 (1924)` | The 1924 Chamonix Olympic Games | 1924 | tt7262026 | 470824 |
| `Where Is My Friend's House (1987)` | Where Is The Friend's House? | 1987 | tt0093342 | 49964 |
| `Ô saisons, ô châteaux (1958)` | O Seasons, O Castles | 1958 | tt0050788 | 278727 |

## Cohort A2 — TITLE VARIANTS (verify cheaply, likely benign)

Normalised containment holds — short title vs full title, subtitle present/absent,
`&` vs `and`, diacritics. Expected to be the same film; confirm by runtime, don't adjudicate by hand.

| disk folder | Radarr title | year |
|---|---|---|
| `A. K. (1985)` | A View to a Kill | 1985 |
| `Alan Partridge (2013)` | Alan Partridge: Alpha Papa | 2013 |
| `Alien³ (1992)` | Aliens | 1986 |
| `Anchorman (2004)` | Anchorman: The Legend of Ron Burgundy | 2004 |
| `Blade Runner 2049 (2017)` | Blade Runner | 1982 |
| `Bluebeard's 8th Wife (1938)` | Bluebeard's 8th Wife | 1923 |
| `Brothers Bloom (2008)` | The Brothers Bloom | 2008 |
| `Chungking Express (1996) (1996)` | Chungking Express | 1994 |
| `Daguerréotypes (1975)` | Daguerréotypes | 1978 |
| `Divine Horsemen The Living Gods of Haiti (1985)` | Divine Horsemen: The Living Gods of Haiti | 1993 |
| `Dont Look Back (1967)` | Bob Dylan – Don't Look Back | 1967 |
| `Dr. Strangelove (1964)` | Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb | 1964 |
| `Duelle (1976)` | Duelle (Une Quarantaine) | 1976 |
| `Fate of the Furious (2017)` | The Fate of the Furious | 2017 |
| `Fellini Satyricon (1969)` | Satyricon | 1969 |
| `Full Body Massage (1995)` | Full Body Massage | 1999 |
| `Get Out (2016)` | Get Out Alive | 2016 |
| `Hero (2002)` | Hero | 2007 |
| `Mary Jane's Not a Virgin Anymore (1996)` | Mary Jane's Not a Virgin Anymore | 1998 |
| `Meanwhile (2012)` | Meanwhile in Mamelodi | 2011 |
| `No Regret (1993)` | No Regret, No Return | 1993 |
| `Noroît (1976)` | Noroît (Une Vengeance) | 1976 |
| `Right Now, Wrong Then (2017)` | Right Now, Wrong Then | 2015 |
| `School of Rock (2003)` | The School of Rock | 2003 |
| `Series 7 The Contenders (2001)` | Series 7 | 2001 |
| `Shadows (1958)` | Shadows | 1960 |
| `Soleil Ô (1967)` | Soleil O | 1973 |
| `Sunrise (1927)` | Sunrise: A Song of Two Humans | 1927 |
| `Symbiopsychotaxiplasm Take 2.5 (2005)` | Symbiopsychotaxiplasm: Take 2½ | 2005 |
| `The American Soldier (1970)` | The American Soldier | 1976 |
| `The Fearless Hyena (1979)` | Fearless Hyena | 1979 |
| `The Gang of Four (1988)` | Gang of Four | 1989 |
| `The Hero (1966)` | The Heroes of Telemark | 1965 |
| `The House, 1984 (1984)` | The House | 1984 |
| `The Nun (1965)` | The Nun's Story | 1959 |
| `The Raid- Redemption (2011)` | The Raid | 2012 |
| `The Swindlers (1955)` | The Swindle | 1955 |
| `The Woman is the Future of Man (2004)` | Woman Is the Future of Man | 2004 |
| `Tokyo Story (1972) (1972)` | Tokyo Story | 1953 |
| `Ulysse (1983)` | Ulysse | 1986 |
| `War and Peace (1966)` | War and Peace | 1968 |
| `X-Men Dark Phoenix (2019)` | Dark Phoenix | 2019 |
| `Ydessa, the Bears and etc. (2004)` | Ydessa, the Bears and etc. | 2026 |
| `Ådalen 31 (1969)` | Adalen 31 | 1969 |

## Cohort A3 — STALE PATHS (hasFile=false, folder named for a different film)

These are landmines: the Radarr record has no file, but its folder is named for another
film. A future grab imports into a wrongly-named folder. `WALL-E (2008)` and
`All the Invisible Children` are residue from the 2026-07-30 mispull remediation —
the bad file was deleted but the record's path was never repointed.

| disk folder | Radarr title | year |
|---|---|---|
| `Fallen Angels (1998)` | Fallen Angels | 1995 |
| `Je, Tu, Il, Elle (1976)` | Je Tu Il Elle | 1974 |
| `Joan the Maid (1993)` | Joan the Maid I: The Battles | 1994 |
| `Lumière and Company (1995)` | Lumière & Company | 1995 |
| `Non Je Ne Regrette Rien (No Regret) (1993)` | No Regret | 1993 |
| `Room 666 (1982)` | Room 666 | 1985 |
| `WALL-E (2008)` | The Berlin Wall:  Escape to Freedom | 2006 |

## Cohort B — ORPHANED (no Radarr record)

Several are known-unmanageable content per the 2026-07-28 cross-app drift audit
(concert/live-theatre, multi-part docs, TMDB-miniseries) — confirm before adding.

- `Curious George 2 Follow That Monkey! (2009)`
- `First Cow (2020)`
- `JOUR DE FÊTE DANS LES MONTS NAGA (1964)`
- `JOUR DE FÊTE DANS LES MONTS NAGA (1995)`
- `Kishi Bashi Live on Valentines Day (2013)`
- `Monster Mash (1970)`
- `Omnibus Monsieur Hulot's Work (1976)`
- `Samson and Delilah (1996)`
- `Secrets and Lies (1996)`
- `World on a Wire (1973)`
- `Zatoichi Supplements`

## Cohort C — UNPARSEABLE FOLDER NAMES

| disk folder | Radarr title | year |
|---|---|---|
| `Calgary '88- 16 Days of Glory` | Calgary ’88: 16 Days of Glory | 1989 |
| `Pioneers of African American Cinema` | Pioneers of African-American Cinema | 2016 |
| `You Sing Loud, I Sing Louder ()` | Bleeding Love | 2024 |

## Radarr records with a file but no imdbId (dual-tagging gap)

2 of 1889 with-file records lack an imdbId.

- Panda! Go Panda! (1972) — tmdb=695839
- Sydney 2000 Olympics Closing Ceremony (2000) — tmdb=716098
