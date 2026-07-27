# Runbook: Move etcd off the QLC pool via Proxmox disk-move (#158 definitive fix)

**Date:** 2026-07-27
**Path chosen:** B (Proxmox-level `zfs send | recv` of the Talos system disk onto the Solidigm).
**Goal:** Relocate the Talos VM system disk — which carries `/var/lib/etcd` — from the QLC mirror (`local-zfs`) onto the **Solidigm D3-S4520** (currently the pool SLOG), collapsing etcd's ~100 ms fsync p99 tail that has repeatedly cascaded into the Longhorn IM death-spiral (#158).

## Why Path B (and not the research's Talos EPHEMERAL relocation)

The obvious Talos-native approach — a `VolumeConfig` with `name: EPHEMERAL` + `diskSelector` — is a trap on an already-provisioned node:
- Talos only applies an EPHEMERAL VolumeConfig **when the volume is not yet provisioned**. On a running node it is a no-op unless you **wipe EPHEMERAL first**, destroying `/var` incl. etcd → single-node etcd snapshot/restore.
- Two open upstream bugs make it fragile: [#11022](https://github.com/siderolabs/talos/issues/11022), [#9394](https://github.com/siderolabs/talos/issues/9394).

Talos does not care which physical disk backs `scsi0`. Moving the zvol **one layer down at Proxmox** reaches the identical end state (etcd on the Solidigm) with:
- **No etcd wipe / snapshot-restore** — etcd blocks are copied intact.
- **No talconfig / genconfig change** — avoids the known apply-drift landmine (node has drifted from talconfig; a full `talos apply` reboots + strips config).
- **No install-disk-selector collision** — `installDiskSelector: size <= 2400GB` (talconfig.yaml) is untouched; `scsi0` stays a 2 TB disk, just on different media.
- **Instant rollback** — the old zvol is retained until verified; revert = repoint `scsi0` back.

## Key facts (from 2026-07-27 host audit)

| Item | Value |
|---|---|
| Talos VM | 105, 8 cores / 48 GB. `scsi0: local-zfs:vm-105-disk-0,cache=writeback,discard=on,iothread=1,size=2T,ssd=1` (the disk we move). Also `efidisk0: local-zfs:vm-105-disk-1` (1 MB EFI — leave it, idle) and `scsi2:` D3-S4510 Longhorn passthrough (untouched). |
| Talos system disk REFER | **1.23 TB** confirmed on `local-zfs` — but `/var/lib` is only ~117 GB → **~1.1 TB is stale, un-TRIMmed blocks** to reclaim via fstrim |
| Target = SLOG (same disk) | `SOLIDIGM_BYID = SLOG_BYID =` **`ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B`** (`sdd`, 447 GiB / 480 GB S4520). PF-1 confirmed it IS the `local-zfs` `logs` vdev. SMART PASSED, **0 % wear, 326 power-on hrs** (near-new). |
| QLC mirror | `nvme0n1` + `nvme1n1` (2× Sabrent Rocket Q) = `local-zfs` `mirror-0` |
| `local-zfs` | 2× Sabrent Rocket Q QLC **mirror**, 3.5 TB usable, 1.33 TB free |
| Other `local-zfs` tenants | `vm-100-disk-0` (TrueNAS boot, 152 GB, low-I/O), `vm-105-disk-1` (3 MB) |
| EPHEMERAL encryption | **none** (`machine.systemDiskEncryption` not set) → host can mount the xfs directly |
| Longhorn data | on the **D3-S4510** (`sdc`, UserVolumeConfig, separate disk) — **untouched** by this move |

**Redundancy tradeoff to accept:** QLC is a 2-disk mirror; the Solidigm is a single disk. This trades etcd redundancy for speed. Mitigated by (a) keeping frequent etcd snapshots (Phase 5 adds a CronJob) and (b) Longhorn/VolSync backups of app data. #158's failures are latency-driven, not disk-failure-driven, so this is the right trade.

---

## Pre-flight (capture your specifics + safety nets)

### PF-1 — Host facts (run on Proxmox `pibbthecat`, substitute into later steps)
```bash
qm config 105                                   # confirm scsi0 line + that there is no 2nd system disk to worry about
ls -l /dev/disk/by-id/ | grep -iE 'solidigm|SSDSC2KB480|<solidigm-serial>'   # SOLIDIGM_BYID
zpool status local-zfs                          # confirm sdd is the 'logs' vdev; note its by-id  -> SLOG_BYID
zpool list -v local-zfs
zfs list -o name,used,refer,avail local-zfs/vm-105-disk-0
smartctl -a /dev/sdd | grep -iE 'model|wear|percentage|health'   # confirm Solidigm healthy, low wearout
```
Record: `SOLIDIGM_BYID=`, `SLOG_BYID=` (may be the same physical disk — the Solidigm IS the SLOG).

### PF-2 — Baseline the metric to beat (cluster-side, I run this)
Already captured 2026-07-23: etcd WAL fsync mean **3.44 ms**, p99 **~100 ms**, **1.68 % of fsyncs in the 64–128 ms tail**. Re-pull just before the window from `http://192.168.10.89:2381/metrics`. **Target after move:** 64–128 ms tail → <0.1 %, p99 → single/low-double-digit ms, zero `apply request took too long` during a Longhorn event.

### PF-3 — Belt-and-suspenders etcd snapshot (cluster-side, I run this)
Even though the move is non-destructive, snapshot first:
```bash
talosctl -n 192.168.10.89 etcd snapshot /tmp/etcd-premove-$(date +%s).db
# copy it off the node to the workstation / a backup location
```
Rollback safety net = this snapshot **plus** the retained old zvol.

### PF-4 — Confirm the destination will fit
Hard gate for Phase 3: the send only fits if reclaimed REFER < ~400 GB. Phase 1 (fstrim) makes this true; **do not proceed to the send until verified.**

---

## Phase 1 — (Optional, live) shrink live `/var` before the window
Reduces the data the send must ship (the fstrim in Phase 3 does the heavy reclaim; this trims *live* bloat).
- Prune stale containerd images (imageMaximumGCAge resets on reboot, so ~479 images have accumulated):
  ```bash
  talosctl -n 192.168.10.89 -- crictl rmi --prune    # removes images not referenced by any container
  ```
- Verify `/var/lib` dropped: `talosctl -n 192.168.10.89 usage /var/lib`.
- No downtime; skippable — Phase 3's host-side fstrim reclaims the stale allocation regardless.

---

## Phase 2 — Free the Solidigm and make it a Proxmox storage (host)

> ⚠️ **CORRECTED SEQUENCING (PF-1 finding):** These steps run **INSIDE the downtime window, AFTER the Talos VM is shut down** (Phase 3 step 2) — **NOT** before. Removing the SLOG while etcd is **live** reverts its fsync from ~0.73 ms back to ~84 ms (the #158 condition per `project_proxmox_etcd_disk_layer` / the Jul-13 SLOG upgrade note), which could trigger the cascade in the interim. With the VM off, etcd isn't writing, so the SLOG-less window is harmless. Nothing SLOG-touching happens before shutdown; the only safe pre-window prep is the etcd snapshot (PF-3) and the optional containerd prune (Phase 1).

1. **Remove the SLOG from `local-zfs`** (log-vdev removal is supported; VM already off):
   ```bash
   zpool remove local-zfs ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B
   zpool status local-zfs         # confirm no 'logs' vdev remains; pool ONLINE
   ```

2. **Wipe the freed disk's old ZFS labels and create the new single-disk pool:**
   ```bash
   wipefs -a /dev/disk/by-id/ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B   # clears the old SLOG label
   zpool create -o ashift=12 -O compression=lz4 -O atime=off solidigm \
     /dev/disk/by-id/ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B
   pvesm add zfspool solidigm -pool solidigm -content images -sparse 1   # -sparse 1 = thin zvols (required)
   ```
   `-sparse 1` is required: the destination zvol keeps its 2 TB `volsize` but only consumes referenced blocks (~150 GB post-fstrim), which must fit the 447 GiB pool.

---

## Phase 3 — The move (downtime window — single node, cluster is down)

The Kyverno `system-cluster-critical` fix (committed 95ce16689) now protects the reboot cold-start, so bring-up is far safer than the 2026-07-26 incident. Still shed VolSync to avoid a mover storm on boot.

1. **Shed load for a clean shutdown/boot** (cluster-side, I run these):
   ```bash
   flux suspend kustomization volsync          # already suspended from the outage; confirm
   kubectl -n volsync scale deploy --all --replicas=0
   # (Optional) freeze helm-controller + scale media to 0 so boot returns to a minimal herd:
   kubectl -n flux-system scale deploy helm-controller kustomize-controller --replicas=0
   ```

2. **Shut down the Talos VM cleanly** (host):
   ```bash
   qm shutdown 105        # graceful; wait for stop. (qm stop 105 if it hangs > 2 min)
   qm status 105          # -> stopped
   ```

3. **→ Now run Phase 2** (remove SLOG + create the `solidigm` pool) — safe only now that etcd is off.

4. **Reclaim the stale ~1.1 TB via host-side `fstrim` of the offline EPHEMERAL xfs** (host):
   ```bash
   # Expose the zvol partitions to the host
   ls /dev/zvol/local-zfs/vm-105-disk-0*        # partitions appear as ...-part1..-part6
   # EPHEMERAL is the large final partition (part6, ~2.2TB). Mount READ-WRITE and trim:
   mkdir -p /mnt/eph
   mount -t xfs -o rw,nouuid /dev/zvol/local-zfs/vm-105-disk-0-part6 /mnt/eph
   df -h /mnt/eph                                # sanity: shows the etcd/containerd data
   fstrim -v /mnt/eph                            # discards freed blocks back to the zvol (discard=on)
   umount /mnt/eph
   zfs list -o name,used,refer local-zfs/vm-105-disk-0   # HARD GATE: REFER must now be < ~400G
   ```
   - `nouuid` avoids an xfs duplicate-UUID mount refusal. Mount **only** EPHEMERAL; do not touch STATE/META.
   - If the EPHEMERAL partition is not `part6`, identify it with `lsblk -f /dev/zvol/local-zfs/vm-105-disk-0` (the large xfs one).
   - **If REFER does NOT drop below ~400 GB, STOP.** Do not attempt the send; investigate (was the 1.1 TB actually stale? is there live data?). Fall back to Path A (contention reduction) for the window.

5. **Snapshot and send to the Solidigm** (host):
   ```bash
   zfs snapshot local-zfs/vm-105-disk-0@migrate
   zfs send local-zfs/vm-105-disk-0@migrate | zfs recv solidigm/vm-105-disk-0
   zfs list -o name,used,refer solidigm/vm-105-disk-0     # confirm it landed (~150G refer)
   ```
   ~150 GB over local NVMe → SATA SSD ≈ a few minutes.

6. **Repoint the VM's system disk and boot** (host):
   ```bash
   qm rescan --vmid 105                    # registers solidigm:vm-105-disk-0 as an unused disk
   qm set 105 -scsi0 solidigm:vm-105-disk-0,cache=writeback,discard=on,iothread=1,ssd=1
   qm config 105 | grep -E 'scsi0|unused'  # confirm scsi0 -> solidigm; note the old disk as unusedN
   qm start 105
   ```
   - Keep the OLD disk attached as `unusedN` (do **not** delete yet — it is the rollback).
   - `qm config` must show `scsi0: solidigm:vm-105-disk-0`. Match the original scsi0 flags (`cache=writeback,discard=on,iothread=1,ssd=1`) exactly.

---

## Phase 4 — Verify (cluster-side, I run this)

1. **Node + etcd healthy:**
   ```bash
   talosctl -n 192.168.10.89 health
   talosctl -n 192.168.10.89 service etcd status          # Running, healthy
   kubectl get --raw='/healthz?verbose' | tail
   ```
2. **etcd is actually on the Solidigm now** — confirm on the host: `zpool iostat -v solidigm 2` shows write activity under load; `local-zfs` etcd zvol is idle.
3. **fsync tail collapsed:** after ~30–60 min of normal load (bring apps back first), re-pull etcd fsync p99 + backend-commit p99. Success = p99 well under the 5 s lease cliff (target single/low-double-digit ms), no `apply request took too long` bursts during a Longhorn/deploy event.
4. **Staged bring-back:** unfreeze helm/kustomize controllers → non-media returns on Flux cadence → un-suspend + `kubectl scale -n media deploy --all --replicas=1`. Resume VolSync **last**, watch for a mover storm (Kyverno priority now guards the IM/Kyverno, but re-enable gradually).

---

## Phase 5 — Cleanup + hardening (after 24–48 h of clean operation)

1. **Destroy the old zvol** (only after full confidence — this is the point of no return for rollback):
   ```bash
   qm set 105 -delete unusedN         # detaches + removes local-zfs:vm-105-disk-0
   zfs destroy local-zfs/vm-105-disk-0@migrate   # if the snapshot lingers
   # frees ~150G (post-trim) + reclaims the stale allocation on local-zfs
   ```
2. **Add a redundancy safety net for single-disk etcd** — a periodic etcd snapshot CronJob to S3/MinIO (belt-and-suspenders atop Talos's native snapshots).
3. **Consider reverting the etcd tuning** now that fsync is fast (controlplane.yaml): `heartbeat-interval: 500` / `election-timeout: 5000` were #158 band-aids. Revert to defaults (100/1000) **only after** confirming the tail is gone — via surgical `talosctl patch mc` (NOT full apply — drift landmine), then bake into talconfig for the next clean genconfig.
4. **Re-evaluate the SLOG:** `local-zfs` no longer has a log vdev. Its remaining tenant (TrueNAS boot) is low-I/O, so likely fine. If TrueNAS write latency regresses, the freed Solidigm capacity can host both a small SLOG partition and etcd — but only if needed.

---

## Rollback (at any point before Phase 5)

Non-destructive throughout. To revert:
```bash
qm shutdown 105
qm set 105 -scsi0 local-zfs:vm-105-disk-0,cache=writeback,discard=on,iothread=1,ssd=1
qm start 105
```
etcd is exactly as it was (the old zvol was never modified — only snapshotted + read). If the boot itself fails, restore the PF-3 etcd snapshot onto a fresh node as the last resort.

## Sources
- Talos System Volumes / EPHEMERAL provisioning: https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/system
- Talos #11022 (EPHEMERAL volumeconfig update fails), #9394 (can't place EPHEMERAL on another disk)
- Supersedes the indirect Path 1 in `2026-07-23-etcd-qlc-isolation.md` (that runbook's "Talos can't relocate etcd" premise is corrected here — it can, but the Proxmox move is safer).
