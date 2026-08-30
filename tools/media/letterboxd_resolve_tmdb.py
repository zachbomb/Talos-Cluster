#!/usr/bin/env python3
"""Resolve every Letterboxd export entry to a TMDB id.

WHY THIS EXISTS: the original backfill matched Letterboxd to Plex on
normalized title + year. That silently failed wherever the two services use
different release titles for the same film — Letterboxd "Dune" (2021) vs Plex
"Dune: Part One" (2021), "Star Wars" vs "Star Wars: Episode IV - A New Hope".
Those films were never marked watched, so they stayed in the "unseen" pools and
turned up on the ambient channel as things the household had already seen.

Title matching cannot be repaired by heuristics. A prefix/containment pass found
only 8 of them, and could never catch translated or re-titled releases. TMDB ids
are the only exact join, and Plex already exposes them in bulk via
/library/sections/{id}/all?includeGuids=1 (2071/2103 films carry tmdb://).

The Letterboxd side has no ids: the export gives only title, year and a boxd.it
short link. letterboxd.com/tmdb/{id} is 403 to scripts, so the only route is to
follow each boxd.it link to the film page and read the TMDB id out of it. That is
one HTTP request per film, hence the pacing and the resume file.

Resolves ALL entries, not just the ones that failed to match — a title+year match
can also be a FALSE positive (two films sharing a normalized title and year), and
only an id comparison detects that.
"""
import argparse, csv, json, os, random, re, sys, time, urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TMDB_RE = re.compile(r'themoviedb\.org/movie/(\d+)')
IMDB_RE = re.compile(r'imdb\.com/title/(tt\d+)')


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def load_entries(dirs):
    """Collect every distinct film across watched.csv and diary.csv in each dir."""
    seen = {}
    for d in dirs:
        for fn in ("watched.csv", "diary.csv"):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    uri = (row.get("Letterboxd URI") or "").strip()
                    if not uri or uri in seen:
                        continue
                    seen[uri] = {"uri": uri, "name": row.get("Name"),
                                 "year": (row.get("Year") or "").strip()}
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+", required=True)
    ap.add_argument("--out", required=True, help="JSON resume/result file")
    ap.add_argument("--pace", type=float, default=1.2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", help="file of Letterboxd URIs to restrict to (one per line)")
    args = ap.parse_args()

    entries = load_entries(args.dirs)
    done = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            done = json.load(f)
        print(f"   resuming: {len(done)} already resolved", flush=True)

    if args.only:
        with open(args.only) as f:
            keep = {ln.strip() for ln in f if ln.strip()}
        entries = {u: e for u, e in entries.items() if u in keep}
    todo = [e for u, e in entries.items() if u not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"   total distinct films: {len(entries)}   to resolve now: {len(todo)}", flush=True)

    ok = fail = 0
    for i, e in enumerate(todo, 1):
        try:
            final, html = fetch(e["uri"])
            m = TMDB_RE.search(html)
            im = IMDB_RE.search(html)
            slug = re.sub(r".*/film/([^/]+)/?.*", r"\1", final)
            done[e["uri"]] = {"name": e["name"], "year": e["year"], "slug": slug,
                              "tmdb": m.group(1) if m else None,
                              "imdb": im.group(1) if im else None}
            ok += 1
        except Exception as exc:
            done[e["uri"]] = {"name": e["name"], "year": e["year"],
                              "error": str(exc)[:80]}
            fail += 1
        # jitter so the request pattern is not perfectly periodic
        time.sleep(args.pace + random.uniform(0, 0.4))
        if i % 50 == 0:
            with open(args.out, "w") as f:
                json.dump(done, f)
            got = sum(1 for v in done.values() if v.get("tmdb"))
            print(f"   {i}/{len(todo)}  ok={ok} fail={fail}  with_tmdb={got}", flush=True)

    with open(args.out, "w") as f:
        json.dump(done, f)
    got = sum(1 for v in done.values() if v.get("tmdb"))
    print(f"   DONE ok={ok} fail={fail}  total_resolved={len(done)}  with_tmdb={got}", flush=True)


if __name__ == "__main__":
    main()
