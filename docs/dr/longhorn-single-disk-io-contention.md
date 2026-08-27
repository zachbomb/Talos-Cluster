# Single-disk I/O contention — fleet-wide probe failures

**Status:** researched 2026-08-26, not yet fixed.
**Severity:** caused a full control-plane cascade on 2026-08-25 and continues to kill
healthy apps nightly.

## The finding

**All 153 Longhorn replicas live on one physical SSD. The 2.2 TB `default-disk` holds zero.**

```
default-disk-080600000000   /var/lib/longhorn/      2196 GB  ->    0 replicas
ssd-hot                     /var/mnt/longhorn-ssd   1919 GB  ->  153 replicas
```

Every volume in the cluster — Plex's SQLite DB, every app config, every VolSync
source and its clone — contends for the same device. Measured sequential read on
the Plex DB volume: **38 MB/s**, which is HDD-class; SQLite's small random reads
are far worse.

## Why it bites

Contention shows up as **probe timeouts**, not as disk errors, and kubelet reports
the node perfectly healthy throughout (`MemoryPressure=False`, `DiskPressure=False`,
`Ready=True`). Requests and limits are not node conditions.

Observed 2026-08-26 within 45 minutes, four unrelated apps:

```
nebula-sync   failed LIVENESS probe, will be restarted
sonarqube     failed STARTUP  probe, will be restarted
neo4j         failed STARTUP  probe, will be restarted
tunarr        failed STARTUP  probe, will be restarted
```

Same class as the 2026-08-25 cascade, where BestEffort Longhorn engine-image pods
could not complete a trivial exec probe within 30s, were SIGKILLed, and took the
whole storage layer -> CSI attach -> kube-controller-manager leader lease with them.
That one is fixed (`core/kyverno-policies/app/longhorn-engine-image-resources.yaml`)
and has held, but the fix protects ONE workload from a condition that still exists.

## Amplifier: VolSync recursive chown on large volumes

`volsync-src-plex-config-config` repeatedly emits `VolumePermissionChangeInProgress`
for many minutes — kubelet recursively chowning Plex's **15 GB** config volume on
every backup, against the same disk Plex's database sits on.

There is an established exemption list for exactly this (`dest.enabled: false` for
calibre, calibre-web, tdarr, tunarr, ollama, tinymediamanager, deluge, mylar).
**plex-config is not on it, and neither is emby-config.**

## What was RULED OUT (do not re-litigate)

Plex was slow (13-31s search, `/related` at 25-40s) while sitting at 53m CPU.

- **NOT collection membership.** A/B with control: films in the new 1181/1258-member
  collections returned `/related` in 11-14s; films in NO collection took **25-40s**.
  Non-members were SLOWER. Deleting the collections would have fixed nothing.
- **NOT CPU.** CPU flat at 53m across a full slow search, 5 samples, zero movement.
- **NOT database cache.** `DatabaseCacheSize=2048`, already the max (default 40).
- **NOT a degraded volume.** `attached`, `robustness=healthy`, no rebuild.
- **NOT butler/scan/sessions.** 0 activities, 0 sessions, no butler task.
- **NOT database bloat.** 195 MB main DB.

Measurement traps hit while investigating, both self-inflicted:
- `curl -m N` times out CLIENT-side while PMS keeps processing; abandoned probes
  accumulated to **12-13 concurrent searches** and each new probe queued behind the
  backlog. Drain for 3 min before measuring, and watch the `(N live)` counter.
- ~2800 collection-tag writes at 0.15s pace broke client playback for ~40 min
  (`FailedToCreateSession` on POST /playQueues). Pacing to 1.0s did NOT fix it —
  sustained metadata WRITES contend with reads regardless of rate. Trivial endpoints
  (`/library/sections`, `/status/sessions`) stay at 60-90ms throughout, which is why
  nothing looks wrong from a health check.

## Also unresolved

Whether Plex's slow search is NEW is **unknown**: the rotated logs contain zero
searches before 2026-08-26, because search is not normally used. No baseline exists.
Plex became fast again (0.87-1.5s) after its pod was REPLACED at 18:33 PDT, which
suggests process-level degradation rather than a persistent data problem — but that
is one observation, not a mechanism.

## Proposed work

1. **Add `default-disk` to Longhorn scheduling and rebalance.** 2.2 TB is sitting
   idle while 153 replicas fight over one device. Biggest single win.
2. **Pin DB-heavy volumes** (plex-config, the CNPG clusters, sonarqube-db) to their
   own disk via Longhorn disk tags, so an app's backup cannot starve its own database.
3. **Add plex-config and emby-config to the lchown exemption list** — a recursive
   chown over 15 GB every backup is pure avoidable I/O.
4. **Audit remaining BestEffort pods.** 9 in longhorn-system alone, including
   `longhorn-driver-deployer` and `longhorn-ui`, both of which were crashlooping on
   2026-08-25. Requests only, never CPU limits.

Blast radius is every stateful app, so 1 and 2 want a maintenance window, not an
improvised change.
