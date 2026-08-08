#!/usr/bin/env python3
"""Resolve Radarr downloads that completed but never imported.

WHAT WAS ACTUALLY WRONG (2026-08-08) - it is NOT one problem
------------------------------------------------------------
11 items, 512.5 GB, stuck in "completed" but never imported. Four distinct causes:

  A. SOFT-REJECT  - movie identified, only blocker is "Unable to determine if file
                    is a sample". Small legitimate films trip this (House Specialty
                    0.96 GB, O Saisons 3.55 GB). SAFE TO FORCE - the movie match is
                    already correct, we are only overriding the sample heuristic.

  B. NOT-UPGRADE  - 249.7 GB across 4 titles, every one a
                    *.REPACK.4K.HDR.DV.2160p.BDRemux.Ita.Eng.x265-NAHOM release,
                    every one rejected "Not a Custom Format upgrade ... Language:
                    Not French". Radarr GRABBED these and then refused them at
                    import. That is a profile defect, not an import defect, and
                    force-importing would install files Radarr scored as WORSE than
                    what you already have. NOT AUTO-RESOLVED - needs your decision.

  C. BROKEN       - Raiders (archive not extracted), Bourne Legacy (manualimport
                    returns NO CANDIDATE FILES). Download-side failures; importing
                    cannot help. NOT AUTO-RESOLVED.

  D. NO-MATCH     - The Lover (1992) 79 GB, M3gan (2022) 53 GB: Radarr has no movie
                    association at all. Guessing an identity here is how you end up
                    with the wrong film in the library - exactly the class of error
                    that produced the Rohmer-vs-Wilder "Love in the Afternoon"
                    mixup. NOT AUTO-RESOLVED.

So this tool ONLY force-imports class A. Everything else is reported for a human.

A QUERY TRAP WORTH KNOWING
--------------------------
`GET /queue` returns movie=null for EVERY record unless you pass
`includeMovie=true`. Without it, all 11 items look like they lost their movie
association - a systemic-looking failure that is purely a missing query parameter.

USAGE
-----
    python3 tools/media/resolve_radarr_imports.py            # dry run (default)
    python3 tools/media/resolve_radarr_imports.py --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"

# Only these rejection reasons are overridden. Anything else is left alone.
SOFT_REJECTIONS = {"unable to determine if file is a sample"}


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


def req(k, path, method="GET", body=None, params=None):
    url = BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"X-Api-Key": k,
                                        "Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=180)
    t = resp.read().decode()
    return resp.status, (json.loads(t) if t.strip() else None)


def classify(rec):
    msgs = []
    for m in (rec.get("statusMessages") or []):
        msgs += (m.get("messages") or [])
    j = " ".join(msgs).lower()
    if "not a custom format upgrade" in j:
        return "NOT-UPGRADE"
    if "archive" in j:
        return "BROKEN-ARCHIVE"
    if "no files found are eligible" in j:
        return "BROKEN-NOFILES"
    if "sample" in j:
        return "SOFT-SAMPLE"
    if "manual import required" in j:
        return "NO-MATCH" if not rec.get("movie") else "SOFT-MATCHED"
    return "OTHER"


def main():
    execute = "--execute" in sys.argv
    k = key()

    _, q = req(k, "/queue", params={"pageSize": 200, "includeMovie": "true",
                                    "includeUnknownMovieItems": "true"})
    recs = [r for r in (q or {}).get("records", [])
            if r.get("trackedDownloadState") != "downloading"]

    buckets = {}
    for r in recs:
        buckets.setdefault(classify(r), []).append(r)

    print("STALLED QUEUE — %d items, %.1f GB\n" % (
        len(recs), sum((r.get("size") or 0) for r in recs) / 1e9))
    for cls in sorted(buckets):
        gb = sum((r.get("size") or 0) for r in buckets[cls]) / 1e9
        print("  %-16s %2d items  %7.1f GB" % (cls, len(buckets[cls]), gb))
    print()

    todo = []
    for r in buckets.get("SOFT-SAMPLE", []) + buckets.get("SOFT-MATCHED", []):
        mv = r.get("movie") or {}
        if not mv.get("id"):
            print("  SKIP (no movie): %s" % r.get("title", "?")[:70])
            continue
        folder = r.get("outputPath")
        try:
            _, cands = req(k, "/manualimport",
                           params={"folder": folder, "filterExistingFiles": "false"})
        except Exception as e:
            print("  SKIP (manualimport failed): %s — %s"
                  % (r.get("title", "?")[:50], str(e)[:60]))
            continue
        for f in (cands or []):
            reasons = {str(x.get("reason", "")).lower()
                       for x in (f.get("rejections") or [])}
            hard = reasons - SOFT_REJECTIONS
            if hard:
                print("  SKIP (hard rejection %s): %s"
                      % (list(hard)[:1], str(f.get("relativePath"))[:52]))
                continue
            todo.append({
                "path": f.get("path"),
                "movieId": mv["id"],
                "quality": f.get("quality"),
                "languages": f.get("languages"),
                "downloadId": r.get("downloadId"),
                "_title": mv.get("title"),
                "_size": f.get("size") or 0,
            })

    print("\nFORCE-IMPORT PLAN (soft rejections only):")
    if not todo:
        print("  nothing safely importable")
    for t in todo:
        print("  %-34s %6.2f GB  %s" % (t["_title"][:34], t["_size"] / 1e9,
                                        os.path.basename(t["path"])[:44]))

    print("\nLEFT FOR A HUMAN — force-importing these would be wrong:")
    for cls in ("NOT-UPGRADE", "BROKEN-ARCHIVE", "BROKEN-NOFILES", "NO-MATCH", "OTHER"):
        for r in buckets.get(cls, []):
            mv = (r.get("movie") or {}).get("title") or "UNMATCHED"
            print("  [%-14s] %-34s %6.2f GB" % (cls, str(mv)[:34],
                                                (r.get("size") or 0) / 1e9))

    if not execute:
        print("\nDRY RUN — nothing imported. Re-run with --execute.")
        return
    if not todo:
        return

    files = [{kk: v for kk, v in t.items() if not kk.startswith("_")} for t in todo]
    st, c = req(k, "/command", "POST",
                {"name": "ManualImport", "files": files, "importMode": "auto"})
    print("\n  ManualImport dispatched: HTTP %s commandId=%s"
          % (st, (c or {}).get("id")))


if __name__ == "__main__":
    main()
