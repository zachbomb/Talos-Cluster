#!/bin/sh
# Plex Transcoder wrapper: hardware-decode Live TV (2026-09-28).
#
# WHY. The Plex tvOS app forces a video transcode for Live TV (directPlay=0 and
# directStream=0 whatever its settings say). PMS builds that transcode with a
# SOFTWARE decoder ("no hardware decode accelerator found"): it decodes H.264 on the
# CPU, scales on the CPU, then hwupload's to the GPU for h264_vaapi. Library
# transcodes on the same box run fully on the GPU (vaapi decode + encode, ~3x).
# On a busy node the software decode reached only 0.1-0.6x, so the Apple TV stuttered.
# Measured on a real Live TV command inside the Plex pod: software 30 s of video in
# 68 s (0.44x); this rewrite 30 s in 14-19 s (1.6-2.1x), output verified as
# H.264 High 1920x1080 with clean frames.
#
# WHAT. Only when ALL of these hold is the command rewritten; otherwise it runs
# byte-for-byte unchanged:
#   - the input is a PMS Live TV session (.../livetv/sessions/...)
#   - there is no -hwaccel already
#   - -init_hw_device names a vaapi device (vaapi=NAME:...)
#   - -filter_complex is EXACTLY PMS's software chain:
#       [0:0]scale=w=W:h=H:force_divisible_by=4[0];[0]format=pix_fmts=nv12[1];[1]hwupload[N]
# The rewrite:
#   - moves -init_hw_device to the front (the named device must exist before the
#     input opens)
#   - adds -hwaccel vaapi -hwaccel_device NAME -hwaccel_output_format vaapi before -i
#   - replaces the filter with [0:0]scale_vaapi=w=W:h=H:format=nv12[N], so frames
#     stay on the GPU
# Library transcodes, the Live TV grabber, subtitle burn-in and deinterlace chains
# don't match and pass through untouched.
#
# HOW IT IS INSTALLED (survives pod restarts and image updates). The Plex root
# filesystem is read-only, and the transcoder loads its bundled loader RELATIVE to
# its install directory, so the binary cannot be moved on its own.
#   - Init container "pmscopy" runs the SAME image as Plex and, on every pod start,
#     copies /usr/lib/plexmediaserver (~218 MB) into the emptyDir at REAL_DIR. An
#     image bump therefore refreshes the copy automatically; it can never run a
#     stale transcoder.
#   - kustomization.yaml generates ConfigMap plex-transcoder-wrap from THIS file
#     (Flux substitution disabled), and it is mounted over
#     /usr/lib/plexmediaserver/Plex Transcoder.
#   - If a future Plex changes the Live TV command shape, nothing matches and every
#     transcode passes through unchanged (back to software decode, never broken).
# Decisions are appended to /transcode/plex-wrap.log (tmpfs, cleared on restart).

# A subdir that cp creates itself: the emptyDir mount root is root-owned, so
# `cp -a` onto it fails for uid 1000 (EPERM setting its times).
REAL_DIR=/opt/pmscopy/pms
REAL="$REAL_DIR/Plex Transcoder"
LOG=/transcode/plex-wrap.log

live=no; hwacc=no; dev=""; fc=""; prev=""
for a in "$@"; do
  case "$a" in
    */livetv/sessions/*) live=yes ;;
    -hwaccel) hwacc=yes ;;
  esac
  [ "$prev" = "-init_hw_device" ] && dev="$a"
  [ "$prev" = "-filter_complex" ] && fc="$a"
  prev="$a"
done

devname=""
case "$dev" in
  vaapi=*:*) devname="${dev#vaapi=}"; devname="${devname%%:*}" ;;
esac

newfc=""
if [ -n "$fc" ]; then
  newfc=$(printf '%s' "$fc" | sed -n 's/^\[0:0\]scale=w=\([0-9]*\):h=\([0-9]*\):force_divisible_by=4\[0\];\[0\]format=pix_fmts=nv12\[1\];\[1\]hwupload\[\([0-9]*\)\]$/[0:0]scale_vaapi=w=\1:h=\2:format=nv12[\3]/p')
fi

decision=pass
if [ "$live" = yes ] && [ "$hwacc" = no ] && [ -n "$devname" ] && [ -n "$newfc" ]; then
  decision=hwdecode
  set -- "$@" "///PLEXWRAPEND///"
  set -- "$@" -init_hw_device "$dev"
  prev=""; seen_i=no
  while [ "$1" != "///PLEXWRAPEND///" ]; do
    a="$1"; shift
    if [ "$prev" = "-init_hw_device" ]; then prev=""; continue; fi
    if [ "$a" = "-init_hw_device" ]; then prev="$a"; continue; fi
    if [ "$prev" = "-filter_complex" ]; then a="$newfc"; fi
    # Hardware decode applies to the FIRST input only (the video stream); any later
    # -i, such as a subtitle file, must stay on the software path.
    if [ "$a" = "-i" ] && [ "$seen_i" = no ]; then
      seen_i=yes
      set -- "$@" -hwaccel vaapi -hwaccel_device "$devname" -hwaccel_output_format vaapi
    fi
    set -- "$@" "$a"
    prev="$a"
  done
  shift
  # "$@" is now: <-init_hw_device DEV> <original args with the rewrite applied>
fi

{ printf '%s %s live=%s hwaccel=%s dev=%s args=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" "$decision" "$live" "$hwacc" "${devname:-none}" "$#"; } >> "$LOG" 2>/dev/null

exec "$REAL" "$@"
