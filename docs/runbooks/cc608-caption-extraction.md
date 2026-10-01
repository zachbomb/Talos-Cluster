# Extracting embedded EIA-608 captions into `.en.srt` sidecars

One-shot procedure used for SQ-175 (2026-09-30). Broadcast captures (PBS `.mkv`
rips, raw HDTV `.ts`, DVD `.mpg`) often carry EIA-608/CEA-708 captions in the
video stream (MPEG-2 user data or H.264 SEI) with no subtitle track. Bazarr and
Plex cannot see those, so they count as "no English text subtitle". This runbook
pulls them out into a `<video basename>.en.srt` sidecar next to the video.

## Rules

- New sidecars only. Never overwrite an existing `.srt` / `.en.srt`; never remux
  or modify the video.
- Run as a Kubernetes Job in `media`, one file at a time, with requests AND
  limits (1-core cap). Do not exec into Plex, Tunarr, Emby or Bazarr.
- Avoid 00:00-04:32 PT (VolSync) and 06:00-09:00 PT (Plex butler).
- Image from docker.io, not tccr.io: `docker.io/linuxserver/ffmpeg:9.0-cli-ls83`
  (ffmpeg + ffprobe, runs fine as uid 1000, which is what owns the media tree).

## Do not trust ffprobe's `closed_captions` flag

`ffprobe -show_streams` only sets `closed_captions=1` when the decoder happens
to see A53 side data inside its probe window. On all eight SQ-175 candidates it
reported nothing, yet four of them carried full caption tracks. Detection has to
be empirical: decode and count cues.

Note that `-t` as an *input* option is ignored by the `lavfi` `movie` source, so
a "first five minutes" detection pass is really a full decode. That is fine:
720p H.264 decodes in ~4 min at the 1-core cap, 1080p in ~15 min, and 1080i
MPEG-2 in ~4 min. Just run one pass in `extract` mode.

## Extraction

The filtergraph treats `[ ] , : '` as syntax, so the script symlinks the file to
`/tmp/in.<ext>` first instead of trying to escape media filenames.

```sh
ln -sfn "/media/tv/.../episode.mkv" /tmp/in.mkv
ffmpeg -nostdin -hide_banner -loglevel error -y \
  -f lavfi -i "movie=/tmp/in.mkv:dec_threads=1[out0+subcc]" \
  -map 0:s:0 -f srt /tmp/out.srt
```

`dec_threads=1` plus `limits.cpu: 1000m` keeps it a background chore on a node
that already runs at 80%+ CPU.

## Validation gates (all must pass before anything is written)

1. Output non-empty.
2. At least 50 cues for anything longer than 20 minutes.
3. Last cue end time within 5% of the container duration.
4. At least 10 distinct text lines (rejects XDS-only or single-repeated-line
   garbage).
5. Target `<stem>.en.srt` and `<stem>.srt` do not exist; the write itself uses
   `set -C` (noclobber) so a race cannot overwrite.
6. Post-write: re-read the sidecar from the share and check size, cue count,
   md5 and last-cue time against the `/tmp` copy.

## Job shape

Inline NFS volume (`192.168.10.123:/mnt/Pibbs-Horde/media/data/media` at
`/media`, read-write only for the extract pass), scripts from a ConfigMap,
`emptyDir` at `/tmp`, `runAsUser/runAsGroup/fsGroup: 1000`,
`readOnlyRootFilesystem: true`, `backoffLimit: 0`, `activeDeadlineSeconds: 21600`,
`resources: {requests: {cpu: 250m, memory: 256Mi}, limits: {cpu: 1000m, memory: 1Gi}}`.
The Job is applied ad hoc with `kubectl apply` and deleted afterwards together
with its ConfigMap; it is deliberately not referenced by any Flux Kustomization.
The manifest template, `cc.sh` and the per-file log live in the Sidequest
evidence directory `verification/SQ-175/`.

Bazarr picks the new sidecars up on its own scheduled disk scan ("Update all
Episode Subtitles from disk"); no API call is needed.

## SQ-175 results (2026-09-30)

Eight candidates from the SQ-172 gap lists. Five carried captions and got a
sidecar; three decoded cleanly with no caption data at all.

| # | File | Duration | Cues | Last cue | Result |
|---|------|---------:|-----:|---------:|--------|
| 1 | American Masters S27E04 Billie Jean King.mkv (720p h264) | 4991 s | 1713 | 4931 s | `.en.srt` written |
| 2 | American Masters S28E05 Plimpton!.mkv | 4991 s | 1251 | 4958 s | `.en.srt` written |
| 3 | American Masters S28E08 The Boomer List.mkv | 4976 s | 1714 | 4958 s | `.en.srt` written |
| 4 | I'm Alan Partridge S00E08 (AMZN WEBDL) | 2548 s | 0 | - | no captions |
| 5 | I'm Alan Partridge S00E09 (AMZN WEBDL) | 2526 s | 0 | - | no captions |
| 6 | Anthony Bourdain S06E20 Rome (Raw-HD MPEG-2 .ts) | 2523 s | 864 | 2520 s | `.en.srt` written |
| 7 | NOVA S45E01 Black Hole Apocalypse (HDTV h264 .ts) | 6767 s | 2083 | 6757 s | `.en.srt` written |
| 8 | American Masters S11E04 Jack Paar (DVD .mpg) | 6999 s | 0 | - | no captions |

Every written sidecar was re-read from the share after the write and matched
the extraction (size, cue count, md5, last cue within 5% of duration). Bazarr
was not queried; it sees the files on its next scheduled disk scan. Per-file
logs and `results.csv` are in the SQ-175 evidence directory.
