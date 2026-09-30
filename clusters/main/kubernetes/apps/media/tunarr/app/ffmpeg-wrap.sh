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

# pass 1d: PRE-TRIM the subtitle sidecar instead of seeking it (SQ-249 trigger fix).
#
# The output-side seek above works, but it makes ffmpeg DECODE AND DISCARD the .srt
# from t=0 at `-readrate 1`, which is the only reason `-readrate_initial_burst` exists.
# That burst then produces its own defect. Measured 2026-09-01 on an 18:07 join:
#   * all 12 .vtt segments were written within ONE SECOND of ffmpeg starting, then
#     NOTHING for ~18 minutes while wall-clock caught up to the burst. Predicted
#     resumption at process age 1147s, observed ~1099s - confirmed independently by
#     two observers, so the mechanism is settled, not inferred.
#   * on resumption the low-index subtitle fetches dragged Tunarr's SHARED
#     minSegmentRequested backward - "Media sequence changed unexpectedly: 269 -> 15"
#     two seconds later - collapsing the video window. Our own workaround was pulling
#     the trigger on the upstream shared-anchor defect.
#   * and after catchup the subtitle input advances at 1x FROM THE JOIN, so cues arrive
#     ~17 min behind the live edge and a player drops them as past. The burst cannot be
#     tuned out of this. It has to be replaced.
#
# Pre-trimming removes the cause: hand ffmpeg a .srt whose t=0 IS the join point. Then
# there is nothing to discard, no burst, no catchup stall, no resumption fetch storm,
# and `-readrate 1` does exactly the job it was added for (stopping the sidecar racing
# 2.4-3.5x ahead of the video).
#
# NOT input-side `-ss`. That was tried FIRST and rejected: it rebases to the first
# SURVIVING CUE'S START rather than to the seek point, so every cue runs early by a
# content-dependent 0.795 / 0.924 / 1.385 / 1.461 / 1.717 / 2.747 s (measured over six
# joins), and -copyts / -itsoffset / -output_ts_offset all fail to prevent it. Doing the
# arithmetic ourselves is the entire point - we control the rebase instead of inheriting
# ffmpeg's seek semantics, which are quietly wrong here.
#
# FAIL-SAFE: if anything does not work out - no path, unreadable, awk trouble, zero
# surviving cues - sub_trim stays empty and the ORIGINAL seek+burst path runs unchanged.
# This can degrade to today's behaviour, never below it.
#
# Validated offline before shipping: 10 seek points against a real 926-cue .srt, exact
# on every surviving cue (start, end, text, renumbering), straddling cues clamped to 0,
# and identical output under the container's mawk 1.3.4 and under macOS awk.
sub_trim=""; sub_src=""
if [ -n "$sub_off" ]; then
  _o=0; _exp=0
  for a in "$@"; do
    if [ "$_exp" = 1 ]; then
      _exp=0
      [ "$_o" = "$srt_ord" ] && sub_src="$a"
    fi
    [ "$a" = "-i" ] && { _o=$(( _o + 1 )); _exp=1; }
  done
  if [ -n "$sub_src" ] && [ -r "$sub_src" ]; then
    # Bound growth: /tmp is a shared MEMORY-backed tmpfs and exec() means this script can
    # never clean up after itself, so each invocation reaps its own old leavings.
    find /tmp -maxdepth 1 -name 'tunarr-subtrim-*.srt' -mmin +180 -delete 2>/dev/null || true
    _tt="/tmp/tunarr-subtrim-$$-$(date +%s 2>/dev/null || echo 0).srt"
    # CR is stripped BEFORE awk. In paragraph mode (RS="") a line holding only CR is not
    # blank, so a CRLF .srt never splits into records and silently yields NOTHING. Caught
    # in testing; it would have shipped as "pre-trim mysteriously drops all subtitles".
    tr -d '\r' < "$sub_src" 2>/dev/null | awk -v off="${sub_off%ms}" '
      function ms(t,   a) {
        gsub(/^[ \t]+|[ \t]+$/, "", t)
        split(t, a, /[:,]/)
        return ((a[1]*3600) + (a[2]*60) + a[3]) * 1000 + a[4]
      }
      function fmt(v,   h, m, s, x) {
        if (v < 0) v = 0
        h = int(v/3600000); v -= h*3600000
        m = int(v/60000);   v -= m*60000
        s = int(v/1000);    x = v - s*1000
        return sprintf("%02d:%02d:%02d,%03d", h, m, s, x)
      }
      BEGIN { RS = ""; FS = "\n"; n = 0 }
      {
        ti = 0
        for (i = 1; i <= NF; i++) if ($i ~ / --> /) { ti = i; break }
        if (!ti) next
        split($ti, tt, / --> /)
        st = ms(tt[1]); en = ms(tt[2])
        if (en < off) next
        n++
        printf "%d\n%s --> %s\n", n, fmt(st - off), fmt(en - off)
        for (i = ti + 1; i <= NF; i++) print $i
        printf "\n"
      }' > "$_tt" 2>/dev/null || true
    # Adopt it only if it actually holds cues. An empty trim would silently remove
    # subtitles for a whole airing - worse than the burst behaviour it replaces.
    if [ -s "$_tt" ] && grep -q -- ' --> ' "$_tt" 2>/dev/null; then
      sub_trim="$_tt"
      sub_burst=""
    else
      rm -f "$_tt" 2>/dev/null || true
    fi
  fi
fi

# pass 2: rotate positional params, dropping the first matching post-i "-ss preval"
after=0; pend=0; dropped=0; rr_added=0; iord=0; map_done=0; sub_pend=0
set -- "$@" "///WRAPEND///"
while [ "$1" != "///WRAPEND///" ]; do
  a="$1"; shift
  # Swap the sidecar path for the PRE-TRIMMED copy. Done here, at the argument
  # immediately following the subtitle `-i`, rather than by matching on filename -
  # the media input can legitimately be an .srt-adjacent name, and a filename match
  # would eventually hit the wrong input.
  if [ "$sub_pend" = 1 ]; then
    sub_pend=0
    [ -n "$sub_trim" ] && a="$sub_trim"
    set -- "$@" "$a"; continue
  fi
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
      # sub_burst is EMPTY when pre-trim succeeded: with a .srt whose t=0 is the join
      # there is no discarded span to cover, and emitting a burst anyway would recreate
      # the 18-minute wall-clock-catchup stall this fix exists to remove.
      [ -n "$sub_burst" ] && set -- "$@" "-readrate_initial_burst" "$sub_burst"
      rr_added=1
    fi
    # Arm the path swap for the very next argument (this input's path).
    [ "$srt_ord" != 0 ] && [ "$iord" = "$srt_ord" ] && [ -n "$sub_trim" ] && sub_pend=1
  fi
  # Attach the seek pair to the SUBTITLE OUTPUT, immediately after its `-map <n>:0`.
  # Anchoring to the map (not to a positional guess) is what keeps these off the video
  # output — a stray -output_ts_offset there would shift VIDEO timestamps and present
  # as an A/V sync bug, i.e. it would be blamed on the wrong subsystem for a while.
  # Input index is srt_ord-1 because srt_ord is a 1-based -i ordinal.
  # Skipped entirely when sub_trim is set: the trimmed file already starts at the join,
  # so an output-side seek would discard a second time and shift cues by another offset.
  if [ -z "$sub_trim" ] && [ -n "$sub_off" ] && [ "$map_done" = 0 ] && [ "$a" = "-map" ]; then
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

# pass 2b: strip QsvPipelineBuilder's hardcoded `fps=24` from -filter_complex (SQ-123/125).
#
# WHY: Tunarr's `getNumericFrameRateOrDefault()` (MediaStream.ts:178-199) is a provable
# constant 24 for EVERY input - the parseInt result is computed and then never used on
# the success path, and the isNaN fallback is unreachable because the numerator is a
# prefix of the same string. QsvPipelineBuilder.ts:179-205 then appends `fps=<that>`
# unconditionally, so every QSV channel is pinned to exactly 24.000. Verified in the
# deployed SEA binary, not just upstream source.
#
# That is a frame-rate CONVERSION, not a passthrough: a 29.97 source loses ~6 frames/sec
# UNEVENLY and 23.976 is resampled to 24.000. The judder is baked into the transcode and
# no client-side setting can undo it. Measured on ch13: every source file is 24000/1001
# or 30000/1001, delivered was 24/1.
#
# VaapiPipelineBuilder never adds this filter and those 13 channels have run without it
# indefinitely - that is the live evidence that removing it is tolerable here.
#
# UPSTREAM INTENT: the filter exists for tunarr#1431, whose body asks to set the rate "to
# the same as the content" - i.e. it was meant to MATCH the source, and the parser defect
# makes it land on the exact default it was written to avoid. Stripping it restores the
# intended behaviour rather than defeating it. REVERT THIS PASS once upstream fixes the
# parser. Note a Math.round(num/den) fix upstream would NOT suffice: it cannot express
# 24000/1001.
#
# ⚠️ COUPLED TO A CLIENT-SIDE DEFECT. Restoring true frame rates means QSV channels will
# modeset on tune/boundary once the client's `refreshrate.auto_switch` is re-enabled, and
# that client's HDMI sink unreliably re-trains - losing picture OR sound depending on the
# attempt. auto_switch is currently FALSE, which is the only reason this is safe to ship.
# DO NOT re-enable auto_switch until the sink fault is fixed. That rule predates this
# change (the 13 VAAPI channels already deliver true rates); this widens it to 26.
#
# SCOPE GUARD: only removes `fps=` when it is a STANDALONE filter - preceded by a chain
# separator (`,` `;` `[` `]`) or string start. Deliberately does NOT touch an `fps=` that
# is a sub-option of another filter (e.g. `minterpolate=fps=50`), which is legitimate.
#
# NO-OP when absent: VAAPI chains pass through byte-for-byte unchanged.
#
# Validated against a REAL production chain recovered from /.local/share/tunarr/logs/tunarr.log:
#   before: [0:0]hwdownload,format=nv12,setpts=PTS-STARTPTS,fps=24[v];[0:1]aresample=...
#   after:  [0:0]hwdownload,format=nv12,setpts=PTS-STARTPTS[v];[0:1]aresample=...
# Separator and label counts preserved; audio and upload chains untouched. Safe because
# `fps=24` sits AFTER hwdownload,format=nv12 - it runs in software, and `[v]` feeds only
# `format=nv12,hwupload,vpp_qsv`, a format conversion that does not depend on frame rate.
# Nothing downstream consumes the filter.
fps_pend=0
set -- "$@" "///WRAPEND2///"
while [ "$1" != "///WRAPEND2///" ]; do
  a="$1"; shift
  if [ "$fps_pend" = 1 ]; then
    fps_pend=0
    case "$a" in
      *[],\;[]fps=[0-9]*|fps=[0-9]*)
        # NOTE the bracket expression is  []; []  ==  ']' ';' '['  - ']' MUST come first
        # inside a BRE class. An earlier draft used [;[] and silently failed the
        # `[0:0]fps=24,...` chain-start case, because the character before `fps=` there is
        # ']' (the end of the pad label), not '['. Caught by unit tests; it would otherwise
        # have shipped as a PARTIAL fix - stripping mid-chain, missing chain-start - which
        # is worse than none, because the inconsistency reads as a different bug.
        a=$(printf '%s' "$a" | sed \
          -e 's/,fps=[0-9][0-9.]*//g' \
          -e 's/\([];[]\)fps=[0-9][0-9.]*,/\1/g' \
          -e 's/^fps=[0-9][0-9.]*,//' \
          -e 's/\([];[]\)fps=[0-9][0-9.]*\([];[]\)/\1\2/g')
        ;;
    esac
    set -- "$@" "-filter_complex" "$a"; continue
  fi
  if [ "$a" = "-filter_complex" ]; then fps_pend=1; continue; fi
  set -- "$@" "$a"
done
shift  # drop the ///WRAPEND2/// sentinel

# pass 2c: rewrite the OpenCL HDR tonemap chain to the native VAAPI filter (tunarr#1951).
#
# WHY: on VAAPI, Tunarr's pipeline ALWAYS builds an OpenCL tonemap and offers no way to
# select `tonemap_vaapi`, though the binary contains both filters (TonemapOpenclFilter,
# TonemapVaapiFilter). The generated chain round-trips every frame VAAPI -> OpenCL ->
# VAAPI:
#     hwmap=derive_device=opencl,tonemap_opencl=...,hwmap=derive_device=vaapi:reverse=1
# The two hwmap device derivations, not the tonemap maths, are the cost.
#
# MEASURED 2026-09-16 on this node, same HDR10 source (3840x2160 yuv420p10le smpte2084
# -> 1080p SDR h264), back to back:
#     opencl (as generated) : cpu 60.32s  wall 81.43s = 0.74x realtime  100.5% of a core
#     tonemap_vaapi         : cpu  5.98s  wall 37.34s = 1.61x realtime   10.0% of a core
# 2.18x faster, ~10x less CPU. 0.74x is BELOW REALTIME, i.e. a 4K HDR channel can never
# sustain itself: every client drains its buffer and rebuffers forever. Observed live on
# ch18 as 0.80x segment production, confirmed independently by the panel at 0.797x.
#
# Upstream issue tunarr#1951 reports the same root cause with the opposite symptom: on an
# iGPU whose OpenCL runtime lacks VA interop the chain FAILS outright ("Function not
# implemented") and shows the error slate. Ours succeeds and merely runs under realtime,
# which is harder to notice. That issue documents this exact rewrite as its workaround.
#
# FAIL-SAFE: rewrites ONLY when the full opencl->tonemap->vaapi triple is present; any
# other filter graph passes through byte-for-byte. If the sed produces nothing, the
# original value is kept.
tm_pend=0
set -- "$@" "///WRAPEND2C///"
while [ "$1" != "///WRAPEND2C///" ]; do
  a="$1"; shift
  if [ "$tm_pend" = 1 ]; then
    tm_pend=0
    case "$a" in
      *hwmap=derive_device=opencl,tonemap_opencl=*hwmap=derive_device=vaapi:reverse=1*)
        _tm=$(printf '%s' "$a" | sed \
          -e 's/hwmap=derive_device=opencl,tonemap_opencl=[^,]*,hwmap=derive_device=vaapi:reverse=1/tonemap_vaapi=format=nv12:t=bt709:m=bt709:p=bt709/g')
        [ -n "$_tm" ] && a="$_tm"
        ;;
    esac
    set -- "$@" "-filter_complex" "$a"; continue
  fi
  if [ "$a" = "-filter_complex" ]; then tm_pend=1; continue; fi
  set -- "$@" "$a"
done
shift  # drop the ///WRAPEND2C/// sentinel

# pass 2c2: pin filter hardware to the VAAPI device when an OpenCL device is also
# initialised (SQ-176, 2026-09-30).
#
# WHY: for HDR sources Tunarr 1.3.15 initialises two devices (`vaapi=va:...`, then
# `opencl=ocl@va`) and never passes -filter_hw_device. ffmpeg then gives filters the
# LAST initialised device, OpenCL. Any `hwupload` in the graph therefore produces OpenCL
# frames that scale_vaapi/overlay_vaapi/h264_vaapi reject:
#   "Impossible to convert between the formats supported by the filter 'Parsed_hwupload_N'
#    and the filter 'auto_scale_N'" -> Error reinitializing filters -> error slate (218).
# Only two HDR graph shapes contain an hwupload: non-16:9 sources (CPU letterbox pad, e.g.
# The Sparks Brothers 1.85:1) and image-subtitle burn-in (e.g. 2001). Loki, 29 days:
# 13/13 of those failed; 29/29 all-GPU tonemap graphs ran. Pass 2c removes the OpenCL
# tonemap but not the device, so it does not help here.
# Upstream fixed exactly this in tunarr 5213e56658 (v2026.9.0+) by adding
# -filter_hw_device for vaapi; this pass carries that fix locally.
#
# FAIL-SAFE: acts only when BOTH a named vaapi device and an opencl device are
# initialised and no -filter_hw_device is already present. Otherwise args pass through.
# PLACEMENT MATTERS: ffmpeg resolves -filter_hw_device by name AS IT PARSES, so it must
# come AFTER the `-init_hw_device vaapi=<name>:...` that creates the device. Placed before
# it, ffmpeg aborts with "Invalid filter device" (verified with ffmpeg 9.0.2, videotoolbox
# stand-in), which would kill every HDR stream. Inserted right after that pair.
_fhd_va=""; _fhd_ocl=0; _fhd_have=0; _fhd_prev=""
for a in "$@"; do
  if [ "$_fhd_prev" = "-init_hw_device" ]; then
    case "$a" in
      vaapi=*:*) [ -z "$_fhd_va" ] && { _fhd_va="${a#vaapi=}"; _fhd_va="${_fhd_va%%:*}"; } ;;
      opencl=*) _fhd_ocl=1 ;;
    esac
  fi
  [ "$a" = "-filter_hw_device" ] && _fhd_have=1
  _fhd_prev="$a"
done
fhd="pass"
if [ "$_fhd_ocl" = 1 ] && [ -n "$_fhd_va" ] && [ "$_fhd_have" = 0 ]; then
  _fhd_prev=""; _fhd_done=0
  set -- "$@" "///WRAPEND2C2///"
  while [ "$1" != "///WRAPEND2C2///" ]; do
    a="$1"; shift
    set -- "$@" "$a"
    if [ "$_fhd_done" = 0 ] && [ "$_fhd_prev" = "-init_hw_device" ]; then
      case "$a" in
        vaapi=*) set -- "$@" "-filter_hw_device" "$_fhd_va"; _fhd_done=1 ;;
      esac
    fi
    _fhd_prev="$a"
  done
  shift  # drop the ///WRAPEND2C2/// sentinel
  fhd="$_fhd_va"
fi

# pass 2d: channel watermark on the GPU, with a periodic fade (2026-09-29).
#
# WHY: on VAAPI, Tunarr draws the channel watermark in SOFTWARE. Every decoded frame is
# pulled off the GPU (hwdownload), a ~192px logo is blended onto the full 1080p frame on
# ONE thread (-threads 1), and the frame is pushed back (hwupload). The logo is only
# visible for the first 15s, but the round trip runs on every frame of the airing. On
# the contended node that is what dropped ch5 to 0.60x live (Apple TV stalls).
#
# The watermark is a REQUIRED feature (owner, 2026-09-29), so it is moved, not removed:
#   * video stays on the GPU: `hwdownload,format=nv12` -> `scale_vaapi=format=nv12`
#     (which also converts p010 -> nv12 on the GPU, so 10-bit sources work; the software
#     path cannot take a p010 frame at all);
#   * the logo is prepared on the CPU (tiny: scale + opacity), uploaded, and blended
#     with `overlay_vaapi`;
#   * the display cycle is what the owner asked for: fade in over 1s, hold for the
#     channel's watermark duration (15s), fade out over 1s, repeating every 2 minutes
#     from the start of each programme.
#
# WHY NOT TUNARR'S OWN `fadeConfig`: tested on ch5. It alternates on/off every period
# (2 min on, 2 min off), and with a duration set it still gates the overlay with
# enable=between(t,0,duration), so the logo fades in, is hard-cut at 15s and never
# returns. It also keeps the same software round trip.
# WHY NOT `geq` for the envelope: a per-pixel expression on every logo frame measured
# 0.73x vs 2.13x. The `fade` + `enable` chain below costs nothing measurable.
#
# THE LOGO IS PREPARED ONCE. Decode, scale and opacity run on the single image, then
# `loop=loop=-1:size=1` repeats that finished frame (setpts=N/24/TB gives it a 24fps
# clock for the fades). The first draft used `-loop 1 -framerate 24` on the input,
# which RE-DECODES and re-scales the image every frame, and that alone cost more CPU
# than Tunarr's whole software round trip.
#
# MEASURED on ch5's REAL production argv (subtitles, join seek and all), CPU seconds
# per 28s of video, 2 runs each:
#   no watermark at all (floor)                  7.2s  (26% of a core)
#   Tunarr's software chain (today)             13.9s  (50%)
#   GPU overlay, logo re-decoded 24fps (draft)  15.0s  (54%)   <- rejected
#   GPU overlay, logo prepared once (this)       8.0s  (28%)
# so the watermark's own cost drops from ~24% of a core to ~3%, and a watermarked
# stream from 50% to 28%. (Wall-clock speed on the full argv is capped elsewhere,
# at ~1.5x by the realtime subtitle input, so CPU is the honest measure for a
# contended node.) Frame-index check against a no-logo render: fade-in 0-1s, full
# from 1s, fading at 15.5/16.25/16.5s, gone from 17s; position, size and opacity
# match Tunarr's chain. The envelope repeats every 120s (sampled to 250s).
#
# SCOPE / FAIL-SAFE: rewrites ONLY Tunarr's exact VAAPI watermark graph (exactly one
# each of the video, logo, overlay and upload pieces below), only with -hwaccel_output_format
# vaapi and -vaapi_device present, only for WMGPU_CHANNELS, and only when the x/y
# expressions contain nothing but W H w h digits and + - * / ( ) . characters. Anything
# else passes through byte-for-byte (wm=pass:<reason> in the trace log).
#   Tunarr (1.3.15) emits:
#     [0:0]<vaapi filters>hwdownload,format=nv12[v]
#     [1:0]scale=192:-2,format=yuva420p|...|ya8,colorchannelmixer=aa=0.81,format=yuva420p[wm]
#     [v][wm]overlay=x=W-w-0:y=H-h-0:format=0:enable='between(t,0,15)'[vwm]
#     [vwm]format=nv12,hwupload[vpf]
#   rewritten to:
#     [0:0]<vaapi filters>scale_vaapi=format=nv12[v]
#     [1:0]scale=192:-2,format=bgra,colorchannelmixer=aa=0.81,<fade chain>,hwupload[wm]
#     [v][wm]overlay_vaapi=x=main_w-overlay_w-0:y=main_h-overlay_h-0:shortest=1[vpf]
#   where the logo is `...,loop=loop=-1:size=1,setpts=N/24/TB,<fades>,hwupload[wm]`:
#   an endless stream, so shortest=1 ends the overlay with the VIDEO. Without the
#   loop, a single-frame logo would be the shortest input and end the output at once.
# ROLLOUT: WMGPU_CHANNELS lists the channel ids to rewrite ("all" = every channel).
# 2026-09-29: ch5 only (live-verified: wm=gpu, overlay_vaapi running), then "all" on the
# owner's instruction. Only watermark-enabled channels (ch1-8) carry the graph at all.
WMGPU_CHANNELS="all"
WM_PERIOD=120; WM_FADE=1
wm=pass:nowm
_p=""; _hb=""; _fc=""; _dur=""; _hwof=""; _vdev=""; _io=0; _wmord=0
for a in "$@"; do
  case "$_p" in
    -hls_base_url) _hb="$a" ;;
    -filter_complex) _fc="$a" ;;
    -t) case "$a" in *ms) _dur="$a" ;; esac ;;
    -hwaccel_output_format) _hwof="$a" ;;
    -vaapi_device) _vdev="$a" ;;
  esac
  if [ "$_p" = "-i" ]; then
    _io=$((_io + 1))
    case "$a" in */cache/images/*) [ "$_wmord" = 0 ] && _wmord=$_io ;; esac
  fi
  _p="$a"
done
case "$_fc" in *'[v][wm]overlay='*) wm=pass:shape ;; esac
_chan=""; case "$_hb" in /stream/channels/*/hls/) _chan="${_hb#/stream/channels/}"; _chan="${_chan%/hls/}" ;; esac
if [ "$wm" = pass:shape ]; then
  if [ "$_hwof" != vaapi ] || [ -z "$_vdev" ] || [ "$_wmord" = 0 ]; then
    wm=pass:nohw
  elif [ "$WMGPU_CHANNELS" != all ] && { [ -z "$_chan" ] || ! case " $WMGPU_CHANNELS " in *" $_chan "*) true ;; *) false ;; esac; }; then
    wm=pass:notlisted
  else
    # classify the graph's pieces; each of the four must occur exactly once
    _nv=0; _nl=0; _no=0; _nu=0; _new=""
    _oldifs=$IFS; IFS=';'; set -f
    for _pc in $_fc; do
      IFS=$_oldifs
      case "$_pc" in
        \[*:*\]*hwdownload,format=nv12\[v\])
          _pre="${_pc%hwdownload,format=nv12\[v\]}"          # "[0:0]" + any vaapi filters
          _flt="${_pre#\[*\]}"; _ok=1
          if [ -n "$_flt" ]; then
            _rest="$_flt"
            while [ -n "$_rest" ]; do
              _f="${_rest%%,*}"; _rest="${_rest#"$_f"}"; _rest="${_rest#,}"
              case "${_f%%=*}" in *_vaapi) : ;; *) _ok=0 ;; esac
            done
          fi
          [ "$_ok" = 1 ] || { _nv=9; }
          _pc="${_pre}scale_vaapi=format=nv12[v]"; _nv=$((_nv + 1)) ;;
        \[*:0\]scale=*,format=yuva420p\|yuva444p\|yuva422p\|rgba\|abgr\|bgra\|gbrap\|ya8,colorchannelmixer=aa=*,format=yuva420p\[wm\])
          _lin="${_pc%%scale=*}"
          _scl="${_pc#"$_lin"scale=}"; _scl="${_scl%%,*}"
          _aa="${_pc#*colorchannelmixer=aa=}"; _aa="${_aa%%,*}"
          case "$_scl" in *[!0-9:-]*|'') _nl=9 ;; esac
          case "$_aa" in *[!0-9.]*|'') _nl=9 ;; esac
          # dropped here; re-emitted (rewritten) at the overlay's position below
          _lpc="$_lin"; _nl=$((_nl + 1)); _pc="" ;;
        '[v][wm]overlay=x='*':y='*':format=0'*'[vwm]')
          _ov="${_pc#\[v\]\[wm\]overlay=x=}"
          _ox="${_ov%%:y=*}"; _ov="${_ov#*:y=}"
          _oy="${_ov%%:format=0*}"; _ov="${_ov#*:format=0}"
          case "$_ov" in
            "[vwm]") _hold="" ;;
            ":enable='between(t,0,"*")'[vwm]") _hold="${_ov#:enable=\'between(t,0,}"; _hold="${_hold%)\'\[vwm\]}" ;;
            *) _no=9 ;;
          esac
          # The class lives in a variable: a literal `)` inside a case pattern ends the
          # pattern in dash ("Syntax error: ( unexpected"), even inside [...].
          _xybad='*[!WHwh0-9+*/().-]*'
          case "$_ox$_oy" in $_xybad|'') _no=9 ;; esac
          case "$_hold" in *[!0-9]*) _no=9 ;; esac
          _no=$((_no + 1)); _pc="///OVERLAY///" ;;
        '[vwm]format=nv12,hwupload[vpf]')
          _nu=$((_nu + 1)); _pc="" ;;
      esac
      [ -n "$_pc" ] && _new="${_new}${_new:+;}${_pc}"
      IFS=';'
    done
    IFS=$_oldifs; set +f
    if [ "$_nv$_nl$_no$_nu" != 1111 ]; then
      wm=pass:pieces=$_nv$_nl$_no$_nu
    else
      # fade chain: one fade-in and one fade-out per period, enough periods for the airing
      _fch=""
      if [ -n "$_hold" ]; then
        _secs=10800
        case "${_dur%ms}" in ''|*[!0-9]*) : ;; *) _secs=$(( ${_dur%ms} / 1000 )) ;; esac
        _k=0; _n=$(( _secs / WM_PERIOD + 2 ))
        while [ "$_k" -lt "$_n" ]; do
          _s=$(( _k * WM_PERIOD )); _o=$(( _s + WM_FADE + _hold ))
          _fch="$_fch,fade=in:st=$_s:d=$WM_FADE:alpha=1:enable='between(t,$_s,$(( _s + WM_FADE )))'"
          _fch="$_fch,fade=out:st=$_o:d=$WM_FADE:alpha=1:enable='between(t,$_o,$(( _s + WM_PERIOD )))'"
          _k=$(( _k + 1 ))
        done
      fi
      _gx=$(printf '%s' "$_ox" | sed -e 's/w/overlay_w/g' -e 's/h/overlay_h/g' -e 's/W/main_w/g' -e 's/H/main_h/g')
      _gy=$(printf '%s' "$_oy" | sed -e 's/w/overlay_w/g' -e 's/h/overlay_h/g' -e 's/W/main_w/g' -e 's/H/main_h/g')
      _lpc="${_lpc}scale=${_scl},format=bgra,colorchannelmixer=aa=${_aa},loop=loop=-1:size=1,setpts=N/24/TB${_fch},hwupload[wm]"
      _ovn="[v][wm]overlay_vaapi=x=${_gx}:y=${_gy}:shortest=1[vpf]"
      _new=$(printf '%s' "$_new" | sed "s|///OVERLAY///|$_lpc;$_ovn|")
      if [ -n "$_new" ] && [ -n "$_gx" ] && [ -n "$_gy" ]; then
        wm=gpu:hold=${_hold:-always}
        _p=""
        set -- "$@" "///WRAPEND2D///"
        while [ "$1" != "///WRAPEND2D///" ]; do
          a="$1"; shift
          if [ "$_p" = "-filter_complex" ]; then a="$_new"; fi
          set -- "$@" "$a"; _p="$a"
        done
        shift  # drop the ///WRAPEND2D/// sentinel
      else
        wm=pass:build
      fi
    fi
  fi
fi

# pass 3: seed a header-only LIVE subtitle playlist BEFORE exec (SQ-70).
# Tunarr's readiness gate (waitForStreamReady) polls for every file from
# getAdditionalRequiredFiles() — which includes the subtitle playlist (subs.m3u8) —
# with {retries:15, minTimeout:1e3} ≈ 16s, then SIGKILLs the transcode. But ffmpeg's
# `segment` muxer is packet-driven, not time-driven (SQ-69: no muxer flag makes it
# emit without packets), so with a sparse .srt the playlist only appears when the
# first CUE is reached. 85.5% of join points on the measured live program have no cue
# inside that 16s window → SIGKILL → "No master playlist found" → 404 → resume: the
# ~18s restart loop, and the channel-10 cold-start 500s. Seeding a valid header up
# front satisfies the existence check immediately; ffmpeg's segment muxer rewrites
# the whole file itself when the first real segment lands.
#
# Rules:
#   * the path comes ONLY from the existing `-segment_list <path>` token in argv —
#     it is per-session, never hardcoded. No token → structural no-op (A/V-only
#     tunes must pass through untouched).
#   * LIVE header only, NO #EXT-X-ENDLIST — an endlist tells the client the track is
#     complete and terminates it.
#   * NEVER truncate a playlist that already has content (a quick restart may
#     inherit real segments): non-empty file → leave untouched.
#   * best-effort and unconditionally non-fatal: a failed seed must never break the
#     tune it exists to protect.
seglist=""; _sl_expect=0
for a in "$@"; do
  if [ "$_sl_expect" = 1 ]; then
    _sl_expect=0
    [ -n "$seglist" ] || seglist="$a"
  fi
  [ "$a" = "-segment_list" ] && _sl_expect=1
done
seed=nosub
if [ -n "$seglist" ]; then
  if [ -s "$seglist" ]; then
    seed=kept
  else
    mkdir -p "$(dirname "$seglist")" 2>/dev/null || true
    printf '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n' \
      > "$seglist" 2>/dev/null || true
    if [ -s "$seglist" ]; then seed=yes; else seed=fail; fi
  fi
fi

# pass 4: a session's FIRST transcode must not append to a dead session's playlist (SQ-167).
# Symptom: every served segment 404s while ffmpeg runs at 1.0x. The on-disk stream.m3u8 lists
# thousands of entries from data000000 while only the newest ~100 files exist, and Tunarr's
# served window (anchored at segment 0 until a client requests one) lists only deleted names.
#
# Mechanism, from the 1.3.15 bundle and its logs. HlsSession.initDirectories() already
# rm -rf's the stream dir when a session starts. But the torn-down session's ffmpeg is
# SIGKILLed ~15-17s after "Stopping stream session", and until then it keeps rewriting its
# whole in-memory playlist into the recreated dir. The new session's first ffmpeg starts ~2s
# after the cleanup. With append_list it parses that resurrected list and continues its
# numbering, and it collides with the old writer's names while both run. ch12 2026-09-23:
# stop 18:10:09.9, cleanup 18:10:10.2, new ffmpeg 18:10:12, old one killed 18:10:26.9.
# So deleting files cannot fix this: Tunarr already deletes them, and the old writer re-creates
# them. The fix is that the first transcode does not READ an existing playlist at all.
#
# Only the first transcode is touched. Tunarr's HlsOutputFormat adds discont_start (and
# -mpegts_flags +initial_discontinuity) whenever isFirstTranscode is false. HlsSession sets
# that flag true for its first transcode only and false after it, so every programme-boundary
# relaunch carries discont_start and keeps append_list for in-session continuity. Without
# append_list the first transcode starts a fresh playlist at data000000 and ignores the corpse.
# The old writer's segments are numbered far above that, so the two cannot collide.
#
# Only the `hls` session type (base URL .../hls/). hls_direct_v2 always passes ptsOffset 0, so
# its mid-session offline/error fillers would also look like a first transcode. hls_concat
# never uses append_list. Anything else passes through byte-for-byte.
hlsnew=n/a; _hb=""; _h_prev=""
set -- "$@" "///WRAPEND4///"
while [ "$1" != "///WRAPEND4///" ]; do
  a="$1"
  [ "$_h_prev" = "-hls_base_url" ] && _hb="$a"
  if [ "$_h_prev" = "-hls_flags" ]; then
    case "$_hb" in
      */hls/)
        case "+$a+" in
          *+discont_start+*) hlsnew=no ;;
          *+append_list+*)
            a="+$a+"; a="${a%%+append_list+*}+${a#*+append_list+}"; a="${a#+}"; a="${a%+}"
            hlsnew=yes ;;
        esac ;;
    esac
  fi
  set -- "$@" "$a"
  _h_prev="$1"; shift
done
shift  # drop the ///WRAPEND4/// sentinel

# Decision trace. Added 2026-08-04 after the subtitle-timeline fix measured as having
# NO effect in production while every offline check passed: emission verified against
# the real captured argv (119/119 tokens in order, 8 injected at the correct
# positions), ffmpeg honouring those same args in a two-output reproduction, and
# `ffmpegExecutablePath` confirmed pointing here. Emission being right while
# production is unchanged leaves exactly one untested link — whether this wrapper is
# invoked at all for streaming transcodes — and that cannot be read after the fact:
# `exec` replaces the process, so argv0 becomes /usr/bin/ffmpeg either way and a
# finished session leaves no trace.
#
# One line per invocation, so the next session answers it definitively instead of
# being re-litigated from playlists. Records the DECISION, not just the fact of
# running: a line with inject=no and srt=0 means "correctly skipped, no subtitle
# input", which is a different answer from no line at all ("never invoked").
#
# Best-effort and unconditionally non-fatal: `|| true` on every write, and a size cap
# so it can never fill the PVC and take Tunarr down. A diagnostic that can break the
# thing it observes is worse than no diagnostic.
_log=/var/logs/ffmpeg-wrap.log
if [ -w "$(dirname "$_log")" ] 2>/dev/null; then
  # cap at ~256KB, keep the tail
  if [ -f "$_log" ] && [ "$(wc -c < "$_log" 2>/dev/null || echo 0)" -gt 262144 ] 2>/dev/null; then
    tail -c 131072 "$_log" > "$_log.tmp" 2>/dev/null && mv -f "$_log.tmp" "$_log" 2>/dev/null || true
  fi
  {
    printf '%s srt_ord=%s preval=%s sub_off=%s burst=%s inject=%s mode=%s seed=%s hlsnew=%s wm=%s fhd=%s args=%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo -)" \
      "${srt_ord:-0}" "${preval:-none}" "${sub_off:-none}" "${sub_burst:-none}" \
      "$([ -n "$sub_off" ] && echo yes || echo no)" \
      "$([ -n "$sub_trim" ] && echo pretrim || { [ -n "$sub_off" ] && echo seek || echo none; })" \
      "${seed:-nosub}" "${hlsnew:-n/a}" "${wm:-n/a}" "${fhd:-n/a}" "$#"
  } >> "$_log" 2>/dev/null || true
fi

exec /usr/bin/ffmpeg "$@"
