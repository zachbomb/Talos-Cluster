#!/usr/bin/env python3
"""Create Plex collections from Karagarga MoM coverage.

Matches by TMDB GUID, never by title. Plex stores guids like "tmdb://1234"; using
them means a remake or same-title film cannot be mis-filed, which is the failure
mode the identity work in SQ-58 exists to prevent. Titles are only ever displayed.

Adds a collection tag to movies already in Plex. It never creates, moves, deletes
or downloads media.

Usage: python3 tools/media/kg_mom_plex_collections.py [--apply]
"""
import json, sys, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from collections import defaultdict

PLEX = "http://192.168.10.203:32400"
TOKEN = open("/tmp/.pt").read().strip()
SECTION = 1
# MOMS is resolved at runtime: every FILM MoM with at least MIN_OWNED distinct
# owned titles. Music/book MoMs are skipped — they are not in the movie library.
MIN_OWNED = 1
PREFIX = "MoM: "

def get(path):
    u = f"{PLEX}{path}{'&' if '?' in path else '?'}X-Plex-Token={TOKEN}"
    with urllib.request.urlopen(u, timeout=180) as r:
        return ET.fromstring(r.read())

def put(path):
    u = f"{PLEX}{path}&X-Plex-Token={TOKEN}"
    req = urllib.request.Request(u, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status

def main():
    apply = "--apply" in sys.argv
    root = get(f"/library/sections/{SECTION}/all?includeGuids=1")
    by_tmdb = {}
    for v in root.findall(".//Video"):
        rk = v.get("ratingKey")
        for g in v.findall("./Guid"):
            gid = g.get("id") or ""
            if gid.startswith("tmdb://"):
                by_tmdb[int(gid.split("//")[1])] = (rk, v.get("title"), v.get("year"))
    print(f"   plex movies indexed by tmdb guid: {len(by_tmdb)}")

    rows = json.load(open("docs/media/kg-mom-coverage.json"))["rows"]
    sel = [r for r in rows if r["type"] == "film" and r["on_disk"] >= MIN_OWNED]
    sel.sort(key=lambda r: -r["on_disk"])
    print(f"   film MoMs with >={MIN_OWNED} owned: {len(sel)}")
    plan = {}
    for r in sel:
        name = r["name"]
        hits, miss = [], 0
        for o in r.get("owned", []):
            t = by_tmdb.get(o.get("tmdbId"))
            if t: hits.append(t)
            else: miss += 1
        plan[PREFIX + name] = hits

    tot = sum(len(v) for v in plan.values())
    sizes = sorted((len(v) for v in plan.values()), reverse=True)
    print(f"   collections to write: {len(plan)}   total tag writes: {tot}")
    print(f"   size distribution: >=24:{sum(1 for s in sizes if s>=24)}  10-23:{sum(1 for s in sizes if 10<=s<24)}  2-9:{sum(1 for s in sizes if 2<=s<10)}  1:{sum(1 for s in sizes if s==1)}")
    if not apply:
        print("\n   DRY RUN — nothing written. Re-run with --apply.")
        return
    done_n=[0]
    for coll, items in plan.items():
        if not items: continue
        ok = 0
        for rk, title, yr in items:
            # collection.locked=1 is REQUIRED. Without it Plex treats the tag as
            # unlocked metadata and a later refresh / agent re-match can silently
            # drop it (python-plexapi's CollectionMixin sends it for this reason).
            q = urllib.parse.urlencode({"type": 1, "id": rk,
                                        "collection[0].tag.tag": coll,
                                        "collection.locked": 1})
            try:
                put(f"/library/sections/{SECTION}/all?{q}"); ok += 1
            except Exception as e:
                print(f"      fail {title}: {str(e)[:70]}")
        done_n[0]+=1
        if done_n[0] % 25 == 0 or len(items)>=24:
            print(f"   [{done_n[0]}/{len(plan)}] {coll}: tagged {ok}/{len(items)}")

main()
