#!/usr/bin/env python3
"""Cap the film-supplement pre-roll on Tunarr's manual-lineup channels.

WHY. The 2026-07-21 filler rollout ("everything, maximal") interleaved EVERY
extra of every film as regular programming immediately before that film
(219 films / 1051 clips on 10 channels). The extras are long Criterion-style
docs (median ~26 min), so viewers sat through hours of supplements between
films: on 2026-09-24 extras were 22-44% of airtime on ch11/13/15/17-21, with
unbroken runs up to 6.1 h (ch15 Sci-Fi!). Owner decision 2026-09-24: at most
2 extras and 20 minutes of pre-roll per film.

WHAT IT DOES. An "extra" is a lineup item whose program is local-source (the
/media/filler library); everything Plex-sourced is programming and is never
touched. Walk the lineup; each run of consecutive extras is one pre-roll
block. Keep the SHORTEST extras that fit within 2 items and 20 minutes, in
their original order, and drop the rest from the lineup only (the files and
library rows stay). Programming order, count and durations are unchanged,
which is checked before and after every write.

Manual-lineup channels only; slot-scheduled channels are skipped (they carry
no local extras). Dry run unless --apply. Each channel's programming is saved
before a write so it can be restored with a manual POST of the saved lineup.

    TUNARR_URL=http://192.168.10.205:8000 ./tunarr_preroll_cap.py [--ch=15] [--apply] [--pause=30]
"""
import json, os, sys, time, urllib.request

T = os.environ.get("TUNARR_URL", "http://192.168.10.205:8000").rstrip("/")
APPLY = "--apply" in sys.argv
ONLY = {a.split("=", 1)[1] for a in sys.argv if a.startswith("--ch=")}
PAUSE = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--pause=")), "30"))
BACKUP = os.path.expanduser(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--backup-dir=")),
                                 "~/tunarr-preroll-backups/" + time.strftime("%Y%m%d")))
MAX_ITEMS, MAX_MS = 2, 20 * 60 * 1000


def api(path, body=None):
    req = urllib.request.Request(T + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=600).read()
    return json.loads(raw) if raw.strip() else None


def dur(e):
    return e.get("duration") or e.get("durationMs") or 0


def keep_from_block(block):
    """block: list of (index, entry). Keep the shortest that fit the cap, in original order."""
    chosen, total = [], 0
    for i, e in sorted(block, key=lambda x: dur(x[1])):
        if len(chosen) < MAX_ITEMS and total + dur(e) <= MAX_MS:
            chosen.append(i); total += dur(e)
    return set(chosen)


def plan(lineup, programs):
    is_extra = [((programs.get(e.get("id")) or {}).get("program") or {}).get("sourceType") == "local" for e in lineup]
    keep, block, longest_before = [], [], 0.0
    run = 0
    for i, e in enumerate(lineup):
        if is_extra[i]:
            block.append((i, e)); run += dur(e); longest_before = max(longest_before, run); continue
        keep_idx = keep_from_block(block)
        keep += [e2 for j, e2 in block if j in keep_idx]
        block, run = [], 0
        keep.append(e)
    if block:
        keep_idx = keep_from_block(block)
        keep += [e2 for j, e2 in block if j in keep_idx]
    return keep, is_extra, longest_before


def programming_only(lineup, is_extra_of):
    return [(e.get("id"), dur(e)) for e in lineup if not is_extra_of(e)]


def main():
    chans = sorted(api("/api/channels"), key=lambda c: c.get("number") or 0)
    if ONLY:
        chans = [c for c in chans if str(c["number"]) in ONLY]
    if APPLY:
        os.makedirs(BACKUP, exist_ok=True)
    failed = 0
    for c in chans:
        try:
            sched = api("/api/channels/" + c["id"] + "/schedule")
        except Exception:
            sched = None
        if sched and sched.get("schedule"):
            continue
        prog = api("/api/channels/" + c["id"] + "/programming")
        lineup, programs = prog.get("lineup") or [], prog.get("programs") or {}
        if any(e.get("type") != "content" for e in lineup):
            print(f"ch{c['number']}: non-content lineup entries; skipped"); continue
        new, is_extra, longest = plan(lineup, programs)
        n_ex = sum(is_extra)
        if not n_ex or len(new) == len(lineup):
            continue
        extra_ids = {e.get("id") for e, x in zip(lineup, is_extra) if x}
        extra_of = lambda e: e.get("id") in extra_ids
        before_h = sum(dur(e) for e, x in zip(lineup, is_extra) if x) / 3.6e6
        after_h = sum(dur(e) for e in new if extra_of(e)) / 3.6e6
        total_h = sum(dur(e) for e in lineup) / 3.6e6
        new_run = max((sum(dur(e) for e in grp) for grp in _runs(new, extra_of)), default=0) / 3.6e6
        print(f"ch{c['number']:>3} {c['name'][:26]:26} extras {n_ex:>4} -> {sum(1 for e in new if extra_of(e)):>4} | "
              f"extras airtime {before_h:6.1f}h -> {after_h:5.1f}h (of {total_h:.1f}h) | longest run {longest/3.6e6:4.1f}h -> {new_run:4.2f}h")
        assert programming_only(lineup, extra_of) == programming_only(new, extra_of), "programming changed"
        if not APPLY:
            continue
        path = os.path.join(BACKUP, f"ch{c['number']}-programming-{time.strftime('%H%M%S')}.json")
        json.dump(prog, open(path, "w"))
        body = [{"type": "content", "id": e["id"], "duration": dur(e)} for e in new]
        api("/api/channels/" + c["id"] + "/programming", {"type": "manual", "lineup": body, "append": False})
        back = api("/api/channels/" + c["id"] + "/programming").get("lineup") or []
        ok = [b.get("id") for b in back] == [e["id"] for e in body]
        print(f"      verify: {'OK' if ok else 'MISMATCH (backup ' + path + ')'}")
        failed += not ok
        time.sleep(PAUSE)
    return 1 if failed else 0


def _runs(lineup, extra_of):
    cur = []
    for e in lineup:
        if extra_of(e):
            cur.append(e)
        elif cur:
            yield cur; cur = []
    if cur:
        yield cur


if __name__ == "__main__":
    sys.exit(main())
