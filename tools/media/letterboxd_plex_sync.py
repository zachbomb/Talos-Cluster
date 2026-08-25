#!/usr/bin/env python3
"""Sync Letterboxd watched history into per-user Plex watched state.

Direction matters: Plex watched state is PER-USER and lives in Plex's own
database. It is NOT read from NFO sidecars, which is why TMM cannot carry it
and why this runs Letterboxd -> Plex rather than the reverse. Confirmed
empirically: a 2103-movie library fully enriched by TMM still showed only 89
watched.

Zach's watched set = his own watched.csv UNION the films Liz tagged #withzach
in her diary (469 films he never logged himself).

Matching is title+year. Bare-title matching is banned here: it silently
inflated the Karagarga MoM coverage by 33% earlier in this project. A +/-1 year
tolerance is allowed ONLY when the normalized title is unique in the library,
because festival-vs-release year disagreement between Letterboxd and TMDB is
common (Beau Travail 1999/2000, Brick 2005/2006) but an ambiguous title plus a
loosened year is exactly how a wrong film gets marked.
"""
import argparse, csv, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

SECTION = "1"
CLIENT_HEADERS = {
    "X-Plex-Product": "TalosLBSync", "X-Plex-Version": "1.0",
    "X-Plex-Client-Identifier": "talos-lb-sync-001", "X-Plex-Platform": "Python",
    "X-Plex-Platform-Version": "3", "X-Plex-Device": "Server",
    "X-Plex-Device-Name": "talos",
}


def get(url, token=None, timeout=180, method="GET"):
    if token:
        url += ("&" if "?" in url else "?") + "X-Plex-Token=" + token
    req = urllib.request.Request(url, method=method)
    for k, v in CLIENT_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def mint_home_token(admin_token, user_id, ip):
    """Obtain a token that the SERVER will accept for another Home user.

    Two distinct tokens are involved and conflating them costs hours:
      1. POST /api/home/users/{id}/switch returns an account token that
         authenticates to plex.tv but is REJECTED 401 by the PMS.
      2. GET /api/resources (with that token) lists each server with its own
         scoped `accessToken`. THAT is what the PMS accepts.
    Requires full client headers on the switch (bare POST -> 422).
    Match the server by machineIdentifier, not by name."""
    body = get(f"https://plex.tv/api/home/users/{user_id}/switch",
               token=admin_token, timeout=60, method="POST")
    acct = ET.fromstring(body).get("authenticationToken") or ET.fromstring(body).get("authToken")
    if not acct:
        raise SystemExit(f"could not switch to home user {user_id}")
    mid = ET.fromstring(get(f"http://{ip}:32400/identity", admin_token)).get("machineIdentifier")
    res = ET.fromstring(get("https://plex.tv/api/resources?includeHttps=1", acct, timeout=60))
    for d in res.findall("Device"):
        if d.get("clientIdentifier") == mid and d.get("accessToken"):
            return d.get("accessToken")
    raise SystemExit(f"home user {user_id} has no accessToken for server {mid}")


def norm(t):
    t = (t or "").strip().lower()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def letterboxd_sets(zach_dir, liz_dir):
    def keys(rows):
        return {(norm(r.get("Name")), (r.get("Year") or "").strip())
                for r in rows if r.get("Name")}
    zach = keys(load_csv(os.path.join(zach_dir, "watched.csv")))
    withzach = keys([r for r in load_csv(os.path.join(liz_dir, "diary.csv"))
                     if "withzach" in (r.get("Tags") or "").lower()])
    liz = keys(load_csv(os.path.join(liz_dir, "watched.csv")))
    return {"zach": zach | withzach, "liz": liz}


def plex_library(ip, token):
    body = get(f"http://{ip}:32400/library/sections/{SECTION}/all", token)
    vids = ET.fromstring(body).findall("Video")
    exact, by_title = {}, {}
    for v in vids:
        n, y = norm(v.get("title")), v.get("year") or ""
        exact.setdefault((n, y), v)
        by_title.setdefault(n, []).append(v)
    return vids, exact, by_title


def resolve(want, exact, by_title):
    """Return {ratingKey: Video} for the wanted (title, year) keys."""
    out, loose, missed = {}, 0, 0
    for n, y in want:
        v = exact.get((n, y))
        if v is None:
            cands = by_title.get(n, [])
            # loosen the year only when the title is unambiguous in the library
            if len(cands) == 1 and y:
                try:
                    if abs(int(cands[0].get("year") or 0) - int(y)) <= 1:
                        v, loose = cands[0], loose + 1
                except ValueError:
                    pass
        if v is None:
            missed += 1
            continue
        out[v.get("ratingKey")] = v
    return out, loose, missed


def watched_state(ip, token, keys):
    """Current viewCount per ratingKey for THIS user's token - the rollback record."""
    state = {}
    body = get(f"http://{ip}:32400/library/sections/{SECTION}/all", token)
    for v in ET.fromstring(body).findall("Video"):
        rk = v.get("ratingKey")
        if rk in keys:
            state[rk] = int(v.get("viewCount") or 0)
    return state


def scrobble(ip, token, rating_key):
    url = (f"http://{ip}:32400/:/scrobble?key={rating_key}"
           f"&identifier=com.plexapp.plugins.library")
    get(url, token, timeout=60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zach-dir", required=True)
    ap.add_argument("--liz-dir", required=True)
    ap.add_argument("--rollback", required=True, help="path to write rollback JSON")
    ap.add_argument("--user", choices=["zach", "liz", "both"], default="both")
    ap.add_argument("--apply", action="store_true", help="without this, dry run")
    ap.add_argument("--pace", type=float, default=0.15)
    args = ap.parse_args()

    admin = os.environ["PLEX_API"]
    ip = os.environ.get("PLEX_IP", "192.168.10.203")
    liz_id = os.environ.get("PLEX_LIZ_ID", "109897463")

    want = letterboxd_sets(args.zach_dir, args.liz_dir)
    _, exact, by_title = plex_library(ip, admin)

    tokens = {"zach": admin}
    if args.user in ("liz", "both"):
        tokens["liz"] = mint_home_token(admin, liz_id, ip)

    rollback = {}
    for who in (["zach", "liz"] if args.user == "both" else [args.user]):
        tok = tokens[who]
        found, loose, missed = resolve(want[who], exact, by_title)
        before = watched_state(ip, tok, set(found))
        todo = [rk for rk in found if before.get(rk, 0) == 0]
        print(f"\n  [{who}] letterboxd={len(want[who])} matched={len(found)} "
              f"(+{loose} via ±1yr) not-in-library={missed}")
        print(f"        already watched={len(found)-len(todo)}  to mark={len(todo)}")
        rollback[who] = {"user_id": liz_id if who == "liz" else "admin",
                         "before": before, "marked": []}
        if not args.apply:
            for rk in todo[:5]:
                v = found[rk]
                print(f"        would mark: {v.get('title')[:44]} ({v.get('year')})")
            continue
        ok = fail = 0
        for i, rk in enumerate(todo, 1):
            try:
                scrobble(ip, tok, rk)
                rollback[who]["marked"].append(rk)
                ok += 1
            except Exception as e:
                fail += 1
                print(f"        FAIL {rk}: {e}")
            time.sleep(args.pace)
            if i % 100 == 0:
                print(f"        {i}/{len(todo)} ok={ok} fail={fail}")
                with open(args.rollback, "w") as f:
                    json.dump(rollback, f, indent=1)
        print(f"        DONE ok={ok} fail={fail}")

    with open(args.rollback, "w") as f:
        json.dump(rollback, f, indent=1)
    print(f"\n  rollback written: {args.rollback}")


if __name__ == "__main__":
    main()
