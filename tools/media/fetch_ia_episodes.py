#!/usr/bin/env python3
"""Fetch specific episodes from archive.org and stage them under YOUR numbering.

WHY THIS EXISTS - three incompatible numbering schemes for one series
--------------------------------------------------------------------
The French Chef had 14 episodes that survived an entire night of *arr backfill.
Every indexer returned nothing. They were on archive.org the whole time - the
Internet Archive indexer in Prowlarr was misconfigured (routed through
FlareSolverr for a site with no Cloudflare).

But you cannot simply grab the season packs, because archive.org carries THREE
disagreeing numbering systems for this series:

  1. the item TITLE      "Season 5"     <- inverted, means season 11-N
  2. the item IDENTIFIER  s-06-e-13     <- the real season of the CONTENTS
  3. the FILE names       S06E13        <- agrees with the identifier

and none of them match TVDB, which is what Sonarr uses:

  TVDB S05E04 "New Year"          == IA file S09E04 "Bringing In The New Year"
  TVDB S07E01 "Bouillabaisse"     == IA file S05E18 "Bouillabaisse A La Marseillaise"
  TVDB S10E05 "VIP Cake"          == IA file S01E07 "V.i.p. Cake"

These are not off by a constant - the schemes are unrelated. Grabbing the pack
labelled "Season 5" delivers Season 6 content and Sonarr files 20 episodes under
the wrong numbers. The ONLY trustworthy signal is the episode TITLE inside the
filename.

So this tool matches on title, downloads the individual .mp4 (not the pack), and
renames to TVDB numbering before Sonarr ever sees it.

THE TVDB DOUBLE-LISTING
-----------------------
TVDB lists four episodes twice, in both S08 and S09, with identical air dates:
  Coq au Vin (S08E17 + S09E01), Mousse au Chocolat (S08E18 + S09E02),
  To Stuff a Sausage (S08E20 + S09E04)
One source file legitimately serves both slots. This tool downloads once and
writes a copy per slot rather than downloading the same episode twice.

USAGE
-----
    python3 tools/media/fetch_ia_episodes.py                 # dry run, prints plan
    python3 tools/media/fetch_ia_episodes.py --execute       # download + stage
    python3 tools/media/fetch_ia_episodes.py --execute --stage /path

Staged files land in --stage (default /tmp/ia-staging) named for Sonarr:
    The French Chef (1963) - S05E04 - New Year.mp4
Import them with Sonarr's Manual Import and VERIFY each mapping - the whole
point of this tool is that labels lie.
"""
import argparse
import json
import os
import sys
import urllib.request

IA = "https://archive.org"
DEFAULT_MAP = ("/private/tmp/claude-501/-Users-zachbaum-dev-Talos-Cluster/"
               "83f43aa9-aa8c-434d-aa23-46c89ebb6330/scratchpad/frenchchef_gap_map.json")
SERIES = "The French Chef (1963)"


def safe(s):
    """Sonarr-friendly filename component."""
    for ch in '/\\:*?"<>|':
        s = s.replace(ch, "-")
    return s.strip()


def outname(slot, src_file):
    """Sonarr-style name for one TVDB slot.

    `series` is per-row so one map can span several shows; SERIES stays the
    default so the original French Chef map keeps working untouched.

    The container is taken from the SOURCE file rather than assumed to be .mp4.
    archive.org's `original` upload is often .mkv or .avi while its derivative
    is .mp4 - and the original is the one worth having, since the derivative is
    a re-encode of it. Hardcoding .mp4 would put an AVI stream in a .mp4
    wrapper, which ffprobe reads fine and Sonarr imports happily right up until
    a client refuses to play it.
    """
    ext = os.path.splitext(src_file)[1].lower() or ".mp4"
    return "%s - S%02dE%02d - %s%s" % (slot.get("series", SERIES), slot["tvdb_s"],
                                       slot["tvdb_e"], safe(slot["tvdb_title"]), ext)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--stage", default="/tmp/ia-staging")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()

    rows = json.load(open(a.map))

    # one download per distinct source file; a file may serve several TVDB slots
    by_src = {}
    for r in rows:
        by_src.setdefault((r["ia_identifier"], r["ia_file"]), []).append(r)

    print("  source files to fetch : %d" % len(by_src))
    print("  TVDB slots to fill    : %d" % len(rows))
    print("  total download        : %.2f GB"
          % (sum(v[0]["gb"] for v in by_src.values())))
    print("  stage dir             : %s\n" % a.stage)

    for (ident, fname), slots in sorted(by_src.items()):
        url = "%s/download/%s/%s" % (IA, ident, urllib.parse.quote(fname))
        print("  %s" % fname[:78])
        print("     from item : %s" % ident[:66])
        print("     %.2f GB -> %d slot(s):" % (slots[0]["gb"], len(slots)))
        for s in slots:
            print("        %s" % outname(s, fname))
        if not a.execute:
            continue
        os.makedirs(a.stage, exist_ok=True)
        tmp = os.path.join(a.stage, ".dl.part")
        try:
            with urllib.request.urlopen(url, timeout=600) as resp, open(tmp, "wb") as fh:
                got = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
            exp = int(slots[0]["gb"] * 1e9)
            # tolerate rounding in the recorded GB figure, catch truncation
            if exp and got < exp * 0.85:
                print("     TRUNCATED: got %.2f GB, expected ~%.2f GB - skipping"
                      % (got / 1e9, exp / 1e9))
                os.remove(tmp)
                continue
            for s in slots:
                out = os.path.join(a.stage, outname(s, fname))
                if len(slots) > 1:
                    import shutil
                    shutil.copyfile(tmp, out)
                else:
                    os.rename(tmp, out)
            if os.path.exists(tmp):
                os.remove(tmp)
            print("     downloaded %.2f GB, staged %d file(s)" % (got / 1e9, len(slots)))
        except Exception as e:
            print("     FAILED: %s" % str(e)[:90])
            if os.path.exists(tmp):
                os.remove(tmp)

    if not a.execute:
        print("\n  DRY RUN - nothing downloaded. Re-run with --execute.")
    else:
        print("\n  staged in %s" % a.stage)
        print("  NEXT: Sonarr -> Wanted/Manual Import -> point at that folder.")
        print("  VERIFY each mapping before importing. Labels lie; that is why this exists.")


if __name__ == "__main__":
    import urllib.parse
    main()
