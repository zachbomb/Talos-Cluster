# DRAFT — Upstream Tunarr defect reports (do not post without review)

Evidence gathered 2026-07-29 on Tunarr v1.3.10 (ghcr digest a195c9d8), single-node
K8s, ~26 channels, PMP/mpv client (lavf 61.7.103) + in-pod ffprobe/curl repro.
Source refs are against the v1.3.10 tag. Prepared by the cluster session; see
`reference_tunarr_livetv_audio_subtitle_constraints` (memory) and SQ-185 (board)
for the full investigation trail.

---

## Report 1 — Served HLS media playlist window is anchored to `minSegmentRequested` and goes stale for joining clients

**Where:** `server/src/stream/hls/HlsSession.ts` → `trimPlaylist()`:

```ts
filterOpts ??= {
  type: 'before_segment_number',
  segmentNumber: this.minSegmentRequested,
  segmentsToKeepBefore: 10,
};
// mutator called with { maxSegmentsToKeep: 20, ... }
```

`GET /stream/channels/:id/{sessionType}/stream.m3u8` (streamApi.ts ~313) serves
the on-disk playlist trimmed to a window anchored at **the lowest segment number
any client has requested**. The anchor only advances on *segment* fetches.

**Failure mode:** a joining client's first request is the playlist, not a
segment. If no client has been requesting segments (session started by a probe
/ readiness gate; or the previous player disconnected), `minSegmentRequested`
stays at 0 and the served window is permanently `data000000..data000019` — while
ffmpeg's real playlist and segment files advance far past it. Measured: two GETs
2 minutes apart returned byte-identical head-anchored 20-entry bodies while the
on-disk playlist grew 61 entries; at session age 3.5 min the served window did
not even contain the live edge, and 17 of its 20 entries referenced files that
no longer existed (in our case removed by an external janitor; see Report 2 for
why any file removal breaks this). lavf (mpv/ffprobe) probes the first listed
segment at open → 404 → the whole open fails → client falls back or dies.

**Net effect:** an HLS session is only reliably joinable while its head segments
still exist. Under any segment-file cleanup, that is the first ~1-2 minutes of
the session. Existing connected clients are unaffected (they never re-probe the
head), which makes the defect look like random client-side tune flakiness.

**Suggested fixes (either suffices):**
- Anchor the joiner window to the **live edge** (e.g. serve the last N segments,
  HLS-live-standard), not to `minSegmentRequested`; or
- Advance/refresh the anchor on playlist fetches too, or floor it at
  `highestDeletedSegment + 1` so the served window never references deleted files.

---

## Report 2 — `append_list` + `hls_list_size 0` + segment deletion = playlist advertises unfetchable segments (HLS semantics violation)

**Where:** HLS output args (ffmpeg invocation): `-hls_list_size 0` and
`-hls_flags ...+append_list...+omit_endlist`, combined with
`HlsSession.deleteOldSegments()` (30s cadence, deletes below the trim sequence).

The on-disk playlist retains every entry ever written while segment files are
deleted from under it. Any consumer that reads the full playlist (or a stale
window per Report 1) will attempt segments that 404. A live playlist must not
advertise segments that are no longer retrievable (RFC 8216 §6.2.2 — the server
must remove segment URIs from the playlist in the order they were added when it
removes the media).

**Suggested fix:** use ffmpeg's own `-hls_flags delete_segments` with a bounded
`hls_list_size` so the playlist and the disk stay in sync by construction; the
serving window (Report 1) then cannot reference deleted files, and external
janitors become unnecessary.

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

**Severity: this one silently breaks HLS playback for any standards-compliant player
that deep-probes at open** (ffmpeg/libavformat, hence mpv, and anything embedding
them). It is the highest-impact defect in this set.

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

## Local mitigation decision (cluster-side, ours — not part of the upstream report)

Our cache-purge sidecar deletes `stream_*/​*.ts` files older than 2 minutes
(guards against the connected-but-idle-client disk leak: a held tuner keeps the
session alive with `minSegmentRequested` never advancing → Tunarr's own janitor
never deletes → ~8.8GB/hr growth). That mtime-based deletion is exactly what
breaks Report 1's invariant for joiners.

**Recommendation:** raise the `.ts` threshold from 2min → 10min for `stream_*`
dirs only (≈1.5GB per active stream; 5Gi PVC safely holds 2-3 concurrent):
- joinability window ×5 (covers all human channel-surf/re-tune patterns),
- disk still hard-bounded for the held-tuner leak,
- pairs with the client gate fix (probe first *listed* segment → reap+re-kick),
- retired entirely once upstream ships `delete_segments` (Report 2).
