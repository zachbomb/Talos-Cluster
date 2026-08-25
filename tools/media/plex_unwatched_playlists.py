#!/usr/bin/env python3
"""Build per-user "unwatched" shuffle playlists in Plex from Letterboxd data.

A playlist is created under the account that owns the token used, exactly like
watched state. If the server's allowedNetworks includes the client's subnet,
PMS ignores the token and every playlist lands on the OWNER - see
[[plex-allowednetworks-defeats-per-user-tokens]]. This script therefore refuses
to run for a non-owner until it has PROVEN token isolation by checking that two
different users report different watched sets.

Membership is computed as: everything in the library MINUS what Letterboxd says
that person has seen. Films that failed to match stay in the pool, so the error
mode is "offered a film you've already seen", never "hidden a film you haven't".
"""
import argparse, csv, json, os, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

H = {"X-Plex-Product": "TalosLBSync", "X-Plex-Version": "1.0",
     "X-Plex-Client-Identifier": "talos-lb-sync-001", "X-Plex-Platform": "Python",
     "X-Plex-Platform-Version": "3", "X-Plex-Device": "Server",
     "X-Plex-Device-Name": "talos"}
BATCH = 200


def call(url, tok=None, method="GET"):
    if tok:
        url += ("&" if "?" in url else "?") + "X-Plex-Token=" + tok
    r = urllib.request.Request(url, method=method)
    for k, v in H.items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=180) as resp:
        return resp.read()


def norm(t):
    t = (t or "").strip().lower()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def load_csv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seen_keys(zach_dir, liz_dir, who):
    def ks(rows):
        return {(norm(r.get("Name")), (r.get("Year") or "").strip())
                for r in rows if r.get("Name")}
    z = ks(load_csv(os.path.join(zach_dir, "watched.csv")))
    wz = ks([r for r in load_csv(os.path.join(liz_dir, "diary.csv"))
             if "withzach" in (r.get("Tags") or "").lower()])
    l = ks(load_csv(os.path.join(liz_dir, "watched.csv")))
    return {"zach": z | wz, "liz": l, "either": z | wz | l}[who]


def library(ip, tok):
    r = ET.fromstring(call(f"http://{ip}:32400/library/sections/1/all", tok))
    return r.findall("Video")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zach-dir", required=True)
    ap.add_argument("--liz-dir", required=True)
    ap.add_argument("--who", choices=["zach", "liz", "either"], required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--as-user", default="owner",
                    help="'owner' or a Plex Home user id to create the playlist for")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    admin = os.environ["PLEX_API"]; ip = os.environ.get("PLEX_IP", "192.168.10.203")
    tok = admin
    if args.as_user != "owner":
        body = call(f"https://plex.tv/api/home/users/{args.as_user}/switch", admin, "POST")
        acct = ET.fromstring(body).get("authenticationToken")
        # the switch token works on plex.tv but the SERVER 401s it; each server
        # publishes its own scoped accessToken via /api/resources
        mid = ET.fromstring(call(f"http://{ip}:32400/identity", admin)).get("machineIdentifier")
        res = ET.fromstring(call("https://plex.tv/api/resources?includeHttps=1", acct))
        tok = next((d.get("accessToken") for d in res.findall("Device")
                    if d.get("clientIdentifier") == mid and d.get("accessToken")), None)
        if not tok:
            raise SystemExit(f"no server accessToken for home user {args.as_user}")
        # PROVE isolation before writing anything under another identity
        a = {v.get("ratingKey") for v in library(ip, admin) if v.get("viewCount")}
        b = {v.get("ratingKey") for v in library(ip, tok) if v.get("viewCount")}
        if a == b:
            raise SystemExit(
                "REFUSING: owner and target user report identical watched sets, so the "
                "server is ignoring tokens (allowedNetworks). The playlist would be "
                "created on the OWNER's account. Narrow allowedNetworks first.")
        print(f"   token isolation verified (owner={len(a)} target={len(b)} watched)")

    seen = seen_keys(args.zach_dir, args.liz_dir, args.who)
    vids = library(ip, tok)
    pool = [v for v in vids if (norm(v.get("title")), v.get("year") or "") not in seen]
    print(f"   library={len(vids)}  seen-per-letterboxd={len(seen)}  playlist pool={len(pool)}")
    if not args.apply:
        for v in pool[:5]:
            print(f"      e.g. {v.get('title')[:44]} ({v.get('year')})")
        return

    mid = ET.fromstring(call(f"http://{ip}:32400/identity", tok)).get("machineIdentifier")
    keys = [v.get("ratingKey") for v in pool]
    base = f"server://{mid}/com.plexapp.plugins.library/library/metadata/"
    q = urllib.parse.urlencode({"type": "video", "title": args.title,
                                "smart": "0", "uri": base + ",".join(keys[:BATCH])})
    r = ET.fromstring(call(f"http://{ip}:32400/playlists?{q}", tok, "POST"))
    pl = r.find("Playlist")
    pid = pl.get("ratingKey")
    print(f"   created playlist {pid} with {min(BATCH,len(keys))} items")
    for i in range(BATCH, len(keys), BATCH):
        chunk = keys[i:i + BATCH]
        q = urllib.parse.urlencode({"uri": base + ",".join(chunk)})
        call(f"http://{ip}:32400/playlists/{pid}/items?{q}", tok, "PUT")
        print(f"      +{len(chunk)} ({min(i+BATCH,len(keys))}/{len(keys)})")
        time.sleep(0.2)
    r = ET.fromstring(call(f"http://{ip}:32400/playlists/{pid}", tok))
    print(f"   FINAL: '{args.title}' leafCount="
          f"{r.find('Playlist').get('leafCount')}")


if __name__ == "__main__":
    main()
