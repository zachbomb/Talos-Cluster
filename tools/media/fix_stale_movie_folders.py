#!/usr/bin/env python3
"""SQ-47: rename five movie folders whose names are stale, via Radarr.

WHAT THIS IS AND IS NOT
-----------------------
The ticket was filed as "5 folders contain a different film than their name
says", on the theory that Radarr's record and the file content disagreed.
Investigation showed the opposite: **Radarr and the file agree in every
case**. The folder name is the only thing that is wrong.

    folder                            Radarr record (correct)         tmdb
    Blade Runner 2049 (2017)          Blade Runner (1982)             78
    Alien³ (1992)                     Aliens (1986)                   679
    The Nun (1965)                    The Nun's Story (1959)          27029
    Tokyo Story (1972) (1972)         Tokyo Story (1953)              18148
    Ten Nights in a Bar Room (1931)   Ten Nights in a Bar-room (1931) 94258

None of the folders' namesakes exists in Radarr at all - there is no Blade
Runner 2049, no Alien³, no The Nun (1965), and "Tokyo Story (1972)" is not a
film (Ozu's is 1953, and that folder carries a doubled year). These are stale
names left by previous occupants; the directories were reused and never
renamed. So nothing is missing and nothing is misfiled.

WHY NOT JUST RUN RADARR'S OWN FOLDER RENAME
-------------------------------------------
`movieFolderFormat` is `{Movie CleanTitle} ({Release Year}) {tmdb-{TmdbId}}`,
but the library's existing folders carry no `{tmdb-}` suffix. Triggering
Radarr's rename would rewrite EVERY folder in the library to add it - a
library-wide change far outside this ticket. So each path is set explicitly,
following the convention the library actually uses.

All five target names were verified free before this was written.

ONE UNRESOLVED IDENTITY QUESTION, deliberately not decided here
--------------------------------------------------------------
`Ten Nights in a Bar Room (1931)/` holds `Ten Nights in a Bar Room (1921).mkv`
(63.9 min) and Radarr tracks it as the 1931 film. Multiple versions of this
title exist (1903, 1910, 1921, 1926, 1931). Renaming the folder to match
Radarr is harmless either way, but WHICH version the file actually is remains
unverified and needs a human who can watch it. The rename does not settle it.

USAGE
-----
    python3 tools/media/fix_stale_movie_folders.py            # dry run
    python3 tools/media/fix_stale_movie_folders.py --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"
SNAPSHOT = "/tmp/radarr_folder_snapshot.json"

# movieId -> (expected current basename, target basename)
# The expected-current guard means a folder already fixed, or a record that
# moved for some other reason, is skipped rather than moved somewhere wrong.
RENAMES = {
    216:  ("Blade Runner 2049 (2017)",        "Blade Runner (1982)"),
    92:   ("Alien³ (1992)",              "Aliens (1986)"),
    1578: ("The Nun (1965)",                  "The Nun's Story (1959)"),
    1730: ("Tokyo Story (1972) (1972)",       "Tokyo Story (1953)"),
    1325: ("Ten Nights in a Bar Room (1931)", "Ten Nights in a Bar-room (1931)"),
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
    resp = urllib.request.urlopen(r, timeout=300)
    t = resp.read().decode()
    return resp.status, (json.loads(t) if t.strip() else None)


def main():
    execute = "--execute" in sys.argv
    k = key()
    prior, plan = {}, []

    for mid, (expect, target) in RENAMES.items():
        _, m = req(k, "/movie/%d" % mid)
        prior[str(mid)] = {"path": m.get("path"), "title": m.get("title")}
        cur = (m.get("path") or "").rstrip("/").split("/")[-1]
        root = m.get("rootFolderPath", "/media/media/movies").rstrip("/")
        newpath = "%s/%s" % (root, target)
        if cur != expect:
            print("  SKIP %-5s %-28s current folder is %r, expected %r"
                  % (mid, m["title"][:28], cur, expect))
            continue
        m["path"] = newpath
        plan.append((mid, m, cur, target))
        print("  %-5s %-30s %r" % (mid, m["title"][:30], cur))
        print("        -> %r" % target)

    if not execute:
        print("\nDRY RUN — nothing moved. Re-run with --execute.")
        return

    json.dump(prior, open(SNAPSHOT, "w"), indent=1)
    print("\nprior paths -> %s" % SNAPSHOT)

    for mid, m, cur, target in plan:
        try:
            st, _ = req(k, "/movie/%d?moveFiles=true" % mid, "PUT", m)
            print("  moved %-5s %-30s HTTP %s" % (mid, m["title"][:30], st))
        except Exception as e:
            print("  FAILED %-5s %-30s %s" % (mid, m["title"][:30], str(e)[:80]))

    print("\nverifying:")
    for mid in RENAMES:
        _, m = req(k, "/movie/%d" % mid)
        print("  %-5s %-30s %s" % (mid, m["title"][:30],
                                   (m.get("path") or "").split("/")[-1]))


if __name__ == "__main__":
    main()
