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

# pass 2: rotate positional params, dropping the first matching post-i "-ss preval"
after=0; pend=0; dropped=0
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
  [ "$a" = "-i" ] && after=1
  set -- "$@" "$a"
done
shift  # drop the ///WRAPEND/// sentinel now at the front

exec /usr/bin/ffmpeg "$@"
