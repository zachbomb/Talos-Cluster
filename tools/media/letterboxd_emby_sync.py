#!/usr/bin/env python3
"""Sync Letterboxd watched history into Emby played state.

Emby differs from Plex in a way that makes this easier: the write is addressed
explicitly by user id (POST /Users/{uid}/PlayedItems/{itemId}), so an admin key
can set another user's state directly. There is no equivalent of Plex's
token-scoped write, and therefore no equivalent of the allowedNetworks trap
where a valid credential silently resolves to the wrong account.

Matching rules are identical to the Plex sync deliberately: exact title+year,
with a +/-1 year tolerance allowed only when the normalized title is unique in
the library. See letterboxd_plex_sync.py for why bare-title matching is banned.
"""
import argparse, csv, json, os, re, time, urllib.parse, urllib.request

PORT = 10079


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


def letterboxd_keys(zach_dir, liz_dir, who):
    def keys(rows):
        return {(norm(r.get("Name")), (r.get("Year") or "").strip())
                for r in rows if r.get("Name")}
    if who == "zach":
        z = keys(load_csv(os.path.join(zach_dir, "watched.csv")))
        wz = keys([r for r in load_csv(os.path.join(liz_dir, "diary.csv"))
                   if "withzach" in (r.get("Tags") or "").lower()])
        return z | wz
    return keys(load_csv(os.path.join(liz_dir, "watched.csv")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zach-dir", required=True)
    ap.add_argument("--liz-dir", required=True)
    ap.add_argument("--user", required=True, help="Emby user NAME")
    ap.add_argument("--who", choices=["zach", "liz"], required=True)
    ap.add_argument("--rollback", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pace", type=float, default=0.1)
    args = ap.parse_args()

    key = os.environ["EMBY_API"]; ip = os.environ.get("EMBY_IP", "192.168.10.204")
    users = api(ip, key, "Users")
    match = [u for u in users if u["Name"].lower() == args.user.lower()]
    if not match:
        raise SystemExit(f"no Emby user named {args.user!r}; have "
                         f"{[u['Name'] for u in users]}")
    uid = match[0]["Id"]

    items = api(ip, key, f"Users/{uid}/Items", {
        "IncludeItemTypes": "Movie", "Recursive": "true",
        "Fields": "ProductionYear,UserData", "Limit": "100000"})["Items"]
    exact, by_title = {}, {}
    for it in items:
        n = norm(it.get("Name")); y = str(it.get("ProductionYear") or "")
        exact.setdefault((n, y), it); by_title.setdefault(n, []).append(it)

    want = letterboxd_keys(args.zach_dir, args.liz_dir, args.who)
    found, loose = {}, 0
    for n, y in want:
        it = exact.get((n, y))
        if it is None:
            c = by_title.get(n, [])
            if len(c) == 1 and y:
                try:
                    if abs(int(c[0].get("ProductionYear") or 0) - int(y)) <= 1:
                        it, loose = c[0], loose + 1
                except ValueError:
                    pass
        if it is not None:
            found[it["Id"]] = it

    before = {i: bool(it.get("UserData", {}).get("Played")) for i, it in found.items()}
    todo = [i for i in found if not before[i]]
    print(f"  [{args.who} -> emby:{args.user}] library={len(items)} "
          f"letterboxd={len(want)} matched={len(found)} (+{loose} via ±1yr)")
    print(f"        already played={len(found)-len(todo)}  to mark={len(todo)}")

    rb = {"emby_user": args.user, "uid": uid, "before": before, "marked": []}
    if not args.apply:
        for i in todo[:5]:
            print(f"        would mark: {found[i]['Name'][:44]} "
                  f"({found[i].get('ProductionYear')})")
    else:
        ok = fail = 0
        for n_, i in enumerate(todo, 1):
            try:
                api(ip, key, f"Users/{uid}/PlayedItems/{i}", method="POST")
                rb["marked"].append(i); ok += 1
            except Exception as e:
                fail += 1; print(f"        FAIL {i}: {e}")
            time.sleep(args.pace)
            if n_ % 100 == 0:
                print(f"        {n_}/{len(todo)} ok={ok} fail={fail}")
                with open(args.rollback, "w") as f: json.dump(rb, f, indent=1)
        print(f"        DONE ok={ok} fail={fail}")
    with open(args.rollback, "w") as f: json.dump(rb, f, indent=1)
    print(f"  rollback: {args.rollback}")


if __name__ == "__main__":
    main()
