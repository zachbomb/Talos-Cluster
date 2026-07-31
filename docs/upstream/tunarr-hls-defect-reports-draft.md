# DRAFT — Upstream Tunarr defect reports (do not post without review)

Evidence gathered 2026-07-29/30 on Tunarr v1.3.10 (ghcr digest a195c9d8), single-node
K8s, ~26 channels, PMP/mpv client (lavf 61.7.103) + in-pod ffprobe/curl repro.
Source refs are against the v1.3.10 tag. Prepared by the cluster session; see
`reference_tunarr_livetv_audio_subtitle_constraints` (memory) and SQ-185 (board)
for the full investigation trail.

---

## Report 1+2 (MERGED) — `trimPlaylist` and `deleteOldSegments` share one anchor with a 10-segment offset, so client activity deterministically makes the served playlist advertise deleted segments

**Severity: this is the limiting factor on live-TV session lifetime.** It was previously
filed as two separate defects; measurement shows they are one defect with two faces, and
splitting them invites fixing each in a way that leaves the other in place.

**Where:** `server/src/stream/hls/HlsSession.ts`

- `trimPlaylist()` serves a window anchored at `minSegmentRequested`, keeping
  `segmentsToKeepBefore: 10` — i.e. it deliberately advertises up to **10 segments
  BEHIND the anchor**.
- `deleteOldSegments()` (30s cadence) deletes segments **below the trim sequence** —
  i.e. below that same anchor.

The two use the same anchor but disagree by 10 segments about what must exist. The
serving window looks back further than the janitor is willing to keep, so **any client
that advances the anchor by fetching segments guarantees the playlist will advertise
segments that were just deleted.** The harder a client works, the faster it breaks
itself. Output flags `-hls_list_size 0` + `append_list` + `omit_endlist` mean the
on-disk playlist never forgets an entry, so nothing else corrects this.

### Measurement A - NO consumer (playlist polled, no segments fetched)

**Caption corrected 2026-07-30.** This exhibit was originally presented as showing the
served window "frozen". That reading was wrong and is retained, corrected, because the
correction is the point: the window is NOT statically frozen - it is **pinned to the
anchor**, and with no consumer fetching segments the anchor never leaves 0. An earlier
probe that only polled playlists therefore produced a misleading picture of a permanent
freeze. With a consumer the window advances normally (see Measurement B).

Sampled from session start. `disk_first` = oldest segment surviving on disk;
`advertised` = first entry in the SERVED media playlist; `->` = its HTTP status.

```
age=0    disk_first=data000008  oldest_age=62s  SEQ=11  advertised=data000011 -> 200
age=21   disk_first=data000008  oldest_age=82s  SEQ=1   advertised=data000001 -> 404   <-- FAILURE
age=41   disk_first=data000000  oldest_age=7s   SEQ=0   advertised=data000000 -> 200   (session restarted)
age=61   disk_first=data000000  oldest_age=27s  SEQ=0   advertised=data000000 -> 200
age=82   disk_first=data000000  oldest_age=48s  SEQ=0   advertised=data000000 -> 200
age=102  disk_first=data000000  oldest_age=68s  SEQ=0   advertised=data000000 -> 200
age=122  disk_first=data000000  oldest_age=88s  SEQ=0   advertised=data000000 -> 200
age=143  disk_first=data000000  oldest_age=108s SEQ=0   advertised=data000000 -> 200
```

Two controls make the mechanism unambiguous:

1. **With a real client fetching segments** (rows at age=0/21): the anchor had advanced
   to 11, `data000000..007` were already deleted, and the served playlist still
   advertised `data000001` — **404**. Note the deletion happened when the session was
   only ~62-98s old, so it was *Tunarr's own janitor*, not any external cleanup.
2. **With NO client fetching segments** (rows from age=41 on, playlist-only polling):
   `minSegmentRequested` never advanced, the janitor therefore never deleted, and
   `data000000` survived monotonically to **108s and beyond, always 200**.

The defect is thus **activity-gated**: it cannot be reproduced by polling the playlist
alone, which is likely why it has evaded notice. It requires a client that actually
consumes segments — i.e. a real viewer.

### The anchor is client-settable, and `segmentsToKeepBefore` is measurable from outside

A **single, never-repeated** GET of one segment moves the served window. Controlled run
on one session, no other consumer:

```
no segment fetches at all      -> SEQ=0,  window data000000..019, disk grew 16->31
one-shot GET data000000.ts     -> SEQ=0,  window UNCHANGED for 60s+, disk grew to 46
one-shot GET data000019.ts     -> SEQ=9,  window data000009..028
```

`19 - 9 = 10` recovers `segmentsToKeepBefore` exactly, from the outside.

Two consequences:

1. **Any consumer that probes the HEAD pins the served window to the head.** The window
   then sits arbitrarily far behind the live edge (measured: window at data000000..019
   while the encoder was writing data000046, i.e. ~100s stale) and a player joining that
   window with `live_start_index=-3` is handed content ~100s old while believing it is
   live. A readiness/validation probe that fetches `segments.first()` does exactly this.
2. **It is not a minimum across concurrent consumers.** A later high fetch moves the
   anchor back up despite an earlier low fetch. The anchor follows the most recent
   request, so a probe that RE-FIRES (retry, re-tune, readiness re-check) drops the
   anchor back down after a player had advanced it - producing a backward
   `EXT-X-MEDIA-SEQUENCE` on demand.

This makes the defect trivially reproducible without a media player: fetch a low
segment, then observe the served window.


### Measurement B - WITH a consumer fetching segments in order

```
t=12..72s  SEQ=0  consuming data000000..011
t=84s      SEQ=1  consuming data000012,013
t=96s      SEQ=3
t=108s     SEQ=5
t=120s     SEQ=7   (disk 42->39: segments being deleted below the anchor)
```

The window tracks the consumer, lagging by ~10 - i.e. `segmentsToKeepBefore`. Sessions
therefore do NOT stall after 20 segments; they advance with the player. The failure is
not a frozen window, it is the 10-segment offset between what the window advertises and
what the janitor is willing to keep.

### ***MOST SEVERE***: all renditions of a session share ONE `minSegmentRequested`, and even a FAILING request moves it

A request for a **subtitle** segment repositions the **video** playlist's window. The two
renditions of a single session are not tracked independently.

Controlled run, single session, no media player. `vtt` files on disk: **0** (the program
had no subtitles at all, so every subtitle request below returned 500):

```
A  GET data000019.ts   -> 200   video EXT-X-MEDIA-SEQUENCE = 9
B  GET sub000000.vtt   -> 500   video EXT-X-MEDIA-SEQUENCE = 0     <- reset to zero
C  (re-raise to 9)
   GET sub999999.vtt   -> 500   video EXT-X-MEDIA-SEQUENCE = 31    <- clamped to live edge - 10
D  GET data0000NN.ts   -> 200   video EXT-X-MEDIA-SEQUENCE = 32
```

Three distinct problems:

1. **Shared anchor across renditions.** A subtitle fetch moves the video window.
2. **The index is parsed from the request PATH**, not from what was actually served.
   `sub999999` clamped to the live edge rather than being rejected.
3. **A request returning HTTP 500 still moves the anchor.** No `.vtt` existed; every
   subtitle request failed; every one repositioned the video window regardless.

**Why this destroys live sessions.** A subtitle rendition legitimately runs ahead of
video (its input is not readrate-throttled, so it bursts until the mux queue blocks —
measured ~3.5x realtime). With video at segment 15 and subtitles at 50, a subtitle fetch
sets the shared anchor to 40 — **ahead of the video playhead**. `deleteOldSegments` then
removes everything below 40, *including segments 15-39 the video player has not reached
yet*. The player's next fetch 404s and the session dies.

It also produces a continuous small oscillation of the served sequence (+-3-7 observed)
with no other trigger: subtitle fetches drag the anchor up, video fetches pull it back
down, forever.

**This defect requires two renditions to express**, which is why it can appear as a
regression introduced by *fixing* subtitles: before a client could open the subtitle
rendition, nothing else was competing for the anchor. The subtitle support did not break
video playback - it revealed this.

**Suggested fix:** track `minSegmentRequested` per rendition (or, better, do not derive
the serving window from client request history at all - serve a live-edge window, per
Report 1). At minimum, a request that does not successfully serve a segment must not
mutate session state, and an out-of-range index must be rejected rather than clamped.

**Reproduction: three curl calls, no media player required.**

### Controlled A/B, single channel, single variable = whether subtitles are consumed

Identical protocol both legs; the ONLY difference is whether the client also fetches
subtitle segments.

**CONTROL (video fetches only), 510s:**
```
EXT-X-MEDIA-SEQUENCE 0 -> 124, strictly monotonic
backward steps: 0        404s: 0        no death
```

**ON LEG (video AND subtitle fetches), same protocol:**
```
t=126  vSEQ=0    sSEQ=40    all 200          subtitles pulling ahead
t=162  vSEQ=44   sSEQ=40    all 200          anchor YANKED to 44 by a subtitle fetch
t=180  vSEQ=34   sSEQ=48    all 200          *** BACKWARD ***
t=198  vSEQ=24   sSEQ=61    vfirst 404       *** BACKWARD ***   first casualty
t=216  vSEQ=14   sSEQ=61    vfirst+vlast 404 *** BACKWARD ***
t=234  vSEQ=4    sSEQ=61    all video 404    *** BACKWARD ***
t=252  vSEQ=0    sSEQ=73    all video 404    *** BACKWARD ***
...
t=486  vSEQ=0    sSEQ=115   all video 404, ALL SUBTITLE FETCHES STILL 200
```
```
backward steps: 5        404s: sustained from t=216 to end (4.5 min)
```

Three points a maintainer can check independently:

1. **The 404s appear exactly ONE SAMPLE AFTER the anchor overshoots** (t=162 overshoot ->
   t=198 first 404). Cause and effect, in order.
2. **The window DESCENDS monotonically (44->34->24->14->4->0) while subtitles CLIMB**
   (40->115). A window that merely lagged would sit still. A descending staircase against
   a climbing counterpart is two consumers writing one variable and pulling opposite
   ways, with the janitor deleting against whichever wrote last.
3. **Video dies while subtitles stay perfectly healthy for 4.5 minutes** in the SAME
   session and SAME directory - which is why this can be mistaken for a stale-directory
   or session-collision problem. It is neither.

Independently reproduced with a real media player (libmpv) on a different channel:
`hls: Media sequence changed unexpectedly: 53 -> 25`, followed by a stall and
auto-retune - i.e. a 28-segment backward jump under authentic sequential playback, not
an artifact of a polling probe.

### Scope note: throttling the subtitle input MITIGATES but does NOT fix this

The subtitle rendition runs ahead because its input is not readrate-throttled
(`-readrate` binds to input 0; the sidecar is a second input). Adding `-readrate` to the
second input collapses the divergence that lets a subtitle fetch push the anchor past
live video, and is worth doing.

**But the shared anchor remains broken.** Any second consumer of the same session - a
client fetching out of order, a second player, a validation probe, a bandwidth-estimator
prefetch - reproduces this with no pacing divergence required at all. The pacing is what
makes it fire reliably today; the shared anchor is what makes it possible. Fix the
anchor.



### Additional observable: served MEDIA-SEQUENCE walks BACKWARD

Across consecutive fetches the served `EXT-X-MEDIA-SEQUENCE` was observed decreasing
(`11 -> 1`, and independently `35 -> 18 -> 8 -> 0` and `27 -> 0` from a second
observer). RFC 8216 requires the media sequence number of a live playlist to be
non-decreasing; a decrease invalidates every client-side assumption about continuity
and causes conforming players to abort.

### Suggested fix (either alone is sufficient; the first is preferred)

- Use ffmpeg's own `-hls_flags delete_segments` with a bounded `-hls_list_size`, so the
  playlist and the on-disk segments stay consistent **by construction** and neither
  `trimPlaylist` nor `deleteOldSegments` needs to guess.
- Otherwise, make the two agree: `segmentsToKeepBefore` must never exceed what
  `deleteOldSegments` retains below the anchor, and the served window should be floored
  at `highestDeletedSegment + 1` so it can never reference a deleted file.

Anchoring the joiner window to the **live edge** (standard HLS-live behaviour) rather
than to `minSegmentRequested` would additionally fix the joinability problem, where a
client joining an established session receives a head-anchored window whose entries are
long gone.

### Related observation (may be the same root, filed separately)

Sessions were seen restarting spontaneously ~40s in (segment numbering reset to
`data000000`, count dropping to 6) with no client action and no server-side teardown
request. If a failing segment fetch triggers a session rebuild, that would convert this
defect into an unrecoverable loop and would explain reports of live channels dying at
roughly the 3-minute mark.

---

## Report 3 — MPEG-TS (`hls_concat`) delivery depends on the in-process HLS master; one broken session takes down both delivery paths

**Where:** the concat pipeline's ffmpeg input is
`http://localhost:8000/stream/channels/<uuid>.m3u8?mode=hls` (observed in
Tunarr's own dumped ffmpeg error logs,
`ffmpeg-error-log-channel-4-concat-*.log`).

When the HLS session fails to start (e.g. readiness timeout → 500 on the master
route), the concat ffmpeg receives the same 500 and exits (code 8), so the
"fallback" `.ts` wire fails together with the HLS wire. Clients treating
MPEG-TS as an independent fallback get nothing. Consider serving concat from
the transcoded stream directly, or documenting that both modes share one
session's fate.

---

## Report 4 — Subtitle rendition playlist (`subs.m3u8`) is served frozen: pre-populated then never updated, with no ENDLIST

**SEVERITY DOWNGRADED 2026-07-30 — the original claim in this section was WRONG and is
retained only so the correction is legible.**

This was originally filed as "the highest-impact defect in this set", on the theory that
a player attaches to `subs.m3u8`, drains its cues, and then blocks forever waiting for
entries that never arrive — starving the video open.

That theory is **refuted**. Live subtitles now render correctly on screen (verified: a
predicted cue captured verbatim against matching picture) with this playlist behaviour
UNCHANGED. What actually broke playback was **deletion**, not pacing — our own janitor
was removing `.vtt` segments the player still needed. Once retention was fixed,
subtitles worked immediately and no `-readrate` or pacing change was required.

The observed non-advance is also explained benignly: the subtitle input is not
readrate-throttled (`-readrate` binds to input 0 only, and the `.srt` sidecar is a
second input), so it bursts ahead, fills ffmpeg's mux queue, and then **blocks** —
normal backpressure, not a runaway. Measured: the subtitle edge sat at cue 08:16.797 at
44s of session age and was still at exactly 08:16.797 at 160s. Because it blocks rather
than running to completion, the playlist never actually exhausts.

What remains genuinely worth reporting is only the **missing `#EXT-X-ENDLIST`**
question below: a rendition that is complete should say so. That is a conformance nit,
not a playback-breaking defect.

**Observed (Tunarr v1.3.10, channel with `subtitlesEnabled` + webvtt sidecar):** on a
freshly-started session, `GET /stream/channels/{id}/hls/subs.m3u8` returns a playlist
containing **17 `.vtt` entries immediately**, and that playlist is **byte-identical
40 seconds later** — first entry `sub000000.vtt`, last `sub000016.vtt`, count 17,
unchanged — while the video variant `stream.m3u8` advances normally over the same
interval (2 → 8 segments). The subtitle playlist carries **no `#EXT-X-ENDLIST`**, so
it advertises itself as a live playlist that will receive more segments.

**Failure mode it produces:** a player whose open-time probe is long enough to pull
the subtitle rendition (e.g. ffmpeg with a multi-second `analyzeduration`) attaches
to `subs.m3u8`, consumes all 17 cues, then — correctly, per RFC 8216 for a live
playlist without ENDLIST — **re-polls the playlist waiting for new entries that never
arrive**. The demuxer never completes its open, so the *video* stream never starts:
the client sits at 0% buffer with no error until its own watchdog aborts. The
resulting client-side error names the first *video* segment, which is misleading —
that fetch is a casualty of the aborted open, not its cause. (Two days were lost to
that misdirection here.)

**Why it looks intermittent:** on a mature session the subtitle playlist has caught
up with real elapsed content, so the drain-then-wait window closes and playback
succeeds. Fresh sessions fail; established ones work.

**Suggested fixes (any one suffices):**
- Keep `subs.m3u8` in lockstep with the video variant — append vtt entries as
  subtitle segments are produced, matching the media sequence of the video playlist; or
- If the subtitle set for the current program is genuinely complete and final, emit
  `#EXT-X-ENDLIST` so players stop polling; or
- Do not advertise the `EXT-X-MEDIA` subtitle rendition in the master until the
  subtitle playlist is being maintained live.

---

## Appendix — two additional reproducible defects (from earlier in this investigation)

**A. Channel-number master URL returns 500 during cold-start (while starting the
transcode anyway).** `GET /stream/channels/<number>.m3u8` returns
`500 "Error starting or retrieving session"` for several seconds on a cold
session (measured: 5×500 over 6.4s, then 200), while
`GET /stream/channels/<uuid>.m3u8` blocks and returns 200 on the first request.
The number-form also leaves the spawned transcode running. Clients using the
number form and not retrying the 500 fail every cold tune.

**B. Double `-ss` (input + output seek, same value) makes QSV transcodes emit
zero output for files with non-zero container start_time.** The pipeline builder
emits `-ss <pos>` both before and after `-i`. For files whose audio/subtitle
streams start at a small negative PTS (e.g. -0.005s, common in some remuxes),
ffmpeg produces no HLS segments at all; dropping the redundant post-input `-ss`
fixes it (verified standalone). Currently worked around here with an
`ffmpegExecutablePath` wrapper that strips the duplicate seek.

---

## Local mitigation notes (cluster-side, ours — NOT part of the upstream report)

### CORRECTION (2026-07-30): our janitor is NOT the cause, and the earlier recommendation here was wrong

An earlier revision of this document blamed our own `cache-purge` sidecar (which
deletes `stream_*/*.ts` older than 2 minutes) for breaking the joiner invariant, and
recommended raising that threshold 2min -> 10min.

**Measurement refuted that.** In the failing session the oldest surviving segment was
only 62s old when `data000000..007` had already been deleted — our purge cannot touch
anything under 120s. The deletions were Tunarr's own `deleteOldSegments`. Raising our
threshold would change nothing. The recommendation is withdrawn.

Our sidecar still exists for a real reason — a client that holds a session open without
advancing `minSegmentRequested` causes Tunarr's request-driven janitor to never run,
and `/.transcode` then grows ~8.8GB/hr per stream — but it is not implicated in this
defect.

### Separate local bug we introduced and fixed (recorded so it is not confused with the above)

Scoping our purge to `*.ts` (to stop it deleting `subs.m3u8` and `.vtt`, which was
breaking live subtitles) left `stream.m3u8` behind permanently. Stream directories are
keyed by CHANNEL UUID and therefore reused across sessions, so an orphaned playlist
survived advertising `EXT-X-MEDIA-SEQUENCE:0` with zero entries, exactly where the next
session for that channel would land. That produced the same *symptom* as the upstream
defect (backward media sequence) by a different route. Fixed by keying the purge on
session liveness: a directory still producing segments keeps its playlists and subtitle
segments; a directory that has stopped producing is cleared entirely.
