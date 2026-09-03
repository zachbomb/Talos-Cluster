# Longhorn IM event 2026-09-03 01:27Z — third recurrence, recovered unattended

## What happened

Instance-manager was replaced at ~01:27Z. Losing it detaches every Longhorn volume,
so every stateful pod lost its storage at once.

    98 attached/healthy  ->  4 attached, 94 attaching, 11 faulted
    longhorn-manager: "All replicas are failed, set engine salvageRequested to true"

Loudest victim was Tunarr, killed with:

    Command was killed with SIGBUS (Bus error due to misaligned, non-existing
    address or paging error): /tunarr/tunarr server

**SIGBUS here means the volume vanished under an mmap**, not a corrupt database.
Tunarr mmaps a 596 MB SQLite db plus a Meilisearch index. This is the mmap analogue
of the `EIO on settings.json` tell from the previous recurrence. immich CrashLooped
for the same reason.

## Recovery: unattended, ~6 minutes

    18:28 local  attached=4   attaching=94  faulted=0
    18:31        attached=28  attaching=61
    18:34        attached=94  attaching=0   faulted=0

The 11 faulted volumes cleared themselves via Longhorn's own salvage path. **No
intervention was made and none was needed** — consistent with the standing note that
this is the recovery, not the fault. Tunarr took a further ~10 min and exactly one
restart, passing through the documented connection-REFUSED-in-6ms stage before 200.

Final state verified: 94 attached/healthy, 0 faulted; Plex/Emby/Sonarr/Bazarr/Tunarr
all 200; **ch22 intact at 206/206 valid, 0 stale.**

## Conditions — still not explained by request exhaustion

    CPU requests    76%
    memory requests 89%
    node loadavg    410-441 on 10 cores

Same sub-100% band as the second recurrence. Load is not sufficient as an explanation:
`node_load1` on this node independently hit **703 at 13:21 and 348 at 17:21 the same
day** with none of this session's work running. It is chronically spiky (12 → 703).

## Attribution — stated plainly

A subtitle ffprobe/ffmpeg sweep of mine was running on this node when the event fired.
**Causation was not established and is not claimed.** The sweep touched NFS, not
Longhorn, and the node was independently unstable all day. It was stopped on discovery
and deliberately not restarted the same night.

## Method notes

* Read the instance-manager's **`age`**, not `restartCount` — it was `restarts=0` while
  being 83 seconds old, because the pod is *replaced*, not restarted.
* `pgrep -f <script>` self-matches the probing shell — it reported "2 running" for a
  script that had been deleted. Walk `/proc/<pid>/cmdline` and exclude the shell.
* On the tunarr pod, `varlogs`, `tmp` and `shared` are **emptyDir**, not volumes. Only
  `config`, `icache`, `local` are PVCs. Checkpoints written to `/var/logs` do NOT
  survive a container restart — this destroyed the sweep's queue and progress twice.
