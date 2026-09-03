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
