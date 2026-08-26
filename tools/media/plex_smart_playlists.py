#!/usr/bin/env python3
"""Create self-updating per-user "unwatched" smart playlists in Plex.

A smart playlist stores a FILTER, not a membership list, and Plex evaluates
`unwatched=1` against whoever owns the playlist. So the per-user pools maintain
themselves: watch something with sound in Plex and it leaves the list, with no
cron job and no recomputation.

This only works for single-user questions. "Unseen by BOTH of us" has no Plex
filter (there is no cross-account predicate), so that one stays a computed
static playlist -- see plex_unwatched_playlists.py.

Verified 2026-08-25: library=2103, watched=841, smart leafCount=1262, and zero
watched titles present in the result.
"""
import argparse, os, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

SW = {"X-Plex-Product": "TalosLBSync", "X-Plex-Version": "1.0",
      "X-Plex-Client-Identifier": "talos-lb-sync-001", "X-Plex-Platform": "Python",
      "X-Plex-Platform-Version": "3", "X-Plex-Device": "Server",
      "X-Plex-Device-Name": "talos"}


def call(url, tok=None, method="GET", hdrs=None):
    if tok:
        url += ("&" if "?" in url else "?") + "X-Plex-Token=" + tok
    r = urllib.request.Request(url, method=method)
    for k, v in (hdrs or {}).items():
        r.add_header(k, v)
    return urllib.request.urlopen(r, timeout=180).read()


def server_token(admin, user_id, ip):
    """Home-switch token authenticates to plex.tv but the PMS 401s it; the
    server's own scoped accessToken from /api/resources is what PMS accepts."""
    acct = ET.fromstring(call(f"https://plex.tv/api/home/users/{user_id}/switch",
                              admin, "POST", SW)).get("authenticationToken")
    mid = ET.fromstring(call(f"http://{ip}:32400/identity", admin)).get("machineIdentifier")
    res = ET.fromstring(call("https://plex.tv/api/resources?includeHttps=1", acct, hdrs=SW))
    for d in res.findall("Device"):
        if d.get("clientIdentifier") == mid and d.get("accessToken"):
            return d.get("accessToken")
    raise SystemExit(f"no server accessToken for home user {user_id}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--as-user", default="owner", help="'owner' or a Home user id")
    ap.add_argument("--section", default="1")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    admin = os.environ["PLEX_API"]; ip = os.environ.get("PLEX_IP", "192.168.10.203")
    tok = admin if args.as_user == "owner" else server_token(admin, args.as_user, ip)

    if args.as_user != "owner":
        a = {v.get("ratingKey") for v in ET.fromstring(
            call(f"http://{ip}:32400/library/sections/{args.section}/all", admin)
        ).findall("Video") if v.get("viewCount")}
        b = {v.get("ratingKey") for v in ET.fromstring(
            call(f"http://{ip}:32400/library/sections/{args.section}/all", tok)
        ).findall("Video") if v.get("viewCount")}
        if a == b:
            raise SystemExit("REFUSING: owner and target report identical watched sets — "
                             "server is ignoring tokens (allowedNetworks). Playlist would "
                             "land on the OWNER.")
        print(f"   token isolation verified (owner={len(a)} target={len(b)})")

    lib = ET.fromstring(call(f"http://{ip}:32400/library/sections/{args.section}/all", tok))
    tot = len(lib.findall("Video"))
    wat = sum(1 for v in lib.findall("Video") if v.get("viewCount"))
    print(f"   library={tot} watched={wat} -> unwatched={tot-wat}")
    if not args.apply:
        return

    for pl in ET.fromstring(call(f"http://{ip}:32400/playlists", tok)).findall("Playlist"):
        if pl.get("title") == args.title:
            call(f"http://{ip}:32400/playlists/{pl.get('ratingKey')}", tok, "DELETE")
            print(f"   removed existing playlist {pl.get('ratingKey')}")

    mid = ET.fromstring(call(f"http://{ip}:32400/identity", tok)).get("machineIdentifier")
    src = (f"server://{mid}/com.plexapp.plugins.library"
           f"/library/sections/{args.section}/all?type=1&unwatched=1")
    q = urllib.parse.urlencode({"type": "video", "title": args.title,
                                "smart": "1", "uri": src})
    pl = ET.fromstring(call(f"http://{ip}:32400/playlists?{q}", tok, "POST")).find("Playlist")
    print(f"   CREATED '{args.title}' rk={pl.get('ratingKey')} "
          f"smart={pl.get('smart')} leafCount={pl.get('leafCount')}")


if __name__ == "__main__":
    main()
