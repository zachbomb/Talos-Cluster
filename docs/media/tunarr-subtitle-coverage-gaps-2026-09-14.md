# Tunarr subtitle coverage gaps

**Status:** investigation, no code or config changed.
**Date:** 2026-09-14
**Sources:** appliance session (client-side, Pi/PMP + ambient mpv) and this session
(server-side, Tunarr pod + ffmpeg invocation log).
**Related:** `docs/dr/longhorn-single-disk-io-contention.md`,
`docs/media/unseen-ambient-playback-design.md`.

## Why this exists

Three independent subtitle problems were being conflated. They have different
causes, different owners, and only one of them is a Tunarr defect. Filed so the
next person does not re-derive the split.

## The structural constraint (this is the root of most of it)

Tunarr's transcode is ONE ffmpeg with TWO outputs on DIFFERENT muxers:

    output 1 (video+audio)  -f hls      -hls_flags program_date_time+append_list+...
    output 2 (subtitles)    -f segment  -segment_format webvtt -segment_list subs.m3u8

`program_date_time` is an HLS-muxer flag; output 2 is the SEGMENT muxer, which has
no equivalent. Exactly ONE subtitle path reaches a client: master advertises
`#EXT-X-MEDIA:TYPE=SUBTITLES` -> a WebVTT rendition. Anything that cannot become
WebVTT — PGS/bitmap, discarded embedded tracks, external sidecars — is
structurally invisible. Changing that is the SQ-30 restructure, which is ON HOLD.
See memory `tunarr-subtitle-rendition-has-no-time-anchor` for why, and do not
start it on the strength of "subs are out of sync" alone.

## Finding A — subtitle output is PER-PROGRAMME and often absent (CONFIRMED, server side)

Tunarr spawns a **new ffmpeg per programme**, not per session:

    23:00:34  channel-11-transcode exited (code=0, expected?=true)
    23:00:38  Creating ffmpeg transcode pipeline (VaapiPipelineBuilder)

Measured 2026-09-11 across all 36 ffmpeg invocations on one channel over 3 h,
checking each for a subtitle output (`segment_format webvtt` / `segment_list`):

    with subtitle output:  30
    WITHOUT:                6      (~17% of programmes emit NO .vtt at all)

**Consequences**
* The video/subtitle divergence is **CUMULATIVE**, not a fixed join offset — it
  grows by the full duration of every subtitle-less programme. Measured: video
  seq 439 vs subs seq 206 (~1000 s apart) mid-session.
* **Never derive timing from subtitle sequence numbers.** They stall during
  subtitle-less programmes and are not a proxy for elapsed stream time.
* A client must RECOMPUTE any offset per programme boundary from absolute time.
  Computing once at join drifts by ~17% of elapsed time — a bug that passes its
  own test on whatever programme you happen to test.
* An EMPTY rendition across a boundary is NORMAL. Roughly one programme in six
  has nothing to render; a client must not treat that as a dropped track, a sync
  failure, or a reason to re-anchor.

The appliance independently observed the client-visible half: the subtitle
playlist ENDLISTs at a boundary and the relaunched generation RESTARTS
MEDIA-SEQUENCE AT 0 while video keeps climbing; when the next programme has no
text subtitles, no successor `subs.m3u8` is written at all and a connected client
waits forever. That is the same mechanism seen from the other end.

## Finding B — a source WITH an embedded SRT produced no rendition (UNVERIFIED here)

Reported by the appliance session, channel 27 "Frederick Wiseman", programme
"Menus-Plaisirs — Les Troisgros":

    /api/programs/<uuid>/stream_details -> details.streamDetails.subtitleDetails
        = [{codec: "srt", type: "embedded", languageCodeISO6392: "eng"}]
    /stream/channels/<uuid>.m3u8   -> only #EXT-X-MEDIA:TYPE=AUDIO, no TYPE=SUBTITLES
    /stream/channels/<uuid>/hls/subs.m3u8 -> 500 ENOENT

**This is the one worth chasing**, because it is materially different from
Finding A: the track EXISTS in the source and the pipeline still emitted nothing.
If true generally, some of the "6 without subtitle output" above are DROPPED
tracks rather than genuinely subtitle-less programmes.

**NOT VERIFIED SERVER-SIDE.** Confirming it requires correlating a live ffmpeg
invocation against its input file's stream list, and there were zero invocations
in the preceding 6 h because no channel was streaming. It costs a live transcode
against a 4.9 GB `/.transcode` volume (see Capacity below).

JSON path trap, from the appliance: the correct path is
`details.streamDetails.subtitleDetails`. Looking for a `subtitleStreams` key
returns a false "no subtitles anywhere" result.

## Finding C — coverage census (appliance session, metadata endpoints only)

    TEXT (srt) present:  ch9 (eng+fra), ch10, ch15, ch18, ch20 (eng/ces/ita),
                         ch27, ch29, ch30, ch31, ch32, ch33, ch36
    BITMAP/PGS only:     ch11, ch12, ch16, ch17, ch21, ch34; upcoming ch29, ch36
    Notable upcoming:    ch28 "Jeanne Dielman" 17 text + 1 bitmap; ch13 25 text

Series channels (2-8, 14, 22-26) returned "program-not-in-lineup" — that is the
appliance's title-matcher failing, NOT a Tunarr data gap. Unresolved, theirs.

Bitmap/PGS-only rows cannot reach a client at all today (no WebVTT conversion
path). Historically ~42% of programmes.

## Capacity note — relevant before any live-stream testing

`/.transcode` is a **4.9 GB PVC, measured 41% full with three concurrent
streams**. Per-stream steady state measured at up to **1.29 GB** (132 .ts at
~9.9 MB). Four concurrent streams overflow it. Subtitle segments are NOT the
problem — 315 .vtt totalled **0.03 MB** against 1303 MB of .ts in the same
directory; the 284-vs-71 file-count ratio inverts completely by bytes.

## What is NOT a Tunarr problem

* **Burn-in.** Tunarr has NO burn-in setting. The complete per-channel subtitle
  config is five fields (`langugeCode` [sic], `priority`, `allowImageBased`,
  `allowExternal`, `filter`). Burned-in text is source-baked into that
  programme's master and cannot be disabled or re-justified downstream.
* **The original "subs out of sync" symptom.** That was a client bug, fixed
  2026-09-03.

## Open decisions (owner)

1. **Does the ambient panel really need ALL subtitle types** (bitmap/PGS,
   embedded, sidecars)? The appliance reports this as a stated requirement. It is
   materially larger than what Tunarr can do and is the trigger that would take
   SQ-30 off hold.
2. **Verify Finding B**, at the cost of a live transcode.
3. **Resize `/.transcode`** before running more concurrent streams.
