#!/usr/bin/env python3
"""Build per-user "unwatched" shuffle playlists in Emby from Letterboxd data.

Companion to plex_unwatched_playlists.py. Emby is the backup player, so it
needs the same per-user pools Plex has - a fallback that shows every film as
unwatched is not a fallback.

No token-isolation guard is needed here (unlike the Plex tool): Emby addresses
both the playlist owner and the played-state write by explicit UserId, so a
request cannot silently resolve to the wrong account the way Plex's
token-scoped calls can under allowedNetworks.

Membership = library MINUS what Letterboxd says that person has seen. Unmatched
films stay in the pool, so the error mode is "offered a film you've seen".
"""
import argparse, csv, json, os, re, time, urllib.parse, urllib.request

PORT = 10079
BATCH = 200


def api(ip, key, path, params=None, method="GET"):
    q = dict(params or {}); q["api_key"] = key
    url = f"http://{ip}:{PORT}/emby/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
    return json.loads(body) if body[:1] in (b"{", b"[") else body


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zach-dir", required=True)
    ap.add_argument("--liz-dir", required=True)
    ap.add_argument("--who", choices=["zach", "liz", "either"], required=True)
    ap.add_argument("--user", required=True, help="Emby user NAME to own the playlist")
    ap.add_argument("--title", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    key = os.environ["EMBY_API"]; ip = os.environ.get("EMBY_IP", "192.168.10.204")
    users = api(ip, key, "Users")
    m = [u for u in users if u["Name"].lower() == args.user.lower()]
    if not m:
        raise SystemExit(f"no Emby user {args.user!r}; have {[u['Name'] for u in users]}")
    uid = m[0]["Id"]

    items = api(ip, key, f"Users/{uid}/Items", {
        "IncludeItemTypes": "Movie", "Recursive": "true",
        "Fields": "ProductionYear", "Limit": "100000"})["Items"]
    seen = seen_keys(args.zach_dir, args.liz_dir, args.who)
    pool = [it for it in items
            if (norm(it.get("Name")), str(it.get("ProductionYear") or "")) not in seen]
    print(f"   [{args.who} -> emby:{args.user}] library={len(items)} "
          f"seen={len(seen)} pool={len(pool)}")
    if not args.apply:
        for it in pool[:5]:
            print(f"      e.g. {it['Name'][:44]} ({it.get('ProductionYear')})")
        return

    # remove a same-named playlist first so re-runs stay idempotent
    for ex in api(ip, key, f"Users/{uid}/Items",
                  {"IncludeItemTypes": "Playlist", "Recursive": "true"})["Items"]:
        if ex.get("Name") == args.title:
            api(ip, key, f"Items/{ex['Id']}", method="DELETE")
            print(f"      removed existing playlist {ex['Id']}")

    ids = [it["Id"] for it in pool]
    pl = api(ip, key, "Playlists", {"Name": args.title, "UserId": uid,
                                    "MediaType": "Movie",
                                    "Ids": ",".join(ids[:BATCH])}, method="POST")
    pid = pl["Id"]
    print(f"   created playlist {pid} with {min(BATCH,len(ids))} items")
    for i in range(BATCH, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        api(ip, key, f"Playlists/{pid}/Items",
            {"Ids": ",".join(chunk), "UserId": uid}, method="POST")
        print(f"      +{len(chunk)} ({min(i+BATCH,len(ids))}/{len(ids)})")
        time.sleep(0.15)
    n = api(ip, key, f"Playlists/{pid}/Items", {"UserId": uid})["TotalRecordCount"]
    print(f"   FINAL: '{args.title}' items={n}")


if __name__ == "__main__":
    main()
