# Runbook: Isolate etcd from QLC-pool contention (#158 close-out)

**Date:** 2026-07-23
**Goal:** Collapse etcd's ~100 ms fsync p99 *tail* by removing all other I/O tenants from the QLC pool (`local-zfs`) so etcd + its Solidigm SLOG have the pool nearly to themselves. **Zero-touch to etcd/Talos** (Talos does not support relocating etcd's data-dir — issue #9726, closed "not planned").

## Background / why this and not a dedicated etcd disk
- etcd lives at `/var/lib/etcd` on Talos EPHEMERAL = Talos VM system disk `vm-105-disk-0` = pool **`local-zfs`** = mirror of 2× **Sabrent Rocket Q QLC** NVMe + Solidigm D3-S4520 **SLOG** (`sdd`).
- The July QLC migration moved **Longhorn** onto the dedicated Intel D3-S4510 passthrough (`sdo`) but **left etcd on the QLC pool** — this is the residual #158.
- Talos blocks pointing etcd at a dedicated disk, so instead: **evict the *other* tenants from `local-zfs`.** Only two tenants exist: `vm-105-disk-0` (Talos/etcd — stays) and `vm-100-disk-0` (TrueNAS boot, 152 G — move off).
- SLOG already handles etcd sync writes (median 0.67 ms healthy); the tail is QLC-pool-busy (txg commits + reads). Removing tenants + cutting containerd write-bursts should collapse it.

## Pre-flight (host = Proxmox `pibbthecat`)
1. **Baseline the metric to beat** (cluster-side, I run this). **Captured 2026-07-23** from `http://192.168.10.89:2381/metrics` (183,851 samples): mean **3.44 ms**, p50 **<1 ms**, p95 **~15 ms**, p99 **~100 ms**; **1.68% of fsyncs in the 64–128 ms tail** + a few outliers to ~2–4 s. Target after Path 1: 64–128 ms tail → <0.1%, p99 → single/low-double-digit ms.
2. **SMART-check the target disk** before trusting TrueNAS's boot to it:
   ```
   smartctl -a /dev/sdn   # CT1000BX500SSD1 — confirm healthy, low wearout
   ```
3. Confirm `vm-100-disk-0` = 152 G fits the 1 TB BX500 (it does).
4. TrueNAS: back up config (System → General → Save Config) in case.

## Step 1 — Make the BX500 a Proxmox storage
```
zpool create -o ashift=12 -O compression=lz4 bx500 /dev/disk/by-id/<sdn-by-id>
pvesm add zfspool bx500 -pool bx500 -content images
```
(Single-disk pool, no redundancy — acceptable for a boot disk; TrueNAS *data* lives on the WD pool, not here.)

## Step 2 — Move TrueNAS boot off the QLC pool (the main win)
Live move (TrueNAS stays up):
```
qm move-disk 100 scsi0 bx500 --delete 1
```
- If live migration isn't allowed for that bus, stop VM 100 briefly (⚠️ media NFS drops while down — schedule it), move, start.
- Verify: TrueNAS boots, NFS shares (the 20 TB `/var/mnt` in Talos) reachable, media apps still mounted.
- Result: **only `vm-105-disk-0` (Talos/etcd) remains on `local-zfs`.**

## Step 3 — Cut containerd write-bursts on the pool (Talos-native GC)
containerd holds **450 images** (~350 stale Renovate digests, 72 GB) on the QLC pool; every image *pull* is a write-burst competing with etcd. Talos kubelet never GCs them (EPHEMERAL is 2.2 TB, % thresholds never trip). Fix = age-based GC via machine config:
```yaml
machine:
  kubelet:
    extraConfig:
      imageMaximumGCAge: 168h   # GC unused images older than 7d
```
Apply via `./forgetool genconfig` → commit → `./forgetool talos apply` (rolling, no reboot). Reclaims ~50 GB and stops future accumulation.

## Step 4 — Light ZFS confirm (host)
```
zfs get logbias,sync,primarycache local-zfs/vm-105-disk-0   # expect logbias=latency, sync=standard
```
- ARC: host has 128 GB RAM; if TrueNAS's footprint dropped, there's headroom — leave ARC cap unless memory pressure returns.
- `volblocksize` is fixed at zvol creation (can't tune live) — note for any future rebuild.

## Step 5 — Verify (cluster-side, I run this)
- After 24–48 h of normal load, re-pull etcd fsync p99 + backend-commit p99 from Prometheus.
- **Success = p99 fsync well under the 5 s lease cliff** (target < 20 ms, ideally single-digit ms) and no `apply request took too long` bursts during a Longhorn/deploy event.
- If the tail persists → escalate to Path 2 (single-node rebuild with system disk on non-QLC media).

## Rollback
- Nothing touches etcd/Talos, so recovery is trivial: `qm move-disk 100 scsi0 local-zfs --delete 1` puts TrueNAS boot back. Step 3 (GC age) is revertible by removing the kubelet setting.

## Sources
- Talos #9726 — Unable to change etcd wal-dir (etcd data-dir relocation unsupported): https://github.com/siderolabs/talos/issues/9726
- Talos Disk Management: https://docs.siderolabs.com/talos/v1.10/configure-your-talos-cluster/storage-and-disk-management/disk-management
