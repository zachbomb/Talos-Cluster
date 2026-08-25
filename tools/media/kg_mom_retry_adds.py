#!/usr/bin/env python3
"""Retry Radarr adds that timed out under CPU throttling.

WHY THIS EXISTS: Radarr runs with a 500m CPU limit. A bulk load of thousands of
POST /movie calls (each triggering a metadata refresh) drove it to 42.9% of CFS
periods throttled, so responses outran the client timeout and 2,190 of 2,411 adds
failed. Nothing was wrong with the data — the plan is reusable verbatim.

Differences from the bulk loader:
  - Reuses the saved plan; performs NO TMDB lookups.
  - Long socket timeout (throttled Radarr is slow, not dead).
  - Paces between POSTs and backs off on timeout instead of hammering.
  - Re-reads existing tmdbIds first so re-runs are idempotent.

Safety contract is unchanged: monitored=False, searchForMovie=False, monitor=none.
"""
import json, ssl, sys, time, urllib.error, urllib.request

B = "http://192.168.10.210:7878/api/v3"
KEY = open("/tmp/.rk").read().strip()
ROOT = "/media/media/movies"
QPROFILE = 16
PACE = 1.0          # seconds between adds; tuned under a 500m CPU limit
TIMEOUT = 240       # throttled Radarr can take minutes, not seconds

def api(path, method="GET", body=None, timeout=TIMEOUT):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method,
        headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        t = resp.read().decode()
        return json.loads(t) if t.strip() else None

def main():
    plan = json.load(open("/tmp/kgmom_plan.json"))["plan"]
    tags = {t["label"]: t["id"] for t in api("/tag")}
    for lbl in sorted({p["label"] for p in plan}):
        if lbl not in tags:
            tags[lbl] = api("/tag", "POST", {"label": lbl})["id"]
            print(f"   created tag {lbl}", flush=True)

    have = {m["tmdbId"] for m in api("/movie")}
    todo = [p for p in plan if p["tmdbId"] not in have]
    print(f"   plan={len(plan)}  already present={len(plan)-len(todo)}  to add={len(todo)}", flush=True)

    ok = fail = 0
    pace = PACE
    for i, p in enumerate(todo, 1):
        body = {"tmdbId": p["tmdbId"], "title": p["title"], "year": p["year"],
                "qualityProfileId": QPROFILE, "rootFolderPath": ROOT,
                "monitored": False, "minimumAvailability": "released",
                "tags": [tags[p["label"]]],
                "addOptions": {"searchForMovie": False, "monitor": "none"}}
        for attempt in (1, 2, 3):
            try:
                api("/movie", "POST", body)
                ok += 1
                pace = max(PACE, pace * 0.95)      # ease back toward baseline
                break
            except Exception as e:
                msg = str(e)
                if "already been added" in msg or "MovieExistsValidator" in msg:
                    ok += 1; break
                if attempt == 3:
                    fail += 1
                    print(f"   FAIL {p['title'][:44]}: {msg[:70]}", flush=True)
                else:
                    pace = min(6.0, pace * 2)      # back off, Radarr is throttled
                    time.sleep(pace * attempt)
        if i % 100 == 0:
            print(f"   [{i}/{len(todo)}] added={ok} failed={fail} pace={pace:.2f}s", flush=True)
        time.sleep(pace)
    print(f"\n   RESULT added={ok} failed={fail}", flush=True)

main()
