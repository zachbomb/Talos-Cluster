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

# pass 1c: subtitle-timeline fix. Tunarr applies the join seek (`-ss <off>`) ONLY to
# input 0 (the video); the .srt input gets none. Video therefore starts at t=0 while
# subtitle cues keep counting from PROGRAM start, and nothing reconciles the two — a
# player matching its own t≈0 lands on the opening credits. Verified on disk: all 275
# live .vtt segments are a bare `WEBVTT` + blank line, and cues run 00:07.099,
# 00:11.132, 00:15.966 ... i.e. program-absolute, never rebased.
#
# X-TIMESTAMP-MAP is NOT an option here. ffmpeg 7.1.1's `webvtt` muxer exposes ZERO
# options and no ffmpeg option anywhere mentions timestamp-map; the header is written
# by the HLS muxer, and Tunarr sends subtitles through `-f segment -segment_format
# webvtt`, which delegates to that optionless muxer.
#
# THE TRAP — do NOT "just seek input 1 to match input 0". Input-side `-ss` on the srt
# rebases the timeline to the first SURVIVING CUE'S START, not to the seek point, so
# every cue runs early by (seek - straddling_cue_start). Measured across six joins:
# 0.795 / 0.924 / 1.385 / 1.461 / 1.717 / 2.747 s. Content-dependent, so no constant
# corrects it. `-copyts`, `-itsoffset` and `-output_ts_offset` do NOT prevent it —
# all get clamped and re-anchored at the muxer (tested individually). It passes a
# casual check (right dialogue, no negatives, pre-join cues dropped) while being
# silently wrong, which is worse than today's obviously-wrong output.
#
# What works is an OUTPUT-side seek plus an equal negative ts offset, applied to the
# SUBTITLE OUTPUT only. Validated at 10 seek points against values computed from the
# source .srt: 10/10 exact, zero drift.
#
# The catch: output-side `-ss` decodes and DISCARDS from t=0, and this same input
# carries `-readrate 1`. Paced at realtime a 37-minute join means ~36 real minutes
# before the first cue appears — measured: NO cue after 40s. Perfectly-timed
# subtitles arriving after the program ends. Invisible to a subtitle-only harness,
# which has no readrate.
#
# Fixed by sizing `-readrate_initial_burst` to cover the discarded span: burst =
# offset_seconds + 60, preserving Tunarr's original 60s headroom. Measured with the
# burst: first cue at t=1s, exact at 00:00.315, then pacing resumes.
#
# NEGATIVE CONTROLS (both must stay no-ops):
#   * no .srt input      -> srt_ord stays 0, nothing is injected
#   * absent/zero offset -> sub_off stays empty, nothing is injected. Program-start
#     joins are the only case working in production today and MUST NOT regress; this
#     is skipped structurally, not by arithmetic that happens to yield zero.
sub_off=""; sub_burst=""
if [ "$srt_ord" != 0 ] && [ -n "$preval" ]; then
  # preval is normally like "2220407ms"; tolerate a bare seconds value too.
  case "$preval" in
    *ms) _n="${preval%ms}"; _secs=$(( _n / 1000 )) ;;
    *)   _n="${preval%%.*}"; _secs="$_n" ;;
  esac
  # Only inject for a real, positive, purely-numeric seek.
  case "$_n" in
    ''|*[!0-9]*) : ;;
    *) [ "$_n" -gt 0 ] && { sub_off="$preval"; sub_burst=$(( _secs + 60 )); } ;;
  esac
fi

# pass 2: rotate positional params, dropping the first matching post-i "-ss preval"
after=0; pend=0; dropped=0; rr_added=0; iord=0; map_done=0
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
    if [ "$srt_ord" != 0 ] && [ "$iord" = "$srt_ord" ] && [ "$rr_added" = 0 ]; then
      set -- "$@" "-readrate" "1"
      # Burst must cover the span the OUTPUT-side seek discards, or the paced read
      # never reaches the join. Only emitted when we are actually injecting the seek.
      [ -n "$sub_burst" ] && set -- "$@" "-readrate_initial_burst" "$sub_burst"
      rr_added=1
    fi
  fi
  # Attach the seek pair to the SUBTITLE OUTPUT, immediately after its `-map <n>:0`.
  # Anchoring to the map (not to a positional guess) is what keeps these off the video
  # output — a stray -output_ts_offset there would shift VIDEO timestamps and present
  # as an A/V sync bug, i.e. it would be blamed on the wrong subsystem for a while.
  # Input index is srt_ord-1 because srt_ord is a 1-based -i ordinal.
  if [ -n "$sub_off" ] && [ "$map_done" = 0 ] && [ "$a" = "-map" ]; then
    set -- "$@" "$a"
    a="$1"; shift                      # the map target, e.g. "2:0"
    if [ "$a" = "$((srt_ord - 1)):0" ]; then
      set -- "$@" "$a" "-ss" "$sub_off" "-output_ts_offset" "-$sub_off"
      map_done=1
      continue
    fi
    set -- "$@" "$a"
    continue
  fi
  set -- "$@" "$a"
done
shift  # drop the ///WRAPEND/// sentinel now at the front

exec /usr/bin/ffmpeg "$@"
