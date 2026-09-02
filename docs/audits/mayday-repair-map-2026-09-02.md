# Mayday repair map — 2026-09-02

**READ-ONLY analysis. No files have been renamed, moved, or re-downloaded.**

## Summary

```
240 episodes · 209 with subtitles at time of run
MATCH 79 · MISFILED 95 · AMBIGUOUS 35 · NO-SRT 31
confident repair rows: 84      contested (>1 claimant): 11
```

## The dominant pattern: season+1

32 of the 84 confident rows are the SAME episode number, one season later.
Mayday has genuinely different season boundaries across broadcasters
(Discovery Canada / National Geographic / UK), so a release numbered by one
convention lands a whole season out of step with TVDB. Sonarr matches on the
SxxExx NUMBER, ignores the title, and renames the file — destroying the evidence.

## Per-season assessment

| Season | verdict |
|---|---|
| S15 | FULLY MISFILED |
| S16 | FULLY MISFILED |
| S17 | FULLY MISFILED |
| S18 | FULLY MISFILED |
| S19 | FULLY MISFILED |
| S20 | FULLY MISFILED |
| S22 | FULLY MISFILED |
| S24 | FULLY MISFILED |
| S25 | FULLY MISFILED |
| S08 | FULLY MISFILED (1 checkable) |
| S14 | 8 of 10 bad |
| S26 | 6 of 8 bad |
| S03 | 2 of 11 bad |
| S04 | 2 of 9 bad |
| S10 | 1 of 6 bad |
| S11 | 2 of 8 bad |
| S12 | 2 of 10 bad |
| S05 | CLEAN |
| S09 | CLEAN |
| S13 | CLEAN |
| S21 | CLEAN |
| S23 | CLEAN |
| S01 | no subtitles — unchecked |
| S02 | no subtitles — unchecked |
| S06 | no subtitles — unchecked |
| S07 | no subtitles — unchecked |

## Confident repair rows

| filed as | actually is | score | identified by (term, corpus freq) |
|---|---|---|---|
| S11E06 | S13E04 | 10.2 | queens(2), 587(2) |
| S12E08 | S05E02 | 13.5 | 96(7), turkish(9), 981(2) |
| S12E10 | S05E08 | 10.2 | 401(3), eastern(17), distraction(22) |
| S14E02 | S15E09 | 17.4 | nations(5), ndola(1), dc-(39), mission(40) |
| S14E04 | S10E04 | 5.9 | 751(2) |
| S14E05 | S15E03 | 17.7 | asiana(1), francisco(4), 214(1), san(12) |
| S14E06 | S15E04 | 11.1 | 2311(1), atlantic(21), southeast(19) |
| S14E07 | S15E05 | 6.5 | 1862(1) |
| S14E08 | S15E06 | 11.6 | 5925(1), express(13), transmission(18) |
| S14E09 | S15E10 | 11.2 | spanair(1), 5022(1) |
| S14E10 | S15E08 | 18.7 | sao(3), 402(1), tam(2), paulo(3) |
| S15E02 | S16E02 | 10.2 | 77(6), attack(47), pentagon(3) |
| S15E03 | S16E03 | 19.6 | klm(4), 4805(1), 1736(2), tenerife(6) |
| S15E05 | S16E05 | 14.3 | proteus(1), 706(2), detour(4) |
| S15E06 | S07E08 | 11.9 | freeze(13), eagle(7), 4184(2) |
| S15E08 | S16E08 | 14.5 | indonesia(14), river(27), garuda(3), 421(2) |
| S15E09 | S16E09 | 13.8 | indonesia(14), airasia(1), 8501(1) |
| S16E01 | S17E01 | 13.0 | airlink(1), 5719(1), northwest(31) |
| S16E02 | S17E02 | 14.3 | myth(1), comair(4), 3272(2) |
| S16E03 | S17E03 | 7.7 | china(23), 129(3) |
| S16E05 | S17E05 | 11.2 | indonesia(14), 152(7), garuda(3) |
| S16E06 | S17E07 | 14.7 | metrojet(1), egypt(5), 9268(1) |
| S16E08 | S14E02 | 12.3 | 004(1), lauda(2), limits(44) |
| S16E09 | S17E08 | 9.5 | transasia(2), 235(4) |
| S16E10 | S17E09 | 11.2 | 3142(1), lapa(1) |
| S17E03 | S18E03 | 8.1 | delta(22), 1141(2) |
| S17E05 | S18E05 | 13.9 | superjet(1), salak(1), sukhoi(1) |
| S17E07 | S18E07 | 10.1 | free(42), 72(12), qantas(1) |
| S17E08 | S22E10 | 10.5 | 710(1), illinois(3) |
| S18E01 | S19E01 | 13.1 | pacific(20), 780(1), cathay(2) |
| S18E02 | S19E04 | 14.9 | klm(4), 433(1), cityhopper(1) |
| S18E03 | S19E03 | 7.1 | 808(3), airways(42) |
| S18E04 | S19E02 | 12.8 | races(11), 2011(13), reno(2), race(29) |
| S18E06 | S07E02 | 13.1 | 103(3), lockerbie(1), pan(10) |
| S18E07 | S16E07 | 12.1 | germanwings(7), murder(10), 9525(2) |
| S18E08 | S19E08 | 15.4 | aeroflot(2), 821(1), nord(1) |
| S18E09 | S19E09 | 13.4 | football(10), lamia(3), 2933(1) |
| S18E10 | S19E10 | 15.3 | slam(19), express(13), 6291(1), dunk(4) |
| S19E01 | S20E03 | 13.5 | pakistan(5), kathmandu(6), 268(1) |
| S19E02 | S20E06 | 10.2 | 294(1), sweden(4) |
| S19E03 | S20E01 | 14.2 | explosive(39), 873(1), uni(2), touchdown(35) |
| S19E04 | S20E02 | 17.1 | taxiway(22), 299(1), northwest(31), 1482(1) |
| S19E05 | S20E10 | 10.5 | 8250(1), aires(3) |
| S19E06 | S20E04 | 14.1 | 5428(1), sol(1), icy(10) |
| S19E08 | S20E07 | 11.2 | 267(1), trigana(1) |
| S19E09 | S20E08 | 14.4 | mozambique(3), 470(1), lam(3) |
| S19E10 | S20E09 | 12.3 | airways(42), 507(1), kenya(2) |
| S20E02 | S21E02 | 10.2 | execuflight(2), 1526(2) |
| S20E03 | S21E03 | 9.3 | comair(4), 5191(3) |
| S20E04 | S21E04 | 11.7 | max(33), lion(3), 610(2) |
| S20E05 | S21E05 | 10.0 | southwest(23), catastrophe(30), 1380(2) |
| S20E06 | S21E06 | 13.6 | kathmandu(6), 211(2), us-bangla(2) |
| S20E07 | S21E07 | 10.6 | 135(6), kc-(2), mission(40) |
| S20E08 | S21E08 | 13.2 | ansett(2), zealand(9), 703(2) |
| S20E09 | S21E09 | 11.2 | propair(2), 420(4), touchdown(35) |
| S20E10 | S21E10 | 12.5 | ups(7), 1354(2), delivery(7) |
| S22E01 | S23E02 | 8.7 | 5966(2), corporate(12) |
| S22E02 | S23E03 | 8.5 | 1851(2), independent(15) |
| S22E04 | S23E04 | 8.8 | png(2), 1600(7) |
| S22E05 | S23E05 | 10.2 | astana(2), 1388(2) |
| S22E06 | S23E06 | 12.1 | sichuan(2), catastrophe(30), 8633(2) |
| S22E08 | S23E08 | 14.4 | balkan(2), 013(2), bulgarian(2) |
| S22E09 | S23E09 | 13.2 | 3591(2), delivery(7), atlas(3) |
| S22E10 | S23E10 | 13.0 | egyptair(3), 804(3), mediterranean(5) |
| S24E02 | S24E07 | 11.5 | penair(1), harbor(5), dutch(7) |
| S24E05 | S24E10 | 8.7 | china(23), 676(1) |
| S24E06 | S24E04 | 12.6 | fight(47), 458(1), pilgrim(1) |
| S24E07 | S24E08 | 10.2 | 9446(1), colgan(4) |
| S24E08 | S24E06 | 11.2 | saudia(1), 163(1) |
| S24E09 | S24E03 | 6.9 | star(14), footballer(2) |
| S25E01 | S25E07 | 9.4 | pacific(20), ditching(17), transair(1) |
| S25E03 | S25E02 | 9.6 | 182(5), sriwijaya(1) |
| S25E04 | S25E05 | 11.2 | 9642(1), luxair(1) |
| S25E05 | S14E01 | 10.5 | british(33), 92(8), midland(2) |
| S25E06 | S25E01 | 9.4 | 583(6), china(23), eastern(17) |
| S25E07 | S25E06 | 10.4 | 105(6), express(13), midwest(10) |
| S25E08 | S25E03 | 18.1 | coulson(1), 130(19), 2020(3), firebomber(1) |
| S25E11 | S09E04 | 7.4 | usair(6), skywest(3) |
| S26E01 | S26E07 | 16.1 | iii(2), gulfstream(1), charter(16), aspen(1) |
| S26E04 | S26E05 | 10.4 | airways(42), 2300(3), eagle(7) |
| S26E05 | S26E03 | 14.1 | airblue(1), pakistan(5), 202(2) |
| S26E06 | S05E09 | 6.5 | mixed(20), birgenair(2) |
| S26E07 | S26E04 | 10.7 | rie(1), crisis(51), alg(1) |
| S26E08 | S26E02 | 6.4 | yeti(1), touchdown(35) |

## Contested — do NOT act on these

Each target below is claimed by more than one file, so at most one attribution
can be right. Listed for completeness, excluded from the repair map.

| filed as | claims to be | score |
|---|---|---|
| S03E04 | S18E01 | 8.3 |
| S03E07 | S20E05 | 7.2 |
| S04E02 | S10E03 | 6.7 |
| S04E08 | S20E05 | 7.0 |
| S08E01 | S12E06 | 13.1 |
| S10E02 | S10E03 | 9.5 |
| S11E10 | S17E10 | 11.1 |
| S16E07 | S17E10 | 11.1 |
| S17E01 | S18E01 | 6.5 |
| S19E07 | S20E05 | 16.4 |
| S24E04 | S12E06 | 7.1 |

## Method — and three scorers that were WRONG first

Each Mayday episode covers one named air accident, so subtitle text can be
scored against every episode title library-wide. Getting a trustworthy score
took three attempts, and the failures are worth keeping:

1. **Raw hit counts.** Franchise vocabulary dominated — "flight" appears 27
   times in every episode. Four unrelated files all resolved to one target.
2. **IDF over TITLES.** "The Plane That Flew Too High" (S11E02) won 13 times,
   because plane/flew/too/high are rare in TITLES but ubiquitous in SPEECH.
3. **IDF over the SUBTITLE CORPUS** — correct. A term is only informative if
   rare in actual dialogue. "tenerife", "4805", "spanair", "8501" are near-
   unique; "plane" and "flight" score zero automatically.

Plus a contested-target check: if two files claim the same episode, both are
demoted rather than trusted. An artifact that yields a plausible answer is more
dangerous than one that yields none.

## Corroboration from container headers

Independently of subtitles, muxer version partitions the library into encode
batches, and `libebml v1.4.2` (S14 S15 S16 S17 S18 S19 S20 S24) is almost
exactly the damaged set. Two unrelated signals, same boundary. Headers carry no
title tags, so they localise damage but cannot identify individual files.

Also: **0 duration outliers across 240 files** (median 45 min). Every file is a
genuine full-length episode — nothing truncated. This is why RENAME is the
right repair and re-download is not.

## Before acting

1. **Sonarr's database must be corrected too.** Its rename-on-import is what
   destroyed the evidence originally; a filesystem-only rename will be undone
   on the next scan.
2. **AMBIGUOUS (35) and NO-SRT (31) are UNCHECKED, not clean.** 31 episodes
   have no subtitle source at all — Seasons 1, 2, 6, 7 are entirely unverified.
3. Rename is reversible; keep this map so it can be undone.
