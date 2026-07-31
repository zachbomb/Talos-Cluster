#!/bin/sh
# Tunarr double-`-ss` workaround (see docs/runbooks/tunarr-double-ss-ffmpeg-wrapper.md).
#
# Tunarr's pipeline builder emits the seek TWICE — `-ss <v>` before `-i` (demuxer
# seek) AND again after `-i` (accurate/output seek). For files with a non-zero
# container start_time this makes ffmpeg produce zero HLS segments → "No master
# playlist" → HTTP 500 → the channel is dead for that whole airing. Reproduced
# standalone; the sole failing element is the redundant post-input `-ss` (decoder-
# and readrate-independent). Removing it fixes the tune (playlist in ~5s).
#
# This wrapper strips the FIRST post-input `-ss <v>` whose value equals the
# pre-input `-ss`, then EXEC's the real ffmpeg — so any signal (incl. SIGKILL from
# Tunarr's session teardown) hits ffmpeg directly, with no orphaned realtime
# process. Non-duplicate commands pass through byte-for-byte unchanged.
#
# Enable: set Tunarr ffmpeg-settings `ffmpegExecutablePath` to this file's path.
# Verified: strips only the dup -ss (audio maps untouched → track selection intact).

# pass 1: preval = last -ss value before the first -i
preval=""; before=1; prev=""
for a in "$@"; do
  [ "$before" = 1 ] && [ "$prev" = "-ss" ] && preval="$a"
  [ "$a" = "-i" ] && before=0
  prev="$a"
done

# pass 1b: which -i ordinal is the SUBTITLE input?
# Do NOT assume "the second -i". Tunarr's pipeline commonly has THREE inputs:
#   0 = the video file
#   1 = the channel watermark image (with -loop 1)
#   2 = the .srt subtitle sidecar
# An earlier version of this wrapper inserted -readrate before the 2nd -i and so
# throttled the WATERMARK, leaving the subtitle unthrottled - the mitigation did
# nothing and rate-limited a looped overlay source instead. Match on the filename.
srt_ord=0; ord=0; expect=0
for a in "$@"; do
  if [ "$expect" = 1 ]; then
    expect=0
    case "$a" in *.srt|*.ass|*.ssa|*.vtt) srt_ord=$ord ;; esac
  fi
  [ "$a" = "-i" ] && { ord=$((ord + 1)); expect=1; }
done

# pass 2: rotate positional params, dropping the first matching post-i "-ss preval"
after=0; pend=0; dropped=0; rr_added=0; iord=0
set -- "$@" "///WRAPEND///"
while [ "$1" != "///WRAPEND///" ]; do
  a="$1"; shift
  if [ "$pend" = 1 ]; then
    pend=0
    if [ -n "$preval" ] && [ "$dropped" = 0 ] && [ "$a" = "$preval" ]; then
      dropped=1; continue
    fi
    set -- "$@" "-ss" "$a"; continue
  fi
  if [ "$after" = 1 ] && [ -n "$preval" ] && [ "$dropped" = 0 ] && [ "$a" = "-ss" ]; then
    pend=1; continue
  fi
  # Throttle the SECOND input (the subtitle sidecar). `-readrate` is an INPUT option,
  # so it must be emitted immediately BEFORE the -i it applies to. Tunarr emits
  # `-readrate 1 -readrate_initial_burst 60` before the FIRST -i only, so the .srt is
  # read as fast as the disk allows: it bursts until ffmpeg's mux queue blocks, running
  # ~2.4-3.5x ahead of video (measured).
  #
  # That divergence is what makes the upstream shared-anchor defect fatal. Tunarr keeps
  # ONE minSegmentRequested for all renditions of a session, so a subtitle fetch far
  # ahead of the playhead drags the anchor past live video; deleteOldSegments then
  # removes segments the video player has not reached, and every video fetch 404s.
  # Measured A/B on one channel: video-only 510s clean vs video+subtitles 5 backward
  # steps and sustained 404 from t=216s.
  #
  # This MITIGATES only. The shared anchor stays broken upstream - any second consumer,
  # or a client fetching out of order, reproduces it with no pacing divergence at all.
  # Remove this once upstream tracks the anchor per rendition.
  if [ "$a" = "-i" ]; then
    after=$((after + 1))
    iord=$((iord + 1))
    [ "$srt_ord" != 0 ] && [ "$iord" = "$srt_ord" ] && [ "$rr_added" = 0 ] && \
      { set -- "$@" "-readrate" "1"; rr_added=1; }
  fi
  set -- "$@" "$a"
done
shift  # drop the ///WRAPEND/// sentinel now at the front

exec /usr/bin/ffmpeg "$@"
