#!/usr/bin/env python3
"""Build/refresh a Tunarr channel from a Plex "unseen" collection.

Tunarr consumes Plex COLLECTIONS, not playlists, and it SNAPSHOTS their contents
when programming is built rather than tracking them live (upstream issue #15,
Milestone 2.0). So a channel goes stale as films get watched, and this script is
meant to be re-run nightly after the collection is recomputed.

Programming is a MANUAL shuffled lineup rather than Time Slots: Time Slots apply
a Max Lateness that truncates films mid-playback, which is fine for 22-minute
episodes and ruinous for a 2-hour feature.

Transcoding must use VAAPI. The QSV path pins output to 24.000 fps via a
constant-parser bug (normalizeFrameRate is inert), so QSV channels judder.

External id format for lookup is `plex|{mediaSourceId}|{ratingKey}` — a bare
ratingKey is rejected with FST_ERR_VALIDATION.
"""
import argparse, json, os, random, time, urllib.request
import xml.etree.ElementTree as ET

CHUNK = 100


def tun(path, method="GET", body=None, base=None, timeout=180):
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw[:1] in (b"{", b"[") else raw


def plex(path, ip, tok, timeout=180):
    sep = "&" if "?" in path else "?"
    with urllib.request.urlopen(f"http://{ip}:32400{path}{sep}X-Plex-Token={tok}",
                                timeout=timeout) as r:
        return ET.fromstring(r.read())


def collection_items(ip, tok, section, title):
    for d in plex(f"/library/sections/{section}/collections", ip, tok).findall("Directory"):
        if d.get("title") == title:
            kids = plex(f"/library/metadata/{d.get('ratingKey')}/children", ip, tok)
            return [v.get("ratingKey") for v in kids.findall("Video")]
    raise SystemExit(f"collection {title!r} not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True)
    ap.add_argument("--channel-name", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--tunarr", default=os.environ.get("TUNARR_URL", "http://192.168.10.205:8000"))
    ap.add_argument("--media-source", default="ae077270-d82a-4010-abbc-fd96463df172")
    ap.add_argument("--transcode", default="c007fc05-42a0-464f-ae8b-8d2648471b89",
                    help="H264-VAAPI; do NOT use a QSV config (fps pinned to 24.000)")
    ap.add_argument("--group", default="Unseen")
    ap.add_argument("--section", default="1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=["random", "manual"], default="random",
                    help="random = Tunarr Random Slots (re-shuffles each regeneration); "
                         "manual = fixed lineup that replays in identical order forever")
    ap.add_argument("--max-days", type=int, default=14)
    ap.add_argument("--cooldown-days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ip = os.environ.get("PLEX_IP", "192.168.10.203"); tok = os.environ["PLEX_API"]
    keys = collection_items(ip, tok, args.section, args.collection)
    print(f"   collection '{args.collection}': {len(keys)} films")

    progs, missing = [], 0
    for i in range(0, len(keys), CHUNK):
        ids = [f"plex|{args.media_source}|{k}" for k in keys[i:i + CHUNK]]
        got = tun("/api/programming/batch/lookup", "POST", {"externalIds": ids},
                  base=args.tunarr)
        for v in (got or {}).values():
            if v.get("uuid") and v.get("duration"):
                progs.append({"type": "content", "id": v["uuid"],
                              "duration": v["duration"]})
        missing += len(ids) - len(got or {})
        time.sleep(0.2)
    print(f"   resolved {len(progs)} Tunarr programs  (unmatched in Tunarr index: {missing})")
    if not progs:
        raise SystemExit("nothing resolved — is the Tunarr library scan current?")

    random.Random(args.seed or None).shuffle(progs)
    total = sum(p["duration"] for p in progs)
    print(f"   shuffled lineup: {len(progs)} items, {total/3600000:.1f} hours")
    if not args.apply:
        return

    existing = {c["number"]: c for c in tun("/api/channels", base=args.tunarr)}
    if args.number in existing:
        ch = existing[args.number]
        print(f"   reusing channel #{args.number} ({ch['name']}) id={ch['id']}")
        cid = ch["id"]
    else:
        import uuid as _u
        cid = str(_u.uuid4())
        body = {"type": "new", "channel": {
            "id": cid, "number": args.number, "name": args.channel_name,
            "startTime": int(time.time() * 1000), "duration": total,
            "stealth": False, "groupTitle": args.group,
            "guideMinimumDuration": 300000, "streamMode": "hls",
            "transcodeConfigId": args.transcode, "subtitlesEnabled": True,
            "disableFillerOverlay": True,
            "icon": {"path": "", "width": 0, "duration": 0, "position": "bottom-right"},
            "offline": {"mode": "pic"},
        }}
        tun("/api/channels", "POST", body, base=args.tunarr)
        # Tunarr ASSIGNS ITS OWN uuid and ignores the one supplied in the body,
        # so the id must be re-read by channel number. Using the submitted id in
        # the follow-up programming call 404s against a channel that never existed.
        cid = next(c["id"] for c in tun("/api/channels", base=args.tunarr)
                   if c["number"] == args.number)
        print(f"   CREATED channel #{args.number} '{args.channel_name}' id={cid}")

    if args.mode == "manual":
        # A manual lineup is a FIXED LOOP: once the cycle completes it replays in
        # the identical order forever. Kept only for debugging.
        body = {"type": "manual", "lineup": progs, "append": False}
    else:
        # Random Slots: Tunarr generates `maxDays` ahead and RE-SHUFFLES on each
        # regeneration, so the channel does not replay a fixed order at end of
        # cycle. cooldownMs stops a film recurring too soon.
        # flexPreference "end" keeps pad AFTER the film — "distribute" can place
        # flex mid-slot, which is fine for episodes and wrong for a feature.
        import uuid as _u
        body = {"type": "random",
                "programs": [p["id"] for p in progs],
                "schedule": {
                    "type": "random", "flexPreference": "end",
                    "maxDays": args.max_days, "padMs": 300000, "padStyle": "slot",
                    "randomDistribution": "uniform",
                    "slots": [{"id": str(_u.uuid4()), "type": "movie",
                               "order": "shuffle", "weight": 1,
                               "cooldownMs": args.cooldown_days * 86400000}],
                }}
    tun(f"/api/channels/{cid}/programming", "POST", body, base=args.tunarr)
    back = tun(f"/api/channels/{cid}/programming", base=args.tunarr)
    print(f"   programming set ({args.mode}): totalPrograms={back.get('totalPrograms')}")


if __name__ == "__main__":
    main()
