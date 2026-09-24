#!/usr/bin/env python3
"""Re-point Tunarr lineups from dead Plex items to the live copies of the same items.

WHY. When Plex re-creates an item (a file move or rename, a library merge, a
metadata refresh), it gets a new ratingKey. Tunarr ingests the new key as a NEW
program row, but every channel lineup still points at the old row, which goes
state=missing and plays an error or filler. A library rescan never fixes it,
because the scan is source-driven and never revisits a row whose key vanished.
Rewriting the old row's key is also impossible: a UNIQUE index is already held
by the healthy row. The public-API fix is to rebuild the lineup and swap the
dead program uuid for the healthy one. This was done by hand on 2026-08-12
(swap_lineups.py, 198 -> 15) and 2026-08-13. On 2026-09-24 an audit found 3046
of 4962 Plex keys dead across 35 channels, so the repair is now a tool.

MATCHING. A dead program matches its live copy by the durable plex-guid,
never by title: a title join once "recovered" the wrong show. For EPISODES whose
plex-guid Plex has re-issued, a fallback matches the TVDB (else IMDb) episode id
inside the same show; the new Tunarr row must carry that same id. Steps:
  dead row's plex-guid -> Plex /library/all?guid= -> current ratingKey
  -> Tunarr batch/lookup -> healthy program row, whose own plex-guid must match.
If Plex finds 0 or more than 1 item for a guid, or Tunarr has not ingested the
new key yet, the slot is left alone and reported. The new row's duration is
used, because that is the file that will actually play.

SCOPE. By default only channels WITHOUT a slot schedule (manual lineups); a
lineup entry of any type other than content aborts that channel untouched.
--slots also handles slot-scheduled ("random") channels: the channel's own
program pool is re-posted with dead uuids swapped for their live copies and
the schedule rules unchanged. Do NOT re-program those from their Plex
collection: when Plex re-creates an item the collection tag is lost, so on
2026-09-24 the MoM collections had shrunk (Wiseman 23 -> 1). The channel pool
is the surviving record. A slot channel is written only if the rebuilt pool is
the same size as before; any schedule type other than "random" is skipped.

SAFETY. Dry run unless --apply. Before a write, the channel's full programming
is saved to --backup-dir. After a write, the channel is re-read: its slot count
must be unchanged and every swapped slot must hold the new uuid.

Env: PLEX_URL, PLEX_API (never on argv), TUNARR_URL.
Flags: --apply, --slots, --ch=N (repeatable), --backup-dir=PATH,
--pause=SECONDS between channel writes (each rewrite costs Tunarr CPU).
NB: this file may be mounted through a Flux-substituted ConfigMap. Do not add
a dollar sign anywhere in it.
"""
import html, json, os, re, sys, time, urllib.parse, urllib.request

PLEX = os.environ.get("PLEX_URL", "http://192.168.10.203:32400").rstrip("/")
TOKEN = os.environ.get("PLEX_API", "")
TUNARR = os.environ.get("TUNARR_URL", "http://192.168.10.205:8000").rstrip("/")
APPLY = "--apply" in sys.argv
SLOTS = "--slots" in sys.argv
PAUSE = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--pause=")), "0"))
ONLY = {a.split("=", 1)[1] for a in sys.argv if a.startswith("--ch=")}
BACKUP = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--backup-dir=")), "/tmp/tunarr-relink-backup")
TIMEOUT = 300


def log(msg):
    print("[tunarr-relink] " + msg, flush=True)


def tun(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TUNARR + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
    return json.loads(raw) if raw.strip() else None


def plex(path):
    sep = "&" if "?" in path else "?"
    url = PLEX + path + sep + "X-Plex-Token=" + urllib.parse.quote(TOKEN)
    try:
        return urllib.request.urlopen(url, timeout=TIMEOUT).read().decode("utf-8", "replace")
    except Exception as e:  # never let the token reach a log line
        raise RuntimeError("plex request failed: " + path.split("?")[0] + " (" + type(e).__name__ + ")") from None


def guid_of(program):
    for i in program.get("identifiers") or []:
        if i.get("type") == "plex-guid":
            return i.get("id")
    return None


def pick_edition(keys, want_ms):
    if not want_ms:
        return None
    close = []
    for k in keys:
        d = re.search(r'<Media\b[^>]*\bduration="(\d+)"', plex("/library/metadata/" + k))
        if d and abs(int(d.group(1)) - want_ms) <= 0.03 * want_ms:
            close.append(k)
    return close[0] if len(close) == 1 else None


def norm(t):
    return re.sub(r"[^a-z0-9]+", "", html.unescape(str(t or "")).casefold())


def ext_id(program, kind):
    for i in program.get("identifiers") or []:
        if i.get("type") == kind:
            return str(i.get("id"))
    return None


def episode_by_external_id(p, cache):
    """Find a dead EPISODE's current Plex key by its TVDB (else IMDb) episode id,
    searching only its own show. Returns ("ok", key, (kind, id)), ("fail", reason), or None."""
    if p.get("type") != "episode":
        return None
    show = p.get("show") or {}
    sg = ext_id(show, "plex-guid")
    if not sg:
        return ("fail", "episode's show has no plex-guid")
    if sg not in cache:
        x = plex("/library/all?guid=" + urllib.parse.quote(sg, safe=""))
        sk = re.findall(r'ratingKey="(\d+)"', x)
        idx = {}
        if len(sk) == 1:
            leaves = plex("/library/metadata/" + sk[0] + "/allLeaves?includeGuids=1")
            for block in re.findall(r"<Video\b.*?</Video>", leaves, re.S):
                key = re.search(r'ratingKey="(\d+)"', block).group(1)
                title = (re.search(r'<Video\b[^>]*\btitle="([^"]*)"', block) or [None, ""])[1]
                for gid in re.findall(r'<Guid id="([a-z]+://[^"]+)"', block):
                    idx.setdefault(gid, []).append((key, title))
        cache[sg] = (len(sk), idx)
    nshows, idx = cache[sg]
    if nshows != 1:
        return ("fail", "episode's show not found in Plex (" + str(nshows) + " matches)")
    for kind in ("tvdb", "imdb"):
        eid = ext_id(p, kind)
        if not eid:
            continue
        hits = idx.get(kind + "://" + eid, [])
        if len(hits) > 1:
            return ("fail", "ambiguous: " + str(len(hits)) + " episodes share " + kind + " id")
        if len(hits) == 1:
            # GUARD, not a match key: providers renumber and swap episode ids (American
            # Masters S33E07/E08, 2026-09-24: tvdb 7246864 moved from McNally to Robert
            # Shaw). An id hit whose title differs is refused rather than trusted.
            if norm(hits[0][1]) != norm(p.get("title")):
                return ("fail", kind + " id now belongs to a differently titled episode (" + hits[0][1] + ")")
            return ("ok", hits[0][0], (kind, eid))
    return ("fail", "gone from Plex (no episode with its tvdb/imdb id)")


def live_keys(keys):
    alive = set()
    keys = sorted(keys)
    for i in range(0, len(keys), 200):
        alive |= set(re.findall(r'ratingKey="(\d+)"', plex("/library/metadata/" + ",".join(keys[i:i + 200]))))
    return alive


def main():
    if not TOKEN:
        log("PLEX_API is empty")
        return 2
    chans = sorted(tun("/api/channels"), key=lambda c: c.get("number") or 0)
    if ONLY:
        chans = [c for c in chans if str(c.get("number")) in ONLY]

    work = []                                   # (channel, programming)
    for c in chans:
        sched = None
        try:
            sched = tun("/api/channels/" + c["id"] + "/schedule")
        except Exception:
            pass
        if sched and sched.get("schedule"):
            if not SLOTS:
                log("ch" + str(c["number"]) + " " + c["name"] + ": slot schedule; skipped (use --slots)")
                continue
            work.append((c, tun("/api/channels/" + c["id"] + "/programming"), sched["schedule"]))
            continue
        work.append((c, tun("/api/channels/" + c["id"] + "/programming"), None))

    plex_progs = {}
    for c, prog, _ in work:
        for uuid, v in (prog.get("programs") or {}).items():
            p = (v or {}).get("program") or {}
            if p.get("sourceType") == "plex" and str(p.get("externalId") or "").isdigit():
                plex_progs[uuid] = p
    alive = live_keys({str(p["externalId"]) for p in plex_progs.values()})
    dead = {u: p for u, p in plex_progs.items() if str(p["externalId"]) not in alive}
    log("channels " + str(len(work)) + " | plex programs " + str(len(plex_progs)) + " | dead " + str(len(dead)))

    # Resolve each dead program to its healthy twin by plex-guid.
    swap, unresolved = {}, {}
    src_of = {}
    guid_cache = {}
    show_cache = {}
    for uuid, p in dead.items():
        g = guid_of(p)
        keys = []
        if g:
            if g not in guid_cache:
                x = plex("/library/all?guid=" + urllib.parse.quote(g, safe=""))
                guid_cache[g] = re.findall(r'ratingKey="(\d+)"', x)
            keys = guid_cache[g]
        if len(keys) == 1:
            src_of[uuid] = (p.get("mediaSourceId"), keys[0], ("plex-guid", g)); continue
        if len(keys) > 1:
            # Editions share one guid (Theatrical / TV / Silent cut, 2026-09-24). Keep the
            # edition the channel was built with: the ONE whose runtime is within 3% of the
            # dead row's duration. Several or none within 3% -> leave it for a human.
            k = pick_edition(keys, p.get("duration"))
            if k:
                src_of[uuid] = (p.get("mediaSourceId"), k, ("plex-guid", g)); continue
            unresolved[uuid] = "ambiguous: " + str(len(keys)) + " editions share the guid, none uniquely matches the scheduled runtime"; continue
        # Fallback for EPISODES only: Plex sometimes re-issues its own episode guids
        # (Kids in the Hall S04, 2026-09-24). The TVDB/IMDb episode id is unchanged, so
        # match on that inside the same show. Never on title or SxxExx.
        hit = episode_by_external_id(p, show_cache)
        if hit and hit[0] == "ok":
            src_of[uuid] = (p.get("mediaSourceId"), hit[1], hit[2]); continue
        unresolved[uuid] = hit[1] if hit else ("gone from Plex" if g else "no plex-guid")
    for i in range(0, len(src_of), 100):
        chunk = list(src_of.items())[i:i + 100]
        ids = ["plex|" + ms + "|" + k for _, (ms, k, _) in chunk]
        got = tun("/api/programming/batch/lookup", {"externalIds": ids}) or {}
        by_key = {str(v.get("externalId")): v for v in got.values() if v.get("uuid")}
        for uuid, (ms, k, check) in chunk:
            v = by_key.get(k)
            if not v:
                unresolved[uuid] = "Tunarr has not ingested new key " + k + " yet"
            elif ext_id(v, check[0]) != check[1]:
                unresolved[uuid] = check[0] + " mismatch on new key " + k
            elif not v.get("duration"):
                unresolved[uuid] = "new row has no duration"
            else:
                swap[uuid] = {"id": v["uuid"], "duration": v["duration"], "old": p_title(dead[uuid]), "new_key": k}
        time.sleep(0.2)
    log("resolvable " + str(len(swap)) + " | unresolved " + str(len(unresolved)))
    for why in sorted(set(unresolved.values())):
        log("  unresolved (" + str(sum(1 for w in unresolved.values() if w == why)) + "): " + why)

    if APPLY:
        os.makedirs(BACKUP, exist_ok=True)
    total, failed = 0, 0
    for c, prog, sched in work:
        if sched is not None:
            t, f = relink_slots(c, prog, sched, swap)
            total += t; failed += f
            if t and APPLY: time.sleep(PAUSE)
            continue
        lineup = prog.get("lineup") or []
        hits = [e for e in lineup if e.get("id") in swap]
        if not hits:
            continue
        other = sorted({e.get("type") for e in lineup if e.get("type") != "content"})
        if other:
            log("ch" + str(c["number"]) + ": lineup has non-content entries " + str(other) + "; ABORT channel"); failed += 1; continue
        rebuilt = []
        for e in lineup:
            s = swap.get(e.get("id"))
            rebuilt.append({"type": "content", "id": s["id"], "duration": s["duration"]} if s
                           else {"type": "content", "id": e["id"], "duration": e.get("duration") or e.get("durationMs")})
        eg = swap[hits[0]["id"]]
        log("ch" + str(c["number"]) + " " + c["name"] + ": " + str(len(hits)) + " of " + str(len(lineup))
            + " slots re-pointed, e.g. '" + eg["old"] + "' -> key " + eg["new_key"])
        total += len(hits)
        if not APPLY:
            continue
        path = os.path.join(BACKUP, "ch" + str(c["number"]) + "-programming-" + time.strftime("%Y%m%dT%H%M%S") + ".json")
        json.dump(prog, open(path, "w"))
        tun("/api/channels/" + c["id"] + "/programming", {"type": "manual", "lineup": rebuilt, "append": False})
        back = tun("/api/channels/" + c["id"] + "/programming").get("lineup") or []
        ok = len(back) == len(rebuilt) and all(b.get("id") == r["id"] for b, r in zip(back, rebuilt))
        log("  verify: " + ("OK" if ok else "MISMATCH (backup " + path + ")"))
        failed += not ok
        time.sleep(PAUSE)
    log(("APPLIED " if APPLY else "DRY RUN: would re-point ") + str(total) + " slots" + ("" if APPLY else ". Re-run with --apply."))
    return 1 if failed else 0


def relink_slots(c, prog, sched, swap):
    """Re-post a random-slot channel's pool with dead uuids swapped. Returns (swapped, failed)."""
    tag = "ch" + str(c["number"]) + " " + c["name"]
    if sched.get("type") != "random":
        log(tag + ": schedule type " + str(sched.get("type")) + " not handled; skipped"); return 0, 0
    pool = [u for u, v in (prog.get("programs") or {}).items() if (v or {}).get("type") == "content"]
    hits = [u for u in pool if u in swap]
    if not hits:
        return 0, 0
    new_pool, seen = [], set()
    for u in pool:
        n = swap[u]["id"] if u in swap else u
        if n not in seen:
            seen.add(n); new_pool.append(n)
    eg = swap[hits[0]]
    log(tag + ": slot pool " + str(len(pool)) + ", " + str(len(hits)) + " re-pointed, e.g. '" + eg["old"] + "' -> key " + eg["new_key"])
    if len(new_pool) != len(pool):
        log("  pool would change size " + str(len(pool)) + " -> " + str(len(new_pool)) + " (a live twin is already in the pool); ABORT channel")
        return 0, 1
    if not APPLY:
        return len(hits), 0
    path = os.path.join(BACKUP, "ch" + str(c["number"]) + "-slots-" + time.strftime("%Y%m%dT%H%M%S") + ".json")
    json.dump({"programming": prog, "schedule": sched}, open(path, "w"))
    tun("/api/channels/" + c["id"] + "/programming", {"type": "random", "programs": new_pool, "schedule": sched})
    back = tun("/api/channels/" + c["id"] + "/programming").get("programs") or {}
    ok = set(back) <= set(new_pool) and not (set(back) & set(hits)) and len(back) >= min(len(new_pool), len(pool)) * 0.9
    log("  verify: " + ("OK, pool " + str(len(back)) if ok else "MISMATCH, pool " + str(len(back)) + " (backup " + path + ")"))
    return len(hits), (0 if ok else 1)


def p_title(p):
    show = (p.get("show") or {}).get("title")
    return (show + " / " if show else "") + str(p.get("title"))


if __name__ == "__main__":
    sys.exit(main())
