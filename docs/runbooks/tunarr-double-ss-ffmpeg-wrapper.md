# Tunarr double-`-ss` ffmpeg wrapper (live-TV tune failures on certain files)

**Status:** wrapper deployed + enabled (2026-07-28); working. **Durability:** wrapper
lives on the `local` PVC and `ffmpegExecutablePath` in the tunarr DB — survives normal
pod rolls, NOT yet reproduced by an initContainer (fresh-PVC edge case → see below).

## Symptom
Some HEVC film/doc channels return HTTP 500 on `/stream/channels/<id>.m3u8` — "No
master playlist found" — for the *entire* airing of certain films, then recover when
the program rolls. PMP/Plex surfaces the 500 to the client as a bogus "unrecognized
file format" codec error (see also SQ-172: client should check status+content-type
before handing a URL to mpv). Distinct from the cache-purge dir-delete race fixed in
`717c81593`.

## Root cause (reproduced standalone, in-pod)
Tunarr's pipeline builder emits the seek **twice**: `-ss <v>` before `-i` (demuxer
seek) **and** again after `-i` (accurate/output seek), same value. For files with a
non-zero container `start_time` (e.g. audio/subs at −5ms → format start_time −0.005)
the redundant post-input seek makes ffmpeg produce **zero segments**.

Isolation matrix (Godzilla vs Hedorah Criterion rip, all seek positions fail):
| variant | result |
|---|---|
| baseline (double `-ss`) | ❌ 0 segments |
| **input-seek only (drop post-`-ss`)** | ✅ playlist ~5s |
| drop `-readrate` (keep double `-ss`) | ❌ (readrate not the cause) |
| software decode (double `-ss`) | ❌ (decoder not the cause) |

**File-specific, not position-specific.** No Tunarr config toggle exists (12
ffmpeg-settings keys, none seek-related). Proper fix is upstream (Tunarr should not
emit the redundant post-input `-ss`, or use `-copyts`/`-noaccurate_seek`) — relayed
to the client/SideQuest session that owns Tunarr upstream work.

## Local workaround (deployed) — `ffmpeg-wrap.sh`
`clusters/main/kubernetes/apps/media/tunarr/app/ffmpeg-wrap.sh` strips the first
post-input `-ss <v>` that duplicates the pre-input `-ss`, then **`exec`s** the real
`/usr/bin/ffmpeg` (so SIGKILL from Tunarr teardown hits ffmpeg directly — no orphaned
realtime process). Non-duplicate commands pass through unchanged; only the dup `-ss`
is removed, so audio-track mapping / language selection is untouched.

### Test gate (all passed before enabling)
- trigger file + double-`-ss` via wrapper → playlist ~5s (fix works)
- normal single-`-ss` via wrapper → unchanged (passthrough)
- SIGKILL the wrapper → real ffmpeg dies, 0 orphans (`exec`)
- real tunes post-enable: ch9 (was 500) → 200; ch13/16/20 → 200

### Enable / disable
```sh
IP=192.168.10.205                                   # tunarr LB
# copy wrapper into the pod's local PVC (persists across rolls):
POD=$(kubectl get pods -n media --no-headers | awk '/^tunarr-app-template-[0-9a-f]/{print $1}'|tail -1)
kubectl cp clusters/main/kubernetes/apps/media/tunarr/app/ffmpeg-wrap.sh \
  media/$POD:/root/.local/share/tunarr/ffmpeg-wrap -c tunarr-app-template
kubectl exec -n media $POD -c tunarr-app-template -- chmod +x /root/.local/share/tunarr/ffmpeg-wrap
# point ffmpegExecutablePath at it (GET-modify-PUT /api/ffmpeg-settings):
#   ffmpegExecutablePath = /root/.local/share/tunarr/ffmpeg-wrap
# DISABLE / rollback: set ffmpegExecutablePath back to /usr/bin/ffmpeg
```
Takes effect immediately (Tunarr reads the setting per-tune; no restart).

## Durability follow-up (NOT done)
Current delivery is the wrapper file on the `local` PVC + the DB setting. A fresh or
restored `local` PVC would leave `ffmpegExecutablePath` pointing at a missing file →
ALL transcodes break. To close this, deliver the wrapper on every boot via either:
- a `lifecycle.postStart` hook on the `main` container (uses its existing `/root/.local`
  mount; lowest risk — no new volume), or
- an initContainer writing to the `local` PVC (needs `targetSelector` so the init
  container mounts `/root/.local`; **must** helm-render verify the main mount isn't
  stripped — see `reference_truecharts_sidecar_mount_targetselector`).
Either way keep `ffmpegExecutablePath` pointed at the delivered path.
