# DRAFT — Upstream Tunarr defect reports (do not post without review)

Evidence gathered 2026-07-29/30 and 2026-08-04 on Tunarr v1.3.10 (ghcr digest a195c9d8),
single-node K8s, ~26 channels, PMP/mpv client (lavf 61.7.103) + in-pod ffprobe/curl repro.
Source refs are against the v1.3.10 tag. Prepared by the cluster session; see
`reference_tunarr_livetv_audio_subtitle_constraints` and
`reference_tunarr_shared_anchor_two_mechanism` (memory), and SQ-185 / SQ-222 (board),
for the full investigation trail.

**2026-08-04 addition:** the shared-anchor defect was reproduced on demand against a
*live production session with a real viewer* — a single failing subtitle GET rewound that
viewer's video window by 42 segments. See "On-demand reproduction" under Report 1+2. That
run also pins down the index mapping (`window_start = requested_index - 10`, clamped at
0), which the earlier exhibits could not distinguish from a reset.

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

#### On-demand reproduction against a LIVE session with a real viewer (2026-08-04)

The exhibit above was produced on an idle probe session with no media player and a
shallow window. This one was fired deliberately at a **production session with a real
`libmpv` client streaming continuously**, at a moment when the window had grown deep.
It is the single cleanest statement of the defect in this document.

```
precondition   video EXT-X-MEDIA-SEQUENCE = 42   (real client streaming, window deep)
single request GET sub000006.vtt  -> 500          (one call, never repeated)
result         video EXT-X-MEDIA-SEQUENCE = 0     *** 42-segment backward jump ***
```

**One failing subtitle GET rewound the video window by 42 segments** — roughly 2.8
minutes of content at 4s/segment — for a viewer who was watching normally and who never
requested a subtitle segment at all.

Three things this establishes that the earlier exhibit could not:

1. **The anchor MAPS, then CLAMPS — it does not "reset".** `window_start = requested_index
   - segmentsToKeepBefore`, with `segmentsToKeepBefore = 10`, gives `max(0, 6 - 10) = 0`.
   The earlier `sub000000 -> SEQ 0` row is consistent with both "reset to zero" and
   "map then clamp" and cannot distinguish them; a non-zero request index can. This
   matters for the fix: clamping a computed index at 0 is a different bug from
   discarding the index.
2. **It is a denial of service against other consumers, not self-inflicted.** The client
   that suffered the rewind issued no subtitle request. Any second consumer on the
   channel — another player, a readiness probe, a bandwidth estimator — can do this to
   every other viewer of that channel at will.
3. **A 500 is sufficient.** No segment was served. The request failed, and still moved
   the anchor.

**Methodological caveat, stated because it cost a cycle here.** A version of this test
fired at `SEQ = 0` proved nothing and looked like a negative result: the anchor cannot
move *backward* from zero, so the experiment was structurally incapable of detecting the
effect it was designed to detect. A valid run needs **a deep window and a low requested
index** — the gap between them is the signal. Anyone attempting to confirm this on a
fresh session will get a false negative.

**Still n=1.** One firing, one channel, one session. The magnitude is not a fixed "42" —
it is bounded by `current_sequence - max(0, requested_index - 10)`.

#### Why that bound is close to the FULL session length, not a modest offset

`current_sequence` is a **video** index; `requested_index` is a **subtitle** index. The
two count at completely different rates, so their difference is not a small lag — it is
most of the session.

Video segments are a uniform 4.000s. Subtitle segments are **cue-driven**: the segmenter
has nothing to split on during silence, so the subtitle index does not advance at all
while no one is speaking. Measured on this appliance: **video at segment ~92 while the
subtitle index was ~32**, i.e. ~11.5s of average subtitle-segment duration against
video's 4.000s. (Consistent with the first-segment measurement recorded in the
two-mechanism model below: 30.488s for a first cue at 27.53s.)

**This is not in tension with the "subtitles run ~3.5x ahead" measurements elsewhere in
this report — those are different quantities.** The subtitle rendition runs ahead in
*timeline* (its content covers a later wall-clock position, because its input is not
readrate-throttled and it bursts until the mux queue blocks). It runs *behind* in *index*
(fewer, longer segments). Ahead in time, behind in index, simultaneously. That is
precisely the incommensurability this report's suggested fix identifies: one shared
`minSegmentRequested` indexing two renditions whose segment durations are set by
different clocks.

Consequence: because a live subtitle index sits far below the concurrent video sequence,
**a subtitle fetch drags the anchor back nearly to the start of the session**, not by a
handful of segments.

#### Inverse severity: quiet content suffers the worst video damage

The subtitle index is a function of how much dialogue has occurred. Therefore:

- **Sparse-dialogue content produces fewer subtitle segments**, so its subtitle index is
  lower relative to the video sequence, so the rewind is **deeper**.
- **Dialogue-heavy content** advances the subtitle index closer to the video rate, so the
  rewind is **shallower**.

A quiet film is damaged more than a talky one. This is a counterintuitive severity
profile and worth stating explicitly, because it inverts the natural triage instinct: the
content *least* likely to be suspected of a subtitle-related fault is the content whose
video playback is destroyed hardest. It also compounds the "intermittent and
unreproducible" character noted below — severity varies with the dialogue density of
whatever happens to be airing.

Both consequences follow from mechanisms already measured in this report (uniform 4.000s
video segmentation, cue-driven subtitle segmentation); only the 92/32 index sample is a
new datapoint.

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

### TWO-MECHANISM MODEL (measured): pacing governs the DRIFT, the origin offset governs the FLOOR

Two independent quantities produce the backward drags. Neither explains the data alone;
together they predict the magnitude for any program from a number readable off the
source `.srt` **without tuning anything**.

**Mechanism 1 - drift.** The subtitle input is not readrate-throttled (`-readrate` binds
to input 0; the sidecar is a later input), so it bursts until the mux queue blocks and
runs ~2.4-3.5x ahead. Throttling it collapses this component.

**Mechanism 2 - origin offset.** The first subtitle segment spans from t=0 to the FIRST
CUE, because a cue-driven segmenter has nothing to split on until dialogue starts.
Measured: a first segment of 30.488s against a first cue at 27.53s in the source .srt -
agreeing within one segment. Video is a uniform 4.000s. So the two index spaces are
offset by `time_to_first_cue / 4` segments **before either stream advances**, and no
amount of pacing can close a gap that exists at the origin.

#### Measured, one variable (time-to-first-cue), same protocol, throttle verified active

| channel | first cue | predicted offset | observed max drag |
|---|---|---|---|
| unthrottled control | - | - | **28 and 99 segments** |
| ch3  | 2.2s  | ~0.6 segments | **0** (26 samples, 520s, zero 404s) |
| ch16 | 19.3s | ~4.8 segments | (not run) |
| ch18 | 27.5s | ~7.6 segments | **6, 6, 8** (plus one 31 outlier, see below) |

A 14x reduction in predicted offset produced a collapse from 6-8 segments to zero.

The ch3 trace is worth reproducing because the SHAPE is the evidence, not just the
count - video and subtitle sequences advance in near-lockstep, crossing by a segment or
two and never diverging:
```
vSEQ/sSEQ:  43/49  48/49  52/58  57/58  61/70  65/70  71/70  76/80  82/85  88/90
```
Contrast the unthrottled run on another channel, where the subtitle sequence climbed to
115 while the video window collapsed to 0.

#### The offset is NOT an edge case - it is present in most content

Sampled 400 cached `.srt` files for time-to-first-cue:
```
min 0.0s   p25 3.1s   median 4.5s   p75 9.4s   max 125.5s   mean 9.4s
  <5s   : 215  (54%)      15-30s:  37
  5-15s : 128             30-60s:  12        >60s: 8
```
At a median of 4.5s the offset is ~1 segment for most programs - small enough never to
be noticed, large enough to always be present. Only the tail (ch18 sits in the top 7%)
fails visibly. That is the profile of a defect that generates "intermittent,
unreproducible" reports for years.

#### Caveats, stated plainly

* **Every point above is n=1.** Three tidy rows imply more replication than exists.
* **The 31-segment outlier on ch18** coincided with a retune and 404s in the same window
  and may be a re-gate artifact rather than a clean drag.
* **Zero is weaker than a small number.** ch3's null is consistent with ~0.6 segments but
  cannot distinguish it from 0; the granularity floor is one segment. A mid-range program
  (~10-15s first cue, ~3 segments) would test the SLOPE rather than only the endpoints.
* **One observer covers only one direction.** The polling instrument that produced the
  ch3 null has only ever reproduced UPWARD drags. A real sequential consumer (libmpv) has
  produced downward drags (161 -> 62). A near-zero-offset run with a real player is
  needed to close that axis; if it drags downward on a near-zero offset, this model needs
  a third term.

#### What this asks of the fix

Both mechanisms trace to the same root - **one shared `minSegmentRequested` indexing two
renditions whose segment durations are set by different clocks** (fixed 4s vs speech).
Pacing narrows the drift but cannot make the index spaces commensurable. Track the anchor
**per rendition**, or do not derive the serving window from client request history at all.

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

#### THIRD divergence mechanism (2026-09-01): program-boundary relaunch renumbers renditions independently

The two mechanisms above (pacing drift, origin offset) both assume a session whose
renditions START aligned and then diverge. A program boundary produces divergence a third
way, and it re-skews even a nominally aligned session:

At the boundary the transcode relaunches. The SUBTITLE rendition restarts numbering at 0
while the VIDEO playlist continues from its running high-water mark. Because
`minSegmentRequested` is parsed from the request path and shared, a perfectly legitimate
`sub000000` request rewrites the video anchor to ~0.

**The sign is the opposite of the intuitive one, which is why this hid for so long.** A
backward anchor does not cause deletion. It causes the server to ADVERTISE segments that
were correctly deleted minutes earlier:

1. anchor climbs to ~80 during normal play; `deleteOldSegments` correctly removes below ~70
2. boundary; subtitle rendition renumbers to 0
3. client requests `sub000000`; shared anchor dragged back to ~0
4. `trimPlaylist` serves a window at ~0 plus `segmentsToKeepBefore: 10`
5. every segment in that window is long gone -> 100% 404

**Server-side confirmation** (new — previous evidence for this defect was client-side and
black-box). Tunarr logs both halves itself at debug level. One session, ~2s apart, the
client walking FORWARD through a stale window:

```
04:49:16.565  GET .../hls/data000019.ts  404
04:49:18.748  GET .../hls/data000028.ts  404
04:49:20.891  GET .../hls/data000037.ts  404
04:49:22.931  GET .../hls/data000046.ts  404
```

with `Deleting old segments from stream (channel ...)` logged 59 times in 30 minutes
(~30s cadence). Client-side, gathered independently: backward media-sequence jumps of
10->0 at the boundary, then 55->23 and 67->34 on an ~80s cadence, each landing at
approximately `sub_index - 10`. That offset is `segmentsToKeepBefore`, recovered a second
time by a completely different route.

**`deleteOldSegments` is EXONERATED.** It behaves correctly against the anchor it is given.
Worth stating explicitly because the disk state — a playlist advertising far more entries
than exist — invites blaming the reaper or an external janitor. Measured on a continuous
8-minute session: 136 playlist entries vs 74 segments on disk, with no external janitor
involved.

**Recovery:** a client retune does NOT help; it reconnects to the same skewed session.
`DELETE` on the session resets both renditions to aligned numbering and playback is
immediately stable.

### Suggested fix (any one is sufficient; the first is preferred)


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

**Smaller fix shape, added 2026-09-01:** renumber ALL renditions together at relaunch.
This does not give renditions independent anchors, but it removes the boundary as a
divergence source, and is a materially smaller change than per-rendition anchors.

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

## Report 5 — ROOT CAUSE: video and subtitles are written by two different muxers, and nothing signals between them

**Added 2026-08-06.** This is not a fourth independent defect. It is the structural
choice that produces Reports 1–4 and both open client-side issues. Stating it separately
because fixing it addresses several symptoms at once, and because each symptom read as
its own bug for weeks.

### The split

Both outputs come from a single ffmpeg invocation, but different muxers:

```
-f hls       -hls_flags program_date_time+append_list+independent_segments+omit_endlist+discont_start
             -> stream.m3u8      (video)

-f segment   -segment_list subs.m3u8  -segment_list_type hls  -segment_list_flags live
             -segment_list_size 20    -segment_format webvtt
             -> subs.m3u8 + sub%06d.vtt   (subtitles)
```

The client is handed two playlists in two HLS dialects and expected to reconcile them,
with no cross-signalling.

### Measured consequences

| observation | cause |
|---|---|
| `subs.m3u8` finalizes mid-session with `#EXT-X-ENDLIST`; `stream.m3u8` never does | `omit_endlist` is an **hls-muxer** flag. It does not reach `-f segment`, whose `seg_write_trailer()` appends ENDLIST on clean exit. Confirmed live: 338 consecutive polls with ENDLIST present on a subtitle playlist while video ran normally. |
| Subtitle cue timeline resets at program transitions with **no marker** | `stream.m3u8` carried `EXT-X-DISCONTINUITY: 3` at an in-process program change. `subs.m3u8` carried **0**. Its complete tag set is `VERSION`, `TARGETDURATION`, `MEDIA-SEQUENCE`, `ALLOW-CACHE` — no discontinuity support at all. Zero subtitle playlists on this deployment have ever carried one. |
| Video playlist index space is unbounded; subtitle window is 20 | `-hls_list_size 0` vs `-segment_list_size 20`. A mature video generation reaches index ~300 while subtitles cycle in a 20-entry window, so a deep join sees a ~300-segment backward jump at a relaunch while a fresh join sees none. |
| The two renditions share one `minSegmentRequested` anchor | see Report 1+2. Independent index spaces, one anchor. |

### Two transition shapes, only one of which is externally visible

Program changes occur in **two** forms, which must not be conflated when analysing logs:

- **Relaunch** — a new ffmpeg process. `MEDIA-SEQUENCE` resets; a new wrapper-log entry appears.
- **In-process** — same ffmpeg, next input. Emits `EXT-X-DISCONTINUITY` on video, **no wrapper-log entry**, no renumber.

Any analysis keyed on wrapper-log presence is blind to the second kind. Classify by
`EXT-X-DISCONTINUITY` count instead.

### Suggested fixes, in order of tractability

1. **Emit `EXT-X-DISCONTINUITY` on the subtitle playlist at program transitions.** A missing
   tag, not architectural state. This alone lets a conforming client reset its expectations
   correctly, and it is standard HLS rather than a Tunarr-specific heuristic.
2. **Suppress the subtitle trailer's ENDLIST for live channels**, matching the intent of
   `omit_endlist` on the video side.
3. **Bound the video playlist** (`-hls_list_size` with `delete_segments`) so both renditions
   share a comparable index space and playlist/disk stay consistent by construction.

### Why this was hard to see

Every symptom is individually plausible as its own bug, and no single vantage shows the
split: the client sees two playlists behaving inconsistently, the server sees one process
behaving normally. It took the ffmpeg argv — which neither seat routinely reads — to make
the two-muxer structure visible at all.

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

### Client-side guard (2026-08-04) — protects ONE client, does not fix the defect

A guard was added to our own client's HLS layer (`hls.c`, ffmpeg 7.1.5 tree): segment
names are treated as valid only for the playlist generation they came from, and any
4xx/5xx triggers a playlist re-read rather than a retry of the stale name. The intent is
that our client never emits the request that moves the anchor.

**This is worth recording in the upstream context precisely because of what it does not
do.** It removes our appliance as a *trigger*; it does nothing about our appliance as a
*victim*. The 2026-08-04 reproduction above makes that concrete: the client that suffered
the 42-segment rewind had issued no subtitle request. Any other consumer on the channel —
a second player, Tunarr's own concat pipeline (see Report 3, which consumes the same HLS
master), a readiness probe — still drags the shared anchor and rewinds video for every
viewer.

So a client-side fix is available to any individual integrator and none of them
compose: each one protects only itself, and a single unguarded consumer re-breaks the
channel for all of them. That is the argument for fixing the anchor server-side.

### Separate local bug we introduced and fixed (recorded so it is not confused with the above)

Scoping our purge to `*.ts` (to stop it deleting `subs.m3u8` and `.vtt`, which was
breaking live subtitles) left `stream.m3u8` behind permanently. Stream directories are
keyed by CHANNEL UUID and therefore reused across sessions, so an orphaned playlist
survived advertising `EXT-X-MEDIA-SEQUENCE:0` with zero entries, exactly where the next
session for that channel would land. That produced the same *symptom* as the upstream
defect (backward media sequence) by a different route. Fixed by keying the purge on
session liveness: a directory still producing segments keeps its playlists and subtitle
segments; a directory that has stopped producing is cleared entirely.
