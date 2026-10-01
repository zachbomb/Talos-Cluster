# Tunarr database: storage options (decision doc)

Written 2026-09-30, after the third Tunarr API hang that day.

## The problem

Tunarr's SQLite database (`/root/.local/share/tunarr/db.db`, 950 MB, up from 587 MB in August) sits on a Longhorn volume. Tunarr runs its SQLite calls synchronously on the Node event loop. When one page read stalls, the whole API stops answering: `/api/*` times out while TCP still connects. Live TV tunes fail during that time, and so do guide checks and session reads.

The signature is the same every time: the main thread (`/tunarr/tunarr server`, pid 28) sits in `D` state with `wchan=folio_wait_bit_common`. See memory `reference_tunarr_hang_sqlite_dstate.md` for the diagnosis procedure.

| When (PDT) | Duration | Recovery | Context |
|---|---|---|---|
| 09-24 15:12 | hours of degradation | pod delete | bulk relink writes + node saturation |
| 09-24 16:27 | ~5 min | pod delete | node saturation only |
| 09-30 02:19 | ~4 min | self | inside the VolSync window |
| 09-30 10:45 | ~45 s | self | daytime |
| 09-30 11:03 | ~3 min | liveness restart 11:06, API back 11:07:43 | daytime; io PSI some avg60 24.6%, mem PSI 13.6%, MemAvailable 10.4 GB |

The self-heal that shipped on 09-24 (`httpGet /api/version` liveness, 6x30s) is working as a backstop. It does not prevent the hangs.

## Constraint that shapes every option

`docs/dr/longhorn-single-disk-io-contention.md`, section "CORRECTION (2026-08-27)", establishes two facts:

- **Every Longhorn replica lives on one physical SSD** (Intel D3-S4510, `ssd-hot`). There is no second Longhorn disk to pin to.
- **Talos EPHEMERAL** (`/var`, and so `openebs-hostpath`) is a thin zvol on the **444 GB Solidigm pool that also holds etcd**.

So "off Longhorn" is not the same as "off contended storage". Every local option moves the DB either onto the busy SSD or next to etcd.

## New finding: snapshot churn on the DB volume

Volume `pvc-68e36d98…` (the 5 Gi `/root/.local` volume, which holds `db.db`) is in Longhorn's `default` recurring-job group:

- `snapshot` daily at 01:00 UTC, retain 14.
- `snapshot-delete` at 02:00 UTC.
- `snapshot-cleanup` at 02:20 UTC.
- `trim` at 02:40 UTC.

It currently holds **15 snapshots totalling 29.4 GB on a 5 GB volume**, because SQLite rewrites 1.5–2.3 GB of blocks a day. Every day Longhorn has to coalesce a ~2 GB snapshot into its parent. That is extra IO on the same single SSD, spread over thousands of fragmented delta blocks.

- These snapshots are **redundant**: VolSync already backs the volume up to S3 with restic every day.
- Not proven: I have not shown that this churn caused any specific hang. The coalesce jobs run at 19:00–19:40 PDT, which matches none of the hang times above. It is load on the one disk that everything shares, not a smoking gun.

## Options

### Option 0: take the DB volume out of the Longhorn snapshot group (cheap, do regardless)

- **Change:** label the Tunarr DB volume `recurring-job-group.longhorn.io/default: disabled`, or add a Tunarr-specific group with `retain: 1`. Then delete the 14 old snapshots, a few at a time rather than all at once.
- **Effect:** frees about 29 GB of SSD, removes the nightly ~2 GB coalesce, and shortens the replica's snapshot chain.
- **Risk:** you lose point-in-time Longhorn rollback for Tunarr. VolSync restic still gives daily restores from S3.
- **Cost:** about 15 minutes. It is reversible by re-labelling.
- **Doesn't fix:** the underlying read stalls under node-wide IO pressure.
- **Also:** a TrueCharts upgrade might recreate the label, so check after chart bumps.

### Option 1: shrink the DB (cheap, do regardless)

The DB grew 62% in about 6 weeks, and a smaller DB means fewer page reads on the event loop.

- Find what grew: run `sqlite3 db.db "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC LIMIT 15"` against a **copy**. Likely candidates are program or lineup history, and guide caches.
- Then, in a quiet window with Tunarr stopped, run `VACUUM`. Take a VolSync snapshot first.
- Delete the stale May `.bak` files and `db.db.pre-restore-*`. They're small (about 72 MB) but they're clutter.
- **Risk:** low if the backup is taken first. It needs Tunarr stopped for a few minutes, which is a viewer outage, so warn the Pi/PMP session.

### Option 2: move `db.db` to `openebs-hostpath` (EPHEMERAL, Solidigm pool)

- **Change:** add a small persistence entry (1–2 Gi, `storageClass: openebs-hostpath`) at `/root/.local/share/tunarr`. Copy the DB over with Tunarr stopped, and keep VolSync on it.
- **What it removes:** the Longhorn engine, replica process and iSCSI (tgt) hop from every page read. On this node those hops are what the probe-timeout history (the IM death-spirals) tracks.
- **Risk:** the DB then writes to **the same pool as etcd**, and the 07-27 etcd disk move exists precisely because etcd fsync latency caused outages.
  - Tunarr's write rate is modest: an 8 MB WAL, and about 2 GB/day of changed blocks, which averages ~25 KB/s.
  - But SQLite fsyncs on every commit.
  - It needs a measurement gate: watch `etcd_disk_wal_fsync_duration_seconds` p99 for 48 h before and after, and roll back if p99 rises by more than 25%.
- **Other trade-offs:**
  - A hostpath PV is node-bound. That's irrelevant on this single-node cluster.
  - Longhorn snapshots no longer apply; VolSync still does.
  - The VolSync mover must be able to mount the hostpath PVC. TrueCharts VolSync works with any storage class, but verify the first backup and the lchown behaviour, because Tunarr already runs `dest.enabled: false`.
- **Effort:** about 1 h plus the 48 h watch. Rollback means copying the DB back and reverting the commit.

### Option 3: page-cache insurance (keep the DB hot in RAM)

- The stall is a page **read** (`folio_wait_bit_common`), which means the page had been evicted. At 10 GB MemAvailable, under memory PSI of about 13%, the node is reclaiming page cache.
- Tunarr has no knob for SQLite `cache_size` or `mmap_size`. The workable version is to raise the container's memory request so the cgroup is less of a reclaim target. Optionally add a periodic `cat db.db > /dev/null` sidecar to keep the file warm. That's a hack; measure it before trusting it.
- **Effect:** partial at best. It doesn't touch writes, and it spends RAM on a node that has had OOM and kubelet-starvation incidents.
- **Recommendation:** skip unless Options 0–2 fail.

### Option 4: tmpfs DB + Litestream replication (rejected)

This would give RAM-speed reads and writes, but a crash loses up to the Litestream lag. It also adds a new moving part and needs about 1 GB of RAM pinned. Too much risk for a TV guide DB.

### Option 5: SQLite on NFS (TrueNAS) (rejected)

SQLite locking over NFS is unsafe and prone to corruption. Moving it would also shift the stall to the USB JBOD link, which has its own failure history.

### Option 6: a second physical SSD for Longhorn (the real fleet-wide fix)

- This is the only way to separate IO for Tunarr, Plex, Emby, the arr DBs and VolSync.
- It's a hardware and hypervisor change, and not repo-controlled. See `longhorn-single-disk-io-contention.md` item 2.
- It would fix this class for every app, not just Tunarr.

## Recommendation

1. **Now:** Option 0 (snapshot group) and Option 1 (find what's bloating the DB, then `VACUUM` in a quiet window). Both are cheap and reversible, and both cut load on the one disk.
2. **If a hang recurs within about 2 weeks:** Option 2, behind the 48 h etcd-fsync gate.
3. **Longer term:** Option 6 is the actual fix for this whole class of incident across the media stack.

Every step that stops Tunarr needs a heads-up to the Pi/PMP session first (standing rule), and a check of `/api/sessions` for live viewers.
