#!/usr/bin/env python3
"""Build the TV identity manifest — does each episode file contain what it claims?

WHY THIS EXISTS
---------------
The movie side has `preservation-manifest.json` (2,420 rows). TV had nothing: scans
were run ad hoc and their results lived in a session transcript, and the shift
detector sat uncommitted in /tmp. This is the durable TV equivalent, and it is step 1
of SQ-58 (identity chain of custody: verify at the FILE, propagate upward).

Nothing above the file verifies identity. Sonarr trusts the filename, Bazarr trusts
Sonarr, TMM trusts the tree, Plex/Emby trust TMM's NFOs, Tunarr trusts Plex. A wrong
ID at the bottom becomes authoritative at the top. Verified failures at every layer
are recorded in SQ-58.

TWO COMPLEMENTARY SIGNALS — neither alone covers the library
------------------------------------------------------------
1. RUNTIME CROSS-CHECK  (sees INTO the file)
   Sonarr stores `episode.runtime` (TVDB: what it should be) and
   `episodeFile.mediaInfo.runTime` (what the file IS). Works regardless of filename,
   so it covers the ~7,220 Sonarr-RENAMED files that signal 2 is blind to.

2. POSITIONAL SHIFT     (sees the NAME)
   Does the filename's episode title match a DIFFERENT episode number in the same
   season? Only works on files that kept their original release names — 888 of 8,108.

Together they cover what neither covers alone. That complementarity is the whole
point; do not report one without the other's denominator.

TV-SPECIFIC TOLERANCE — percentage-off is the WRONG axis, see CALIBRATION below
--------------------------------------------------------------------------------
TVDB stores the broadcast SLOT length; the file holds the CONTENT length. For
commercial TV a 60-min slot legitimately holds a 43-44 min file. A first pass using
percent-deviation flagged 17% of files, 223 of which were exactly that normal
relationship — the whole Bourdain run reported as suspect while being correct.

This classifies by RATIO against what ad breaks can explain. See the CALIBRATION
block for the measured bands and why each boundary sits where it does.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
- It does not rename, move or delete anything. Ever. It writes two report files.
- It does not "fix" longer-than-expected files. Multiple editions and double-episode
  files are legitimate and must stay independently selectable.
- It does not claim a series is clean when it is merely unassessable. Every count
  carries its denominator, and the blind spot is reported as a first-class number.

USAGE
-----
    python3 tools/media/build_tv_manifest.py            # writes docs/media/tv-manifest.*
    python3 tools/media/build_tv_manifest.py --limit 20 # quick sample run
"""
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HOST = "192.168.10.211"
OUT_JSON = "docs/media/tv-manifest.json"
OUT_MD = "docs/media/tv-manifest.md"

# ---------------------------------------------------------------------------
# CALIBRATION — measured, not guessed. Read this before changing a number.
#
# TVDB stores the broadcast SLOT length. The file holds the CONTENT length. For
# commercially-broadcast TV those differ by the ad fraction, ALWAYS:
#
#     60-min slot -> 43-44 min file   ratio ~0.72   <- NORMAL
#     30-min slot -> 21-22 min file   ratio ~0.72   <- NORMAL
#
# A first pass using "percent deviation" flagged 226 of 1,329 files (17%). 223 of
# those were 60-min slots holding 43-44 min — i.e. the entire Anthony Bourdain run
# was reported as suspect while being perfectly correct. Percentage-off is the WRONG
# axis for TV.
#
# The right question is whether the ratio is explicable by ad breaks:
#
#     ratio < 0.55        content genuinely missing / truncated / wrong episode
#     0.55 .. 1.15        NORMAL (ad breaks through to ad-free streaming cuts)
#     1.15 .. 1.60        longer than any single cut should be — look
#     >= 1.60             almost certainly a DOUBLE EPISODE (30 Rock 22m -> 42m,
#                         ratio 1.92, verified) or an extended/feature-length special
#
# Do not "correct" anything at ratio >= 1.60 without checking — double episodes and
# extended cuts are legitimate and must stay independently selectable.
# ---------------------------------------------------------------------------
RATIO_TOO_SHORT = 0.55
RATIO_NORMAL_HI = 1.15
RATIO_LONG_HI = 1.60
ABS_FLOOR_S = 240     # ignore <4 min absolute difference whatever the ratio

MULTI_EP = (re.compile(r"[Ss]\d+[Ee]\d+[-_ ]?[Ee]\d+"),
            re.compile(r"[Ee]\d+[-_][Ee]\d+"))

# ---------------------------------------------------------------------------
# TV-SPECIFIC NUANCE — carried over from the movie manifest, plus what only TV has.
#
# 1. SAME-TITLE SERIES (the TV form of the movie title-collision check).
#    Revivals share a title with their original and are DIFFERENT WORKS:
#        The Kids in the Hall (1989) CBC        tvdb-75303   5 seasons, ~24 min eps
#        The Kids in the Hall (2022) Prime      tvdb-419533  1 season,  ~25 min eps
#    Both exist here and are correctly separated. The check is not "is there a
#    duplicate" — it is "are same-titled series distinct entries with distinct tvdbIds
#    and distinct folders". Collapsing them is how a revival's episodes end up filed
#    under the original, and vice versa.
#
# 2. TVDB RUNTIME IS UNRELIABLE AT THE EPISODE LEVEL.
#    Discovered the hard way: 31 of 101 original-Kids-in-the-Hall episodes flagged
#    TOO-SHORT (60m expected vs 24m actual) — but it is a HALF-HOUR sketch show and
#    24 min is correct. TVDB's runtime was the error, not the files.
#    So a runtime flag is only trustworthy when the series' OWN episodes disagree
#    with each other. If a whole series deviates uniformly, suspect the metadata.
#    `series_uniform` below carries that judgement into every row.
#
# 3. SPECIALS (season 0) HAVE NO RELIABLE RUNTIME.
#    Behind-the-scenes, webisodes and shorts sit in season 0 with inherited or absent
#    runtimes. They are excluded from runtime judgement rather than flagged.
#
# 4. MULTI-EPISODE FILES cannot be judged for positional shift at all (a file
#    legitimately holding two titles is not a mismatch), and their duration is
#    legitimately ~2x. Both are handled explicitly, never silently.
# ---------------------------------------------------------------------------
SPECIALS_SEASON = 0
SERIES_UNIFORM_PCT = 0.70   # >=70% of a series flagged => suspect the metadata

# FOUR identity categories look like duplicates/errors but are DISTINCT WORKS or
# correct-but-renumbered. Conflating any of them corrupts the library:
#
#   REVIVAL/REBOOT     same title, different production era
#                      Kids in the Hall 1989 CBC vs 2022 Prime; Clone High 2002 vs 2023
#   REGIONAL VARIANT   same format, different country production. The exact-title
#                      check MISSES these because the suffix differs:
#                      Taskmaster (US)/(AU)/(NZ), Top Chef (FR)/(GR)/(ES)/(SA),
#                      Come Dine with Me /(CA)/(IR)
#   NETWORK TRANSFER   one series that moved network mid-run and got RENUMBERED by
#                      TVDB relative to release groups. This produces exactly the
#                      positional-shift signature while nothing is actually wrong:
#                      Futurama (Fox -> Comedy Central -> Hulu) 1 shift,
#                      King of the Hill (Fox -> Hulu revival) 6 shifts.
#                      Syndication re-ordering does the same: The French Chef, 27.
#   SPINOFF            shares a base title, adds a qualifier, DIFFERENT show:
#                      Top Chef vs Top Chef: Masters vs Top Chef Amateurs;
#                      Destination Flavour vs ...Japan vs ...China
#   SPECIALS           season 0, unreliable runtimes, excluded from runtime judgement
#
# A shift in a network-transfer or syndicated series is a NUMBERING disagreement, not
# a misfiled file. Fixing it means re-linking to the right episode record, never
# touching the file.
REGION_SUFFIX = re.compile(r"\((US|UK|GB|AU|NZ|CA|IE|IR|FR|DE|ES|IT|GR|SA|SE|NO|DK|NL|BE|PL|BR|MX|JP|KR|IN|ZA)\)\s*$", re.I)


def key():
    if os.environ.get("SONARR_API"):
        return os.environ["SONARR_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; set SONARR_API")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.SONARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read SONARR_API")
    return k


def norm(s):
    s = (s or "").lower().replace("&", " and ").replace("+", " and ")
    return re.sub(r"[^a-z0-9]+", "", s)


def secs(rt):
    """mediaInfo.runTime is 'H:MM:SS' or 'MM:SS'."""
    if not rt:
        return None
    p = [int(x) for x in re.findall(r"\d+", str(rt))]
    if len(p) == 3:
        return p[0] * 3600 + p[1] * 60 + p[2]
    if len(p) == 2:
        return p[0] * 60 + p[1]
    return None


def main():
    k = key()
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    base = "http://%s:8989/api/v3" % HOST

    def api(p):
        return json.load(urllib.request.urlopen(
            urllib.request.Request(base + p, headers={"X-Api-Key": k}), timeout=180))

    series = api("/series")
    if limit:
        series = series[:limit]

    rows = []
    stats = collections.Counter()
    checked_per = collections.Counter()

    for s in series:
        try:
            eps = api("/episode?seriesId=%d&includeEpisodeFile=true" % s["id"])
        except Exception:
            stats["series_query_failed"] += 1
            continue
        stats["series"] += 1
        idx = {(e.get("seasonNumber"), e.get("episodeNumber")): (e.get("title") or "")
               for e in eps}

        for e in eps:
            ef = e.get("episodeFile") or {}
            path = ef.get("relativePath") or ""
            if not path:
                stats["episodes_no_file"] += 1
                continue
            stats["episodes_with_file"] += 1
            rel = os.path.basename(path)
            sn, en = e.get("seasonNumber"), e.get("episodeNumber")
            multi = any(p.search(rel) for p in MULTI_EP)

            # ---- signal 1: runtime cross-check (works on renamed files too) ----
            exp = (e.get("runtime") or 0) * 60
            act = secs((ef.get("mediaInfo") or {}).get("runTime"))
            rt_flag, ratio, delta = None, None, None
            if sn == SPECIALS_SEASON:
                stats["specials_runtime_skipped"] += 1
            elif not exp:
                stats["no_expected_runtime"] += 1
            elif act is None:
                stats["no_mediainfo_runtime"] += 1
            else:
                stats["runtime_checked"] += 1
                checked_per[s.get("title")] += 1
                delta = act - exp
                ratio = act / float(exp)
                if abs(delta) < ABS_FLOOR_S:
                    stats["runtime_normal"] += 1
                elif ratio < RATIO_TOO_SHORT:
                    rt_flag = "TOO-SHORT"      # unexplainable by ad breaks
                elif ratio >= RATIO_LONG_HI:
                    rt_flag = "DOUBLE-OR-EXT"  # ~2x slot, or a feature-length special
                elif ratio > RATIO_NORMAL_HI:
                    rt_flag = "LONG"
                else:
                    stats["runtime_normal"] += 1   # ad-break band — CORRECT, not a fault
                if rt_flag:
                    stats["runtime_" + rt_flag] += 1

            # ---- signal 2: positional shift (name-based, blind on renamed files) ----
            shift = None
            if multi:
                stats["multi_episode_skipped"] += 1
            else:
                own = norm(idx.get((sn, en), ""))
                if len(own) >= 6 and own in norm(rel):
                    stats["name_matches_own_title"] += 1   # THE BLIND SPOT
                else:
                    stats["shift_assessable"] += 1
                    for off in (-3, -2, -1, 1, 2, 3):
                        other = norm(idx.get((sn, en + off), ""))
                        if len(other) >= 6 and other in norm(rel):
                            shift = {"offset": off,
                                     "sonarr_title": idx.get((sn, en), ""),
                                     "file_title": idx.get((sn, en + off), "")}
                            stats["shifts"] += 1
                            break

            if rt_flag or shift:
                rows.append({
                    "series": s.get("title"), "tvdbId": s.get("tvdbId"),
                    "season": sn, "episode": en,
                    "sonarr_title": idx.get((sn, en), ""),
                    "file": rel, "path": path,
                    "multi_episode": multi,
                    "expected_s": exp or None, "actual_s": act,
                    "delta_s": delta,
                    "ratio": round(ratio, 3) if ratio is not None else None,
                    "runtime_flag": rt_flag,
                    "direction": (None if delta is None else
                                  ("LONGER" if delta > 0 else "SHORTER")),
                    "shift": shift,
                    "both_signals": bool(rt_flag and shift),
                })

    # ---- TV nuance: same-title series must be DISTINCT entries ----
    bytitle = collections.defaultdict(list)
    for s2 in series:
        base = re.sub(r"\s*\(\d{4}\)\s*$", "", (s2.get("title") or "")).strip().lower()
        bytitle[base].append(s2)
    collisions = []
    for base, group in bytitle.items():
        if len(group) < 2:
            continue
        ids = {g.get("tvdbId") for g in group}
        paths = {g.get("path") for g in group}
        collisions.append({
            "title": base,
            "entries": [{"id": g.get("id"), "tvdbId": g.get("tvdbId"),
                         "title": g.get("title"), "year": g.get("year"),
                         "network": g.get("network"), "path": g.get("path"),
                         "files": (g.get("statistics") or {}).get("episodeFileCount")}
                        for g in group],
            "distinct_tvdb": len(ids) == len(group),
            "distinct_paths": len(paths) == len(group),
        })
    # ---- regional variants: same franchise, different country production ----
    fran = collections.defaultdict(list)
    for s2 in series:
        t = re.sub(r"\s*\(\d{4}\)\s*$", "", (s2.get("title") or "")).strip()
        m = REGION_SUFFIX.search(t)
        if m:
            fran[REGION_SUFFIX.sub("", t).strip().lower()].append((m.group(1).upper(), s2))
    regionals = []
    for base, group in fran.items():
        # include the un-suffixed original if present
        for s2 in series:
            t = re.sub(r"\s*\(\d{4}\)\s*$", "", (s2.get("title") or "")).strip()
            if t.lower() == base and not REGION_SUFFIX.search(t):
                group = group + [("(orig)", s2)]
        if len(group) < 2:
            continue
        regionals.append({
            "franchise": base,
            "variants": [{"region": r, "title": g.get("title"), "year": g.get("year"),
                          "tvdbId": g.get("tvdbId"), "network": g.get("network"),
                          "files": (g.get("statistics") or {}).get("episodeFileCount")}
                         for r, g in group],
            "distinct_tvdb": len({g.get("tvdbId") for _, g in group}) == len(group),
        })
    # ---- spinoffs: shares a base title, adds a qualifier ----
    def bare(t):
        t = re.sub(r"\s*\(\d{4}\)\s*$", "", (t or "")).strip()
        return REGION_SUFFIX.sub("", t).strip()
    titles = [(bare(s2.get("title")), s2) for s2 in series]
    spinoffs = collections.defaultdict(set)
    for a, sa in titles:
        for b, sb in titles:
            if sa is sb or not a or not b:
                continue
            # b extends a with a qualifier: "Top Chef" -> "Top Chef: Masters"
            if b.lower().startswith(a.lower()) and len(b) > len(a) + 2:
                sep = b[len(a):len(a) + 2]
                if sep[:1] in (":", " ", "-"):
                    spinoffs[a].add((b, sb.get("year"), sb.get("tvdbId"),
                                     (sb.get("statistics") or {}).get("episodeFileCount")))
    spin = [{"base": k, "derived": sorted(v)} for k, v in spinoffs.items() if v]
    stats["spinoff_families"] = len(spin)
    stats["spinoff_derived_total"] = sum(len(x["derived"]) for x in spin)

    stats["regional_franchises"] = len(regionals)
    stats["regional_variants_total"] = sum(len(r["variants"]) for r in regionals)

    stats["same_title_series_groups"] = len(collisions)
    stats["same_title_not_distinct"] = sum(
        1 for c in collisions if not (c["distinct_tvdb"] and c["distinct_paths"]))

    # ---- TV nuance: is a runtime flag series-uniform? then suspect the METADATA ----
    # DENOMINATOR MATTERS: divide by episodes actually RUNTIME-CHECKED in that series,
    # not by episodeFileCount. Kids in the Hall has 101 files but only 44 carry a
    # mediainfo duration; 31 flagged is 31% of 101 but 70% of 44. Using the wrong
    # denominator hid a confirmed metadata defect (TVDB says 60 min for 80 episodes;
    # every measurable file is 18-28 min).
    flagged_per = collections.Counter(r["series"] for r in rows if r["runtime_flag"])
    uniform = {t for t, n in flagged_per.items()
               if checked_per.get(t) and n / checked_per[t] >= SERIES_UNIFORM_PCT}
    for r in rows:
        r["series_uniform"] = r["series"] in uniform
        if r["series_uniform"] and r["runtime_flag"]:
            r["likely_cause"] = "TVDB runtime wrong for this series"
        elif r["runtime_flag"]:
            r["likely_cause"] = "file-level — worth checking"
    stats["series_uniform_series"] = len(uniform)
    stats["rows_in_uniform_series"] = sum(1 for r in rows if r.get("series_uniform"))

    stats["flagged_rows"] = len(rows)
    stats["both_signals"] = sum(1 for r in rows if r["both_signals"])

    os.makedirs("docs/media", exist_ok=True)
    meta = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "host": HOST, "thresholds": {"ratio_too_short": RATIO_TOO_SHORT,
                                         "ratio_normal_hi": RATIO_NORMAL_HI,
                                         "ratio_long_hi": RATIO_LONG_HI,
                                         "abs_floor_s": ABS_FLOOR_S},
            "stats": dict(stats), "same_title_series": collisions, "regional_variants": regionals, "spinoffs": spin, "rows": rows}
    json.dump(meta, open(OUT_JSON, "w"), indent=1)

    # ---------------- markdown report ----------------
    L = []
    A = L.append
    A("# TV Identity Manifest\n")
    A("Generated %s from Sonarr at %s.\n" % (meta["generated"][:19], HOST))
    A("Step 1 of SQ-58 — verify identity AT THE FILE, then propagate upward. "
      "This report changes nothing; it never renames, moves or deletes.\n")

    A("## Coverage — read the denominators before the counts\n")
    A("| Metric | Count |")
    A("|---|---|")
    for lbl, k2 in (("Series scanned", "series"),
                    ("Episodes with a file", "episodes_with_file"),
                    ("Episodes with no file", "episodes_no_file"),
                    ("Runtime cross-check possible", "runtime_checked"),
                    ("— no TVDB runtime (unverifiable)", "no_expected_runtime"),
                    ("— no mediainfo runtime (unverifiable)", "no_mediainfo_runtime"),
                    ("Shift check possible", "shift_assessable"),
                    ("— name already matches own title (BLIND SPOT)",
                     "name_matches_own_title"),
                    ("— multi-episode file (unjudgeable)", "multi_episode_skipped")):
        A("| %s | %d |" % (lbl, stats.get(k2, 0)))
    A("")
    blind = stats.get("name_matches_own_title", 0)
    assess = stats.get("shift_assessable", 0)
    if assess:
        A("**The shift rate is %d of %d assessable = %.1f%%, NOT %d of %d.** "
          "Where Sonarr has renamed a file its numbering is baked into the name, so a "
          "shift there is invisible to that method. A clean result on a renamed series "
          "is not evidence of correctness.\n"
          % (stats.get("shifts", 0), assess,
             100.0 * stats.get("shifts", 0) / assess,
             stats.get("shifts", 0), assess + blind))

    A("## Findings\n")
    A("| Signal | Count |")
    A("|---|---|")
    A("| Runtime TOO-SHORT (ratio <%.2f — content missing) | %d |" % (RATIO_TOO_SHORT, stats.get("runtime_TOO-SHORT", 0)))
    A("| Runtime LONG (%.2f-%.2f) | %d |" % (RATIO_NORMAL_HI, RATIO_LONG_HI, stats.get("runtime_LONG", 0)))
    A("| DOUBLE-EPISODE or EXTENDED (ratio >=%.2f — usually legitimate) | %d |" % (RATIO_LONG_HI, stats.get("runtime_DOUBLE-OR-EXT", 0)))
    A("| Within ad-break band (NORMAL) | %d |" % stats.get("runtime_normal", 0))
    A("| Positional shifts | %d |" % stats.get("shifts", 0))
    A("| **Both signals on one file** | **%d** |" % stats["both_signals"])
    A("")
    A("A file carrying BOTH signals is the strongest evidence available here — the "
      "name says one episode and the duration disagrees too.\n")

    def table(title, sel, note=""):
        sub = [r for r in rows if sel(r)]
        if not sub:
            return
        A("## %s (%d)\n" % (title, len(sub)))
        if note:
            A(note + "\n")
        A("| Series | S/E | Sonarr title | Expected | Actual | Δ | Note |")
        A("|---|---|---|---|---|---|---|")
        for r in sorted(sub, key=lambda x: -(abs(x["delta_s"] or 0)))[:60]:
            ex = "%.0fm" % (r["expected_s"] / 60) if r["expected_s"] else "—"
            ac = "%.0fm" % (r["actual_s"] / 60) if r["actual_s"] else "—"
            dl = "%+.0fm" % (r["delta_s"] / 60) if r["delta_s"] is not None else "—"
            note2 = ""
            if r["shift"]:
                note2 = "shift %+d → file says *%s*" % (r["shift"]["offset"],
                                                        r["shift"]["file_title"])
            elif r["multi_episode"]:
                note2 = "multi-episode file"
            A("| %s | S%02dE%02d | %s | %s | %s | %s | %s |"
              % (r["series"], r["season"] or 0, r["episode"] or 0,
                 (r["sonarr_title"] or "")[:40], ex, ac, dl, note2))
        A("")

    table("Both signals — highest confidence", lambda r: r["both_signals"])
    table("TOO-SHORT — content missing or wrong episode",
          lambda r: r["runtime_flag"] == "TOO-SHORT",
          "Ratio below %.2f: shorter than ad breaks can explain. **These are the real errors.**" % RATIO_TOO_SHORT)
    table("DOUBLE-EPISODE or EXTENDED",
          lambda r: r["runtime_flag"] == "DOUBLE-OR-EXT",
          "Ratio >=%.2f — usually a legitimate double episode or feature-length special. "
          "Verify; do NOT 'correct' these." % RATIO_LONG_HI)
    table("LONG — longer than a single cut should be",
          lambda r: r["runtime_flag"] == "LONG")

    sh = [r for r in rows if r["shift"] and not r["runtime_flag"]]
    if sh:
        A("## Positional shifts without a runtime signal (%d)\n" % len(sh))
        A("| Series | S/E | Sonarr says | File says | Offset |")
        A("|---|---|---|---|---|")
        for r in sh:
            A("| %s | S%02dE%02d | %s | %s | %+d |"
              % (r["series"], r["season"] or 0, r["episode"] or 0,
                 (r["shift"]["sonarr_title"] or "")[:34],
                 (r["shift"]["file_title"] or "")[:34], r["shift"]["offset"]))
        A("")

    A("## Same-title series — revivals are DIFFERENT WORKS\n")
    if not collisions:
        A("No same-titled series pairs found.\n")
    else:
        A("| Title | Entries | Distinct tvdbId | Distinct folder |")
        A("|---|---|---|---|")
        for c in collisions:
            det = "; ".join("%s (%s, %s, %s files)"
                            % (e["title"], e["year"], e["network"], e["files"])
                            for e in c["entries"])
            A("| %s | %s | %s | %s |"
              % (c["title"], det, "yes" if c["distinct_tvdb"] else "**NO**",
                 "yes" if c["distinct_paths"] else "**NO**"))
        A("")
        A("Distinct on both axes means the split is correct. A **NO** in either column "
          "means a revival and its original may be sharing an identity — that is how a "
          "2022 episode ends up filed under a 1989 series.\n")

    A("## Regional variants — same format, DIFFERENT productions\n")
    if not regionals:
        A("None found.\n")
    else:
        A("The exact-title check does not catch these: the country suffix makes the "
          "titles differ. They are separate productions and must never be merged.\n")
        A("| Franchise | Variants | Distinct tvdbId |")
        A("|---|---|---|")
        for rg in sorted(regionals, key=lambda x: -len(x["variants"])):
            det = "; ".join("%s %s (%s, %s files)" % (v["region"], v["year"],
                                                      v["network"], v["files"])
                            for v in rg["variants"])
            A("| %s | %s | %s |" % (rg["franchise"], det,
                                    "yes" if rg["distinct_tvdb"] else "**NO**"))
        A("")

    A("## Spinoffs — a shared base title does NOT mean a shared show\n")
    if not spin:
        A("None found.\n")
    else:
        A("| Base series | Derived |")
        A("|---|---|")
        for f in sorted(spin, key=lambda x: -len(x["derived"])):
            A("| %s | %s |" % (f["base"], "; ".join("%s (%s, %s files)" % (d[0], d[1], d[3])
                                                    for d in f["derived"])))
        A("")
        A("These are separate shows sharing a franchise name. Merging them, or letting "
          "one scrape over the other, mixes unrelated episode numbering.\n")

    A("## Network transfers and syndication — shifts that are NOT misfiles\n")
    A("A series that changed network mid-run, or was re-ordered for syndication, gets "
      "renumbered by TVDB relative to release-group numbering. That produces exactly "
      "the positional-shift signature while nothing is wrong with the files. Known "
      "cases in this library: **Futurama** (Fox to Comedy Central to Hulu), "
      "**King of the Hill** (Fox, plus the Hulu revival), **The French Chef** (1960s "
      "syndication). Correcting these means re-linking to the right episode record — "
      "**never** renaming or moving a file.\n")

    A("## What must happen next, and in this order\n")
    A("1. Triage LONGER results — double episodes and extended cuts are legitimate.")
    A("2. Correct Sonarr identities for confirmed errors (no file operations).")
    A("3. **Then** delete and re-fetch subtitles for corrected episodes. Doing this "
      "before step 2 makes Bazarr re-download the same wrong ones under the same "
      "wrong identity.")
    A("4. **Then** scan TV into TMM and scrape — TMM owns TV metadata and writes the "
      "NFOs Plex/Emby read, so scraping earlier makes unverified identities "
      "authoritative.")
    A("5. **Then** refresh the players and relink Tunarr.\n")

    open(OUT_MD, "w").write("\n".join(L))
    print("wrote %s (%d rows) and %s" % (OUT_JSON, len(rows), OUT_MD))
    for k2 in sorted(stats):
        print("  %-34s %d" % (k2, stats[k2]))


if __name__ == "__main__":
    main()
