#!/usr/bin/env python3
"""SQ-49: repair the two Radarr quality profiles whose language contradicts
their own name.

THE DEFECT
----------
Two profiles are named for non-English content but have their `language` field
set to English, which makes Radarr hard-reject releases in the film's own
language before custom formats ever get to score them:

    id=13  UHD Bluray + WEB [Original]   language=English   365 movies
    id=12  UHD Bluray + WEB [German]     language=English   143 movies

Every other profile is already correct - notably `UHD Bluray + WEB [French]`
(id 8), which uses `Original` and works. This script makes 12 and 13 match it.

HOW IT WAS FOUND
----------------
While diagnosing why 17 corrupt films could not be replaced. Satyricon is an
Italian film on profile 13; its search returned 140 candidate releases and
rejected 109 with `English is wanted, but found Italian`.

WHY `Original` AND NOT `German` FOR id=12
-----------------------------------------
All 143 movies on it are German-original, so the two are equivalent today.
`Original` matches the established convention set by [French], and is more
robust: a stray non-German film landing on the profile later will not be
hard-rejected. Profile 13 holds 365 movies across Japanese, Chinese, Swedish,
Italian, Spanish, Persian and more - only `Original` can serve that.

WHY THE PROFILE FIELD AND NOT THE CUSTOM FORMATS
------------------------------------------------
Language handling here is already done properly with custom formats - profile
13 scores `Language: Not Original`, profile 12 scores `Not German or English`,
`German DL`, `German`. That is the intended design. The `language` field is a
hard gate that runs BEFORE scoring, so setting it to English discards the
releases the custom formats were written to rank. Only the gate is wrong.

DO NOT "fix" this by reassigning movies to other profiles. The assignments are
correct; the profiles are not. Rewriting 508 movie records to work around two
fields would be far harder to undo.

USAGE
-----
    python3 tools/media/fix_radarr_profile_language.py            # dry run
    python3 tools/media/fix_radarr_profile_language.py --execute  # apply

Writes the full prior profile JSON to /tmp/radarr_profile_snapshot.json before
changing anything, so the previous state can be restored verbatim.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BASE = "http://192.168.10.210:7878/api/v3"
SNAPSHOT = "/tmp/radarr_profile_snapshot.json"

# profile id -> language name it should carry
FIXES = {13: "Original", 12: "Original"}


def key():
    if os.environ.get("RADARR_API"):
        return os.environ["RADARR_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; run with RADARR_API=<key> instead")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.RADARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read RADARR_API: %s"
                         % (out.stderr or "empty")[:200])
    return k


def req(k, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"X-Api-Key": k,
                                        "Content-Type": "application/json"})
    resp = urllib.request.urlopen(r, timeout=180)
    text = resp.read().decode()
    return resp.status, (json.loads(text) if text.strip() else None)


def main():
    execute = "--execute" in sys.argv
    k = key()

    _, langs = req(k, "/language")
    by_name = {l["name"]: l for l in langs}

    prior = {}
    plan = []
    for pid, want in FIXES.items():
        _, p = req(k, "/qualityprofile/%d" % pid)
        prior[str(pid)] = p
        cur = (p.get("language") or {}).get("name")
        plan.append((pid, p["name"], cur, want, cur == want))
        print("  id=%-3s %-34s language=%-9s -> %-9s %s"
              % (pid, p["name"][:34], cur, want,
                 "(already correct)" if cur == want else "CHANGE"))

    if not execute:
        print("\nDRY RUN - nothing changed. Re-run with --execute to apply.")
        return

    json.dump(prior, open(SNAPSHOT, "w"), indent=1)
    print("\nprior profiles -> %s" % SNAPSHOT)

    for pid, name, cur, want, same in plan:
        if same:
            continue
        p = prior[str(pid)]
        p["language"] = by_name[want]
        st, _ = req(k, "/qualityprofile/%d" % pid, "PUT", p)
        print("  updated id=%-3s %-34s HTTP %s" % (pid, name[:34], st))

    print("\nverifying:")
    for pid, want in FIXES.items():
        _, p = req(k, "/qualityprofile/%d" % pid)
        got = (p.get("language") or {}).get("name")
        print("  id=%-3s language=%-9s %s"
              % (pid, got, "OK" if got == want else "MISMATCH"))


if __name__ == "__main__":
    main()
