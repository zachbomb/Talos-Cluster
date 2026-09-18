#!/usr/bin/env python3
"""Query Prowlarr, parse the results into something readable, and enrich
Internet Archive hits with their rights metadata.

WHY THIS EXISTS. Prowlarr's API returns a firehose of loosely-structured JSON
per indexer, and its UI is awkward to work through when you want to compare
what several indexers hold for the same title. Worse, a generic title produces
mostly false matches: "I Love the 80s" returns 92 results across the usenet and
torrent indexers, and every one of them is a music compilation or an adult
release that happens to share the words. Eyeballing that is the painful part.

So this does three things the raw API does not:

  1. Groups and dedupes results per indexer, newest/largest first, so you can
     see at a glance which indexer actually has the thing.
  2. Scores titles against the query so obvious false matches sort to the
     bottom instead of burying the real hits.
  3. For Internet Archive hits, looks up the item's rights metadata on
     archive.org and prints it, because IA's `opensource_movies` collection is
     the DEFAULT UPLOAD BUCKET and does not mean the item is open. Genuinely
     public-domain / CC material carries a `licenseurl` or a `rights` string;
     community rips carry neither. That distinction is invisible in Prowlarr's
     own results, which is precisely when it matters.

This tool SEARCHES and REPORTS. It does not download anything and has no grab
path -- point it at a query, read the manifest, decide for yourself.

CREDENTIALS. Prowlarr's URL and API key are read from the environment, never
argv (argv leaks into shell history and process listings):

    PROWLARR_URL   default http://192.168.10.10:9696
    PROWLARR_API   required

Note the Prowlarr key is NOT in clusters/main/clusterenv.yaml or the
cluster-config ConfigMap; it lives in the homepage pod's services.yaml widget
block. Pull it from there into the env rather than pasting it on a command line.

USAGE

    export PROWLARR_API=...
    ./prowlarr_search.py --query "Hans Namuth Pollock"
    ./prowlarr_search.py --query "I Love the 80s" --indexer-ids 16 --rights
    ./prowlarr_search.py --query "Prelinger" --rights --json out.json

TIMEOUTS. The Internet Archive indexer on this Prowlarr responds in ~83s, far
past most defaults, which is why Sonarr's searches against it time out and trip
Prowlarr's failure backoff. --timeout defaults to 150 so a deliberate manual
search actually completes; that is the whole reason it is generous.
"""
import argparse, json, os, re, sys, urllib.error, urllib.parse, urllib.request

PROWLARR = os.environ.get("PROWLARR_URL", "http://192.168.10.10:9696")
IA_META = "https://archive.org/metadata/"
IA_SEARCH = "https://archive.org/advancedsearch.php"

# collections that are curated//open, vs the default upload bucket
OPEN_HINTS = ("prelinger", "publicmovies", "feature_films", "classic_tv_",
              "librivox", "opensource_audio", "usgovfilms", "newsandpublicaffairs")
DEFAULT_BUCKET = ("opensource_movies", "opensource", "community")


def get(url, key=None, timeout=150):
    req = urllib.request.Request(url)
    if key:
        req.add_header("X-Api-Key", key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def score(title, query):
    """Crude relevance: fraction of query tokens present, minus junk penalties.

    Sorting by this is what separates the real hits from the 92 music
    compilations -- it is not clever, it just has to beat 'unsorted'."""
    t = title.lower()
    toks = [w for w in re.split(r"\W+", query.lower()) if w]
    hit = sum(1 for w in toks if w in t) / max(len(toks), 1)
    for junk in ("xxx", "flac", "cd320", "vol.", "-cd-", "discography", "mp3"):
        if junk in t:
            hit -= 0.35
    return round(hit, 3)


def ia_rights(identifier, timeout=25):
    """Look up an archive.org item's rights posture.

    Returns (verdict, detail). `opensource_movies` with no licenseurl is the
    signature of a community upload, NOT an open licence -- that is the case
    this function exists to make visible."""
    try:
        m = get(IA_META + urllib.parse.quote(identifier), timeout=timeout) or {}
    except Exception as e:
        return "unknown", f"metadata lookup failed: {e}"
    md = m.get("metadata") or {}
    lic = md.get("licenseurl") or ""
    rights = md.get("rights") or ""
    coll = md.get("collection") or []
    coll = [coll] if isinstance(coll, str) else list(coll)
    if lic or rights:
        return "declared", f"licenseurl={lic or '-'} rights={rights or '-'}"
    if any(any(h in c for h in OPEN_HINTS) for c in coll):
        return "curated-collection", f"collection={coll[:3]} (no explicit licence)"
    if any(c in DEFAULT_BUCKET for c in coll):
        return "UNDECLARED-UPLOAD", f"collection={coll[:3]} — default upload bucket, no licence/rights"
    return "unknown", f"collection={coll[:3]}"


def ia_identifier(title):
    """Best-effort map a Prowlarr IA result title back to an archive.org id."""
    try:
        q = urllib.parse.urlencode({
            "q": f'title:("{title[:80]}")', "fl[]": "identifier",
            "rows": 1, "output": "json"})
        d = get(f"{IA_SEARCH}?{q}", timeout=25) or {}
        docs = (d.get("response") or {}).get("docs") or []
        return docs[0].get("identifier") if docs else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True)
    ap.add_argument("--indexer-ids", help="comma-separated Prowlarr indexer ids")
    ap.add_argument("--type", default="search", choices=["search", "tvsearch", "moviesearch"])
    ap.add_argument("--limit", type=int, default=15, help="rows shown per indexer")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--rights", action="store_true",
                    help="look up archive.org rights for Internet Archive hits")
    ap.add_argument("--timeout", type=int, default=150,
                    help="IA responds in ~83s; default is deliberately generous")
    ap.add_argument("--json", help="write the full manifest here")
    args = ap.parse_args()

    key = os.environ.get("PROWLARR_API")
    if not key:
        sys.exit("PROWLARR_API is not set. It is in the homepage pod's "
                 "/app/config/services.yaml widget block, not in clusterenv.yaml.")

    # NOTE: Prowlarr wants indexerIds as REPEATED params
    # (?indexerIds=12&indexerIds=13). A comma-separated list returns HTTP 400.
    # Same family of quirk as Sonarr's /api/v3/episodefile, which silently
    # honours only the FIRST seriesId when given repeats -- opposite convention,
    # equally undocumented, and both fail quietly-ish. Always verify.
    pairs = [("query", args.query), ("type", args.type)]
    if args.indexer_ids:
        pairs += [("indexerIds", i.strip())
                  for i in args.indexer_ids.split(",") if i.strip()]
    url = f"{PROWLARR}/api/v1/search?{urllib.parse.urlencode(pairs)}"
    print(f"   querying {PROWLARR} … (timeout {args.timeout}s)", flush=True)
    try:
        rows = get(url, key, timeout=args.timeout) or []
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Prowlarr returns a bare 400 for at least TWO different causes.
            # Neither is explained in the body, so check both before believing
            # it is a syntax problem.
            sys.exit(
                "   HTTP 400 from Prowlarr. Two known causes, same status code:\n"
                "     1. A requested indexer is currently DISABLED by failure backoff.\n"
                "        Check: GET /api/v1/indexerstatus -> disabledTill.\n"
                "     2. indexerIds was passed comma-separated instead of repeated\n"
                "        (this tool always repeats, so cause 1 is far likelier).\n"
                "   The Internet Archive indexer self-disables in a loop here: it takes\n"
                "   ~83s to answer, which exceeds Prowlarr's own indexer timeout, so a\n"
                "   query that SUCCEEDS for the caller is still booked as a failure and\n"
                "   re-trips the backoff. Raise Prowlarr's indexer timeout to break it.")
        sys.exit(f"   search failed: HTTP {e.code} {e.reason}")
    except Exception as e:
        sys.exit(f"   search failed: {e}")

    for r in rows:
        r["_score"] = score(str(r.get("title", "")), args.query)
    rows = [r for r in rows if r["_score"] >= args.min_score]

    by = {}
    for r in rows:
        by.setdefault(r.get("indexer", "?"), []).append(r)

    print(f"   {len(rows)} results across {len(by)} indexer(s)\n")
    for ix in sorted(by, key=lambda k: -len(by[k])):
        got = sorted(by[ix], key=lambda r: (-r["_score"], -(r.get("size") or 0)))
        print(f"  == {ix}  ({len(got)}) ==")
        for r in got[:args.limit]:
            gb = (r.get("size") or 0) / 1e9
            line = f"    [{r['_score']:.2f}] {str(r.get('title'))[:76]}"
            if gb:
                line += f"  {gb:.2f}GB"
            print(line)
            if args.rights and "archive" in ix.lower():
                ident = ia_identifier(str(r.get("title", "")))
                if ident:
                    verdict, detail = ia_rights(ident)
                    flag = "!!" if verdict == "UNDECLARED-UPLOAD" else "  "
                    print(f"      {flag} rights: {verdict} — {detail}")
                    r["_ia_identifier"], r["_ia_rights"] = ident, verdict
        print()

    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
        print(f"   manifest -> {args.json}")

    if args.rights:
        print("   NOTE: 'UNDECLARED-UPLOAD' means archive.org has no licence or rights\n"
              "   statement for the item and it sits in the default upload bucket.\n"
              "   That is not the same as public domain.")


if __name__ == "__main__":
    main()
