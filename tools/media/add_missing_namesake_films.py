#!/usr/bin/env python3
"""Add the three films whose names were left on stale folders (SQ-47 follow-on).

CONTEXT
-------
Five movie folders carried names of films that were not in the library at all;
the directories had been reused by other films and never renamed. The renames
are done (tools/media/fix_stale_movie_folders.py). This adds back the films
those folder names referred to, which turned out to be genuinely absent:

    Blade Runner 2049 (2017)   tmdb 335984   not in Radarr
    Alien³ (1992)              tmdb 8077     not in Radarr
    The Nun (1965 -> 1967)     tmdb 42722    not in Radarr

IDENTIFYING "The Nun (1965)"
---------------------------
TMDB's "The Nun" hits are 2018/2023 horror films, which do not belong in a
library sitting next to Rohmer, Bresson, Ozu and Varda. Searching the French
title resolves it: tmdb 42722, Rivette's `La Religieuse` / `Suzanne Simonin,
la religieuse de Denis Diderot`. The library already holds Rivette's `Céline
and Julie Go Boating`, which corroborates it.

TMDB dates it 1967; the folder said 1965. That is the same release-year drift
that made `School for Postmen` unacquirable - Radarr matches releases on
title+year, so a drifted year silently breaks acquisition. Adding by tmdbId
rather than by title+year avoids reintroducing it.

PROFILE ASSIGNMENT follows the convention the audit established: English-
language films to `UHD Bluray + WEB` (7), French-language to
`UHD Bluray + WEB [French]` (8). Both now allow 1080p tiers, so these are
actually acquirable - before that change they could only have matched a 2160p
release.

USAGE
-----
    python3 tools/media/add_missing_namesake_films.py            # dry run
    python3 tools/media/add_missing_namesake_films.py --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"
ROOT = "/media/media/movies"

# tmdbId -> (label, qualityProfileId)
ADD = {
    335984: ("Blade Runner 2049 (2017)", 7),
    8077:   ("Alien 3 (1992)", 7),
    42722:  ("The Nun / La Religieuse (1967, Rivette)", 8),
}


def key():
    if os.environ.get("RADARR_API"):
        return os.environ["RADARR_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; use RADARR_API=<key>")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.RADARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read RADARR_API")
    return k


def req(k, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"X-Api-Key": k,
                                        "Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=240)
    t = resp.read().decode()
    return resp.status, (json.loads(t) if t.strip() else None)


def main():
    execute = "--execute" in sys.argv
    k = key()
    _, lib = req(k, "/movie")
    have = {m["tmdbId"] for m in lib}

    plan = []
    for tid, (label, prof) in ADD.items():
        if tid in have:
            print("  SKIP  %-42s already in Radarr" % label)
            continue
        # Look up by tmdbId so the record carries TMDB's own title and year,
        # rather than the drifted year the folder name used.
        _, res = req(k, "/movie/lookup/tmdb?tmdbId=%d" % tid)
        m = res if isinstance(res, dict) else (res[0] if res else None)
        if not m:
            print("  FAIL  %-42s tmdb lookup returned nothing" % label)
            continue
        print("  ADD   %-42s -> %s (%s) profile=%s"
              % (label, m.get("title"), m.get("year"), prof))
        m.update({"qualityProfileId": prof, "rootFolderPath": ROOT,
                  "monitored": True, "minimumAvailability": "released",
                  "addOptions": {"searchForMovie": True}})
        plan.append((label, m))

    if not execute:
        print("\nDRY RUN — nothing added. Re-run with --execute.")
        return

    for label, m in plan:
        try:
            st, added = req(k, "/movie", "POST", m)
            print("  added %-42s HTTP %s id=%s"
                  % (label, st, (added or {}).get("id")))
        except Exception as e:
            print("  FAILED %-42s %s" % (label, str(e)[:100]))


if __name__ == "__main__":
    main()
