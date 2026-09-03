# Plex ↔ Tunarr DVR baseline (before any Plex-side change)

Captured 2026-09-03, immediately after `subtitlePreferences` was rolled out to all
27 subtitle-enabled Tunarr channels. This is the reference point for judging any
later Plex reconfiguration.

## Plex DVR as configured today

```
Dvr.key            27
Dvr.uuid           7a0351eb-9fac-4184-9f93-0ef039c6a10a
Dvr.lineupTitle    Tunarr
Dvr.lineup         lineup://tv.plex.providers.epg.xmltv/media/app_backups/
                     DizqueTV_Backups/xmltv/xmltv.xml#Tunarr
Dvr.epgIdentifier  tv.plex.providers.epg.xmltv:27
Dvr.refreshedAt    1788411935

Device
  uuid             device://tv.plex.grabbers.hdhomerun/Tunarr   <-- HDHomeRun grabber
  uri              http://192.168.10.205:8000
  make/model       Tunarr - Silicondust / Tunarr (HDTC-2US)
  state            enabled
  status           dead
  lastSeenAt       1788306743   (~30h before capture)
  tuners           2
  canTranscode     1
  ChannelMapping   36 entries
```

## What this baseline establishes

1. **Plex is attached via the HDHomeRun grabber.** That interface is served by
   `/discover.json` + `/lineup.json`, and `lineup.json` advertises
   `/stream/channels/<uuid>.ts` for all 36 channels. The `.ts` is an internal
   `-map 0 -c copy -f mpegts` remux of Tunarr's HLS output, and **WebVTT cannot be
   copied into MPEG-TS**. This is the direct, sufficient explanation for "no
   selectable subtitles in Plex" — independent of anything on the Tunarr side.
2. **The channel mapping is healthy** — all 36 channels are mapped. Do not chase
   the lineup as the fault. (An earlier read of "0 channels" came from querying
   `/livetv/dvrs/27/channels`; the mappings live on the Device object.)
3. **`status: dead`, last seen ~30h ago** — yet the Plex pod reaches
   `http://192.168.10.205:8000/discover.json` in 1.8 ms at capture time. So the
   status is stale rather than a live reachability failure. Worth a re-probe before
   treating it as a fault.
4. **The EPG lineup points at a legacy DizqueTV backup FILE path**
   (`/media/app_backups/DizqueTV_Backups/xmltv/xmltv.xml`), not Tunarr's live
   endpoint `http://192.168.10.205:8000/api/xmltv.xml`. `lastEpgUpdatedAt` is unset.
   A leftover from the DizqueTV era.

## The alternative interface Tunarr already publishes

`GET /api/channels.m3u` returns an M3U whose entries are, per channel:

```
http://192.168.10.205:8000/stream/channels/<uuid>?streamMode=hls
  -> 302 -> /stream/channels/<uuid>.m3u8?mode=hls
  -> 200    application/vnd.apple.mpegurl
     #EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="eng",...
     #EXT-X-STREAM-INF:...,SUBTITLES="subs",AUDIO="audio"
```

with the guide at `http://192.168.10.205:8000/api/xmltv.xml`. Verified: that chain
**does** carry the English WebVTT rendition, where the `.ts` chain does not.

**UNVERIFIED and the crux:** whether Plex's M3U tuner surfaces a WebVTT rendition to
clients as a selectable `streamType=3`. Plex's M3U/IPTV tuner consumes HLS, but its
subtitle-rendition handling has not been measured here. Do not present the M3U switch
as a fix until a client census confirms it.

**Cost to test:** re-adding a DVR device in the Plex UI is disruptive — it can reset
channel mappings and guide data (36 mappings currently intact). Treat as a deliberate
change, not an experiment to run casually.

## Tunarr-side state at capture

27 channels `subtitlesEnabled: true` and now all 27 with `subtitlePreferences` set;
9 channels deliberately have subtitles off and were left untouched. Proven on ch4:
the transcode maps a subtitle input, emits `subs.m3u8`, and the `.vtt` segments carry
real timed text.
