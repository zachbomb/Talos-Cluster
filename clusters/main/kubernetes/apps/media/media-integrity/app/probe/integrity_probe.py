#!/usr/bin/env python3
"""SQ-48: continuously detect media files that exist but cannot be played.

WHY THIS EXISTS
---------------
On 2026-08-07 a scan looking for something else found 17 movie files that
cannot be demuxed at all - 14 failing `EBML header parsing failed`, several
10-16 GB. They had been unplayable since April 2025.

Every service reported them as fine. Radarr: hasFile=true, quality
Bluray-1080p, monitored, cutoff-unmet. Plex and Emby listed them as available.
The entire stack tracks PRESENCE and METADATA; nothing checks CONTENT. No
dashboard, alert or exporter could have surfaced this, because none of them
ever opens a file.

FALSE-POSITIVE TRAPS, every one of them hit in practice
-------------------------------------------------------
Encoded here deliberately, because getting any of them wrong makes the metric
worthless - and in opposite directions, which is worse than useless.

1. ffprobe CANNOT demux a filesystem image. `Wonderstruck (2017).iso` (45 GB)
   reported `Invalid data found when processing input` while being perfectly
   intact - a valid UDF volume (BEA01 / NSR03 / TEA01). Judging an ISO with
   ffprobe condemns every healthy disc image in the library. ISOs are checked
   on their volume descriptors instead.

2. stderr output is NOT failure. `Long Day's Journey Into Night (1962)` emitted
   a dvdsub warning yet returned 10220.34 s across 5 streams. A check keying on
   "did ffprobe print to stderr" flags working files. The verdict must key on
   whether streams or a duration actually came back.

3. An AUDIO CD image has no filesystem at all. A raw CD rip legitimately has
   nothing at 0x8000, so the descriptor check must look for a cuesheet beside
   it before calling one damaged. `Dick Around + Waterproof UK CD Single.img`
   was flagged corrupt on exactly that basis.

4. The low-bitrate heuristic is VIDEO-only. 250 kbps is diagnostic for a
   feature and ordinary for an MP3; running it over music flags every long
   classical movement and live set.

Implausibly low bitrate is reported SEPARATELY and never as corruption. 170
min in 0.25 GB is a bad encode, not a broken file, and conflating them would
bury the files that genuinely cannot be opened.

OUTPUT
------
Prometheus text format on stdout, or served on --port for scraping:

    media_integrity_files_total{library="movies"}
    media_integrity_unreadable{library="movies"}        <- the alert signal
    media_integrity_low_bitrate{library="movies"}
    media_integrity_scan_duration_seconds{library="movies"}
    media_integrity_last_scan_timestamp{library="movies"}
    media_integrity_scan_errors{library="movies"}

USAGE
-----
    python3 integrity_probe.py --root /media/media/movies --library movies
    python3 integrity_probe.py --root ... --library ... --port 9838 --interval 21600
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time

VIDEO_EXT = ("*.mkv", "*.mp4", "*.m4v", "*.avi", "*.mpg", "*.ts", "*.wmv")

# Audio. Their ABSENCE from the first version of this file is the most
# instructive bug it has had: pointed at three music libraries holding 111,208
# audio files, it examined 16 of them - the stray video files - and reported
# `unreadable=0`. A clean bill of health for a population it never opened.
#
# That is exactly the failure this whole component exists to prevent, produced
# by the component itself. A scan that examines nothing is indistinguishable
# from a healthy library, which is why media_integrity_files_total is exported
# alongside the defect counts and why the alerting must treat a sudden drop in
# files_total as suspicious rather than reassuring.
AUDIO_EXT = ("*.flac", "*.mp3", "*.m4a", "*.ogg", "*.opus", "*.wav",
             "*.aiff", "*.aif", "*.wma", "*.alac", "*.ape", "*.dsf", "*.wv")

IMAGE_EXT = (".iso", ".img", ".bin")

# A disc image sitting next to one of these is a raw CD image, not a
# filesystem image. Audio CDs carry NO filesystem at all - no ISO9660, no UDF -
# so judging one on its volume descriptors condemns a perfectly good rip.
CUESHEET_EXT = (".cue", ".toc", ".ccd")

# A feature film under this bitrate is very unlikely to be intact video.
LOW_BITRATE_BPS = 250_000
MIN_DURATION_FOR_BITRATE = 600      # don't judge shorts / clips


def check_disc_image(path):
    """(ok, detail) for a filesystem image, judged on volume descriptors.

    ffprobe cannot demux a UDF/ISO9660 image and reports a valid one as
    corrupt, so it must not be used here.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0x8000)
            pvd = fh.read(2048)
            fh.seek(0x8800)
            udf = fh.read(8)
    except OSError as e:
        return False, "unreadable: %s" % type(e).__name__
    if pvd[1:6] == b"CD001":
        return True, "valid ISO9660 volume descriptor"
    if pvd[1:6] == b"BEA01" or udf[1:6] in (b"NSR02", b"NSR03"):
        return True, "valid UDF volume descriptor"
    # No filesystem descriptor. Before calling that damage, check for a
    # cuesheet beside it: an AUDIO CD carries no filesystem at all, so a raw
    # audio-CD rip legitimately has nothing at 0x8000. The first version of
    # this check flagged `Dick Around + Waterproof UK CD Single.img` as
    # corrupt on exactly that basis.
    stem = os.path.splitext(path)[0]
    for ext in CUESHEET_EXT:
        if os.path.exists(stem + ext) or os.path.exists(stem + ext.upper()):
            return True, ("raw CD image with a %s cuesheet - audio CDs carry "
                          "no filesystem, so no descriptor is expected" % ext)
    return False, ("no ISO9660 or UDF volume descriptor at 0x8000 and no "
                   "cuesheet beside it")


def is_audio(path):
    return path.lower().endswith(tuple(e.lstrip("*") for e in AUDIO_EXT))


def check_media(path):
    """(state, detail) where state is ok | unreadable | low_bitrate."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type", "-of", "json", path],
            capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return "unreadable", "ffprobe timed out"
    except OSError as e:
        return "error", "ffprobe unavailable: %s" % e

    dur, nstreams = None, 0
    try:
        j = json.loads(r.stdout or "{}")
        dur = (j.get("format") or {}).get("duration")
        nstreams = len(j.get("streams") or [])
    except ValueError:
        pass

    # Streams or a duration came back => the file opened. stderr may still
    # carry warnings; those are not failures.
    if not nstreams and not dur:
        why = (r.stderr or "no output").strip().splitlines()
        return "unreadable", (why[0][:160] if why else "no streams, no duration")

    try:
        d = float(dur) if dur else 0.0
    except ValueError:
        d = 0.0
    # The low-bitrate heuristic is calibrated for VIDEO and is meaningless
    # for audio: 250 kbps is diagnostic for a feature film and completely
    # ordinary for an MP3. Running it over a music library would flag every
    # long classical movement, live set and DJ mix - a steady stream of
    # non-defects that trains people to ignore the metric.
    if not is_audio(path) and d > MIN_DURATION_FOR_BITRATE:
        try:
            bps = os.path.getsize(path) * 8.0 / d
        except OSError:
            bps = None
        if bps is not None and bps < LOW_BITRATE_BPS:
            return "low_bitrate", "%.0f min at %.0f kbps" % (d / 60, bps / 1000)
    return "ok", "%d streams, %.0f s" % (nstreams, d)


def scan(root):
    t0 = time.time()
    counts = {"total": 0, "unreadable": 0, "low_bitrate": 0, "errors": 0}
    detail = {"unreadable": [], "low_bitrate": []}
    if not os.path.isdir(root):
        counts["errors"] += 1
        return counts, detail, 0.0

    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            low = fn.lower()
            if low.endswith(IMAGE_EXT) or any(
                    low.endswith(p.lstrip("*"))
                    for p in VIDEO_EXT + AUDIO_EXT):
                files.append(os.path.join(dirpath, fn))

    for path in files:
        counts["total"] += 1
        if path.lower().endswith(IMAGE_EXT):
            ok, why = check_disc_image(path)
            if not ok:
                counts["unreadable"] += 1
                detail["unreadable"].append((path, why))
            continue
        state, why = check_media(path)
        if state == "unreadable":
            counts["unreadable"] += 1
            detail["unreadable"].append((path, why))
        elif state == "low_bitrate":
            counts["low_bitrate"] += 1
            detail["low_bitrate"].append((path, why))
        elif state == "error":
            counts["errors"] += 1
    return counts, detail, time.time() - t0


def render(library, counts, elapsed):
    L = [
        "# HELP media_integrity_files_total Media files examined.",
        "# TYPE media_integrity_files_total gauge",
        'media_integrity_files_total{library="%s"} %d' % (library, counts["total"]),
        "# HELP media_integrity_unreadable Files that exist but cannot be opened.",
        "# TYPE media_integrity_unreadable gauge",
        'media_integrity_unreadable{library="%s"} %d' % (library, counts["unreadable"]),
        "# HELP media_integrity_low_bitrate Files whose bitrate is too low to be intact video.",
        "# TYPE media_integrity_low_bitrate gauge",
        'media_integrity_low_bitrate{library="%s"} %d' % (library, counts["low_bitrate"]),
        "# HELP media_integrity_scan_errors Probe failures, not file defects.",
        "# TYPE media_integrity_scan_errors gauge",
        'media_integrity_scan_errors{library="%s"} %d' % (library, counts["errors"]),
        "# HELP media_integrity_scan_duration_seconds Wall-clock of the last scan.",
        "# TYPE media_integrity_scan_duration_seconds gauge",
        'media_integrity_scan_duration_seconds{library="%s"} %.1f' % (library, elapsed),
        "# HELP media_integrity_last_scan_timestamp Unix time of the last completed scan.",
        "# TYPE media_integrity_last_scan_timestamp gauge",
        'media_integrity_last_scan_timestamp{library="%s"} %d' % (library, int(time.time())),
    ]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    # Repeatable `--lib name=/path` so ONE process covers every library. The
    # alternative - a container per library - multiplies the scrape surface
    # and makes "which library stopped being scanned" hard to see, which is
    # the exact question this component must always be able to answer.
    ap.add_argument("--lib", action="append", default=[],
                    metavar="NAME=PATH",
                    help="repeatable; e.g. --lib movies=/media/movies")
    ap.add_argument("--root")
    ap.add_argument("--library")
    ap.add_argument("--port", type=int)
    ap.add_argument("--interval", type=int, default=21600)
    ap.add_argument("--list", action="store_true",
                    help="print offending paths to stderr")
    a = ap.parse_args()

    libs = []
    for spec in a.lib:
        if "=" not in spec:
            raise SystemExit("--lib expects NAME=PATH, got %r" % spec)
        name, path = spec.split("=", 1)
        libs.append((name, path))
    if a.root and a.library:
        libs.append((a.library, a.root))
    if not libs:
        raise SystemExit("give --lib NAME=PATH (repeatable) or --root/--library")

    def run_once():
        blocks, agg = [], {"total": 0, "unreadable": 0,
                           "low_bitrate": 0, "errors": 0}
        for name, path in libs:
            counts, detail, elapsed = scan(path)
            blocks.append(render(name, counts, elapsed))
            for k in agg:
                agg[k] += counts[k]
            if a.list:
                for kind in ("unreadable", "low_bitrate"):
                    for pp, why in detail[kind]:
                        print("%-12s [%s] %s  (%s)"
                              % (kind.upper(), name, pp, why), file=sys.stderr)
        # Only the first block keeps the HELP/TYPE headers; repeating them
        # for every library makes Prometheus reject the whole exposition.
        out = [blocks[0]] if blocks else []
        for b in blocks[1:]:
            out.append("\n".join(l for l in b.splitlines()
                                  if not l.startswith("#")) + "\n")
        return "".join(out), agg

    if not a.port:
        text, counts = run_once()
        sys.stdout.write(text)
        print("scanned=%d unreadable=%d low_bitrate=%d errors=%d"
              % (counts["total"], counts["unreadable"],
                 counts["low_bitrate"], counts["errors"]), file=sys.stderr)
        return

    from http.server import BaseHTTPRequestHandler, HTTPServer
    state = {"text": render(libs[0][0], {"total": 0, "unreadable": 0,
                                         "low_bitrate": 0, "errors": 0}, 0.0)}

    def loop():
        while True:
            try:
                state["text"], _ = run_once()
            except Exception as e:                     # keep serving stale data
                print("scan failed: %s %s" % (type(e).__name__, e),
                      file=sys.stderr)
            time.sleep(a.interval)

    threading.Thread(target=loop, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = state["text"].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    HTTPServer(("", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
