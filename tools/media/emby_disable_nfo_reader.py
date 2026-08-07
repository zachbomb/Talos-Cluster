#!/usr/bin/env python3
"""Stop Emby reading TMM's NFO residue (SQ-44 / layer-3 alignment).

THE DEFECT, verified directly rather than inherited from the audit
------------------------------------------------------------------
Emby's Movies library reports 2,208 items against Radarr's 1,889 files. The
difference breaks down as:

    1,889  match a Radarr file exactly
      221  an extras SUBDIR file promoted to a first-class movie
       36  an extras SUFFIX file (`-trailer.mkv`) promoted the same way
       62  real alternate cuts/editions Radarr cannot track (one file per
           movie), e.g. {edition-Redux}, {edition-1945 Pre-Release},
           -bootlegcut, -alternate. NOT a defect - these are the multiple
           editions that must stay independently selectable.

The 257 promoted extras carry `ExtraType=None`, so Emby is not classifying
them as extras at all - they are genuine Movie items.

MECHANISM, confirmed by looking at the files
--------------------------------------------
    Godzilla (1954)/Interviews/
        Akira Ifukube-interview.mkv        4.99 GB
        Akira Ifukube-interview.nfo        <- sidecar NFO
        Akira Ifukube-interview-poster.jpg

Every extra carries a TMM-written NFO. Emby's Movies library has
`DisabledLocalMetadataReaders: []`, so the NFO reader is active: Emby reads
each NFO, gets an identity, and creates a movie. 1,356 extras directories
exist.

The same reader is why 57 folders whose TMM NFO contradicts Radarr's TMDB id
mis-resolve in Emby, and why 76 extras are confidently misidentified as real
films. Plex ignores NFOs entirely and is immune to all of it.

THE FIX
-------
Add "Nfo" to `DisabledLocalMetadataReaders` on the Movies library. Emby then
identifies from TheMovieDb only - the same posture as Plex.

Touches NO files on disk. The NFOs stay where they are; Emby simply stops
believing them. Rollback is removing "Nfo" and rescanning.

NOTE: `SaveLocalMetadata` is True, so Emby also WRITES NFOs. That is left
alone here - this change is about what Emby BELIEVES, and altering the write
path is a separate decision.

USAGE
-----
    python3 tools/media/emby_disable_nfo_reader.py            # dry run
    python3 tools/media/emby_disable_nfo_reader.py --execute
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.204:10079/emby"   # NOT :8096 - that port is closed
SNAPSHOT = "/tmp/emby_libraryoptions_snapshot.json"
TARGET_COLLECTION = "movies"


def key():
    if os.environ.get("EMBY_API"):
        return os.environ["EMBY_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; use EMBY_API=<key>")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.EMBY_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read EMBY_API")
    return k


def req(k, path, method="GET", body=None):
    url = BASE + path + ("&" if "?" in path else "?") + "api_key=" + k
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=180)
    t = resp.read().decode()
    return resp.status, (json.loads(t) if t.strip() else None)


def main():
    execute = "--execute" in sys.argv
    k = key()
    _, folders = req(k, "/Library/VirtualFolders")
    target = [f for f in folders
              if (f.get("CollectionType") or "") == TARGET_COLLECTION]
    if not target:
        raise SystemExit("no %s library found" % TARGET_COLLECTION)

    plan = []
    for f in target:
        opts = f.get("LibraryOptions") or {}
        cur = list(opts.get("DisabledLocalMetadataReaders") or [])
        print("  library %-14s id=%-38s DisabledLocalMetadataReaders=%s"
              % (f.get("Name"), f.get("ItemId") or f.get("Id"), cur))
        if "Nfo" in cur:
            print("        already disabled — nothing to do")
            continue
        plan.append((f, opts, cur))

    if not plan:
        print("\nnothing to change.")
        return
    if not execute:
        print("\nDRY RUN — would set DisabledLocalMetadataReaders to "
              "%s. Re-run with --execute." % (["Nfo"],))
        return

    json.dump([{"Id": f.get("ItemId") or f.get("Id"),
                "Name": f.get("Name"),
                "DisabledLocalMetadataReaders": cur}
               for f, _o, cur in plan],
              open(SNAPSHOT, "w"), indent=1)
    print("\nprior settings -> %s" % SNAPSHOT)

    for f, opts, cur in plan:
        lid = f.get("ItemId") or f.get("Id")
        opts["DisabledLocalMetadataReaders"] = cur + ["Nfo"]
        st, _ = req(k, "/Library/VirtualFolders/LibraryOptions", "POST",
                    {"Id": lid, "LibraryOptions": opts})
        print("  updated %-14s HTTP %s" % (f.get("Name"), st))

    _, folders = req(k, "/Library/VirtualFolders")
    print("\nverifying:")
    for f in folders:
        if (f.get("CollectionType") or "") != TARGET_COLLECTION:
            continue
        got = (f.get("LibraryOptions") or {}).get(
            "DisabledLocalMetadataReaders")
        print("  %-14s -> %s" % (f.get("Name"), got))


if __name__ == "__main__":
    main()
