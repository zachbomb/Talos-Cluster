#!/usr/bin/env python3
"""Fetch external .srt sidecars for films that Bazarr considers already covered.

WHY THIS IS NEEDED. Bazarr's coverage model has a blind spot:
`general.use_embedded_subs = true` makes embedded subtitle tracks count as
existing, and `ignore_ass_subs` / `ignore_pgs_subs` / `ignore_vobsub_subs` are
true so ASS/PGS/VobSub are EXCLUDED from that counting and therefore stay
eligible for extraction. There is no equivalent flag for embedded SRT — so a
film carrying an embedded SRT reads as fully covered, never appears in "wanted",
and never gets a sidecar written to disk.

That matters because a live-TV client consuming a Tunarr transcode cannot use an
embedded track at all; it needs a real .srt file next to the video. Crouching
Tiger, Hidden Dragon (radarrId 354) had TWO embedded English SRTs, zero files on
disk, and did not appear among Bazarr's 83 "wanted" movies.

DO NOT "FIX" THIS BY FLIPPING THE ignore_* FLAGS. They are inverted from what
their names suggest: setting them False makes those items count as covered and
SHRINKS coverage. See memory: bazarr-ignore-flags-are-inverted.

So this sweep drives Bazarr's MANUAL provider search per film instead, which
ignores the "missing" calculation entirely.

Ordered foreign-language first: a missing sidecar makes a foreign-language film
unwatchable, where for an English film it is merely inconvenient.
"""
import argparse, json, os, time, urllib.parse, urllib.request

BASE = os.environ.get("BAZARR_URL", "http://192.168.10.216:6767")


def api(path, key, method="GET", form=None, timeout=180):
    url = f"{BASE}/api/{path}"
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-KEY", key)
    if data:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)


def pick(results, lang="en"):
    """Best candidate: right language, not hearing-impaired, not forced, top score.

    Bazarr returns these fields as STRINGS ("False", not False) — filtering on
    Python truthiness silently matches nothing."""
    c = [r for r in results
         if r.get("language") == lang
         and str(r.get("hearing_impaired")).lower() == "false"
         and str(r.get("forced")).lower() == "false"]
    if not c:
        c = [r for r in results if r.get("language") == lang]
    return max(c, key=lambda r: r.get("score") or 0) if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True, help="JSON list with radarrId/title/year")
    ap.add_argument("--state", required=True, help="resume/result file")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--pace", type=float, default=6.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-score", type=int, default=70)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    key = os.environ["BAZARR_API"]
    targets = json.load(open(args.targets))
    state = json.load(open(args.state)) if os.path.exists(args.state) else {}
    todo = [t for t in targets if str(t["radarrId"]) not in state]
    if args.limit:
        todo = todo[:args.limit]
    print(f"   targets={len(targets)} done={len(state)} to process={len(todo)} "
          f"apply={args.apply}", flush=True)

    got = skip = fail = 0
    for i, t in enumerate(todo, 1):
        rid = str(t["radarrId"])
        try:
            st, res = api(f"providers/movies?radarrid={rid}", key)
            rows = res.get("data", []) if isinstance(res, dict) else []
            best = pick(rows, args.lang)
            if not best or (best.get("score") or 0) < args.min_score:
                state[rid] = {"title": t.get("title"), "result": "no-candidate",
                              "n": len(rows),
                              "best": (best or {}).get("score")}
                skip += 1
            elif not args.apply:
                state[rid] = {"title": t.get("title"), "result": "dry-run",
                              "score": best.get("score")}
            else:
                form = {"radarrid": rid, "hi": best["hearing_impaired"],
                        "forced": best["forced"], "provider": best["provider"],
                        "subtitle": best["subtitle"],
                        "original_format": best["original_format"],
                        "language": best["language"]}
                dst, _ = api("providers/movies", key, "POST", form)
                state[rid] = {"title": t.get("title"), "result": f"http-{dst}",
                              "score": best.get("score"),
                              "provider": best.get("provider")}
                got += 1
        except Exception as e:
            msg = str(getattr(e, "code", e))
            state[rid] = {"title": t.get("title"), "result": f"error:{msg[:60]}"}
            fail += 1
            # provider quota / auth failures are terminal for the run — stop
            # rather than burning the remaining targets against a closed door
            if msg in ("401", "403", "429"):
                print(f"   STOPPING: provider returned {msg} on {t.get('title')} "
                      f"— likely quota exhausted", flush=True)
                break
        time.sleep(args.pace)
        if i % 10 == 0:
            json.dump(state, open(args.state, "w"), indent=1)
            print(f"   {i}/{len(todo)} got={got} no-candidate={skip} fail={fail}", flush=True)

    json.dump(state, open(args.state, "w"), indent=1)
    print(f"   DONE got={got} no-candidate={skip} fail={fail} total_state={len(state)}",
          flush=True)


if __name__ == "__main__":
    main()
