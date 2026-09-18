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

> **UPDATED 2026-09-14 from the appliance session — the panel is INSTALLED and
> running, and several assumptions below were wrong. Corrections first:**
>
> * **It is on `HDMI-A-2`, not HDMI-A-1.** HDMI-A-1 is the Sony 4K TV. Any
>   `edid-decode /sys/class/drm/card*-HDMI-A-1/edid` decodes the TELEVISION and
>   returns a confident wrong answer. The panel is `card1-HDMI-A-2`.
> * **The EDID is NOT thin or absent.** Full 256 bytes + 1 extension block:
>   mfg LZT, product 0x0001, EDID 1.3, 12/2017, descriptor name "Viewedge.CR".
>   Exactly ONE usable detailed timing: **1080x1200 @ 89.992 Hz** (pclk 147.900
>   MHz, htotal 1356, vtotal 1212). Remaining descriptors are malformed filler.
> * **⚠ THE RANGE DESCRIPTOR LIES.** It claims vert 23-75 Hz / horiz 15-240 kHz /
>   pclk <=300 MHz, but the panel locks ONLY its single DTD. Proven: a runtime
>   modeset to 1080x1200@71.928 plus a full output off/on cycle both produced a
>   BLACK panel, while the host measured perfect — 1.000x achieved rate, 0.00
>   delayed frames/s (vs ~4.0/s at 90 Hz), cadence exactly 3.0000 refreshes/frame.
>   **So the 24p judder on firmware 1 is STRUCTURAL and no host-side work fixes
>   it.** 48/72 Hz is not available; firmware 2's mode list is the only lever left.
> * **Rotation is already solved** by the compositor (`transform=270` on that
>   output, set by `~/start-pmp-ambient.sh` `apply_output_layout`), and survives
>   mode changes. The `cmdline.txt` approach below is NOT what is used.
> * The ambient panel does **not** route through `~/select-display-mode.sh` —
>   that script still owns the TV on HDMI-A-1, so the 16:9-only caveat applies
>   only to that path.
>
> **Firmware:** two buttons on the drive board; one is "basically not used", the
> other toggles between firmware 1 (WIN mode, default) and firmware 2 (WIN+MAC
> compatible). It is a hardware toggle — nothing to flash. No press duration, no
> active-firmware indicator, and no button labelling is published by the vendor.
> After a button press the EDID was byte-for-byte identical, and `status` stayed
> `connected` through a `wlr-randr --off/--on`, so HPD never dropped and the
> kernel served its cached EDID. Open: inert button vs toggle-needs-power-cycle
> vs both firmwares sharing one HDMI EDID. A full power-and-HDMI unplug decides it.


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
- Pi not yet built; EDID unknown — `edid-decode` is an owner step once the hardware exists.
- ~~PMP Live TV support unverified~~ **RESOLVED 2026-09-10.** Reported by the appliance
  session (their direct testing, not verified here): **PMP tunes Tunarr channels fine over
  HLS** via the native EPG guide, with channel up/down, mini-guide and a live OSD. The
  Tunarr-direct path is the same code, so an ambient box on that image inherits it.
  **⚠ PRECISE CLAIM (do not broaden it):** that client tunes Tunarr **DIRECTLY over Tunarr's
  own HLS endpoints, bypassing PMS for live**. What was observed is that tuning a Tunarr
  channel THROUGH Plex DVR — the PMS live remux/transcoder path — segfaults SERVER-side. So
  "HLS is mandatory" is true *for this client's Tunarr path*; it is NOT a general statement
  about Plex DVR. The PMS-side segfault is the appliance board's SQ-95 finding and is
  PMS-version dependent. Channels 40/41/42 would tune by number. The shuffle-the-`Ambient`-playlist fallback is STILL worth
  keeping (their words, correcting an earlier overstatement of mine that this made it
  redundant); a "Play Random" enhancement with season scope and a fresh order each run is on
  the PMP board as US-4.
- **Identity mechanism confirmed** (appliance session): the modern client signs in via a
  plex.tv PIN and the token lives in the CLIENT'S LOCAL STORAGE PER BOX. So an ambient image
  simply logs in as `Ambient` once. Nothing in PMP scrobbles outside the signed-in account and
  the host never marks watched on its own — which is exactly the property the
  "prevention by identity" decision depends on.
- **⚠ CAPACITY — size the channels BEFORE all three go live.** Measured 2026-09-09/10 under
  contention: the media NFS export delivered only **3.9 MB/s** to a client alongside one live
  stream, and ~25 MB/s read from inside a pod. Three Tunarr transcodes at ~8.8 GB/hr
  (**~2.4 MB/s each**) plus one 4K remux direct-play (**7.75 MB/s sustained**) comes to
  ~15 MB/s — which EXCEEDS what the export actually delivered that day. Longhorn is also
  single-disk (see docs/dr/longhorn-single-disk-io-contention.md). Bring channels up one at a
  time and measure.
- `panscan` confirmed cheap to expose: it is an mpv runtime property and the appliance player
  already proxies mpv properties over its host API. Burned-in wide subs DO clip at
  panscan=1.0; mpv-rendered subs stay centered.
- Mode selection on the appliance image is done by `~/select-display-mode.sh`, which picks
  among EDID-advertised modes with a content-rate-matching policy. **NOT automatic for this
  panel:** that script has only ever run against 16:9 TV/projector EDIDs, and a 10:9
  driver-board panel with a thin or absent EDID is precisely the case it has not seen.
  Record as: *expected* to pick a 24-multiple mode if one is advertised — **verify on first
  boot** with `edid-decode` plus the script's `Mode select:` log line.

**NOTE — do not conflate two devices.** The compositor/4K appliance session runs on a Sony 4K
TV for testing (production display: 1080p Optoma projector). That is NOT the ViewEdge panel.
None of the 1200x1080 / rotate=180 / 90 Hz items above apply to it.
