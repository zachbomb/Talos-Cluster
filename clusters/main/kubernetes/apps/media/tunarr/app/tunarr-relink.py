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

MATCHING. A dead program matches its live copy by the durable plex-guid only,
never by title: a title join once "recovered" the wrong show. Steps:
  dead row's plex-guid -> Plex /library/all?guid= -> current ratingKey
  -> Tunarr batch/lookup -> healthy program row, whose own plex-guid must match.
If Plex finds 0 or more than 1 item for a guid, or Tunarr has not ingested the
new key yet, the slot is left alone and reported. The new row's duration is
used, because that is the file that will actually play.

SCOPE. Only channels WITHOUT a slot schedule (manual lineups). A slot channel's
programming view shows only the generated window, so rebuilding it from that
view could shrink its pool. Re-program those from their Plex collection
instead (docs/media/tunarr-mom-channels.md). A lineup entry of any type other
than content aborts that channel untouched.

SAFETY. Dry run unless --apply. Before a write, the channel's full programming
is saved to --backup-dir. After a write, the channel is re-read: its slot count
must be unchanged and every swapped slot must hold the new uuid.

Env: PLEX_URL, PLEX_API (never on argv), TUNARR_URL.
Flags: --apply, --ch=N (repeatable), --backup-dir=PATH.
NB: this file may be mounted through a Flux-substituted ConfigMap. Do not add
a dollar sign anywhere in it.
"""
import json, os, re, sys, time, urllib.parse, urllib.request

PLEX = os.environ.get("PLEX_URL", "http://192.168.10.203:32400").rstrip("/")
TOKEN = os.environ.get("PLEX_API", "")
TUNARR = os.environ.get("TUNARR_URL", "http://192.168.10.205:8000").rstrip("/")
APPLY = "--apply" in sys.argv
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
            log("ch" + str(c["number"]) + " " + c["name"] + ": slot schedule; skipped (re-program from its collection)")
            continue
        work.append((c, tun("/api/channels/" + c["id"] + "/programming")))

    plex_progs = {}
    for c, prog in work:
        for uuid, v in (prog.get("programs") or {}).items():
            p = (v or {}).get("program") or {}
            if p.get("sourceType") == "plex" and str(p.get("externalId") or "").isdigit():
                plex_progs[uuid] = p
    alive = live_keys({str(p["externalId"]) for p in plex_progs.values()})
    dead = {u: p for u, p in plex_progs.items() if str(p["externalId"]) not in alive}
    log("manual channels " + str(len(work)) + " | plex programs " + str(len(plex_progs)) + " | dead " + str(len(dead)))

    # Resolve each dead program to its healthy twin by plex-guid.
    swap, unresolved = {}, {}
    src_of = {}
    guid_cache = {}
    for uuid, p in dead.items():
        g = guid_of(p)
        if not g:
            unresolved[uuid] = "no plex-guid"; continue
        if g not in guid_cache:
            x = plex("/library/all?guid=" + urllib.parse.quote(g, safe=""))
            guid_cache[g] = re.findall(r'ratingKey="(\d+)"', x)
        keys = guid_cache[g]
        if len(keys) != 1:
            unresolved[uuid] = ("gone from Plex" if not keys else "ambiguous: " + str(len(keys)) + " Plex items share the guid"); continue
        src_of[uuid] = (p.get("mediaSourceId"), keys[0], g)
    for i in range(0, len(src_of), 100):
        chunk = list(src_of.items())[i:i + 100]
        ids = ["plex|" + ms + "|" + k for _, (ms, k, _) in chunk]
        got = tun("/api/programming/batch/lookup", {"externalIds": ids}) or {}
        by_key = {str(v.get("externalId")): v for v in got.values() if v.get("uuid")}
        for uuid, (ms, k, g) in chunk:
            v = by_key.get(k)
            if not v:
                unresolved[uuid] = "Tunarr has not ingested new key " + k + " yet"
            elif guid_of(v) != g:
                unresolved[uuid] = "guid mismatch on new key " + k
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
    for c, prog in work:
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
    log(("APPLIED " if APPLY else "DRY RUN: would re-point ") + str(total) + " slots" + ("" if APPLY else ". Re-run with --apply."))
    return 1 if failed else 0


def p_title(p):
    show = (p.get("show") or {}).get("title")
    return (show + " / " if show else "") + str(p.get("title"))


if __name__ == "__main__":
    sys.exit(main())
