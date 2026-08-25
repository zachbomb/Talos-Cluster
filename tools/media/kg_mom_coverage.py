#!/usr/bin/env python3
"""Match the Karagarga Masters-of-the-Month catalog against the Radarr library.

PURPOSE: curation, not acquisition. The output answers "which MoM could I build a
Plex collection or Tunarr channel from RIGHT NOW" — i.e. how many of each MoM's
titles are already on disk. It never adds, downloads, or modifies anything.

MATCHING NOTES
  - KG serves windows-1252 and writes many titles in the original language, often
    as "Foreign Title AKA English Title". Both sides are tried.
  - Radarr contributes title, originalTitle and every alternateTitle.
  - Accents are folded and punctuation stripped, because "La jetée" / "La jetee"
    must match. Year tolerance is +/-1: KG dates by production, TMDB by release.
  - A match requires title AND year agreement. Title-only matching was rejected:
    it collapses remakes and same-title films, which is the exact identity error
    class recorded in SQ-58.
"""
import json, re, sys, unicodedata, collections

def fold(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"^(the|a|an|le|la|les|les|el|il|lo|der|die|das|un|une)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip()

def variants(title):
    """KG titles frequently carry AKA / alternate forms."""
    out = set()
    parts = re.split(r"\s+AKA\s+|\s+aka\s+|\s*/\s*", title)
    for p in parts:
        p = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", p).strip()
        if p: out.add(fold(p))
    out.add(fold(title))
    return {x for x in out if x}

def main():
    cat = json.load(open("docs/media/kg-mom-catalog.json"))
    movies = json.load(open("/tmp/radarr_movies.json"))

    # index library by (folded title, year) -> movie, including alternates
    idx = collections.defaultdict(list)
    for m in movies:
        yr = m.get("year")
        names = {m.get("title"), m.get("originalTitle")}
        for at in (m.get("alternateTitles") or []):
            names.add(at.get("title"))
        for n in names:
            f = fold(n)
            if f: idx[f].append((yr, m))

    def owned(title, year):
        try: y = int(str(year)[:4])
        except Exception: y = None
        for v in variants(title):
            for (yr, m) in idx.get(v, []):
                if y is None or yr is None or abs(yr - y) <= 1:
                    return m
        return None

    rows = []
    for mid, mom in cat["moms"].items():
        # DEDUPE BY tmdbId. Karagarga lists the same film repeatedly (alternate
        # rips, AKA variants), so counting matched ENTRIES double-counts library
        # films. An early version reported Rivette as 25 owned when only 10
        # distinct films existed; Plex's own childCount is what exposed it.
        hit, seen_tmdb = [], set()
        for e in mom["entries"]:
            m = owned(e["title"], e["year"])
            if not m: continue
            if m.get("tmdbId") in seen_tmdb: continue
            seen_tmdb.add(m.get("tmdbId"))
            hit.append({"kg": e["title"], "radarr": m["title"], "year": m.get("year"),
                        "tmdbId": m.get("tmdbId"), "hasFile": m.get("hasFile")})
        onfile = [h for h in hit if h["hasFile"]]
        rows.append({"id": mom["id"], "name": mom["name"], "date": mom["date"],
                     "type": mom["type"], "total": mom["count"],
                     "matched": len(hit), "on_disk": len(onfile),
                     "pct": round(100*len(onfile)/mom["count"], 1) if mom["count"] else 0.0,
                     "examples": [h["radarr"] for h in onfile[:6]],
                     "owned": onfile})
    rows.sort(key=lambda r: (-r["on_disk"], -r["pct"]))
    json.dump({"generated_from": cat["harvested"], "rows": rows},
              open("docs/media/kg-mom-coverage.json", "w"), ensure_ascii=False, indent=1)
    return rows

if __name__ == "__main__":
    rows = main()
    films = [r for r in rows if r["type"] == "film"]
    print(f"   film MoMs: {len(films)}   total on-disk matches: {sum(r['on_disk'] for r in films)}")
    print()
    print("   TOP 25 MoMs BY TITLES YOU ALREADY OWN (Tunarr/Plex candidates)")
    print(f"   {'on-disk':>7} {'of':>6} {'pct':>6}  {'date':<9} name")
    for r in films[:25]:
        print(f"   {r['on_disk']:>7} {r['total']:>6} {r['pct']:>5}%  {str(r['date'] or ''):<9} {r['name'][:52]}")
