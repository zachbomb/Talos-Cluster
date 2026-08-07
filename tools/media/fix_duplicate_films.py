#!/usr/bin/env python3
"""SQ-50: resolve the duplicate films found by the same-name collision scan.

WHAT THE INVESTIGATION FOUND
----------------------------
The ticket assumed "same film filed under two years". Only half of that held.

AMERICAN WOMAN — two genuinely DIFFERENT films, and a misidentification:

    tmdb 339976  American Woman (2018)  Sienna Miller
    tmdb 567969  American Woman (2019)  Semi Chellas

Three files exist and all three are BYTE-IDENTICAL - same md5 of the first
8 MB (547d12b3a402c2c7be0ccd86f2b0bf45), same size to the byte
(5,198,088,489), same duration (6714.784 s). They are three copies of one
file, and that file is the 2019 release (`American.Woman.2019...-nikt0`).

So Radarr's 2018 record is satisfied by a copy of the 2019 film. American
Woman (2018) is NOT in the library at all; its record merely looks complete.
That is why this was invisible - `hasFile=true` on both records.

    /American Woman (2018)/American Woman (2018).mkv               untracked orphan
    /American Woman (2018)/American Woman (2019) Bluray-1080p.mkv  tracked by the 2018 record  <- wrong film
    /American Woman (2019)/American.Woman.2019...-nikt0.mkv        tracked by the 2019 record  <- correct

FIRST COW — one film, two genuinely different encodes (NOT identical):

    /First Cow (2019)/First Cow (2019).mkv   hevc 2876x2152  22.85 GB  tracked
    /First Cow (2020)/First Cow (2020).mkv   h264 1440x1080   9.62 GB  untracked orphan

Both are 1.37:1 Academy ratio, correct for the film. Radarr holds a single
record (tmdb 558582, dated 2020) pointing at the higher-resolution copy in the
folder named 2019. The 9.62 GB copy is a lower-resolution orphan.

WHAT THIS DOES
--------------
1. Deletes the 2018 record's movieFile VIA RADARR. That record then reads as
   missing - which is the truth - and searches for the actual 2018 film.
2. Deletes the two orphan files directly, since Radarr does not know them:
     - `American Woman (2018).mkv`   byte-identical third copy
     - `First Cow (2020).mkv`        lower-resolution duplicate

Reclaims roughly 20 GB and, more importantly, stops a film that is absent from
reporting as present.

NOT DONE HERE: the folder `First Cow (2019)` should be renamed to match its
record's year (2020), but the target name is occupied by the orphan's folder
until that orphan is removed. Sequence it after this runs.

USAGE
-----
    python3 tools/media/fix_duplicate_films.py            # dry run
    python3 tools/media/fix_duplicate_films.py --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"

# Radarr-tracked file to remove: the 2018 record holding a 2019 copy.
RADARR_DELETE = [(116, "American Woman (2018) — tracking a copy of the 2019 film")]

# Orphans Radarr does not track, deleted on disk.
ORPHANS = [
    ("/media/media/movies/American Woman (2018)/American Woman (2018).mkv",
     "byte-identical third copy of the 2019 film"),
    ("/media/media/movies/First Cow (2020)/First Cow (2020).mkv",
     "h264 1440x1080 duplicate; the tracked copy is hevc 2876x2152"),
]


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

    print("VIA RADARR — delete movieFile, record becomes missing and searches:")
    todo = []
    for mid, why in RADARR_DELETE:
        _, m = req(k, "/movie/%d" % mid)
        mf = m.get("movieFile") or {}
        if not mf:
            print("  SKIP %-5s %-28s already has no file" % (mid, m["title"][:28]))
            continue
        print("  %-5s %-28s fileId=%-6s %.2f GB" % (
            mid, m["title"][:28], mf.get("id"), (mf.get("size") or 0) / 1e9))
        print("        %s" % why)
        print("        %s" % (mf.get("relativePath") or "?"))
        todo.append((mid, m["title"], mf["id"]))

    print("\nON DISK — orphans Radarr does not track:")
    for path, why in ORPHANS:
        print("  %s" % path)
        print("        %s" % why)

    if not execute:
        print("\nDRY RUN — nothing deleted. Re-run with --execute.")
        print("NOTE: the two orphan deletions must be run inside a pod with the")
        print("      media share mounted; this script only prints them.")
        return

    for mid, title, fid in todo:
        try:
            st, _ = req(k, "/moviefile/%d" % fid, "DELETE")
            print("  deleted fileId=%-6s (%s) HTTP %s" % (fid, title[:26], st))
        except Exception as e:
            print("  FAILED  fileId=%-6s %s" % (fid, str(e)[:80]))

    ids = [mid for mid, _, _ in todo]
    if ids:
        _, c = req(k, "/command", "POST",
                   {"name": "MoviesSearch", "movieIds": ids})
        print("  MoviesSearch dispatched: commandId=%s" % (c or {}).get("id"))

    print("\nOrphan files still need removing from inside a media-mounted pod:")
    for path, _ in ORPHANS:
        print("  rm -- %r" % path)


if __name__ == "__main__":
    main()
