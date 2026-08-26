# Unseen — ambient playback & watch-next design

**Status:** design, not yet implemented.
**Date:** 2026-08-25
**Depends on:** the Letterboxd watched-state backfill (commit `82d2fccfc`), which is what
makes any of this possible — before it, Plex knew about 89 watched films out of 2,103.

## Goal

Continuously play films *neither of us has seen* to ambient displays, let us flag anything
interesting for proper viewing later, and have the unwatched pools stay correct on their own.

## The semantic model (the load-bearing decision)

**Passing exposure is not watching, and the system must agree.**

- **Ambient displays are a discovery surface**, not a consumption surface. They are silent.
  Catching 20 minutes of a muted film has not "used it up", so it must not leave the pool.
- **The webapp is the bridge** — it converts passive exposure into an intentional queue entry.
- **Deliberate viewing in Plex, with sound, is what counts.** That marks watched natively and
  drops the film from every pool.

```
ambient screen  ->  "what is that?"  ->  webapp tap  ->  Priority - Watch Next
                                                              |
                                                  watch properly (sound)
                                                              |
                                            marked watched -> leaves all pools
```

## Keeping ambient playback off the record

A PMP Pi is a real Plex client, so it WILL mark things watched. Two candidate fixes:

1. **Correction (rejected as primary):** Tautulli watches sessions and calls `/:/unscrobble`
   when the player is an ambient device. Workable — Tautulli's proper role is observing
   playback, unlike using it as a watched-state *destination*, which would mean fabricating
   sessions. But an undo that fails leaves a permanent wrong mark.
2. **Prevention by identity (CHOSEN):** ambient displays sign into a dedicated Plex Home
   account, `Ambient`. Its watched state is meaningless, so there is nothing to undo and no
   event that can be missed. Zach's and Liz's history is structurally untouchable from those
   screens.

Side benefit: `Ambient` accumulating watched state gives free short-term repeat avoidance.
Wipe it periodically to reset the pool.

Keep the Tautulli rule as an optional safety net for signing into an ambient screen by habit.

## Playlists — two different mechanisms

| Playlist | Mechanism | Why |
|---|---|---|
| `Zach — Unwatched` | **smart**, self-updating | `unwatched` resolves against the owning account |
| `Liz — Unwatched` | **smart**, self-updating | same |
| `Both — Unwatched` | **static**, nightly rebuild | Plex cannot filter "unseen by ANOTHER user" |
| `Priority — Watch Next` | static, webapp-managed | manual queue |

The static ones need a rebuild job — which Tunarr needs regardless (below).

## Tunarr channels

Tunarr consumes Plex **collections**, not playlists, and **snapshots** their contents when
building programming rather than tracking them live (upstream issue #15, Milestone 2.0). So:

- nightly job recomputes the three unseen sets,
- writes them to Plex **collections** (`collection.locked=1` or the tags drop on refresh),
- then rebuilds each channel's programming via `POST /api/channels/{id}/programming`.

Channels 40/41/42 = Both / Zach / Liz. Use **Random Slots + Pad Slot**, not Time Slots
(Max Lateness truncates films). Use **VAAPI, not QSV** — QSV pins output to 24.000 fps via a
constant-parser bug. Watch `/.transcode`: ~8.8 GB/hr per stream, and three channels means up
to three concurrent streams.

## The ViewEdge display

Cary Works ViewEdge — 3.81" AM-OLED, **1200x1080 (10:9)**, 90 Hz, HDMI in, USB-C power.
Three known difficulties, all consistent with a driver-board panel with poor/absent EDID:
arrives flipped, capped at 90 Hz, and shows nothing unless fed its exact native resolution.

**Playback is pan-and-scan by choice** ("full-screen VHS"), not letterbox:

| Source | scaled to 1080 tall | cropped to 1200 | kept |
|---|---|---|---|
| 2.39:1 | 2581x1080 | 1200x1080 | 47% |
| 1.85:1 | 1998x1080 | 1200x1080 | 60% |
| 16:9   | 1920x1080 | 1200x1080 | 63% |

Implement client-side: PMP is mpv-based, and **`panscan=1.0`** does exactly this — fills by
cropping, centered, at no transcode cost and affecting no other client. Because it is a
runtime property the webapp can expose it as a zoom slider (dial back to letterbox for films
where composition matters). Cropping the SIDES keeps mpv-rendered centered subtitles visible;
burned-in wide subs may clip.

Mode and rotation are set once at the KMS layer, before any app runs:

```
# /boot/firmware/cmdline.txt
video=HDMI-A-1:1200x1080@90,rotate=180
```

**FIRST BUILD STEP — do not guess timings:**
```bash
edid-decode /sys/class/drm/card*-HDMI-A-1/edid
```
This settles whether the panel publishes usable timings and whether anything other than 90 Hz
is offered. 90/24 = 3.75, so 24p at 90 Hz lands on an uneven 4-4-3-4 refresh cadence (visible
judder on pans). **48 Hz or 72 Hz are exact multiples of 24** — if either is available, take it
and the judder problem disappears rather than being tolerated.

## Sync / staying current

- **Plex watched state is the source of truth** for anything in the library. It updates itself
  on real playback, which is why the smart playlists need no maintenance.
- **Trakt** is the durable, off-site, cross-device record, and the only place that can hold the
  full ~3,259-film history (Plex and Emby can only ever reflect what is in the library).
- **Letterboxd has NO public write API.** It can never be a live sync target — import is
  CSV-only, by hand. It stays a periodic manual export, for films watched away from home.

## Open items

- Trakt API app (blocked on account owner) — then device-code auth.
- Emby profile for Liz (blocked on account owner) — then watched sync + playlists.
- Verify Plex smart-playlist creation via API (`uri=server://.../all?type=1&unwatched=1`).
- Pi not yet built; EDID unknown; PMP Live TV support unverified (Konvergo's is patchy — if it
  cannot tune Tunarr, ambient screens shuffle the `Ambient` playlist instead, which is exactly
  why the dedicated account matters).
