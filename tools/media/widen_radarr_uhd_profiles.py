#!/usr/bin/env python3
"""Allow 1080p tiers on Radarr's four UHD profiles.

THE PROBLEM
-----------
Profiles 7, 8, 12 and 13 permit ONLY 2160p qualities, while the library they
serve is overwhelmingly 1080p. 1,311 of 1,874 movies with a file (70%) hold a
quality their own profile forbids:

    861/1350 (64%)  UHD Bluray + WEB       Bluray-1080p×372 WEBDL-1080p×347 DVD×60
    147/165  (89%)  UHD Bluray + WEB [French]
    235/278  (85%)  UHD Bluray + WEB [Original]
     66/69   (96%)  UHD Bluray + WEB [German]

Radarr cannot upgrade or replace any of them, which is why 1,596 movies sit
permanently cutoff-unmet, and why 17 films deleted after being found corrupt
could not be re-acquired.

THE CHANGE
----------
Set `allowed = true` on three items per profile:

    id 1002  WEB 1080p     (group: WEBDL-1080p, WEBRip-1080p)
    id 7     Bluray-1080p
    id 30    Remux-1080p

The cutoff stays `Remux-2160p`, and Radarr's item ordering already places the
1080p tiers BELOW the 2160p ones, so 2160p remains preferred. The effect is
that Radarr accepts 1080p when nothing better exists, and still upgrades to
2160p if a 2160p release appears later.

NOT INCLUDED, deliberately: DVD, 480p and 720p tiers. The operator chose the
four 1080p qualities specifically. That leaves a residue still non-compliant -
roughly DVD×60, WEBDL-480p×23, Bluray-720p×4, WEBDL-720p×1 - which is a
separate decision, not an oversight.

No movie records are touched. The assignments were always correct; the
profiles were not.

USAGE
-----
    python3 tools/media/widen_radarr_uhd_profiles.py            # dry run
    python3 tools/media/widen_radarr_uhd_profiles.py --execute

Radarr's own backup was taken before this change (Backup command, 2026-08-07),
and the prior profile JSON is snapshotted to /tmp/radarr_uhd_snapshot.json.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"
SNAPSHOT = "/tmp/radarr_uhd_snapshot.json"

PROFILES = [7, 8, 12, 13]

# Concrete qualities have stable global ids and correct names - match by name.
ENABLE_QUALITIES = {"Bluray-1080p", "Remux-1080p"}

# Groups are matched by their CONTENTS, because neither their ids nor their
# names are trustworthy:
#
#   * ids (1000-1003) are per-profile ordinals assigned by position in that
#     profile's own list. On profile 13 id 1002 is `WEB 1080p`; on profile 8
#     the same id is `WEB 2160p`.
#   * names on profile 8 are simply wrong - it carries FOUR groups all named
#     `WEB 2160p`, holding 480p, 720p, 1080p and 2160p children respectively.
#     Only the labels are corrupt; every group's contents are correct.
#
# So the only reliable identifier is what a group actually contains.
ENABLE_GROUP_CONTENTS = frozenset({"WEBDL-1080p", "WEBRip-1080p"})


def key():
    if os.environ.get("RADARR_API"):
        return os.environ["RADARR_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; use RADARR_API=<key> instead")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.RADARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read RADARR_API")
    return k


def req(k, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"X-Api-Key": k,
                                        "Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=180)
    t = resp.read().decode()
    return resp.status, (json.loads(t) if t.strip() else None)


def item_identity(it):
    """(id, name) for a profile item, whether it is a group or a quality."""
    if it.get("name"):
        return it.get("id"), it["name"]
    q = it.get("quality") or {}
    return q.get("id"), q.get("name")


def main():
    execute = "--execute" in sys.argv
    k = key()
    prior, plan = {}, []

    for pid in PROFILES:
        _, p = req(k, "/qualityprofile/%d" % pid)
        prior[str(pid)] = json.loads(json.dumps(p))   # deep copy for rollback
        changes = []
        seen = set()
        for it in p["items"]:
            _, nm = item_identity(it)
            kids = frozenset(s["quality"]["name"]
                             for s in (it.get("items") or [])
                             if s.get("quality"))
            hit = None
            if kids and kids == ENABLE_GROUP_CONTENTS:
                hit = "WEB 1080p group (contents %s, labelled %r)" % (
                    ", ".join(sorted(kids)), nm)
                seen.add("group")
            elif not kids and nm in ENABLE_QUALITIES:
                hit = nm
                seen.add(nm)
            if hit and not it.get("allowed"):
                it["allowed"] = True
                changes.append(hit)
            elif hit:
                changes.append("%s (already allowed)" % hit)
        missing = (ENABLE_QUALITIES | {"group"}) - seen
        if missing:
            raise SystemExit(
                "profile %s (%s) is missing %s — refusing to guess"
                % (pid, p["name"], ", ".join(sorted(missing))))
        plan.append((pid, p, [c for c in changes if "already allowed" not in c]))
        print("  %-3s %-34s enable: %s" % (
            pid, p["name"][:34], ", ".join(changes) if changes else "(nothing)"))

    if not execute:
        print("\nDRY RUN — nothing changed. Re-run with --execute.")
        return

    json.dump(prior, open(SNAPSHOT, "w"), indent=1)
    print("\nprior profiles -> %s" % SNAPSHOT)

    for pid, p, changes in plan:
        if not changes:
            continue
        st, _ = req(k, "/qualityprofile/%d" % pid, "PUT", p)
        print("  updated %-3s %-34s HTTP %s" % (pid, p["name"][:34], st))

    print("\nverifying:")
    for pid in PROFILES:
        _, p = req(k, "/qualityprofile/%d" % pid)
        got = sorted(nm for nm in (item_identity(it)[1] for it in p["items"]
                                   if it.get("allowed")) if nm)
        print("  %-3s %-30s allowed: %s" % (pid, p["name"][:30], ", ".join(got)))


if __name__ == "__main__":
    main()
