#!/usr/bin/env python3
"""Triage Radarr/Sonarr downloads that completed but never imported.

WHY THIS EXISTS - "stalling post download" is never ONE problem
---------------------------------------------------------------
Measured 2026-08-08. Radarr had 512.5 GB stuck across 11 items; Sonarr had 81.9 GB
across 61. Same symptom, completely different distributions, and only ONE class is
safe to resolve automatically:

  SOFT-SAMPLE   item identified, sole blocker "Unable to determine if file is a
                sample". Small legitimate films and 1.4 GB episodes trip this
                heuristic constantly. SAFE TO FORCE - the match is already correct
                and we are only overriding a size guess.
                Radarr: 2 items / 4.4 GB.  Sonarr: 57 items / 77.3 GB.

  NOT-UPGRADE   the app GRABBED it and then refused its own grab. Force-importing
                installs a file it scored as WORSE than what you have. On Radarr
                this was 249.7 GB of *.Ita.Eng.x265-NAHOM releases; on Sonarr a
                1080p grabbed over an existing WEBDL-2160p. NOT AUTO-RESOLVED.
                See SQ-56 - one of these silently REPLACED a 6305-score file with
                a 500-score file in April and called it an upgrade.

  XEM-MAPPING   (Sonarr only) "This show has individual episode mappings on TheXEM
                but the mapping for this episode has not been..." - scene/absolute
                numbering disagreement. Related to SQ-55 (positional episode
                shifts); American Dad! appears in BOTH. NOT AUTO-RESOLVED.

  BROKEN        archive never extracted, or manualimport returns NO CANDIDATE
                FILES. Download-side failure; importing cannot help.

  NO-MATCH      no movie/series association at all. Guessing an identity here is
                how the Rohmer-vs-Wilder "Love in the Afternoon" mixup happened.
                NOT AUTO-RESOLVED - a human decides.

So this tool ONLY force-imports SOFT-SAMPLE. Everything else is reported.

A QUERY TRAP WORTH KNOWING
--------------------------
`GET /queue` returns movie/series = null for EVERY record unless you pass
`includeMovie=true` (Radarr) / `includeSeries=true` (Sonarr). Without it every item
looks like it has lost its association - a systemic-looking failure that is purely a
missing query parameter. That cost real time before it was spotted.

USAGE
-----
    python3 tools/media/resolve_arr_imports.py --app radarr
    python3 tools/media/resolve_arr_imports.py --app sonarr --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

APPS = {
    "radarr": {
        "base": "http://192.168.10.210:7878/api/v3",
        "key_var": "RADARR_API",
        "id_field": "movieId",
        "entity": "movie",
        "include": "includeMovie",
        "unknown": "includeUnknownMovieItems",
    },
    "sonarr": {
        "base": "http://192.168.10.211:8989/api/v3",
        "key_var": "SONARR_API",
        "id_field": "seriesId",
        "entity": "series",
        "include": "includeSeries",
        "unknown": "includeUnknownSeriesItems",
    },
}

SOFT_REJECTIONS = {"unable to determine if file is a sample"}


def key(var):
    if os.environ.get(var):
        return os.environ[var].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; use %s=<key>" % var)
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.%s}" % var],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read %s" % var)
    return k


def req(cfg, k, path, method="GET", body=None, params=None):
    url = cfg["base"] + path
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
    if "not an upgrade" in j or "not a custom format upgrade" in j:
        return "NOT-UPGRADE"
    if "thexem" in j or "mapping for this episode" in j:
        return "XEM-MAPPING"
    if "archive" in j:
        return "BROKEN-ARCHIVE"
    if "no files found are eligible" in j:
        return "BROKEN-NOFILES"
    if "sample" in j:
        return "SOFT-SAMPLE"
    if "manual import" in j:
        return "NO-MATCH"
    return "OTHER"


def main():
    app = "radarr"
    if "--app" in sys.argv:
        app = sys.argv[sys.argv.index("--app") + 1]
    if app not in APPS:
        raise SystemExit("--app must be radarr or sonarr")
    cfg = APPS[app]
    execute = "--execute" in sys.argv
    k = key(cfg["key_var"])

    _, q = req(cfg, k, "/queue", params={
        "pageSize": 300, cfg["include"]: "true", cfg["unknown"]: "true"})
    recs = [r for r in (q or {}).get("records", [])
            if r.get("trackedDownloadState") not in ("downloading", None)]

    buckets = {}
    for r in recs:
        buckets.setdefault(classify(r), []).append(r)

    print("%s STALLED QUEUE — %d items, %.1f GB\n"
          % (app.upper(), len(recs),
             sum((r.get("size") or 0) for r in recs) / 1e9))
    for cls in sorted(buckets, key=lambda c: -len(buckets[c])):
        gb = sum((r.get("size") or 0) for r in buckets[cls]) / 1e9
        print("  %-16s %3d items  %8.2f GB" % (cls, len(buckets[cls]), gb))

    todo = []
    for r in buckets.get("SOFT-SAMPLE", []):
        ent = r.get(cfg["entity"]) or {}
        if not ent.get("id"):
            print("  SKIP (no %s): %s" % (cfg["entity"], r.get("title", "?")[:60]))
            continue
        folder = r.get("outputPath")
        if not folder:
            continue
        try:
            _, cands = req(cfg, k, "/manualimport",
                           params={"folder": folder, "filterExistingFiles": "false"})
        except Exception as e:
            print("  SKIP (manualimport failed): %s — %s"
                  % (r.get("title", "?")[:44], str(e)[:50]))
            continue
        for f in (cands or []):
            reasons = {str(x.get("reason", "")).lower()
                       for x in (f.get("rejections") or [])}
            if reasons - SOFT_REJECTIONS:
                continue
            item = {"path": f.get("path"),
                    "quality": f.get("quality"),
                    "languages": f.get("languages"),
                    "downloadId": r.get("downloadId")}
            if app == "radarr":
                item["movieId"] = ent["id"]
            else:
                item["seriesId"] = ent["id"]
                eps = f.get("episodes") or []
                if not eps:
                    continue          # never import an episode we cannot identify
                item["episodeIds"] = [e["id"] for e in eps]
            item["_label"] = ent.get("title")
            item["_size"] = f.get("size") or 0
            todo.append(item)

    print("\nFORCE-IMPORT PLAN (soft rejections only): %d files" % len(todo))
    for t in todo[:15]:
        print("  %-34s %6.2f GB  %s" % (str(t["_label"])[:34], t["_size"] / 1e9,
                                        os.path.basename(t["path"])[:40]))
    if len(todo) > 15:
        print("  ... and %d more" % (len(todo) - 15))

    print("\nLEFT FOR A HUMAN:")
    for cls in ("NOT-UPGRADE", "XEM-MAPPING", "BROKEN-ARCHIVE",
                "BROKEN-NOFILES", "NO-MATCH", "OTHER"):
        for r in buckets.get(cls, []):
            ent = (r.get(cfg["entity"]) or {}).get("title") or "UNMATCHED"
            print("  [%-14s] %-34s %6.2f GB" % (cls, str(ent)[:34],
                                                (r.get("size") or 0) / 1e9))

    if not execute:
        print("\nDRY RUN — nothing imported. Re-run with --execute.")
        return
    if not todo:
        return

    files = [{kk: v for kk, v in t.items() if not kk.startswith("_")} for t in todo]
    st, c = req(cfg, k, "/command", "POST",
                {"name": "ManualImport", "files": files, "importMode": "auto"})
    print("\n  ManualImport dispatched: HTTP %s commandId=%s"
          % (st, (c or {}).get("id")))


if __name__ == "__main__":
    main()
