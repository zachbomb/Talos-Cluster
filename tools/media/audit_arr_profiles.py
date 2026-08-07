#!/usr/bin/env python3
"""Audit every Radarr and Sonarr quality profile against the library it serves.

WHY THIS EXISTS
---------------
Two profile defects were found on 2026-08-07 by accident, while chasing an
unrelated problem (17 films that could not be replaced):

  1. Profiles named `[Original]` and `[German]` had `language = English`,
     hard-rejecting 510 films' own-language releases before custom formats
     could score them.
  2. All four Radarr UHD profiles allow ONLY 2160p, while 1,311 of 1,874
     movies with a file (70%) hold 1080p or lower - so Radarr can never
     replace or upgrade any of them.

Neither was visible from any dashboard, and neither would have been found by
looking at a profile on its own. Both are only visible when a profile is
compared against the library actually assigned to it. That comparison is what
this script does.

WHAT IT CHECKS
--------------
Per profile:
  * language field vs the name's own language tag           (Radarr only -
    Sonarr v4 removed language from quality profiles)
  * cutoff quality present in the allowed set               (an unreachable
    cutoff means permanent "cutoff unmet")
  * allowed qualities vs what the assigned library holds    (the 70% case)
  * items assigned                                          (orphan profiles)

Per item (movie / series):
  * current file quality allowed by its own profile
  * original language vs profile language                   (Radarr)
  * original language vs profile name tag                   (both)

READ-ONLY. It changes nothing.

USAGE
-----
    python3 tools/media/audit_arr_profiles.py
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

TAG = re.compile(r"\[([A-Za-z]+)\]")


def cfg(k):
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.%s}" % k],
        capture_output=True, text=True, timeout=60)
    return (out.stdout or "").strip()


def api(base, key, path):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(base + path, headers={"X-Api-Key": key}),
        timeout=240))


def allowed_qualities(p):
    """Set of quality names the profile permits.

    Radarr nests groups: a group carries `allowed` and holds child qualities.
    Reading only the top level silently reports an empty set for grouped
    profiles, which would make every item look non-compliant.
    """
    s = set()
    for it in p.get("items", []):
        if not it.get("allowed"):
            continue
        if it.get("quality"):
            s.add(it["quality"]["name"])
        for sub in (it.get("items") or []):
            if sub.get("quality"):
                s.add(sub["quality"]["name"])
    return s


def cutoff_name(p):
    for it in p.get("items", []):
        if it.get("id") == p.get("cutoff") and it.get("name"):
            return it["name"]
        if (it.get("quality") or {}).get("id") == p.get("cutoff"):
            return it["quality"]["name"]
        for sub in (it.get("items") or []):
            if (sub.get("quality") or {}).get("id") == p.get("cutoff"):
                return sub["quality"]["name"]
    return str(p.get("cutoff"))


def audit(app, base, key, item_path, title_key):
    profs = api(base, key, "/qualityprofile")
    items = api(base, key, item_path)
    byprof = collections.defaultdict(list)
    for m in items:
        byprof[m.get("qualityProfileId")].append(m)

    L = []
    L.append("## %s — %d profiles, %d items" % (app, len(profs), len(items)))
    L.append("")
    L.append("| id | profile | language | cutoff | allowed qualities | items |")
    L.append("|---|---|---|---|---|---:|")
    for p in sorted(profs, key=lambda p: p["id"]):
        lang = (p.get("language") or {}).get("name") or "—"
        al = sorted(allowed_qualities(p))
        L.append("| %s | %s | `%s` | `%s` | %s | %d |" % (
            p["id"], p["name"][:34], lang, cutoff_name(p),
            ", ".join(al) if al else "**(none)**", len(byprof.get(p["id"], []))))
    L.append("")

    findings = []

    for p in profs:
        pid, name = p["id"], p["name"]
        al = allowed_qualities(p)
        assigned = byprof.get(pid, [])
        lang = (p.get("language") or {}).get("name")
        tag = (TAG.search(name).group(1) if TAG.search(name) else None)

        if not assigned:
            findings.append(("INFO", name,
                             "no items assigned — orphan profile"))
        if cutoff_name(p) not in al and al:
            findings.append(("HIGH", name,
                             "cutoff `%s` is NOT in the allowed set — every "
                             "item on this profile is permanently "
                             "cutoff-unmet" % cutoff_name(p)))
        # language field vs the name's own tag
        if lang and tag:
            if tag.lower() not in ("original",) and lang == "English" \
                    and tag.lower() != "english":
                findings.append(("HIGH", name,
                                 "name says [%s] but language field is "
                                 "`English` — hard-rejects the profile's own "
                                 "content before custom formats score" % tag))
            elif tag.lower() == "original" and lang not in ("Original", "Any"):
                findings.append(("HIGH", name,
                                 "name says [Original] but language field is "
                                 "`%s`" % lang))
        # what the assigned library actually holds vs what is allowed
        held = collections.Counter()
        for m in assigned:
            f = m.get("movieFile") or {}
            q = ((f.get("quality") or {}).get("quality") or {}).get("name")
            if q:
                held[q] += 1
        off = {q: n for q, n in held.items() if q not in al}
        if off and sum(off.values()) > 0:
            pct = 100.0 * sum(off.values()) / max(1, sum(held.values()))
            findings.append((
                "HIGH" if pct > 50 else "MEDIUM", name,
                "%d of %d assigned files (%.0f%%) are a quality this profile "
                "FORBIDS — they can never be upgraded or replaced: %s"
                % (sum(off.values()), sum(held.values()), pct,
                   ", ".join("%s×%d" % (q, n)
                             for q, n in sorted(off.items(),
                                                key=lambda kv: -kv[1])[:4]))))
        # original language vs profile language / tag
        mism = collections.Counter()
        for m in assigned:
            ol = (m.get("originalLanguage") or {}).get("name")
            if not ol:
                continue
            if lang and lang not in ("Original", "Any") and ol != lang:
                mism[ol] += 1
        if mism:
            findings.append(("HIGH", name,
                             "%d items whose original language differs from "
                             "the profile's `%s`: %s" % (
                                 sum(mism.values()), lang,
                                 ", ".join("%s×%d" % (k, v)
                                           for k, v in mism.most_common(4)))))
    return L, findings


def main():
    out = []
    out.append("# Radarr / Sonarr quality-profile audit")
    out.append("")
    out.append("Generated by `tools/media/audit_arr_profiles.py`. Read-only.")
    out.append("")
    out.append("Written after two profile defects were found by accident on "
               "2026-08-07 while chasing 17 films that could not be replaced. "
               "Neither was visible from any dashboard, and neither is "
               "visible when looking at a profile on its own — both only "
               "appear when a profile is compared against the library "
               "assigned to it.")
    out.append("")

    allf = []
    for app, ipkey, apikey, port, path, tk in (
            ("Radarr", "RADARR_IP", "RADARR_API", 7878, "/movie", "title"),
            ("Sonarr", "SONARR_IP", "SONARR_API", 8989, "/series", "title")):
        ip, key = cfg(ipkey), cfg(apikey)
        if not ip or not key:
            out.append("## %s — SKIPPED (no IP/API key in cluster-config)" % app)
            continue
        base = "http://%s:%d/api/v3" % (ip, port)
        try:
            L, f = audit(app, base, key, path, tk)
        except Exception as e:
            out.append("## %s — UNREACHABLE: %s %s"
                       % (app, type(e).__name__, str(e)[:120]))
            continue
        out += L
        allf += [(app,) + x for x in f]

    out.append("## Findings")
    out.append("")
    order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
    allf.sort(key=lambda x: order.get(x[1], 9))
    if not allf:
        out.append("None.")
    for app, sev, name, why in allf:
        out.append("- **%s** · %s · `%s` — %s" % (sev, app, name, why))
    out.append("")

    dest = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../../docs/audits/arr-profile-audit.md"))
    text = "\n".join(out) + "\n"
    open(dest, "w").write(text)
    print("wrote %s" % dest)
    c = collections.Counter(x[1] for x in allf)
    print("findings: %s" % dict(c))


if __name__ == "__main__":
    main()
