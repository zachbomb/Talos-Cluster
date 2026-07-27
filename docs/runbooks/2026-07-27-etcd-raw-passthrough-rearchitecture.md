# Runbook: Re-architect etcd onto a RAW Solidigm passthrough (permanent pool-ratchet fix)

**Date:** 2026-07-27 (planning — NOT executed)
**Status:** ⚠️ **SUPERSEDED / NOT NEEDED** (2026-07-27, same day). The pool bloat that motivated this was NOT the discard path — it was a **leftover `@migrate` zfs snapshot** pinning 185 G of freed blocks. `zfs destroy solidigm/vm-105-disk-0@migrate` took the pool 87% → 43% with zero downtime, and a clean fstrim then reclaimed further (203→194 G) — proving **in-guest discard works**. The only residual is a fixed ~35% volblocksize-fragmentation floor (minor, non-growing), not worth a destructive reinstall. This runbook is kept ONLY as a documented last-resort option if the fragmentation floor ever becomes a real problem; **do not execute it** — the CronJobs + snapshot hygiene self-manage the pool.
**Goal:** Eliminate the Solidigm pool space-ratchet by removing the ZFS/zvol layer under etcd. Move the Talos system disk from a **thin 16 K zvol on a ZFS pool** to a **raw disk passthrough** of the Solidigm — exactly how the D3-S4510 (Longhorn) is attached today (`scsi2: /dev/disk/by-id/ata-INTEL…`). etcd then writes straight to the SSD, TRIM/discard works at native granularity, and the pool can never ratchet full.

## Why (root cause, see project_etcd_solidigm_diskmove_done_2026_07_27 memory)
The 2026-07-27 disk-move put the Talos system disk on a `volblocksize=16K` thin zvol. The guest xfs writes/discards at 4 K; ZFS only frees a 16 K volblock when all four 4 K sub-blocks are free+discarded, so post-churn scatter reclaims ~nothing (measured: `/var` dropped 202→144 G but pool ALLOC stayed 388 G — **zero reclaim**). In-guest fstrim is a no-op here; the pool grows monotonically. A raw disk has no zvol layer, so discard reclaims normally.

**This does NOT re-introduce #158.** etcd stays on the fast Solidigm — only the *layer* under it changes (raw vs zvol). fsync stays resolved.

## Tradeoffs / what this does NOT change
- Still a **single drive** → no redundancy (same as today). Mitigate with etcd snapshots; true redundancy = a 2nd SSD to mirror (separate hardware decision). ZFS's single-drive value (checksums/compression/snapshots) is lost, but for a churny 4 K etcd/containerd volume that was net-negative anyway.
- **Cheaper alternative to try FIRST** (avoids this whole reinstall): a `qm set 105 -scsi0 …` disk-option change to fix QEMU discard propagation (drop `iothread`, or `detect-zeroes=unmap`) + one VM restart, then test whether an in-guest fstrim reclaims. If it does (even partially), this reinstall may be unnecessary. The 16 K volblocksize still caps reclaim, so raw passthrough remains the clean answer — but the qm test is 10 min vs a reinstall.

## Key difference from the 2026-07-27 disk-move
That move was **non-destructive** (`zfs send`). This is **destructive** — the 2 TB zvol's partition layout can't be copied onto a 444 GB raw disk, so Talos must be **reinstalled** onto the raw disk and **etcd restored from snapshot**. It's a single-node Talos disaster-recovery, done deliberately.

## Safety nets (BOTH must exist before starting)
1. **etcd snapshot** taken at pre-flight (the cluster state).
2. **The pre-migration disk still exists** as `unused0: local-zfs:vm-105-disk-0` (the QLC zvol from before the 07-27 move — do NOT destroy it until this re-architecture is proven). **Rollback = repoint scsi0 back to it and boot** → returns to the exact pre-reinstall state. Confirm it's still present: `qm config 105 | grep unused`.
3. **Longhorn data is on the D3-S4510** (`scsi2`, a separate passthrough) — untouched by wiping the Solidigm. App PVCs survive. VolSync/S3 backups exist as a third line.

## Procedure

### Phase 0 — Pre-flight (cluster-side + host)
1. Cluster healthy, VolSync idle (no mover storm), note the current state.
2. **etcd snapshot off-node:** `talosctl -n 192.168.10.89 etcd snapshot /path/etcd-preraw-$(date).db` → copy off the workstation.
3. Save the running machineconfig: `talosctl -n 192.168.10.89 get mc v1alpha1 -o yaml > mc-backup.yaml`.
4. Confirm rollback disk present: `qm config 105 | grep -E 'unused|scsi2'` (unused0 = QLC rollback; scsi2 = D3-S4510 Longhorn).
5. Note the Solidigm by-id: `ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B`.
6. **Shed load** (freeze helm+kustomize controllers → 0, scale app namespaces → 0, suspend/scale VolSync) — same as the 07-27 move, to keep the post-reinstall boot herd small.

### Phase 1 — talconfig: point the installer at the raw Solidigm
Update `installDiskSelector` in talconfig to match the **Solidigm specifically** (distinct from the D3-S4510 1.9 TB and the QLC). By size window or serial:
```yaml
installDiskSelector:
  # Solidigm S4520 480GB (447GiB). Distinct from D3-S4510 (1.9TB) + QLC.
  size: '>= 400GB && <= 500GB'   # or match by serial/model via a CEL diskSelector
```
Render via `./clustertool genconfig`, commit. (Handle the SOPS decrypt-in-place + auto-stage gotcha — `git status` before commit.)

### Phase 2 — Swap the disk (host, VM off)
1. `qm shutdown 105` (graceful).
2. Detach the zvol system disk: `qm set 105 -delete scsi0` (moves it to unused — keep it, do NOT destroy yet; it's a second rollback alongside unused0).
3. Destroy the solidigm ZFS pool + wipe the disk:
   ```
   zpool destroy solidigm
   wipefs -a /dev/disk/by-id/ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B
   ```
4. Attach the **raw** Solidigm as scsi0 (passthrough, like scsi2):
   ```
   qm set 105 -scsi0 /dev/disk/by-id/ata-SOLIDIGM_SSDSCKKB480GZ_PHYK5051023U480B,discard=on,iothread=1,ssd=1
   ```
5. Attach the Talos installer ISO (matching v1.13.5 + the schematic/extensions) and set boot order to it for this one boot, OR use Talos PXE.

### Phase 3 — Reinstall Talos + recover etcd
1. Boot the VM → Talos maintenance mode (from ISO/PXE).
2. Apply the machineconfig: `talosctl apply-config --insecure -n 192.168.10.89 --file <rendered-controlplane.yaml>` → Talos installs to the raw Solidigm (per installDiskSelector).
3. **Recover etcd from the snapshot** (single-node): `talosctl bootstrap -n 192.168.10.89 --recover-from-snapshot /path/etcd-preraw.db` (verify exact flag for the Talos version — this is the step to validate on a throwaway VM first).
4. Remove the installer ISO from the boot order once installed; boot from the Solidigm.

### Phase 4 — Verify (cluster-side)
1. `talosctl -n 192.168.10.89 health`; node Ready; etcd `HEALTH OK`; member list correct.
2. **Verify the raw disk has NO ZFS layer + discard works:** in-guest `fstrim -v /var`, then confirm actual reclaim (df drop should now correspond to real reclaim — no zvol to hide it). Longhorn volumes (D3-S4510) re-attach; apps come back staged.
3. etcd fsync still clean (should be — same SSD, just raw).

### Phase 5 — Bring back + cleanup
1. Staged bring-back (unfreeze Flux, scale apps, resume VolSync last) — same as the 07-27 move.
2. **Remove the now-ineffective `node-fstrim`** CronJob (in-guest reclaim now works on raw, but the daily job is still low-value; keep the weekly `node-image-prune` for image bounding). Re-evaluate the `solidigm-etcd-pool` alert thresholds (the pool no longer ratchets, so 90/95% become real signals).
3. After 24–48 h confidence: destroy the rollback disks (`unused0` QLC zvol + the detached solidigm zvol).

## Rollback (at any point pre-Phase-5-cleanup)
- Before/after the wipe: `qm shutdown 105` → `qm set 105 -scsi0 local-zfs:vm-105-disk-0` (the retained unused0 QLC disk = pre-move state) → boot. etcd is exactly as it was at the 07-27 move.
- If etcd restore fails on the raw disk: the pre-flight snapshot is the last resort.

## To validate before executing (open questions)
- Exact `talosctl bootstrap --recover-from-snapshot` invocation for v1.13.5 (test on a throwaway single-node VM).
- Whether Talos needs the installer ISO vs a `talosctl reset --wipe-mode` in place (the ISO path is more predictable for a disk swap).
- installDiskSelector must NOT also match the D3-S4510 (1.9 TB) — verify the size/serial selector is unambiguous with 3 disks attached (Solidigm, D3-S4510, and no QLC system disk anymore).
- EFI: `efidisk0` stays on local-zfs (QLC); confirm the VM still boots (EFI NVRAM → Solidigm bootloader) after reinstall.
