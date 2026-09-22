#!/usr/bin/env python3
"""Import files into Sonarr against an explicit, pre-verified episode manifest.

WHY THIS EXISTS. For some shows Sonarr cannot be trusted to work out which
episode a file is. VH1's "I Love the..." titles its episodes by YEAR, and the
same year appears in several seasons (S1, S3 and S6 all cover 1980-1989), while
archive.org names like `VH 1 I Love The 80s 1980 360p` do not parse to the
series at all (SQ-152). Mayday is the same failure from the other side: Sonarr
matched on an SxxExx number, imported the wrong episode, renamed it, and
destroyed the evidence. Letting the parser guess is exactly how a library gets
damaged.

So this tool never lets Sonarr guess:

  1. Every candidate file is identified by its MD5, not its name. A file whose
     MD5 is not in the manifest is reported and left untouched.
  2. Each matched file is imported with Sonarr's Manual Import API bound to an
     EXPLICIT episode id from the manifest.
  3. An episode that already has a file is skipped - never overwritten.
  4. After import, every episode is re-read and its bound file size must equal
     the manifest's size. Anything else is reported as a failure.

The manifest is produced separately (see `manifest-verified.json` beside the
intake folder); this tool only executes it.

DEFAULT IS A DRY RUN. Nothing moves without --apply.

ACCESS. Media is not on this Mac. MD5s are computed inside the Sonarr pod via
`kubectl exec` (KUBECONFIG must point at the loopback relay; plain kubectl from
this Mac reports a misleading "no route to host"). Sonarr's URL and key come
from the environment, or from the cluster-config ConfigMap if unset:

    SONARR_URL   e.g. http://192.168.10.211:8989
    SONARR_API   never passed on argv

USAGE

    ./manifest_import.py --series-id 80 --intake "/media/media/_intake/i-love-the"
    ./manifest_import.py --series-id 80 --intake "/media/media/_intake/i-love-the" --apply
"""
import argparse, json, os, subprocess, sys, time, urllib.request

NS = "media"
POD_SELECTOR = "app.kubernetes.io/instance=sonarr"
CONTAINER = "sonarr"          # the pod's DEFAULT container is exportarr, which has no shell
VIDEO_EXT = ("mp4", "mkv", "avi", "m4v")


def kube(*args):
    return subprocess.run(["kubectl", *args], capture_output=True, text=True, check=True).stdout


def cluster_value(key):
    return kube("get", "cm", "cluster-config", "-n", "flux-system",
                "-o", f"jsonpath={{.data.{key}}}").strip()


def sonarr(method, path, key, base, body=None, timeout=120):
    req = urllib.request.Request(f"{base}/api/v3/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("X-Api-Key", key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def pod_name():
    return kube("get", "pod", "-n", NS, "-l", POD_SELECTOR,
                "-o", "jsonpath={.items[0].metadata.name}").strip()


def intake_md5s(pod, intake):
    """md5 -> path for every video file under the intake folder.

    Passed as argv, not a piped heredoc: piping a script into `kubectl exec -i
    ... sh` feeds the script to any inner `read`, which then silently reads
    nothing and yields a clean, plausible, wrong "0 files"."""
    names = []
    for ext in VIDEO_EXT:
        names += ["-o", "-iname", f"*.{ext}"]
    out = kube("exec", "-n", NS, pod, "-c", CONTAINER, "--",
               "find", intake, "-type", "f", "(", *names[1:], ")",
               "-exec", "md5sum", "{}", "+")
    found = {}
    for line in out.splitlines():
        md5, _, path = line.partition("  ")
        if md5 and path:
            found.setdefault(md5, []).append(path)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series-id", type=int, required=True)
    ap.add_argument("--intake", required=True, help="folder as the Sonarr pod sees it")
    ap.add_argument("--manifest", help="local manifest JSON; default: <intake>/manifest-verified.json read from the pod")
    ap.add_argument("--apply", action="store_true", help="actually import (default is a dry run)")
    args = ap.parse_args()

    base = os.environ.get("SONARR_URL") or f"http://{cluster_value('SONARR_IP')}:8989"
    key = os.environ.get("SONARR_API") or cluster_value("SONARR_API")
    pod = pod_name()

    if args.manifest:
        manifest = json.load(open(args.manifest))
    else:
        manifest = json.loads(kube("exec", "-n", NS, pod, "-c", CONTAINER, "--",
                                   "cat", f"{args.intake.rstrip('/')}/manifest-verified.json"))
    rows = {r["md5"]: r for r in manifest["manifest"]}
    print(f"   manifest: {len(rows)} rows; hashing intake {args.intake} ...", flush=True)

    found = intake_md5s(pod, args.intake)
    episodes = {e["id"]: e for e in sonarr("GET", f"episode?seriesId={args.series_id}", key, base)}

    plan, skipped, unknown = [], [], []
    for md5, paths in sorted(found.items()):
        row = rows.get(md5)
        if not row:
            unknown += paths
            continue
        ep = episodes.get(row["episodeId"])
        tag = f"S{row['season']:02d}E{row['episode']:02d} {row['title']}"
        if ep is None:
            skipped.append((tag, "episode id not in this series"))
        elif ep.get("hasFile"):
            skipped.append((tag, "already has a file - never overwritten"))
        else:
            plan.append((row, paths[0]))

    print(f"   matched by MD5: {len(plan)}   skipped: {len(skipped)}   "
          f"unknown files (left alone): {len(unknown)}\n")
    for row, path in plan:
        print(f"  IMPORT S{row['season']:02d}E{row['episode']:02d} {row['title']:<24} <- {path.rsplit('/', 1)[-1]}")
    for tag, why in skipped:
        print(f"  SKIP   {tag:<32} {why}")
    for path in unknown:
        print(f"  ??     not in manifest: {path}")

    if not plan:
        return
    if not args.apply:
        print("\n   DRY RUN - nothing moved. Re-run with --apply to import.")
        return

    # Sonarr supplies quality/language per path; we override ONLY the episode binding.
    detected = {i["path"]: i for i in sonarr(
        "GET", f"manualimport?folder={urllib.request.quote(args.intake)}"
               f"&seriesId={args.series_id}&filterExistingFiles=false", key, base, timeout=600)}
    files = []
    for row, path in plan:
        d = detected.get(path, {})
        files.append({"path": path, "seriesId": args.series_id, "episodeIds": [row["episodeId"]],
                      "quality": d.get("quality"), "languages": d.get("languages") or [{"id": 1, "name": "English"}],
                      "releaseGroup": d.get("releaseGroup") or "", "indexerFlags": 0,
                      "releaseType": "singleEpisode"})
    cmd = sonarr("POST", "command", key, base, {"name": "ManualImport", "files": files, "importMode": "move"})
    print(f"\n   ManualImport queued (command {cmd['id']}); waiting ...", flush=True)
    while True:
        st = sonarr("GET", f"command/{cmd['id']}", key, base)["status"]
        if st not in ("queued", "started"):
            break
        time.sleep(5)
    print(f"   command finished: {st}")

    after = {e["id"]: e for e in sonarr(
        "GET", f"episode?seriesId={args.series_id}&includeEpisodeFile=true", key, base)}
    ok = bad = 0
    for row, _ in plan:
        e = after.get(row["episodeId"], {})
        size = (e.get("episodeFile") or {}).get("size")
        good = e.get("hasFile") and size == row["size"]
        ok += good
        bad += not good
        if not good:
            print(f"  FAIL   S{row['season']:02d}E{row['episode']:02d}: hasFile={e.get('hasFile')} "
                  f"size={size} want={row['size']}")
    print(f"\n   verified: {ok} imported with byte-exact size, {bad} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
