#!/usr/bin/env python3
"""Maintain Plex COLLECTIONS holding the per-person "unseen" film sets.

Tunarr consumes collections, not playlists (PlexApiClient.getAllLibraryCollections
-> GET /library/sections/{id}/collections), which is why this exists alongside the
smart playlists. Collections are library-global tags, so the per-person naming is
a label, not an access control.

Membership is DIFFED, not rewritten: films that became watched are untagged and
newly-eligible ones tagged. A full re-tag of ~4000 items every night would be
needless load on a single-node cluster.

`collection.locked=1` is REQUIRED. Without it Plex treats the tag as unlocked
metadata and a later refresh or agent re-match can silently drop it.
"""
import argparse, os, time, urllib.parse, urllib.request
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
    acct = ET.fromstring(call(f"https://plex.tv/api/home/users/{user_id}/switch",
                              admin, "POST", SW)).get("authenticationToken")
    mid = ET.fromstring(call(f"http://{ip}:32400/identity", admin)).get("machineIdentifier")
    for d in ET.fromstring(call("https://plex.tv/api/resources?includeHttps=1",
                                acct, hdrs=SW)).findall("Device"):
        if d.get("clientIdentifier") == mid and d.get("accessToken"):
            return d.get("accessToken")
    raise SystemExit(f"no server accessToken for {user_id}")


def watched(ip, tok, section):
    return {v.get("ratingKey") for v in ET.fromstring(
        call(f"http://{ip}:32400/library/sections/{section}/all", tok)
    ).findall("Video") if v.get("viewCount")}


def all_keys(ip, tok, section):
    return {v.get("ratingKey") for v in ET.fromstring(
        call(f"http://{ip}:32400/library/sections/{section}/all", tok)).findall("Video")}


def collection_members(ip, tok, section, title):
    for d in ET.fromstring(call(f"http://{ip}:32400/library/sections/{section}/collections",
                                tok)).findall("Directory"):
        if d.get("title") == title:
            items = ET.fromstring(call(f"http://{ip}:32400/library/metadata/"
                                       f"{d.get('ratingKey')}/children", tok))
            return d.get("ratingKey"), {v.get("ratingKey") for v in items.findall("Video")}
    return None, set()


def tag(ip, tok, section, rk, title, add=True):
    key = "collection[0].tag.tag" if add else "collection[].tag.tag-"
    q = urllib.parse.urlencode({"type": 1, "id": rk, key: title, "collection.locked": 1})
    call(f"http://{ip}:32400/library/sections/{section}/all?{q}", tok, "PUT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", choices=["zach", "liz", "both"], required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--liz-id", default="109897463")
    ap.add_argument("--section", default="1")
    ap.add_argument("--pace", type=float, default=0.12)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    admin = os.environ["PLEX_API"]; ip = os.environ.get("PLEX_IP", "192.168.10.203")
    liz = server_token(admin, args.liz_id, ip)
    zw = watched(ip, admin, args.section)
    lw = watched(ip, liz, args.section)
    if zw == lw:
        raise SystemExit("REFUSING: identical watched sets — server ignoring tokens")
    seen = {"zach": zw, "liz": lw, "both": zw | lw}[args.who]
    desired = all_keys(ip, admin, args.section) - seen

    cid, current = collection_members(ip, admin, args.section, args.title)
    add, rm = desired - current, current - desired
    print(f"   [{args.who}] zach_watched={len(zw)} liz_watched={len(lw)} "
          f"seen={len(seen)} desired={len(desired)}")
    print(f"   collection '{args.title}' exists={cid is not None} current={len(current)} "
          f"-> add={len(add)} remove={len(rm)}")
    if not args.apply:
        return
    ok = fail = 0
    for i, rk in enumerate(sorted(add), 1):
        try:
            tag(ip, admin, args.section, rk, args.title, True); ok += 1
        except Exception as e:
            fail += 1; print(f"      FAIL add {rk}: {e}")
        time.sleep(args.pace)
        if i % 200 == 0:
            print(f"      added {i}/{len(add)} ok={ok} fail={fail}")
    for i, rk in enumerate(sorted(rm), 1):
        try:
            tag(ip, admin, args.section, rk, args.title, False); ok += 1
        except Exception as e:
            fail += 1; print(f"      FAIL rm {rk}: {e}")
        time.sleep(args.pace)
    cid2, final = collection_members(ip, admin, args.section, args.title)
    print(f"   DONE ok={ok} fail={fail}  collection now={len(final)} (expected {len(desired)})")


if __name__ == "__main__":
    main()
