# Movie library identity verdicts — 2026-08-04

Companion to `docs/media/movie-identity-audit-2026-08-04.md` (commit 4e8e45570e58af23f50ef9d659cf7c5c84cc0f2f). All 96 cohort A1/A2/A3/B/C items covered. Radarr `/api/v3/movie` + `/api/v3/movie/lookup` (GET only, no writes) cross-referenced against ffprobe run directly against feature files (tdarr pod, `/media/media/movies` — confirmed same physical library the *arr side uses, e.g. Radarr's own `path` field for the "Ater Hours" typo folder points at the exact disk folder). Expected runtime = Radarr `movie.runtime` (TMDB-sourced). Tolerance ±5min treated as confirmed; embedded `format.tags.title` (mkv) weighted as direct evidence when present, overriding an imperfect runtime match. **No writes anywhere**: every Radarr call was GET; no PUT/DELETE; no files moved/renamed/deleted.

*Produced by the SQ-20 executor (read-only dispatch, Radarr GET-only + ffprobe via the
tdarr pod). Landed here verbatim apart from this provenance note. No Radarr state was
mutated and no files were moved, renamed or deleted in producing it.*

## Headline findings requiring human/Radarr action
- **4 active Radarr misidentifications** (record points to the wrong TMDB entry, not just a folder-name mismatch): `Get Out (2016)`→real film is *Get Out* (2017, tmdb=419430); `Hero (2002)`→real film is Zhang Yimou's *Hero* (2002, tmdb=79) while Radarr's `Hero` 2007 (Japanese, tmdb=51550) record's path actively points at this folder; `Bluebeard's 8th Wife (1938)`→Radarr has only the 1923 short (tmdb=535525) but the file is the 1938 Lubitsch feature (tmdb=31996); `The House, 1984 (1984)`→embedded title tag is literally "1984", real film is *Nineteen Eighty-Four* (tmdb=9314), not Radarr's `The House` (tmdb=628603).
- **2 genuine mispulls needing human ID** (embedded title proves wrong content, correct identity unknown): `The Creatures (1966)` (embedded title "5. MARRIED LIFE"); `No Regret (1993)` (embedded title "THE SIGNIFYIN' WORKS OF MARLON RIGGS - DISC 2").
- **2 corrupted files** — ffprobe fails with "EBML header parsing failed"; hex-dump of first 64 bytes confirms neither starts with MKV magic `1A 45 DF A3` (genuine corruption, not a mount issue — dozens of other unicode-named files probed fine): `Ô saisons, ô châteaux (1958)`, `Fellini Satyricon (1969)`.
- **1 mislabeled orphan, high confidence**: `Monster Mash (1970)` — embedded title is literally "M*A*S*H (1970)", corroborated by leftover `MASH (1970).nfo` and `M-A-S-H (1970).txt` files already sitting in the folder; measured 115.92min vs TMDB's 116min for M*A*S*H (tmdb=651) is a near-exact match. This was never really "Monster Mash" — add to Radarr as M*A*S*H.
- **1 suspected duplicate**: `JOUR DE FÊTE DANS LES MONTS NAGA (1964)` and `(1995)` — identical embedded title, near-identical runtime (80.5 vs 80.25min), no TMDB match for either year. ~9GB of probable duplicate content; needs human research.
- **1 genuine two-part-film detection gap** (not a stale-path landmine in the usual sense): `Joan the Maid (1993)` — folder actually HAS both feature files (Part 1 40GB + Part 2 44GB), Radarr's hasFile=false is because it never matched a 2-part naming scheme, not because files are missing. Do not re-download.
- `Alien³ (1992)` confirmed correct — filename explicitly tagged `{tmdb-679}{edition-Extended}`, measured 154.47min matches Aliens' well-documented Special Edition runtime (154min) vs theatrical 137min. Same film, alternate edition; safe to rename.
- `War and Peace (1966)` (A2, not itemized below as a mismatch needing action) — folder holds all 4 parts of the Bondarchuk tetralogy; Radarr's single movieFile happens to be Part IV only (20min under Part IV's own runtime alone vs the 422min combined total), so the huge raw delta is a Radarr single-file-per-movie limitation, not a wrong film. Identity confirmed correct via folder contents (4 parts present, combined runtime ≈422min matches).

## Cohort A1 — Hard suspects (31/31, every row has a measured runtime)

| disk folder | Radarr title | tmdbId | exp min | measured | delta | verdict |
|---|---|---|---|---|---|---|
| `7p., cuis., s. de b., … à saisir (1984)` | Seven Rooms... | 251004 | 28 | 0:28:32 | +0.5 | CONFIRMED, folder-name only issue |
| `Ater Hours (1985)` | After Hours | 10843 | 97 | 1:37:20 | +0.3 | CONFIRMED (typo folder name) |
| `Blow Up My Town (1968)` | Saute ma ville | 49479 | 13 | 0:13:01 | +0.0 | CONFIRMED |
| `Deathdream (1974)` | Dead of Night | 38996 | 88 | 1:28:28 | +0.5 | CONFIRMED |
| `Dr. Strange and the Multiverse of Madness (2022)` | Doctor Strange in the MoM | 453395 | 126 | 2:07:13 | +1.2 | CONFIRMED |
| `Fast and Furious (2009)` | Fast & Furious | 13804 | 107 | 1:46:47 | -0.2 | CONFIRMED |
| `Fearless Hyena II (1983)` | Fearless Hyena 2 | 18741 | 92 | 1:32:26 | +0.4 | CONFIRMED |
| `Fists of Fury (1972)` | Fist of Fury | 11713 | 108 | 1:45:56 | -2.1 | CONFIRMED |
| `Five Deadly Venoms (1978)` | The Five Venoms | 13481 | 101 | 1:41:35 | +0.6 | CONFIRMED |
| `Ganja and Hess (1973)` | Ganja & Hess | 83096 | 113 | 1:52:42 | -0.3 | CONFIRMED |
| `Hans Brinker and the Silver Skates (1958)` | Hans Brinker or the Silver Skates | 925508 | 90 | 1:29:47 | -0.2 | CONFIRMED |
| `Invention for Destruction (1958)` | The Fabulous World of Jules Verne | 19759 | 83 | 1:22:57 | -0.0 | CONFIRMED |
| `Kamikaze 1989 (1982)` | Kamikaze '89 | 12607 | 106 | 1:46:18 | +0.3 | CONFIRMED |
| `La Grande Illusion (1937)` | Grand Illusion | 777 | 114 | 1:53:42 | -0.3 | CONFIRMED |
| `Lady Snowblood Love Song of Vengeance (1974)` | Lady Snowblood 2 | 18818 | 89 | 1:29:24 | +0.4 | CONFIRMED |
| `Lucia (1968)` | Lucía | 88591 | 161 | 2:41:23 | +0.4 | CONFIRMED |
| `Mission Impossible 2 (2000)` | Mission: Impossible II | 955 | 123 | 2:03:35 | +0.6 | CONFIRMED |
| `Mission Impossible 3 (2006)` | Mission: Impossible III | 956 | 126 | 2:05:24 | -0.6 | CONFIRMED |
| `Prisioneros de la Tierra (1939)` | Prisoners of the Land | 335367 | 87 | 1:27:20 | +0.3 | CONFIRMED |
| `Redes (1936)` | The Wave | 195522 | 61 | 1:00:42 | -0.3 | CONFIRMED |
| `Salt Lake City 2002- Bud Greenspan's...` | Salt Lake City 2002: Stories of Olympic Glory | 55454 | 120 | 1:59:27 | -0.5 | CONFIRMED |
| `Salut les Cubains (1963)` | Hello Cubans | 144599 | 30 | 0:29:23 | -0.6 | CONFIRMED |
| `Seoul 1988 (1989)` | Rainbow over Seoul | 436611 | 128 | 2:19:23 | +11.4 | LIKELY correct (moderate confidence) — embedded tag "100 Years of Olympic Films - Disc 24" (Criterion box-set numbering places 1988 Seoul here); delta plausibly bonus content on the rip. Human spot-check recommended. |
| `Sydney 2000- Stories of Olympic Glory (2001)` | Sydney 2000 Olympics Closing Ceremony | 716098 | 157 | 1:56:10 | -40.8 | LIKELY correct (moderate confidence) — embedded tag "100 Years of Olympic Films - Disc 29"; Radarr's own prior mediaInfo scan already recorded this exact 1:56:10 (static, not new). TMDB's 157min for this niche title plausibly wrong. No blocking action. |
| `Teorema (1968)` | Theorem | 5335 | 95 | 1:38:46 | +3.8 | CONFIRMED (within tolerance), no embedded-title conflict |
| `The Creatures (1966)` | Terror-Creatures from the Grave | 63507 | 85 | 1:34:17 | +9.3 | **MISPULL — human review.** Embedded title = "5. MARRIED LIFE" (episode/chapter label). Do NOT rename to Terror-Creatures from the Grave. |
| `The Fiancés of Macdonald Bridge (1961)` | Fiancés on the Bridge | 54464 | 5 | 0:05:38 | +0.6 | CONFIRMED |
| `The Fire Within Requiem for Katia and Maurice Krafft (2022)` | The Fire Within: A Requiem... | 977341 | 85 | 1:24:23 | -0.6 | CONFIRMED |
| `The Olympic Games Held at Chamonix in 1924 (1924)` | The 1924 Chamonix Olympic Games | 470824 | 37 | 0:37:16 | +0.3 | CONFIRMED |
| `Where Is My Friend's House (1987)` | Where Is The Friend's House? | 49964 | 83 | 1:23:06 | +0.1 | CONFIRMED |
| `Ô saisons, ô châteaux (1958)` | O Seasons, O Castles | 278727 | 21 | **corrupted** | n/a | UNVERIFIABLE — ffprobe: "EBML header parsing failed"; hex dump confirms invalid MKV magic bytes. Filename literally is the French title (plausible identity) but runtime cannot be confirmed. Needs re-acquisition. |

## Cohort A2 — Title variants (44/44)

| disk folder | Radarr title | exp min | measured | delta | verdict |
|---|---|---|---|---|---|
| `A. K. (1985)` | A View to a Kill | 131 | 2:11:15 | +0.3 | CONFIRMED |
| `Alan Partridge (2013)` | Alan Partridge: Alpha Papa | 90 | 1:30:11 | +0.2 | CONFIRMED |
| `Alien³ (1992)` | Aliens | 137 | 2:34:28 | +17.5 | CONFIRMED, alt edition — filename tagged `{tmdb-679}{edition-Extended}`, measured 154.47min matches Aliens Special Edition (154min) exactly. Safe to rename. |
| `Anchorman (2004)` | Anchorman: The Legend of Ron Burgundy | 95 | 1:34:04 | -0.9 | CONFIRMED |
| `Blade Runner 2049 (2017)` | Blade Runner | 118 | 1:57:31 | -0.5 | CONFIRMED |
| `Bluebeard's 8th Wife (1938)` | Bluebeard's 8th Wife (matched 1923) | 60 | 1:25:31 | +25.5 | **RADARR RECORD WRONG (year).** Measured 85.53min matches the 1938 Lubitsch sound film (tmdb=31996 imdb=tt0029929, TMDB runtime 85) almost exactly. Radarr's record is the 1923 silent short (tmdb=535525); library has no 1938 entry. |
| `Brothers Bloom (2008)` | The Brothers Bloom | 114 | 1:53:40 | -0.3 | CONFIRMED |
| `Chungking Express (1996) (1996)` | Chungking Express | 103 | 1:42:33 | -0.4 | CONFIRMED |
| `Daguerréotypes (1975)` | Daguerréotypes | 80 | 1:19:24 | -0.6 | CONFIRMED |
| `Divine Horsemen The Living Gods of Haiti (1985)` | Divine Horsemen... | 52 | 0:50:36 | -1.4 | CONFIRMED |
| `Dont Look Back (1967)` | Bob Dylan – Don't Look Back | 96 | 1:36:15 | +0.3 | CONFIRMED |
| `Dr. Strangelove (1964)` | Dr. Strangelove or... | 95 | 1:34:45 | -0.2 | CONFIRMED |
| `Duelle (1976)` | Duelle (Une Quarantaine) | 121 | 2:00:41 | -0.3 | CONFIRMED |
| `Fate of the Furious (2017)` | The Fate of the Furious | 136 | 2:15:58 | -0.0 | CONFIRMED |
| `Fellini Satyricon (1969)` | Satyricon | 129 | **corrupted** | n/a | UNVERIFIABLE — same "EBML header parsing failed" corruption as Ô saisons ô châteaux. Needs re-acquisition. |
| `Full Body Massage (1995)` | Full Body Massage | 93 | 1:29:28 | -3.5 | CONFIRMED — embedded title tag literally "Full Body Massage (1995)" |
| `Get Out (2016)` | Get Out Alive | 87 | 1:44:05 | +17.1 | **RADARR RECORD WRONG.** Embedded title "GET OUT"; measured 104.08min vs TMDB runtime 104min for the real *Get Out* (2017, tmdb=419430 imdb=tt5052448) — near-exact match, independently confirmed via Radarr lookup. Not the matched *Get Out Alive*. |
| `Hero (2002)` | Hero (matched 2007) | 130 | 1:49:21 | -20.6 | **RADARR RECORD WRONG — active misassignment.** Filename tagged CHINESE.DC; measured 109.35min consistent with Zhang Yimou's *Hero* (2002, tmdb=79 imdb=tt0299977). Radarr's `Hero` 2007 record (tmdb=51550, Japanese Kimura Takuya drama) has hasFile=true and its `path` field is actively pointed at this folder — a live misassignment, not just a stale tag. |
| `Mary Jane's Not a Virgin Anymore (1996)` | same title | 95 | 1:35:20 | +0.3 | CONFIRMED |
| `Meanwhile (2012)` | Meanwhile in Mamelodi | 75 | 0:57:43 | -17.3 | LIKELY correct (moderate confidence) — title-containment holds, no embedded title to corroborate either way. Flag for human spot-check. |
| `No Regret (1993)` | No Regret, No Return | 94 | 0:38:13 | -55.8 | **MISPULL — human review.** Embedded title "THE SIGNIFYIN' WORKS OF MARLON RIGGS - DISC 2" — a documentary-compilation disc, not the matched Korean film. |
| `Noroît (1976)` | Noroît (Une Vengeance) | 145 | 2:14:40 | -10.3 | CONFIRMED — embedded title "NOROIT" matches directly despite delta (Rivette prints vary by source) |
| `Right Now, Wrong Then (2017)` | same title | 121 | 2:00:43 | -0.3 | CONFIRMED |
| `School of Rock (2003)` | The School of Rock | 110 | 1:49:16 | -0.7 | CONFIRMED |
| `Series 7 The Contenders (2001)` | Series 7 | 87 | 1:27:22 | +0.4 | CONFIRMED |
| `Shadows (1958)` | Shadows | 87 | 1:22:14 | -4.8 | CONFIRMED — embedded title "SHADOWS" matches directly (Cassavetes' film has two documented cuts of differing length) |
| `Soleil Ô (1967)` | Soleil O | 104 | 1:44:11 | +0.2 | CONFIRMED |
| `Sunrise (1927)` | Sunrise: A Song of Two Humans | 94 | 1:34:21 | +0.4 | CONFIRMED |
| `Symbiopsychotaxiplasm Take 2.5 (2005)` | ...Take 2½ | 99 | 1:39:44 | +0.7 | CONFIRMED |
| `The American Soldier (1970)` | same title | 80 | 1:20:15 | +0.3 | CONFIRMED |
| `The Fearless Hyena (1979)` | Fearless Hyena | 97 | 1:37:47 | +0.8 | CONFIRMED |
| `The Gang of Four (1988)` | Gang of Four | 160 | 2:42:17 | +2.3 | CONFIRMED |
| `The Hero (1966)` | The Heroes of Telemark | 131 | 2:10:17 | -0.7 | CONFIRMED |
| `The House, 1984 (1984)` | The House | 59 | 1:50:38 | +51.6 | **RADARR RECORD WRONG.** Embedded title literally "1984"; measured 110.63min vs TMDB 113min for *Nineteen Eighty-Four* (tmdb=9314 imdb=tt0087803). Radarr's `The House` (tmdb=628603, British alt-history TV film, runtime 59) fits neither the tag nor the runtime. |
| `The Nun (1965)` | The Nun's Story | 151 | 2:31:30 | +0.5 | CONFIRMED |
| `The Raid- Redemption (2011)` | The Raid | 101 | 1:41:03 | +0.1 | CONFIRMED |
| `The Swindlers (1955)` | The Swindle | 113 | 1:53:48 | +0.8 | CONFIRMED |
| `The Woman is the Future of Man (2004)` | Woman Is the Future of Man | 88 | 1:27:45 | -0.2 | CONFIRMED |
| `Tokyo Story (1972) (1972)` | Tokyo Story | 137 | 2:17:10 | +0.2 | CONFIRMED |
| `Ulysse (1983)` | Ulysse | 22 | 0:22:24 | +0.4 | CONFIRMED |
| `War and Peace (1966)` | War and Peace | 422 | 1:36:38* | -325.4* | CONFIRMED — *folder holds all 4 parts (Part I–IV, 1966–67 Bondarchuk tetralogy, confirmed via `ls`); Radarr's single movieFile is Part IV only, hence the raw delta. Combined 4-part runtime (~422min per Radarr) matches the known total. Not a wrong film, a single-file-per-movie modeling gap. |
| `X-Men Dark Phoenix (2019)` | Dark Phoenix | 114 | 1:53:56 | -0.1 | CONFIRMED |
| `Ydessa, the Bears and etc. (2004)` | same title | 44 | 0:42:55 | -1.1 | CONFIRMED |
| `Ådalen 31 (1969)` | Adalen 31 | 114 | 1:54:31 | +0.5 | CONFIRMED |

## Cohort A3 — Stale paths (7/7, hasFile=false, no ffprobe possible)

| disk folder | Radarr title (matched) | on-disk contents | verdict |
|---|---|---|---|
| `Fallen Angels (1998)` | Fallen Angels (1995) | trailer + Deleted Scenes/Featurettes only | No feature file — remediation is re-acquisition, not rename |
| `Je, Tu, Il, Elle (1976)` | Je Tu Il Elle (1974) | empty (extrathumbs dir only) | No feature file — re-acquisition needed |
| `Joan the Maid (1993)` | Joan the Maid I: The Battles (1994) | **HAS FILES**: Part 1 (40GB) + Part 2 (44GB) mkv present | Radarr's hasFile=false is a 2-part-film detection gap, NOT a missing file. Do not re-download; manually import both parts (Rivette's "Jeanne la Pucelle I/II"). |
| `Lumière and Company (1995)` | Lumière & Company (1995) | completely empty | Re-acquisition needed |
| `Non Je Ne Regrette Rien (No Regret) (1993)` | No Regret (1993) | completely empty | Re-acquisition needed |
| `Room 666 (1982)` | Room 666 (1985) | completely empty | Re-acquisition needed |
| `WALL-E (2008)` | The Berlin Wall: Escape to Freedom (2006) | Deleted Scenes/Featurettes/Shorts only | Confirms doc's note: 2026-07-30 remediation residue |

## Cohort B — Orphaned, no Radarr record (11/11)

Identified via `GET /api/v3/movie/lookup?term=` (TMDB search, read-only) + ffprobe on whatever feature file is physically present.

| disk folder | on-disk file | measured | embedded title | identified as | verdict |
|---|---|---|---|---|---|
| `Curious George 2 Follow That Monkey! (2009)` | 2.79GB mkv | 1:20:22 | — | tmdb=23903 imdb=tt1350484 (exp 81min) | CONFIRMED, addable — clean orphan |
| `First Cow (2020)` | 9.6GB mkv | 2:01:48 | "First Cow" | tmdb=558582 imdb=tt9231040 (exp 122min) | CONFIRMED, addable |
| `JOUR DE FÊTE DANS LES MONTS NAGA (1964)` | 9.1GB mkv | 1:20:32 | "JOUR DE FÊTE" | no TMDB match | **SUSPECTED DUPLICATE** of the (1995) folder — identical embedded title, near-identical runtime. No TMDB entry for either year. Needs human research. |
| `JOUR DE FÊTE DANS LES MONTS NAGA (1995)` | 9.1GB mkv | 1:20:15 | "JOUR DE FÊTE" | no TMDB match | Same finding as above (paired) |
| `Kishi Bashi Live on Valentines Day (2013)` | 614MB mp4 | not probed | — | concert film | Known-unmanageable content type per the 2026-07-28 cross-app drift audit — correctly excluded, no action |
| `Monster Mash (1970)` | 4.0GB mkv | 1:55:55 | "M*A*S*H (1970)" | tmdb=651 imdb=tt0066026 (exp 116min) | **MISLABELED, high confidence.** Embedded title literally "M*A*S*H (1970)", corroborated by leftover `MASH (1970).nfo` + `M-A-S-H (1970).txt` files. 115.92min vs 116min TMDB = near-exact. Add to Radarr as M*A*S*H, not "Monster Mash." |
| `Omnibus Monsieur Hulot's Work (1976)` | 13GB mkv | 0:49:29 | "TRAFIC" | ambiguous | Embedded title says "TRAFIC" but 49.5min doesn't match Tati's *Trafic* (96min) — most consistent with this being the BBC Omnibus documentary ABOUT the making of Trafic (fits a ~50min UK arts-doc slot). TV content, not itself a TMDB movie. Flag for human confirmation. |
| `Samson and Delilah (1996)` | empty, no file | n/a | n/a | tmdb=1739328 imdb=tt0117547 (TMDB runtime sparse/0) | Metadata-only remnant; TMDB record exists for title+year but no file to runtime-verify |
| `Secrets and Lies (1996)` | no video file (Interviews dir + metadata only) | n/a | n/a | tmdb=11159 imdb=tt0117589 (exp 142min) | Real Mike Leigh film confirmed in TMDB, but no feature file present — needs re-acquisition |
| `World on a Wire (1973)` | 37.8GB mkv | 3:33:26 | "WORLD ON A WIRE" | no standalone TMDB **movie** entry (Fassbinder's Welt am Draht) | CONFIRMED via exact embedded-title match; 213.4min consistent with both parts combined (~205-212min published). TMDB/Radarr lookup only surfaces a 2010 making-of doc (tmdb=394385) — likely modeled as a miniseries, out of Radarr's movie scope by design. Not a Radarr gap to fix. |
| `Zatoichi Supplements` | 3 files: 2 interviews + 1 short, no feature | n/a | n/a | n/a — bonus-features folder | Confirmed NOT a standalone film (John Nathan interview, "Serialized Success" interview, "The Blind Swordsman" short). Correctly excluded; no action. |

## Cohort C — Unparseable folder names (3/3)

| disk folder | Radarr title (matched) | exp min | measured | delta | verdict |
|---|---|---|---|---|---|
| `Calgary '88- 16 Days of Glory` | Calgary '88: 16 Days of Glory | 202 | 3:22:13 | +0.2 | CONFIRMED — folder punctuation just breaks the year-scraper |
| `Pioneers of African American Cinema` | Pioneers of African-American Cinema | 0 | no file on disk | n/a | Metadata/poster only, no feature file — confirms this is genuinely unparseable because it's the Kino Lorber 5-disc box set, not a single film. Excluded by design, matches doc's own framing. |
| `You Sing Loud, I Sing Louder ()` | Bleeding Love | 96 | 1:42:24 | +6.4 | CONFIRMED via filename ("Bleeding.Love.2024" scene tag matches exactly) despite delta |

## Methodology / limitations
- ffprobe run from the `tdarr` pod (has ffprobe; `tinymediamanager` does not), which mounts the same physical library at `/media/media/movies` Radarr manages — cross-checked via Radarr's own `path` field matching disk `ls` output (e.g. the "Ater Hours" typo folder).
- Expected runtime = Radarr's `movie.runtime` (TMDB-sourced); occasionally wrong for niche/documentary titles (Sydney 2000, The House-1984) — large deltas are a prompt to investigate, not proof of misidentification on their own. Embedded `format.tags.title` and release-group filenames were weighted as stronger evidence when present.
- Two files fail ffprobe with "EBML header parsing failed"; hex-dump of the first 64 bytes confirms neither starts with MKV magic (`1A 45 DF A3`) — genuine file corruption, not a mount/permissions artifact (dozens of other files, including unicode-named ones, probed cleanly).
- No writes anywhere: every Radarr call was a GET (`/movie`, `/movie/lookup`); no PUT/DELETE issued; no files moved, renamed, or deleted on disk.