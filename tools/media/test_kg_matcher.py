#!/usr/bin/env python3
"""Offline validator for kg_recheck.py's title matcher. No network, no tracker.

WHY THIS EXISTS
The accent-folding fix shipped in kg_recheck.py was "verified" only to the point of
'the query string changed'. Nobody checked whether the COMPARISON step could succeed
on pairs already known to match. It could not: measured here, the shipped matcher
scored 22/709 (3.1%), so 96.9% of all comparisons were false negatives, and a
456-row re-check came back uninterpretable after ~2h of tracker queries.

THE TEST SET IS GROUND TRUTH
kg_disc_audit.json carries 709 rows marked PRESENT, each pairing a manifest title
with the kg_title that confirmed it. Those pairs are known to correspond. Any pair
this matcher fails to match is a measured false negative — no queries required.

IT IMPORTS THE REAL keys_of()
Deliberately. A validator that re-implements the logic it validates is a parallel
implementation that happens to work; it proves nothing about the shipped path. That
is precisely how the previous control passed (a hardcoded ASCII literal) while the
code it guarded was broken.

CAVEAT ON THE CEILING
The PRESENT rows were labelled by the ORIGINAL matcher, which had its own false
positives — it paired 'Trainspotting' with 'Trainspotting OST', 'Blade Runner 2049'
with 'The Art and Soul of Blade Runner 2049', 'The Matrix' with 'The Matrix Comics'.
The current matcher correctly REJECTS those, and is scored as missing them. So 100%
is not the target and would in fact be a red flag.

Usage:  test_kg_matcher.py <kg_disc_audit.json>
Exit:   0 if the gates pass, 1 otherwise.
"""
import json, os, re, sys, importlib.util

MIN_RATE = 0.85          # regression floor; current is ~0.93
CANON = ["8½", "The Leopard", "Mirror", "Black Girl", "Killer of Sheep",
         "Céline And Julie Go Boating"]

def load_matcher():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kg_recheck.py")
    spec = importlib.util.spec_from_file_location("kg_recheck", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)          # safe: kg_recheck does nothing at import
    return m

def main():
    kg = load_matcher()
    rows = json.load(open(sys.argv[1]))
    truth = [r for r in rows if r.get("kg") == "PRESENT" and r.get("kg_title")]
    if not truth:
        print("FAIL: no ground-truth pairs in input"); return 1
    ok = True

    # --- gate 1: match rate against known-good pairs -------------------------
    hits, misses = 0, []
    for r in truth:
        if kg.keys_of(r["title"]) & kg.keys_of(str(r["kg_title"])): hits += 1
        else: misses.append((r["title"], str(r["kg_title"])))
    rate = hits / len(truth)
    print("match rate      : %d/%d (%.1f%%)  floor %.0f%%  %s"
          % (hits, len(truth), 100*rate, 100*MIN_RATE,
             "PASS" if rate >= MIN_RATE else "FAIL"))
    if rate < MIN_RATE: ok = False

    # --- gate 2: every canon title must produce at least one key -------------
    # An aggregate rate cannot see this: 12 dead titles out of 1165 do not move a
    # percentage. `8½` folded to '812' and was dropped by a len>=4 guard, so it was
    # unmatchable by construction and no rate would ever have revealed it.
    dead = [c for c in CANON if not kg.keys_of(c)]
    print("canon keys      : %d/%d produce keys  %s"
          % (len(CANON)-len(dead), len(CANON), "PASS" if not dead else "FAIL " + str(dead)))
    if dead: ok = False

    # --- gate 3: nothing in the manifest may be unmatchable ------------------
    nokey = [r["title"] for r in rows if not kg.keys_of(r["title"])]
    print("unmatchable rows: %d  %s" % (len(nokey), "PASS" if not nokey else "FAIL " + str(nokey[:8])))
    if nokey: ok = False

    # --- informational: short-key collisions between DIFFERENT films ---------
    from collections import defaultdict
    short = defaultdict(set)
    for r in rows:
        for k in kg.keys_of(r["title"]):
            if len(k) < 4: short[k].add(r["title"])
    coll = {k: sorted(v) for k, v in short.items() if len(v) > 1}
    print("short-key collisions: %d %s" % (len(coll), coll if coll else ""))

    if misses:
        print("\nsample non-matches (many are CORRECT rejections — soundtracks, art books, comics):")
        for t, k in misses[:8]:
            print("  manifest %-34s  kg %s" % (t[:34], k[:62]))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
