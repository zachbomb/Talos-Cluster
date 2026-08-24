# TV Identity Manifest

Generated 2026-08-24T21:39:41 from Sonarr at 192.168.10.211.

Step 1 of SQ-58 — verify identity AT THE FILE, then propagate upward. This report changes nothing; it never renames, moves or deletes.

## Coverage — read the denominators before the counts

| Metric | Count |
|---|---|
| Series scanned | 152 |
| Episodes with a file | 8206 |
| Episodes with no file | 5936 |
| Runtime cross-check possible | 8006 |
| — no TVDB runtime (unverifiable) | 44 |
| — no mediainfo runtime (unverifiable) | 57 |
| Shift check possible | 812 |
| — name already matches own title (BLIND SPOT) | 7384 |
| — multi-episode file (unjudgeable) | 10 |

**The shift rate is 1 of 812 assessable = 0.1%, NOT 1 of 8196.** Where Sonarr has renamed a file its numbering is baked into the name, so a shift there is invisible to that method. A clean result on a renamed series is not evidence of correctness.

## Findings

| Signal | Count |
|---|---|
| Runtime TOO-SHORT (ratio <0.55 — content missing) | 66 |
| Runtime LONG (1.15-1.60) | 99 |
| DOUBLE-EPISODE or EXTENDED (ratio >=1.60 — usually legitimate) | 221 |
| Within ad-break band (NORMAL) | 7620 |
| Positional shifts | 1 |
| **Both signals on one file** | **0** |

A file carrying BOTH signals is the strongest evidence available here — the name says one episode and the duration disagrees too.

## TOO-SHORT — content missing or wrong episode (66)

Ratio below 0.55: shorter than ad breaks can explain. **These are the real errors.**

| Series | S/E | Sonarr title | Expected | Actual | Δ | Note |
|---|---|---|---|---|---|---|
| Top Chef (FR) | S16E11 | Épisode 11 : 24 heures au palace | 156m | 31m | -125m |  |
| Top Chef (FR) | S15E03 | Émission 3 | 120m | 51m | -69m |  |
| Top Chef (FR) | S15E06 | Émission 6 | 120m | 51m | -69m |  |
| Top Chef (FR) | S15E09 | Émission 9 | 120m | 52m | -68m |  |
| American Masters | S30E05 | Loretta Lynn: Still a Mountain Girl | 120m | 53m | -67m |  |
| Top Chef (FR) | S15E10 | Émission 10 | 120m | 56m | -64m |  |
| Top Chef (FR) | S15E04 | Émission 4 | 120m | 57m | -63m |  |
| Top Chef (FR) | S15E02 | Émission 2 | 120m | 59m | -61m |  |
| Top Chef (FR) | S15E05 | Émission 5 | 120m | 60m | -60m |  |
| Top Chef (FR) | S15E08 | Émission 8 | 120m | 62m | -58m |  |
| Top Chef (FR) | S15E12 | Émission 12 | 120m | 65m | -55m |  |
| American Masters | S25E02 | Troubadors: Carole King/James Taylor & t | 101m | 53m | -48m |  |
| Top Chef | S18E14 | The Next Top Chef Is ... | 90m | 44m | -46m |  |
| American Masters | S23E07 | Joan Baez: How Sweet the Sound | 90m | 49m | -41m |  |
| The Kids in the Hall | S04E18 | #418 | 60m | 22m | -38m |  |
| The Kids in the Hall | S04E09 | #409 - Chalet 2000 | 60m | 23m | -37m |  |
| The Kids in the Hall | S03E20 | #320 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E07 | #507 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E10 | #510 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E17 | #517 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E19 | #519 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E08 | #508 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E09 | #509 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E11 | #511 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E12 | #512 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E13 | #513 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E14 | #514 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E15 | #515 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E16 | #516 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E18 | #518 | 60m | 23m | -37m |  |
| The Kids in the Hall | S05E20 | #520 | 60m | 23m | -37m |  |
| The Kids in the Hall | S04E13 | #413 | 60m | 23m | -37m |  |
| The Kids in the Hall | S02E01 | #201 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E06 | #406 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E07 | #407 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E08 | #408 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E10 | #410 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E12 | #412 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E14 | #414 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E15 | #415 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E16 | #416 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E17 | #417 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E19 | #419 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E11 | #411 | 60m | 24m | -36m |  |
| The Kids in the Hall | S04E20 | #420 | 60m | 24m | -36m |  |
| Come Dine With Me New Zealand | S01E09 | Episode 9 | 30m | 1m | -29m |  |
| It's Always Sunny in Philadelphia | S06E13 | A Very Sunny Christmas | 45m | 20m | -25m |  |
| Come Dine With Me Australia | S02E19 | Week 4: Kate | 45m | 20m | -24m |  |
| Come Dine With Me Australia | S02E11 | Week 3: Dominic | 45m | 21m | -24m |  |
| Come Dine With Me Australia | S02E12 | Week 3: Michelle | 45m | 23m | -22m |  |
| Come Dine With Me Australia | S03E18 | Week 4: Gerald | 45m | 23m | -22m |  |
| Come Dine With Me Australia | S03E17 | Week 4: Jacki | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S01E03 | Week 1: Ben | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S03E14 | Week 3: Lachlan | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S02E18 | Week 4: Karen | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S02E17 | Week 4: David | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S03E19 | Week 4: Bromwyn | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S03E16 | Week 4: Suze | 45m | 24m | -21m |  |
| Come Dine With Me Australia | S03E15 | Week 3: Warren | 45m | 25m | -20m |  |
| Come Dine With Me Australia | S01E06 | Week 2: Trudi | 45m | 25m | -20m |  |

## DOUBLE-EPISODE or EXTENDED (221)

Ratio >=1.60 — usually a legitimate double episode or feature-length special. Verify; do NOT 'correct' these.

| Series | S/E | Sonarr title | Expected | Actual | Δ | Note |
|---|---|---|---|---|---|---|
| Top Chef (FR) | S16E12 | Épisode 12 : Le choc des titans | 127m | 238m | +111m |  |
| Tim and Eric Awesome Show, Great Job! | S04E01 | Snow | 15m | 122m | +107m |  |
| imagine... | S23E05 | The One and Only Mike Leigh | 50m | 111m | +61m |  |
| ER | S03E10 | Homeless for the Holidays | 45m | 106m | +61m |  |
| ER | S03E11 | Night Shift | 45m | 104m | +59m |  |
| ER | S03E17 | Tribes | 45m | 104m | +59m |  |
| ER | S03E03 | Don't Ask, Don't Tell | 45m | 104m | +59m |  |
| ER | S03E05 | Ghosts | 45m | 104m | +59m |  |
| Come Dine With Me Australia | S02E01 | Week 1: Helen | 45m | 98m | +53m |  |
| imagine... | S25E01 | Shylock's Ghost | 50m | 102m | +52m |  |
| NOVA | S37E08 | Telescope: Hunting the Edge of Space - T | 60m | 112m | +52m |  |
| imagine... | S26E06 | Serial Killers - The Women Who Write Cri | 50m | 100m | +50m |  |
| imagine... | S28E05 | Rachel Whiteread: Ghost in the Room | 50m | 93m | +43m |  |
| Come Dine with Me | S2026E20 | Bedfordshire / Cambridgeshire, Michaela  | 23m | 65m | +42m |  |
| imagine... | S23E02 | The Art That Hitler Hated: The Sins of t | 50m | 91m | +41m |  |
| imagine... | S27E03 | Alice Neel: Dr Jekyll And Mrs Hyde | 50m | 90m | +40m |  |
| imagine... | S21E02 | McCullin | 50m | 89m | +39m |  |
| imagine... | S21E01 | Vivian Maier - Who Took Nanny's Pictures | 50m | 89m | +39m |  |
| imagine... | S24E01 | Frank Gehry: The Architect Says | 50m | 89m | +39m |  |
| imagine... | S23E06 | Colm Toibin: His Mother's Son | 50m | 84m | +34m |  |
| imagine... | S30E04 | Edna O'Brien, Fearful and Fearless | 50m | 84m | +34m |  |
| imagine... | S22E02 | Philip Roth Unleashed, Part One | 50m | 83m | +33m |  |
| imagine... | S24E03 | Beware of Mr Baker | 50m | 83m | +33m |  |
| Iron Chef | S05E38 | 1997 World Cup | 45m | 76m | +31m |  |
| Charlie Brooker's Weekly Wipe | S02E01 | Episode 1 | 30m | 59m | +29m |  |
| Come Dine With Me Australia | S02E09 | Week 2: David | 45m | 73m | +28m |  |
| Come Dine with Me | S2013E32 | All in One: Bristol | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E59 | All in One: Kings Lynn | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E43 | All in One: North Kent Coast | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E111 | All in One: North Hertfordshire | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E120 | All in One: Salford | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E121 | All in One: East Dorset | 25m | 48m | +23m |  |
| Come Dine with Me | S2014E04 | All in One: Bristol | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E02 | All in One: Wrexham | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E123 | All in One: Ealing, London | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E49 | All in One: Chesterfield | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E67 | All in One: Surrey | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E119 | All in One: Loughborough | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E65 | All in One Burnley | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E105 | All in One: Guernsey | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E108 | All in One: Staffordshire | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E115 | All in One: Mid Cornwall | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E118 | All in One: Worcester | 25m | 48m | +23m |  |
| Come Dine with Me | S2013E20 | All in One: Barnsley | 25m | 48m | +22m |  |
| Come Dine with Me | S2014E05 | All in One: Worcestershire | 25m | 48m | +22m |  |
| Come Dine with Me | S2013E26 | All in One: Edinburgh | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E114 | All in One: West Lancashire Coast | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E08 | All in One: East Coast of Yorkshire | 25m | 47m | +22m |  |
| Come Dine with Me | S2014E03 | All in One: Suffolk | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E55 | All in One: Chippenham | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E63 | All in One: Kensington And Chelsea | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E73 | All in One: Cumbria | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E107 | All in One: North Norfolk | 25m | 47m | +22m |  |
| Come Dine with Me | S2014E01 | All in One: South Oxfordshire | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E116 | All in One: Southampton | 25m | 47m | +22m |  |
| Come Dine with Me | S2014E02 | All in One: Northumberland | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E64 | All in One: Turnbridge Wells | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E117 | All in One: High Wycombe | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E14 | All in One: Lake District | 25m | 47m | +22m |  |
| Come Dine with Me | S2013E66 | All in One: Banbury | 25m | 47m | +22m |  |

## LONG — longer than a single cut should be (99)

| Series | S/E | Sonarr title | Expected | Actual | Δ | Note |
|---|---|---|---|---|---|---|
| Top Chef (FR) | S16E05 | Épisode 5 : Face à face avec les inspect | 116m | 179m | +63m |  |
| Top Chef (FR) | S16E09 | Épisode 9 : La guerre des restos | 111m | 170m | +59m |  |
| Top Chef (FR) | S16E08 | Épisode 8 : Je cuisine ce que je suis | 112m | 170m | +58m |  |
| American Masters | S27E01 | Sister Rosetta Tharpe: The Godmother of  | 90m | 143m | +53m |  |
| Top Chef (FR) | S16E10 | Épisode 10 : Fâce à l'étoile suprême | 117m | 167m | +50m |  |
| Top Chef (FR) | S17E05 | The MOFs - Jules Verne Circus in Amiens | 109m | 158m | +49m |  |
| Top Chef (FR) | S16E04 | Épisode 4 : Goûtez-moi ce plat magique ! | 110m | 158m | +48m |  |
| Top Chef (FR) | S17E03 | Tribute to Paul Bocuse - Collonges Abbey | 111m | 159m | +48m |  |
| Top Chef (FR) | S09E01 | TBA | 120m | 167m | +47m |  |
| Top Chef (FR) | S10E01 | TBA | 120m | 164m | +44m |  |
| Top Chef (FR) | S08E01 | TBA | 120m | 163m | +43m |  |
| Top Chef (FR) | S04E11 | TBA | 120m | 157m | +37m |  |
| American Masters | S24E04 | Merle Haggard: Learning to Live with Mys | 82m | 116m | +34m |  |
| imagine... | S28E03 | Alma Deutscher: Finding Cinderella | 50m | 77m | +27m |  |
| imagine... | S26E02 | Georgia O'Keeffe: By Myself | 50m | 76m | +26m |  |
| American Masters | S31E02 | Maya Angelou: And Still I Rise | 90m | 115m | +25m |  |
| imagine... | S26E04 | The Seven Killings of Marlon James | 50m | 74m | +24m |  |
| imagine... | S20E02 | Do or Die: Lang Lang's Story | 50m | 74m | +24m |  |
| American Masters | S30E02 | B.B. King: The Life of Riley | 90m | 114m | +24m |  |
| imagine... | S21E05 | Woody Allen: A Documentary - Part Two | 50m | 74m | +24m |  |
| American Masters | S32E01 | Lorraine Hansberry: Sighted Eyes/Feeling | 90m | 114m | +24m |  |
| American Masters | S25E08 | Woody Allen: A Documentary (2) | 90m | 113m | +23m |  |
| American Masters | S30E06 | Janis: Little Girl Blue | 90m | 113m | +23m |  |
| American Masters | S22E04 | You Must Remember This - The Warner Bros | 60m | 83m | +23m |  |
| American Masters | S24E02 | I.M. Pei: Building China Modern | 60m | 83m | +23m |  |
| American Masters | S23E04 | Neil Young: Don't Be Denied | 60m | 83m | +23m |  |
| American Masters | S34E08 | Keith Haring: Street Art Boy | 60m | 83m | +23m |  |
| American Masters | S25E04 | James Levine: America's Maestro | 60m | 83m | +23m |  |
| American Masters | S24E06 | A Letter to Elia | 90m | 113m | +23m |  |
| American Masters | S26E06 | The Day Carl Sandburg Died | 90m | 113m | +23m |  |
| American Masters | S25E05 | Pearl Jam Twenty | 90m | 113m | +23m |  |
| American Masters | S22E07 | You Must Remember This - The Warner Bros | 60m | 83m | +23m |  |
| imagine... | S29E04 | Tacita Dean: Looking to See | 50m | 73m | +23m |  |
| American Masters | S28E06 | Tanaquil Le Clercq: Afternoon of a Faun | 92m | 113m | +21m |  |
| Top Chef (ES) | S04E08 | TBA | 90m | 110m | +20m |  |
| Out 1 | S01E02 | From Thomas to Frederique | 90m | 110m | +20m |  |
| imagine... | S23E01 | The Art That Hitler Hated | 50m | 70m | +20m |  |
| imagine... | S24E04 | Toni Morrison Remembers | 50m | 69m | +19m |  |
| Out 1 | S01E03 | From Frederique to Sarah | 90m | 108m | +18m |  |
| imagine... | S20E04 | The Many Lives of William Klein | 50m | 68m | +18m |  |
| Eight Hours Don't Make A Day | S01E01 | Jochen and Marion | 90m | 107m | +17m |  |
| imagine... | S20E07 | A Beauty is Born: Matthew Bourne's Sleep | 50m | 67m | +17m |  |
| imagine... | S28E07 | Philip Pullman: Angels and Daemons | 50m | 67m | +17m |  |
| Out 1 | S01E04 | From Sarah to Colin | 90m | 106m | +16m |  |
| imagine... | S20E03 | Lang Lang | 50m | 66m | +16m |  |
| Babylon Berlin | S03E12 | Episode 28 | 45m | 61m | +16m |  |
| imagine... | S30E02 | Jo Brand: No Holds Barred | 50m | 66m | +16m |  |
| Top Chef (ES) | S03E01 | TBA | 90m | 106m | +16m |  |
| imagine... | S27E02 | Maya Angelou: And Still I Rise | 50m | 66m | +16m |  |
| imagine... | S28E06 | Mel Brooks: Unwrapped | 50m | 66m | +16m |  |
| The Venture Bros. | S05E01 | What Color Is Your Cleansuit? | 30m | 45m | +15m |  |
| imagine... | S28E01 | Mapplethorpe: Look at the Pictures | 50m | 65m | +15m |  |
| Eight Hours Don't Make A Day | S01E02 | Oma and Gregor | 90m | 105m | +15m |  |
| imagine... | S30E03 | Bill Viola: The Road to St Paul's | 50m | 65m | +15m |  |
| imagine... | S26E05 | The Triumph and Laments of William Kentr | 50m | 64m | +14m |  |
| imagine... | S21E04 | Woody Allen: A Documentary - Part One | 50m | 64m | +14m |  |
| imagine... | S26E03 | Sir Roderick Stewart: Can't Stop Me Now | 50m | 64m | +14m |  |
| imagine... | S25E03 | My Curious Documentary | 50m | 64m | +14m |  |
| Come Dine With Me Australia | S02E16 | Week 4: Megan | 45m | 58m | +13m |  |
| imagine... | S25E02 | Antony Gormley: Being Human | 50m | 63m | +13m |  |

## Positional shifts without a runtime signal (1)

| Series | S/E | Sonarr says | File says | Offset |
|---|---|---|---|---|
| Carlos | S01E03 | Episode 3 | Episode 1 | -2 |

## Same-title series — revivals are DIFFERENT WORKS

| Title | Entries | Distinct tvdbId | Distinct folder |
|---|---|---|---|
| clone high | Clone High (2002, Cartoon Network (CA), 13 files); Clone High (2023) (2023, HBO Max, 20 files) | yes | yes |
| the kids in the hall | The Kids in the Hall (1989, CBC, 101 files); The Kids in the Hall (2022) (2022, Prime Video, 8 files) | yes | yes |

Distinct on both axes means the split is correct. A **NO** in either column means a revival and its original may be sharing an identity — that is how a 2022 episode ends up filed under a 1989 series.

## Regional variants — same format, DIFFERENT productions

The exact-title check does not catch these: the country suffix makes the titles differ. They are separate productions and must never be merged.

| Franchise | Variants | Distinct tvdbId |
|---|---|---|
| top chef | FR 2010 (M6, 103 files); GR 2010 (Skai, 0 files); ES 2013 (Antena 3, 4 files); SA 2016 (MBC Shahid, 0 files); (orig) 2006 (Bravo, 343 files) | yes |
| taskmaster | US 2018 (Comedy Central, 8 files); AU 2023 (Network 10, 50 files); NZ 2020 (TVNZ 2, 60 files); (orig) 2015 (Channel 4, 230 files) | yes |
| come dine with me | CA 2010 (None, 0 files); IR 2010 (Manoto TV, 0 files); (orig) 2005 (Channel 4, 810 files) | yes |

## Spinoffs — a shared base title does NOT mean a shared show

| Base series | Derived |
|---|---|
| Destination Flavour | Destination Flavour China (2018, 10 files); Destination Flavour Down Under (2014, 10 files); Destination Flavour Japan (2013, 10 files); Destination Flavour Scandinavia (2016, 7 files); Destination Flavour Singapore (2017, 9 files) |
| Top Chef | Top Chef Amateurs (2021, 12 files); Top Chef Canada (2011, 115 files); Top Chef Duels (2014, 10 files); Top Chef Suomi (2011, 0 files); Top Chef: Masters (2009, 50 files) |
| Come Dine with Me | Come Dine With Me Australia (2010, 52 files); Come Dine With Me New Zealand (2015, 40 files); Come Dine with Me: The Professionals (2022, 40 files) |
| Come Dine With Me | Come Dine With Me Australia (2010, 52 files); Come Dine With Me New Zealand (2015, 40 files); Come Dine with Me: The Professionals (2022, 40 files) |
| Taskmaster | Taskmaster: Champion of Champions (2017, 5 files) |

These are separate shows sharing a franchise name. Merging them, or letting one scrape over the other, mixes unrelated episode numbering.

## Network transfers and syndication — shifts that are NOT misfiles

A series that changed network mid-run, or was re-ordered for syndication, gets renumbered by TVDB relative to release-group numbering. That produces exactly the positional-shift signature while nothing is wrong with the files. Known cases in this library: **Futurama** (Fox to Comedy Central to Hulu), **King of the Hill** (Fox, plus the Hulu revival), **The French Chef** (1960s syndication). Correcting these means re-linking to the right episode record — **never** renaming or moving a file.

## What must happen next, and in this order

1. Triage LONGER results — double episodes and extended cuts are legitimate.
2. Correct Sonarr identities for confirmed errors (no file operations).
3. **Then** delete and re-fetch subtitles for corrected episodes. Doing this before step 2 makes Bazarr re-download the same wrong ones under the same wrong identity.
4. **Then** scan TV into TMM and scrape — TMM owns TV metadata and writes the NFOs Plex/Emby read, so scraping earlier makes unverified identities authoritative.
5. **Then** refresh the players and relink Tunarr.
