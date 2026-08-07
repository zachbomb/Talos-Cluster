#!/usr/bin/env python3
"""Delete the 17 verified-corrupt movie files via Radarr, then re-search.

WHY THIS IS A SCRIPT AND NOT AN INLINE COMMAND
----------------------------------------------
It deletes files. That deserves an explicit, reviewable artifact rather than a
shell one-liner buried in a transcript.

WHAT MAKES THE DELETION SAFE
----------------------------
Every target was verified undemuxable before this list was built - 14 fail with
`EBML header parsing failed` (the Matroska header itself is unreadable), plus a
fatal dvdsub error, an EBML length error and one more. Plex, Emby and Tunarr
cannot play a single frame of any of them. Deleting them cannot lose anything.

Two files that the first pass flagged are deliberately NOT here, because
re-probing showed they are fine:
  - `Wonderstruck (2017).iso` - ffprobe cannot demux a filesystem image, so its
    "Invalid data found" was the expected result for an intact UDF volume
    (BEA01 / NSR03 / TEA01 present).
  - `Long Day's Journey Into Night (1962)` - reads 10220.34 s across 5 streams.
    A 196 kbps encode is a quality problem, not a corruption.

WHAT THIS WILL AND WILL NOT ACHIEVE
-----------------------------------
Deleting clears the `Existing file on disk is of equal or higher preference`
and `equal or higher Custom Format score` rejections. It does NOT clear the
other two blockers observed on Satyricon's 140 candidate releases:

    109  English is wanted, but found Italian
     41  Bluray-1080p is not wanted in profile
     17  Remux-1080p is not wanted in profile

So titles whose only obstacle was the incumbent file will now grab; foreign-
language titles under an English-demanding profile, and titles whose only
available quality is disabled between `Bluray-1080p` and the `Remux-2160p`
cutoff, will still find nothing. That is a quality-profile problem, not an
indexer one, and it is worth fixing separately - the profiles currently reject
the very releases that would replace these films.

USAGE
-----
    python3 tools/media/replace_corrupt_via_radarr.py            # dry run
    python3 tools/media/replace_corrupt_via_radarr.py --execute  # do it

The API key is read from the cluster-config ConfigMap, never hard-coded.
A snapshot of every movieId / movieFileId / path is written before any
deletion so the prior state stays reconstructable.
"""
import json
import os
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"
SNAPSHOT = "/tmp/radarr_predelete_snapshot.json"

# Verified undemuxable. Basenames, matched against the manifest.
READABLE_DO_NOT_TOUCH = {
    "Wonderstruck (2017).iso",
    "Long Day's Journey Into Night (1962) Bluray-1080p.mkv",
}


def key():
    """RADARR_API from cluster-config, or $RADARR_API as an override.

    Resolves kubectl explicitly rather than trusting PATH: an interactive
    shell and a tool-run shell do not always agree on it, and a bare
    `kubectl: not found` here would otherwise look like an empty API key.
    """
    if os.environ.get("RADARR_API"):
        return os.environ["RADARR_API"].strip()
    import shutil
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit(
            "kubectl not found on PATH. Either add it, or run with:\n"
            "  RADARR_API=<key> python3 %s --execute" % sys.argv[0])
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.RADARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read RADARR_API from cluster-config: %s"
                         % (out.stderr or "empty result")[:200])
    return k


def req(k, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"X-Api-Key": k,
                                        "Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=180)
    text = resp.read().decode()
    return resp.status, (json.loads(text) if text.strip() else None)


def main():
    execute = "--execute" in sys.argv
    k = key()

    here = os.path.dirname(os.path.abspath(__file__))
    man = json.load(open(os.path.join(
        here, "../../docs/media/preservation-manifest.json")))
    broken = [r for r in man["rows"]
              if r.get("implausible") and r["file"] not in READABLE_DO_NOT_TOUCH]

    _, movies = req(k, "/movie")
    by_path = {}
    for m in movies:
        mf = m.get("movieFile") or {}
        if mf.get("path"):
            by_path[mf["path"]] = m

    targets = []
    for r in sorted(broken, key=lambda r: r["folder"]):
        m = by_path.get(r["path"])
        if not m:
            print("  UNTRACKED  %s" % r["file"][:60])
            continue
        targets.append({"movieId": m["id"], "movieFileId": m["movieFile"]["id"],
                        "title": m["title"], "year": m.get("year"),
                        "path": r["path"], "sizeGB": round(r["size"] / 1e9, 2)})

    print("targets: %d\n" % len(targets))
    for t in targets:
        print("  %-32s movieId=%-5s fileId=%-6s %6.2f GB"
              % (t["title"][:32], t["movieId"], t["movieFileId"], t["sizeGB"]))

    if not execute:
        print("\nDRY RUN - nothing deleted. Re-run with --execute to proceed.")
        return

    json.dump(targets, open(SNAPSHOT, "w"), indent=1)
    print("\nsnapshot -> %s" % SNAPSHOT)

    ok = fail = 0
    for t in targets:
        try:
            st, _ = req(k, "/moviefile/%d" % t["movieFileId"], "DELETE")
            print("  deleted %-30s HTTP %s" % (t["title"][:30], st))
            ok += 1
        except Exception as e:
            print("  FAILED  %-30s %s" % (t["title"][:30], str(e)[:70]))
            fail += 1
    print("\ndeleted=%d failed=%d" % (ok, fail))

    ids = [t["movieId"] for t in targets]
    _, c = req(k, "/command", "POST", {"name": "MoviesSearch", "movieIds": ids})
    print("MoviesSearch dispatched: commandId=%s status=%s"
          % (c.get("id"), c.get("status")))
    print("\nCheck results with:  /queue  and  /history?eventType=grabbed")


if __name__ == "__main__":
    main()
