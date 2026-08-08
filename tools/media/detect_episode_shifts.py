#!/usr/bin/env python3
"""Detect POSITIONAL episode-numbering shifts across the Sonarr TV library.

WHAT THIS ANSWERS
-----------------
"Does the filename's episode title match a DIFFERENT episode number in the same
season?" That is unambiguous where a plain string comparison is not.

WHY POSITIONAL, NOT STRING-EQUALITY
-----------------------------------
A naive filename-vs-Sonarr-title comparison over 15 series flagged 155 of 1,283
(12.1%) as mismatched. Almost all were noise:

  * `&` vs `and`, `+` vs `and`, punctuation  -> `Dope & Faith` / `Dope and Faith`
  * multi-episode files (`S06E06-E07`) whose name legitimately holds two titles

Both are handled here: titles are normalised before comparison, and multi-episode
files are SKIPPED because a shift cannot be judged from them at all.

The real signal is a file whose title belongs to a neighbouring episode number:

    American Dad! S15E08  sonarr="Death by Dinner Party"    file=...The.Never-Ending.Stories
    American Dad! S15E09  sonarr="The Never-Ending Stories" file=...Railroaded

RESULT WHEN LAST RUN (2026-08-07, full library)
-----------------------------------------------
    8,100 episode files checked (10 multi-episode skipped)
    41 positional shifts across 6 series:

      The French Chef                27 episodes   offsets [-2,1,2,3]
      King of the Hill                6 episodes   offsets [-2,-1,1,3]
      Anthony Bourdain: No Reservations 4 episodes offsets [1,2,3]
      American Dad!                   2 episodes   offsets [1]
      Carlos                          1 episode    offsets [-2]
      Futurama                        1 episode    offsets [-1]

**Offsets are NOT constant within a series** (Bourdain shows +1, +2 AND +3). That
rules out a season-wide scene-numbering mapping as the fix — TVDB ordering and
release-group ordering disagree episode-by-episode, so each file needs re-linking
individually.

THE LIMIT THIS CANNOT SEE - read before trusting a low count
------------------------------------------------------------
This works by comparing the FILENAME's title against Sonarr's. Where Sonarr has
already RENAMED a file, its own numbering is baked into the name, the comparison
trivially agrees, and a shift becomes invisible. The Bourdain conflict was only
detectable because that series kept its original release names.

**A clean result on a fully-renamed series is not evidence of correctness.**
It is evidence the detector cannot see that series.

WHY IT MATTERS DOWNSTREAM (SQ-55, SQ-58)
----------------------------------------
Bazarr fetches subtitles for the identity Sonarr reports. A shifted file gets the
WRONG episode's subtitles written beside the RIGHT video, under a filename matching
the video. Verified on disk: `...S03E07.Cleveland...en.sdh.srt` contains Shanghai's
dialogue. Correcting identity does NOT fix those sidecars — they must be deleted and
re-fetched AFTER the identity is corrected, or Bazarr re-downloads the same wrong ones.

USAGE
-----
    python3 tools/media/detect_episode_shifts.py [<api-key> <host>]

Defaults read SONARR_API from the cluster-config ConfigMap.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

DEFAULT_HOST = "192.168.10.211"


def key():
    if os.environ.get("SONARR_API"):
        return os.environ["SONARR_API"].strip()
    kc = shutil.which("kubectl") or next(
        (p for p in ("/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl",
                     "/usr/bin/kubectl") if os.path.exists(p)), None)
    if not kc:
        raise SystemExit("kubectl not found; pass the key as argv[1]")
    out = subprocess.run(
        [kc, "get", "cm", "-n", "flux-system", "cluster-config",
         "-o", "jsonpath={.data.SONARR_API}"],
        capture_output=True, text=True, timeout=60)
    k = (out.stdout or "").strip()
    if not k:
        raise SystemExit("could not read SONARR_API")
    return k


def norm(s):
    """Normalise a title so `&`/`and`/punctuation differences stop being mismatches."""
    s = (s or "").lower().replace("&", " and ").replace("+", " and ")
    return re.sub(r"[^a-z0-9]+", "", s)


MULTI_EP = (re.compile(r"[Ss]\d+[Ee]\d+[-_ ]?[Ee]\d+"),
            re.compile(r"[Ee]\d+[-_][Ee]\d+"))


def main():
    k = sys.argv[1] if len(sys.argv) > 2 else key()
    host = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_HOST
    base = "http://%s:8989/api/v3" % host

    def api(p):
        return json.load(urllib.request.urlopen(
            urllib.request.Request(base + p, headers={"X-Api-Key": k}),
            timeout=180))

    series = api("/series")
    shifts, checked, multi, renamed = [], 0, 0, 0

    for s in series:
        try:
            eps = api("/episode?seriesId=%d&includeEpisodeFile=true" % s["id"])
        except Exception:
            continue
        idx = {(e.get("seasonNumber"), e.get("episodeNumber")): (e.get("title") or "")
               for e in eps}
        for e in eps:
            ef = e.get("episodeFile") or {}
            rel = os.path.basename(ef.get("relativePath") or "")
            if not rel:
                continue
            if any(p.search(rel) for p in MULTI_EP):
                multi += 1
                continue
            checked += 1
            sn, en = e.get("seasonNumber"), e.get("episodeNumber")
            own = norm(idx.get((sn, en), ""))
            if len(own) >= 6 and own in norm(rel):
                renamed += 1        # matches its own title — may be Sonarr-renamed
                continue
            for off in (-3, -2, -1, 1, 2, 3):
                other = norm(idx.get((sn, en + off), ""))
                if len(other) >= 6 and other in norm(rel):
                    shifts.append((s["title"], sn, en, idx.get((sn, en), ""),
                                   idx.get((sn, en + off), ""), off, rel))
                    break

    print("episode files checked: %d   (multi-episode skipped: %d)" % (checked, multi))
    print("files whose name already matches their own title: %d" % renamed)
    print("  ^ a shift in these is INVISIBLE to this method — see the module docstring")
    print("\nPOSITIONAL SHIFTS: %d\n" % len(shifts))

    for t, c in collections.Counter(x[0] for x in shifts).most_common(20):
        offs = sorted({x[5] for x in shifts if x[0] == t})
        print("  %-36s %3d episodes   offsets=%s" % (t[:36], c, offs))

    print("\nexamples:")
    for x in shifts[:10]:
        print("  %-24s S%02dE%02d sonarr=%-26s file says=%-26s (off %+d)"
              % (x[0][:24], x[1], x[2], (x[3] or "")[:26], (x[4] or "")[:26], x[5]))


if __name__ == "__main__":
    main()
