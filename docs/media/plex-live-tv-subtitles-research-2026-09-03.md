# Deep research: can Plex Live TV show selectable subtitles from Tunarr?

**Date:** 2026-09-03 · **Answer: No — not selectably. The industry answer is burn-in.**

## The chain of constraints (each independently sourced)

1. **Plex clients only support MPEG-TS for live channels.** ErsatzTV — the most mature
   project in this space — states it flatly in its own Plex documentation:
   > "The only channel streaming mode supported directly by Plex clients is MPEG-TS."

2. **Plex has NO native M3U / IPTV tuner.** The feature request has been open since
   April 2018 with no staff response and no implementation. Users are pushed to
   third-party proxies (xTeVe, Threadfin) — and those *also* emulate an HDHomeRun tuner,
   so they deliver MPEG-TS too. The workaround does not change the container.

3. **MPEG-TS cannot carry WebVTT.** So the WebVTT rendition Tunarr now produces can never
   reach Plex through the DVR path, regardless of tuner configuration.

4. **Plex's only live-TV subtitle format is CEA-608/708 embedded captions** — the OTA
   broadcast path — and it is widely reported broken even with genuine HDHomeRun tuners:
   "Unknown (EIA_608)" appears as a track and selecting it displays nothing. Multi-year,
   multi-client reports.

5. **ErsatzTV's answer to this exact problem is BURN-IN.** Its subtitle extraction exists
   "in order to subsequently burn the subtitles". Tunarr's own docs say the same thing:
   extraction is enabled "in order to subsequently burn the subtitles", and it is
   "currently a requirement for using said subtitle streams".

## ⚠ Correction to earlier advice in this project

An earlier note in this session proposed **switching Plex's DVR to Tunarr's M3U tuner**
(`/api/channels.m3u`, whose URLs 302 to the HLS master carrying `TYPE=SUBTITLES`).
**That is not viable and should not be attempted.** Plex has no native M3U tuner to
switch to. The M3U endpoint is real and does carry the subtitle rendition — but Plex
cannot consume it. The suggestion was based on Tunarr's capability without checking
Plex's.

## What Tunarr documents about its own subtitle paths

* `enableSubtitleExtraction` (currently **true**) — hourly scan, extracts embedded text
  subtitles so they can be burned. Documented as "resource-intensive".
* Sidecar subtitles (`.srt`, `.vtt`) are auto-discovered next to media and downloaded
  from Plex/Jellyfin/Emby. Marked **experimental**, gated behind Settings > Features.
* "When using **HLS Direct** stream mode, sidecar text-based subtitles are served as
  WebVTT tracks in the HLS master playlist" — selectable in modern players.
* All 36 channels here are currently `streamMode: hls` (not `hls_direct`).

Note the measured behaviour is broader than the docs: with `subtitlePreferences` set,
plain `hls` mode also produced `subs.m3u8` + real WebVTT segments (verified on ch4).

## The three real options

| option | selectable? | works in Plex live TV? | cost |
|---|---|---|---|
| **Burn-in (hardsub)** | ✗ always on | ✓ yes, every client | re-encode; per-channel, all-or-nothing |
| **HLS rendition** (what is now enabled) | ✓ yes | ✗ no | already done, free — but only for HLS-capable clients |
| **Emby / Jellyfin for live TV** | ✓ likely | n/a | Emby already runs here at 192.168.10.204; native M3U/IPTV tuner support |

CEA-608 injection was considered and rejected: Tunarr's filtergraph re-encode maps
`[vpf]` (raw pixels), so caption side-data has no path through, no `-a53cc` is emitted,
and a 50-file library sample carried zero `closed_captions`. Plex's handling of it is
also the broken path described above.

## ★ dvbsub-in-TS is the one surviving path for SELECTABLE subs — better odds than assumed

An earlier draft of this document guessed the odds were poor. **Measured, they are not.**
Plex ships its own transcoder, and it carries the codec:

    DECODERS: dvbsub (dvb_subtitle), cc_dec (eia_608/cea_708), pgssub, subrip,
              webvtt, mov_text, dvdsub
    ENCODERS: dvbsub, subrip, webvtt, mov_text

So Plex **can decode DVB subtitles**. That is a necessary precondition and it is satisfied.

Why this is now a small change rather than a big one: Tunarr ALREADY does the hard parts.
With `subtitlePreferences` set it selects the correct track and materialises it as a text
file in the pipeline (observed: `/tmp/tunarr-subtrim-*.srt` passed as a third `-i` input
and mapped as `2:0`). The only missing step is that the `.ts` remux
(`-map 0 -c copy -f mpegts`) drops it instead of encoding it as `-c:s dvbsub`.

**STILL UNVERIFIED — and it is the whole question:** whether PMS's *live-TV* pipeline
surfaces a dvbsub track from a tuner's MPEG-TS as a selectable subtitle to clients.
Decoder capability is not the same as DVR-path plumbing, and Plex's live subtitle
handling is CEA-608-oriented. Caveats that remain regardless: dvbsub is BITMAP, so no
restyling or client-side sizing, and rendering text to bitmap costs CPU.

Note this is NOT "two sources for one channel" — Plex cannot compose a live channel from
a TS plus a separate subtitle feed. Sidecars match by filename adjacency to a library
FILE; a live session has no file and its metadata object is ephemeral. The subtitle has
to be inside the transport stream.

## Bottom line

The Tunarr-side work was correct and is not wasted — subtitles now genuinely exist,
are correctly selected, and are served as a real WebVTT rendition. Any client that
consumes the HLS master gets selectable English subtitles today.

Plex is simply not such a client for live TV. To see subtitles **in Plex**, they must be
burned into the video. That is not a workaround for a Tunarr limitation; it is what every
project in this category does, because Plex's live-TV pipeline accepts nothing else.

## Sources

* ErsatzTV Plex docs — https://ersatztv.org/docs/clients/plex/
* Plex forum, M3U in Live TV (open since 2018) — https://forums.plex.tv/t/support-for-m3u-playlistss-in-live-tv/232215
* Plex forum, closed captions Live TV — https://forums.plex.tv/t/closed-captions/934390
* Plex forum, CC not working on Live TV — https://forums.plex.tv/t/closed-captions-not-working-on-livetv/369691
* Tunarr FFmpeg/subtitle configuration — https://tunarr.com/configure/ffmpeg/
* ErsatzTV subtitle extraction/burn issue — https://github.com/ErsatzTV/ErsatzTV/issues/1761

---

# ADDENDUM 2026-09-03 — the dvbsub path is CLOSED. Tested, not assumed.

The earlier addendum said dvbsub-in-TS was the one surviving path for selectable
subtitles and that Plex's decoder support made the odds decent. **Tested end to end;
it does not work, for a reason upstream of Plex entirely.**

## Two independent blockers, both measured in the tunarr pod

**1. lavf will not expose the WebVTT rendition as an input stream.**

    ffprobe -extension_picky 0 -allowed_extensions ALL \
            'http://localhost:8000/stream/channels/<uuid>.m3u8?mode=hls'
    -> 0,h264,video
       1,aac,audio          (no subtitle stream, even with the extension guards off)

So a `-map 0:s:0?` remux of Tunarr's own HLS master silently produces nothing. This is
the SQ-114 demuxer behaviour applying to the internal `.ts` remux, not just to clients.

**2. ffmpeg cannot encode TEXT subtitles to a BITMAP codec.** Feeding the extracted
`.srt` directly as a second input and asking for `-c:s dvbsub`:

    [sost#0:2/dvbsub] Subtitle encoding currently only possible from
                      text to text or bitmap to bitmap
    Error opening output file.

This is categorical, not a flag problem. Available subtitle encoders are
`ssa, ass, dvbsub, dvdsub, mov_text, srt, subrip, text` — the two bitmap encoders
refuse text input, and every text encoder is uncarriable in MPEG-TS.

## Therefore

MPEG-TS is the only container Plex accepts for live channels. Our subtitles exist only
as TEXT (srt/WebVTT). Text cannot be converted to a TS-carriable subtitle codec by
ffmpeg. **The only remaining way to put these subtitles into a Plex live stream is to
draw them onto the video — burn-in.** Whether Plex would surface a dvbsub track is now
moot; we cannot produce one from this source material.

Getting selectable subtitles into Plex live TV would require rendering text to bitmap
images outside ffmpeg (BDSup2Sub-class tooling) and muxing those — a bespoke pipeline
per program, on a live stream. Not proportionate.

## Where that leaves the options

| path | selectable | reaches Plex clients | status |
|---|---|---|---|
| HLS WebVTT rendition | yes | no | **working today** for HLS-capable clients |
| Burn-in | no | yes | possible; explicitly ruled out by the owner |
| dvbsub in TS | yes | yes | **IMPOSSIBLE from a text source** |
| Emby / Jellyfin for live TV | yes | n/a | native M3U/IPTV + HLS; already deployed at .204 |

The realistic route to "selectable subtitles on more than one client" is a client/server
that consumes HLS — i.e. Emby or Jellyfin for live TV — not Plex.

## Separately: forced-track selection (measured, bounded)

`subtitlePreferences.filter` has no value meaning "not forced", and `none` does not avoid
one; Tunarr picks a forced track when the file flags it `default=1`. Blast radius:

    26,343  programs with an english TEXT track
       767  have a forced english track            (2.9%)
       671  forced AND default=1  <- shows near-empty subs   (2.5%)
       545  of those have a better non-forced track available

97.5% of programs are unaffected. The pre-trim in `ffmpeg-wrap` was suspected and
**exonerated** by an offline reproduction: a synthetic 1080-cue source trimmed at
745728ms yielded 782 cues against 781 expected. The sparse output was the forced track
itself, not cue loss.
