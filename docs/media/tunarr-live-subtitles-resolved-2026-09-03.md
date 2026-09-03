# Tunarr live-TV subtitles: the missing config was `subtitlePreferences`

**Date:** 2026-09-03 · **Status:** HLS leg RESOLVED · Plex DVR (`.ts`) leg still open

## Result

Live-TV subtitles were missing on every channel because the per-channel selection rule
was never configured — not because of any pipeline or code defect. No `ffmpeg-wrap`
edit, no fork, no dvbsub work was required for the HLS path.

Measured state before: **36 channels, 27 with `subtitlesEnabled: true`, 0 with
`subtitlePreferences` set.** Subtitles were switched on everywhere while the resolver
had no rule telling it which track to pick.

## The config

Per-channel, `PUT /api/channels/{id}` (full-object round-trip — 14 fields are required):

```json
"subtitlePreferences": [
  { "langugeCode": "eng", "priority": 0,
    "allowImageBased": false, "allowExternal": true, "filter": "any" }
]
```

⚠️ The API key is **misspelled `langugeCode`** (no 'a') and the schema is
`additionalProperties: false`, so the correct spelling is rejected. Note the
stream-selection-profile rules spell `languages` correctly — two spellings, one API.

## Evidence — controlled A/B, ch4 SimpsonsWorld, same program ("Homer Defined")

|                  | before (`prefs=null`) | after (`prefs` set)        |
|------------------|-----------------------|----------------------------|
| ffmpeg argc      | 95                    | 120                        |
| `-map`           | `[vpf] [a]`           | `[vpf] [a]` **`2:0`**      |
| inputs           | video + watermark     | + `tunarr-subtrim-*.srt`   |
| `subs.m3u8`      | absent                | present                    |
| `.vtt` segments  | 0                     | 3                          |

Verified on the wire, not from the manifest: `sub000000.vtt` is 159 bytes of real timed
text (`WEBVTT / 00:00.000 --> 00:00.875 / "That four-eyes with the big nose?"`). The
served master advertises
`#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="eng"` plus
`#EXT-X-STREAM-INF:...,SUBTITLES="subs"`.

## What is still missing: the Plex DVR `.ts` leg

`ffprobe` of `/stream/channels/<uuid>.ts` still returns only `h264` + `aac`. The `.ts`
is an internal remux of Tunarr's own HLS output:

```
ffmpeg -i http://localhost:8000/stream/channels/<uuid>.m3u8?mode=hls \
       -map 0 -c copy -f mpegts pipe:1
```

`-map 0` takes every stream, so master advertisement is **not** the blocker. WebVTT
cannot be `-c copy`'d into MPEG-TS, and lavf's HLS demuxer may not open `.vtt` segments
at all (the `allowed_extensions` / `extension_picky` rejection applies to this remux's
own HLS input). Plex DVR therefore still needs either a subtitle elementary stream in the
TS (`-c:s dvbsub`, bitmap, uneven client support) or a tuner URL Plex can consume as HLS.
`/lineup.json` advertises `.ts` for all 36 channels.

## Three traps that made a working config look broken

1. **Filler is not a program.** The first channel tested was airing
   `type=other_video`, `sourceType=local`, `/media/filler/rollout/...`. Filler is a
   different pipeline; do not judge the setting on it.
2. **`allowImageBased:false` correctly excludes PGS.** That filler's only subtitle was
   `hdmv_pgs_subtitle`, so "no subtitle mapped" was the config obeying instructions.
   Control on a program with an English **text** track.
3. **Read the SERVED master, not the disk one.** `/.transcode/stream_<uuid>/playlist.m3u8`
   has no `EXT-X-MEDIA` line — the master is generated per request. Reading the disk copy
   briefly produced a wrong "rendition not advertised" conclusion.

## Supply is not the constraint

`program_subtitles` holds **214,046** rows: 125k `srt`, 64k `subrip`, 14k `pgs`;
**29,362 English `srt`** plus 12,372 English `subrip`. 4,511 rows are `sidecar` type
(2,142 with a cached path). `is_extracted = 0` for every row.

## Current state

Applied to **ch4 (560d3fb5) and ch10 (a0b3f5c0) only**; the other 34 are untouched.
Pre-change channel objects are backed up; revert is a single `PUT` of the backup.
ch10 will read as a false negative until it airs a non-filler program.
