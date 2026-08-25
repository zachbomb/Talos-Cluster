#!/usr/bin/env python3
"""Load Karagarga MoM gap titles into Radarr — UNMONITORED, tagged, never searching.

SAFETY CONTRACT (the whole point of this script):
  monitored              = False   -> Radarr will not track or auto-grab it
  addOptions.searchForMovie = False -> no search fires at add time
  addOptions.monitor     = "none"  -> belt and braces on the add path
Anything that would cause an immediate grab is explicitly disabled. The operator
triggers a search per-MoM later via its tag. Over-grabbing is the failure mode
this guards against.

Films are matched via Radarr's own /movie/lookup (TMDB). Titles that do not
resolve are reported, never guessed at.

Usage:  python3 tools/media/kg_mom_load.py --dry-run
        python3 tools/media/kg_mom_load.py --apply
"""
import json, os, re, sys, time, unicodedata, urllib.parse, urllib.request

B = "http://192.168.10.210:7878/api/v3"
KEY = open("/tmp/.rk").read().strip()
ROOT = "/media/media/movies"
QPROFILE = 16          # Remux + WEB 1080p [Original] - language=Original
MOMS = {
    281: "kg-mom-deleuze-s-images",
    23: "kg-mom-the-birth-of-cinema",
    255: "kg-mom-the-olympics",
    296: "kg-mom-frank-tashlin-jerry-lewis",
    71: "kg-mom-ingmar-bergman",
    139: "kg-mom-amos-vogel-film-as-a-subversive-ar"
}

# Override for batched runs: KGMOM_MOMS="140:kg-mom-queer-cinema,309:kg-mom-japanese-queer-cinema"
if os.environ.get("KGMOM_MOMS"):
    MOMS = {int(k): v for k, v in
            (pair.split(":", 1) for pair in os.environ["KGMOM_MOMS"].split(","))}

def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method,
        headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    import ssl
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    with urllib.request.urlopen(r, timeout=90, context=ctx) as resp:
        t = resp.read().decode()
        return json.loads(t) if t.strip() else None

def fold(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def main():
    apply = "--apply" in sys.argv
    cat = json.load(open("docs/media/kg-mom-catalog.json"))
    cov = {r["id"]: r for r in json.load(open("docs/media/kg-mom-coverage.json"))["rows"]}
    existing = api("/movie")
    have_tmdb = {m["tmdbId"] for m in existing}
    have_key  = {(fold(m["title"]), m.get("year")) for m in existing}

    tags = {t["label"]: t["id"] for t in api("/tag")}
    plan, unresolved, skipped = [], [], []

    for mid, label in MOMS.items():
        mom = cat["moms"][str(mid)]
        matched = {fold(h) for h in []}  # coverage stores radarr titles, re-derive by lookup below
        for e in mom["entries"]:
            if not e["year"] or len(str(e["year"])) != 4:
                continue
            title = re.split(r"\s+AKA\s+", e["title"])[0].strip()
            if (fold(title), int(e["year"])) in have_key:
                skipped.append((label, title)); continue
            term = urllib.parse.quote(f"{title} {e['year']}")
            try:
                res = api(f"/movie/lookup?term={term}")
            except Exception as ex:
                unresolved.append((label, title, e["year"], f"lookup-error {ex}")); continue
            time.sleep(0.35)
            if not res:
                unresolved.append((label, title, e["year"], "no tmdb match")); continue
            best = None
            for c in res[:5]:
                if c.get("year") and abs(c["year"] - int(e["year"])) <= 1:
                    best = c; break
            if not best:
                unresolved.append((label, title, e["year"], f"year mismatch (got {res[0].get('year')})")); continue
            if best["tmdbId"] in have_tmdb:
                skipped.append((label, best["title"])); continue
            have_tmdb.add(best["tmdbId"])
            plan.append({"label": label, "tmdbId": best["tmdbId"], "title": best["title"],
                         "year": best.get("year"), "kg": title})

    print(f"   TO ADD: {len(plan)}   already present: {len(skipped)}   unresolved: {len(unresolved)}")
    from collections import Counter
    print("   by MoM:", dict(Counter(p["label"] for p in plan)))
    print()
    for p in plan[:12]:
        print(f"      + [{p['label']:<20}] {p['title'][:44]} ({p['year']})  tmdb={p['tmdbId']}")
    if len(plan) > 12: print(f"      ... +{len(plan)-12} more")
    print()
    print("   sample unresolved:")
    for u in unresolved[:8]: print(f"      ? [{u[0]:<20}] {u[1][:42]} ({u[2]}) -> {u[3]}")

    json.dump({"plan": plan, "unresolved": unresolved}, open("/tmp/kgmom_plan.json","w"), ensure_ascii=False)
    if not apply:
        print("\n   DRY RUN — nothing written. Re-run with --apply to add.")
        return

    for lbl in set(p["label"] for p in plan):
        if lbl not in tags:
            tags[lbl] = api("/tag", "POST", {"label": lbl})["id"]
            print(f"   created tag {lbl} -> {tags[lbl]}")
    ok = fail = 0
    for p in plan:
        body = {"tmdbId": p["tmdbId"], "title": p["title"], "year": p["year"],
                "qualityProfileId": QPROFILE, "rootFolderPath": ROOT,
                "monitored": False, "minimumAvailability": "released",
                "tags": [tags[p["label"]]],
                "addOptions": {"searchForMovie": False, "monitor": "none"}}
        try:
            api("/movie", "POST", body); ok += 1
        except Exception as ex:
            fail += 1
            if fail <= 5: print(f"   FAIL {p['title'][:40]}: {str(ex)[:90]}")
        time.sleep(0.2)
    print(f"\n   added={ok} failed={fail}")

main()
