# JBOD Passthrough Cutover — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop passing the whole xHCI controller through to the TrueNAS VM, and instead let the Proxmox host own the six USB-attached Seagate drives, passing them per-disk as `scsi-block` LUNs — the exact pattern the eight WD drives already use with a zero-incident record on this host.

**Architecture:** Remove `hostpci2: 0000:3a:00.0` from VM 100. The host's mature `xhci_hcd` driver then owns USB error recovery for the enclosure instead of the guest's passthrough-fragile path. Each Seagate gets a stable udev symlink (`/dev/tn9`–`/dev/tn14`) keyed on its serial, referenced by a `scsi-block` device in the VM's `args:` line. ZFS keeps addressing pool members by partition UUID, so `Pibbs-Horde` should import unchanged.

**Tech Stack:** Proxmox VE (host `pibbthecat`), QEMU/KVM, udev, vfio-pci, TrueNAS SCALE (VM 100), OpenZFS.

**This is hypervisor work. NOTHING here is repo-controlled.** Every command runs manually on the Proxmox host or inside the TrueNAS guest. The deliverable is a runbook; there is no code to commit and no Flux reconcile that will apply it.

> **Revision note (2026-08-05):** this document incorporates all ten findings from the SQ-33 independent review. The two most consequential were structural: Task 0.4's evidence check could never have returned data (`journalctl -k` implies current-boot-only), and the Phase 5 host reboot takes down the entire Kubernetes cluster — which the original blast-radius section did not mention.

---

## Why this plan exists

`docs/dr/jbod-usb-failure-class-research.md` (commit `494c51e84`) identifies a two-layer failure:

- **Layer 1 (trigger):** ASMedia `174c:55aa` UAS firmware defect, fires under the sustained whole-vdev read a scrub or healing resilver performs.
- **Layer 2 (amplifier):** the entire xHCI PCI function is passed to the guest, so the guest owns error recovery. One device's recoverable UAS timeout becomes a controller-wide `HC died`, taking all six drives at once.

**This plan removes Layer 2 only.** Layer 1 remains — per-device UAS resets can still happen, but they would be handled by the host's well-tested USB stack rather than escalating to total vdev loss. That is a genuine risk reduction, not elimination. Say so plainly to anyone who asks.

## Blast radius — read this before scheduling

**Two separate systems go down, not one.**

1. **The ZFS pool.** If the cutover fails, `Pibbs-Horde` does not import and the entire media library plus MinIO (which backs VolSync) is offline until rolled back.
2. **The entire Kubernetes cluster.** Phase 5 reboots the Proxmox host, which takes down **VM 105 — the single-node Talos cluster**: etcd, Longhorn, and every application. This cluster has documented fragility after restarts (Longhorn instance-manager, mass volume re-attach). Phase 5 includes explicit post-reboot cluster verification for this reason.

Schedule accordingly. This is a whole-infrastructure maintenance window, not a storage-only one. Every step below has an explicit rollback. **Do not improvise past a failed step.**

### On backups — read this and decide consciously

**There is no second copy of the 117 TB pool, and this plan does not create one.**

That is a deliberate judgement, not an oversight: **no step in this runbook writes to the pool.** The sequence is export → change how the host presents the same physical disks → import. The on-disk data is never modified, and every member is addressed by partition UUID, which does not change.

The realistic failure is **"the pool does not import"**, not "the pool is destroyed" — and the rollback for that is restoring two small config files and re-importing, which Phase 3 specifies.

**What is genuinely at risk, and what protects it:**

| risk | protection |
|---|---|
| Pool won't import after reconfiguration | Config backups + documented rollback (Phase 3) |
| Dirty export corrupts in-flight writes | Task 3.1 requires a clean middleware export; workload shed first |
| Wrong disks referenced by udev | Task 3.3 Step 4 captures authoritative host-side serials |
| Host reboot re-steals the controller | Task 2.3 + Task 5.3 Step 3 |

**Accept this consciously.** If you are not willing to proceed without a full backup, stop here — the honest options are to accept the risk as analysed above, or to not do the cutover. There is no third option in which 117 TB gets backed up first; the capacity does not exist.

**What you should verify before starting:** that VolSync's backups of the *application* configs (Radarr, Sonarr, Plex, Emby, and the rest) are current, since those are small, replaceable-by-restore, and independent of this pool. The media files themselves are re-acquirable; the app state is what would actually hurt to lose.

---

## Phase 0: Hard preconditions

**None of the following may be skipped.** Each is a gate, not a suggestion.

### Task 0.1: Confirm the resilver has completed

**Step 1: Check resilver state**

Run on **TrueNAS**:
```bash
zpool status Pibbs-Horde | grep -A3 'scan:'
```

Expected: a line beginning `scan: resilvered ... with 0 errors on <date>`.

**ABORT if** the output says `resilver in progress`. As of 2026-08-05 09:00 the ETA was ~14 hours (≈23:00 the same day). ZFS will refuse an export mid-resilver anyway, and forcing it risks the vdev.

**Step 2: Confirm the pool is ONLINE, not merely functioning**

```bash
zpool status Pibbs-Horde | head -5
```

Expected: `state: ONLINE` with no `status:` line about resilvering or degradation.

### Task 0.2: Detach the hot spare

The spare (`sdf2`, serial `2LGEVB6F`, a WD 20TB) was auto-attached during the incident. It must return to standby before reconfiguration, or the cutover happens against a non-standard vdev layout.

**Step 1: Detach**

Run on **TrueNAS**:
```bash
zpool detach Pibbs-Horde sdf2
```

Expected: silent success.

**If it errors `no valid replicas`**, the resilver has not truly finished — return to Task 0.1.

**Step 2: Verify the vdev is back to its normal shape**

```bash
zpool status Pibbs-Horde
```

Expected: `raidz2-1` lists six members directly, with **no** `spare-3` grouping. The `spares` section shows `sdf2  AVAIL` (not `INUSE`).

### Task 0.3: Capture the error baseline — do NOT run a scrub

> **Changed by review finding 4.** An earlier draft ordered a full scrub here. That is the *exact operation that triggered both prior incidents*, run against the still-unmodified architecture, with the media stack still loaded (the shed does not happen until Phase 3). The risk was real and the plan did not acknowledge it.
>
> It is also unnecessary. **The healing resilver in Task 0.1 just read the entire vdev.** Its error snapshot is fresh and is a valid attribution baseline — that is what a scrub would have produced, at the cost of running the known trigger.

**Step 1: Record the post-resilver error list**

Run on **TrueNAS**:
```bash
zpool status -v Pibbs-Horde > /root/zpool-errors-baseline.txt
cat /root/zpool-errors-baseline.txt
```

Expected: the resilver's own error list. As of 2026-08-05 this was **15 permanent errors**, resolving to a small set of real objects: two TV episodes (`Mr. Show S03E09`, `The Eric Andre Show S03E09`), a MinIO temp file, one MinIO `xl.meta` belonging to an Emby VolSync backup, and a `<metadata>:<0x0>` object.

**Step 2: Confirm nothing unexplained is present**

Compare against the known list above. **ABORT if new, unattributable errors appear** — that suggests ongoing corruption rather than a snapshot of the incident, and cutting over on top of active corruption makes any later problem unattributable.

**Note:** the corrupt files also exist in snapshots `auto-2026-07-29` through `auto-2026-08-04`. Errors will not fully clear until those expire or are destroyed. Expected; not a blocker.

**If you genuinely need a scrub** at this stage for some reason not anticipated here, throttle it first — see "Available lever: I/O throttling" at the end of this document — and shed the media stack before starting rather than at Phase 3.

### Task 0.4: Resolve the memory discrepancy

Project memory for the 2026-08-03 incident records **"No HC died — the xHCI controller stayed healthy."** The 2026-08-04 incident produced raw dmesg showing exactly `HC died`. **One of those is wrong, and this plan's entire justification rests on the passthrough layer failing.**

> **Changed by review finding 1 (anchor 100).** The earlier draft used `journalctl -k --since ... --until ...`. **`-k` implies `-b`, i.e. the current boot only.** Both machines have rebooted since 2026-08-03, so that command was guaranteed to return nothing, and the operator would have recorded "inconclusive" while the evidence sat in the persistent journal. The commands below read across boots.

**Step 1: On TrueNAS — the primary target, since the guest owned the controller at incident time**

```bash
journalctl --list-boots | head -20
```

Identify the boot ID covering 2026-08-03, then:

```bash
journalctl -b <boot-id> _TRANSPORT=kernel --since "2026-08-03" --until "2026-08-04" \
  | grep -iE 'xhci|HC died|uas' | head -40
```

**Step 2: On the Proxmox host — for vfio and PCI-layer evidence**

```bash
journalctl --list-boots | head -20
journalctl -b <boot-id> _TRANSPORT=kernel --since "2026-08-03" --until "2026-08-04" \
  | grep -iE 'vfio|pci_rescan|xhci|3a:00' | head -40
```

**Step 3: Record the finding**

- **If `HC died` appears on 2026-08-03 too:** the memory is wrong. Correct it. The passthrough hypothesis is strengthened — two controller deaths, both on the passed-through side.
- **If 2026-08-03 shows only per-device UAS resets and no `HC died`:** the two incidents differ in kind, and the memory is right. **This weakens the plan's premise** — one controller death is a smaller evidence base than two. Proceed, but downgrade confidence in the ranking and record that downgrade in `docs/dr/jbod-usb-failure-class-research.md`.
- **If persistent journaling was not enabled** (`journalctl --list-boots` shows only the current boot): record that the check was genuinely inconclusive, and note that this is an infrastructure gap worth fixing — `Storage=persistent` in `journald.conf` — so the next incident is diagnosable.

---

## Phase 1: Pre-flight checks (READ-ONLY — nothing changes)

These two checks can each independently kill the plan. Run them **before** touching any config.

### Task 1.1: Do the six Seagates present distinct serials?

USB-SATA bridges are documented to fake or duplicate serial numbers. If two Seagates report the same identifier, udev symlinks cannot distinguish them and this approach is **not viable**.

**Step 1: Get the serials from inside the guest**

The host cannot see these yet — the controller is still passed through — so the guest is the only vantage available at this stage.

Run on **TrueNAS**:
```bash
ls -l /dev/disk/by-id/ | grep -i ST18000 | grep -v part
lsblk -o NAME,SIZE,SERIAL,MODEL | grep -i ST18000
```

Expected: **six rows, six distinct values in the SERIAL column.**

Serials observed in the 2026-08-04 alert, for cross-check only:
```
ZR54LWFK   ZR54FNNY   ZR54FPQZ   ZR54LX7G   ZR54LWRJ   ZR53ZGGZ
```

**ABORT the whole plan if** fewer than six distinct serials appear, or any is blank, or two match. Record exactly what was seen; the fallback is Option A (split the pool) or Option B (SAS HBA) from the research.

> **Note, per review finding 6:** these guest-observed values are ATA-style serials. The udev rules in Task 3.4 key on the **host-side USB descriptor** `ID_SERIAL_SHORT`, which ASMedia bridges are documented to fake, truncate, or alter. **These values are a prediction, not the input.** Task 3.3 Step 4 captures the authoritative host-side values, and those are what Task 3.4 uses.

### Task 1.2: Does SMART survive the extra layer?

`scsi-block` forwards SCSI commands, but SAT (SCSI/ATA Translation) through an ASMedia bridge has mixed reports. Losing SMART means losing drive-failure warning — a real cost that must be known before, not after.

**Step 1: Establish the baseline inside the guest**

Run on **TrueNAS**, for one Seagate:
```bash
smartctl -a /dev/disk/by-id/<one-of-the-six-ST18000-ids> | head -30
```

Expected: model, serial, and a populated SMART attributes table.

**Step 2: Record which transport flag works**

If plain `smartctl -a` fails, try in order and record which succeeds:
```bash
smartctl -a -d sat /dev/<dev>
smartctl -a -d sntasmedia /dev/<dev>
smartctl -a -d scsi /dev/<dev>
```

**Step 3: Decide**

- **SMART works today:** carry the working flag forward and re-verify after cutover (Task 4.4).
- **SMART already does NOT work today:** the cutover cannot make it worse. Note it and proceed — but flag that this vdev has no drive-level health monitoring at all, which is its own finding worth a ticket.

---

## Phase 2: Backups and staging (still no behaviour change)

### Task 2.1: Back up the VM configuration

**Step 1: Copy the config**

On the **Proxmox host**:
```bash
cp /etc/pve/qemu-server/100.conf /root/100.conf.pre-cutover-2026-08-05
```

**Step 2: Verify the backup and record the current args length**

```bash
diff /etc/pve/qemu-server/100.conf /root/100.conf.pre-cutover-2026-08-05 && echo "BACKUP OK"
grep -c '^args:' /etc/pve/qemu-server/100.conf
grep '^args:' /etc/pve/qemu-server/100.conf | wc -c
```

Expected: `BACKUP OK`, exactly **1** args line, and a character count — record it. It was ~623 chars for the eight WD drives.

**⚠️ CRITICAL GOTCHA:** this host has previously hit a limit where a long `args:` line got wrapped by Proxmox's config filesystem and **broke VM start** (`unable to parse config` / `-drive: requires an argument`). That failure occurred around **1254 characters**. Adding six drives adds roughly **470**. Do the arithmetic in Task 3.4 Step 2 before writing, and if it approaches 1200, stop and shorten the drive IDs rather than pushing through.

### Task 2.2: Back up the udev rules

```bash
cp /etc/udev/rules.d/99-truenas-disks.rules /root/99-truenas-disks.rules.pre-cutover-2026-08-05
cat /etc/udev/rules.d/99-truenas-disks.rules
```

Expected: eight `KERNEL=="sd*" ... SYMLINK+="tnN"` lines, `tn1` through `tn8`.

### Task 2.3: Check for a STATIC vfio-pci binding

> **Added by review finding 7.** This host passes GPUs to VM 105, so a static vfio claim is plausible. If `0000:3a:00.0` is statically bound, two things break: Task 3.3's rebind hands the controller straight back to vfio-pci, and — far worse — **the Phase 5 host reboot silently re-steals the controller after everything worked**, all six Seagates vanish, and the pool comes up missing `raidz2-1`.

**Step 1: Search every static-binding mechanism**

```bash
grep -rE 'vfio' /etc/modprobe.d/ 2>/dev/null
grep -E 'vfio' /etc/default/grub /etc/kernel/cmdline 2>/dev/null
cat /proc/cmdline | tr ' ' '\n' | grep -i vfio
lsinitramfs /boot/initrd.img-$(uname -r) 2>/dev/null | grep -i vfio | head
```

**Step 2: Act on what you find**

- **No mention of `3a:00.0` or `8086:15d4`:** binding is dynamic (Proxmox binds at VM start). Nothing to do.
- **`3a:00.0` or `8086:15d4` claimed statically:** remove or narrow that claim so it covers only the GPU IDs, then refresh:
  ```bash
  update-initramfs -u -k all
  proxmox-boot-tool refresh   # or update-grub, per Task 5.2's detection
  ```
  **This must be done before Phase 3**, and re-verified after the Phase 5 reboot (Task 5.3).

### Task 2.4: Record the pool's identity for post-cutover comparison

Run on **TrueNAS**:
```bash
zpool status Pibbs-Horde > /root/zpool-status-pre-cutover.txt
zpool get guid Pibbs-Horde
zpool list -v Pibbs-Horde
```

Record the pool GUID. After cutover it must be **identical** — a different GUID means a different pool was imported.

**Rollback for all of Phase 2:** nothing has changed except possibly the vfio static binding in 2.3, whose original state is recoverable from the files you edited.

---

## Phase 3: The cutover (DISRUPTIVE — everything below changes state)

**Before starting:** shed the cluster workload so nothing is mid-write. See `SQ-30`. Media apps should be at 0 replicas.

### Task 3.1: Export the pool cleanly — via the middleware

> **Changed by review finding 3.** Raw `zpool export` bypasses TrueNAS's middleware, which tracks pool state, shares, and apps separately. SMB/NFS exports may not reattach after a raw import. Use the middleware so its state stays consistent with reality.

**Step 1: Stop services that hold the pool open**

In the TrueNAS UI, stop the SMB/NFS/iSCSI services and any apps using `Pibbs-Horde`.

**Step 2: Export through the middleware**

Preferred — **TrueNAS UI**: Storage → `Pibbs-Horde` → Export/Disconnect. **Leave "Destroy data" unchecked.**

CLI equivalent if the UI is unavailable:
```bash
midclt call pool.export <pool-id> '{"cascade": true, "destroy": false}'
```

(Get `<pool-id>` from `midclt call pool.query | jq '.[] | {id, name}'`.)

**Only if the middleware path fails**, fall back to `zpool export Pibbs-Horde` — and record that you did, because Task 4.3 then needs the middleware re-import to reconcile.

**If it errors "pool is busy"**, find the holder:
```bash
fuser -vm /mnt/Pibbs-Horde
lsof +D /mnt/Pibbs-Horde 2>/dev/null | head
```
Stop that consumer and retry. **Do not use `zpool export -f`** unless you have exhausted this — a forced export with in-flight writes is how you create the corruption this plan exists to avoid.

**Step 3: Confirm it is gone**

```bash
zpool list
```

Expected: `Pibbs-Horde` absent.

**Rollback:** re-import via the UI (Storage → Import Pool) — returns to the pre-cutover state exactly.

### Task 3.2: Shut down VM 100

On the **Proxmox host**:
```bash
qm shutdown 100
qm status 100
```

Expected: `status: stopped`.

**If it hangs beyond ~2 minutes**, the pool export probably did not complete. Verify, then:
```bash
qm stop 100
```

`qm stop` is a hard power-off, safe here specifically because the pool is already exported.

### Task 3.3: Remove the controller passthrough

**Step 1: Comment out the hostpci line**

```bash
sed -i 's/^hostpci2: 0000:3a:00.0/#&/' /etc/pve/qemu-server/100.conf
grep -n 'hostpci' /etc/pve/qemu-server/100.conf
```

Expected: the line present but prefixed with `#`. Commenting rather than deleting makes rollback a one-character edit.

**Step 2: Apply the UAS quirk at runtime BEFORE the host enumerates anything**

> **Added by review finding 2.** The quirk only reaches the host kernel cmdline at Phase 5. Without this step, the host's first enumeration of all six drives — and every read in Phase 4 — happens with UAS active and no mitigation, which is precisely the Layer 1 trigger condition. Phase 5 makes it persistent; this makes it effective now.

```bash
modprobe usb_storage 2>/dev/null
echo "174c:55aa:u" > /sys/module/usb_storage/parameters/quirks
cat /sys/module/usb_storage/parameters/quirks
```

Expected: the quirk string echoed back.

**Step 3: Confirm the host reclaims the controller**

```bash
lspci -nnk -s 3a:00.0
```

Expected: `Kernel driver in use: xhci_hcd`.

If it still shows `vfio-pci`:
```bash
echo "" > /sys/bus/pci/devices/0000:3a:00.0/driver_override
echo "0000:3a:00.0" > /sys/bus/pci/drivers/vfio-pci/unbind
echo "0000:3a:00.0" > /sys/bus/pci/drivers_probe
lspci -nnk -s 3a:00.0
```

**If it rebinds to `vfio-pci` anyway**, a static binding exists that Task 2.3 missed — go back and remove it.

**Step 4: Capture the AUTHORITATIVE host-side serials**

> **Added by review finding 6.** The udev rules key on `ENV{ID_SERIAL_SHORT}` as the *host* sees it. Task 1.1's values came from the guest and may differ. These are the values Task 3.4 uses.

```bash
lsblk -o NAME,SIZE,SERIAL,MODEL | grep -i ST18000
for d in $(lsblk -dno NAME | grep '^sd'); do
  S=$(udevadm info --query=property --name=/dev/$d 2>/dev/null | grep -E '^ID_SERIAL_SHORT=' | cut -d= -f2)
  M=$(udevadm info --query=property --name=/dev/$d 2>/dev/null | grep -E '^ID_MODEL=' | cut -d= -f2)
  case "$M" in *ST18000*) echo "  /dev/$d  ID_SERIAL_SHORT=$S  $M";; esac
done
```

Expected: **six lines, six distinct `ID_SERIAL_SHORT` values.** Write these down — they are the input to Task 3.4, not the Task 1.1 values.

**ABORT and roll back if** fewer than six appear, or any `ID_SERIAL_SHORT` is empty or duplicated. Rollback: uncomment `hostpci2`, `qm start 100`, import the pool via the UI.

### Task 3.4: Add udev symlinks for the six Seagates

**Step 1: Append the rules using the Task 3.3 Step 4 values**

Substitute the **host-observed** `ID_SERIAL_SHORT` values:

```bash
cat >> /etc/udev/rules.d/99-truenas-disks.rules << 'EOF'
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_1>", SYMLINK+="tn9"
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_2>", SYMLINK+="tn10"
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_3>", SYMLINK+="tn11"
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_4>", SYMLINK+="tn12"
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_5>", SYMLINK+="tn13"
KERNEL=="sd*", ENV{DEVTYPE}=="disk", ENV{ID_SERIAL_SHORT}=="<HOST_SERIAL_6>", SYMLINK+="tn14"
EOF

udevadm control --reload-rules && udevadm trigger
sleep 5
ls -l /dev/tn*
```

Expected: **fourteen symlinks**, `tn1`–`tn14`, each pointing at a distinct `sdX`.

**ABORT if** any `tn9`–`tn14` is missing — a serial did not match. Re-check with the Task 3.3 Step 4 loop.

**Step 2: Calculate the new args line length BEFORE writing it**

```bash
CUR=$(grep '^args:' /etc/pve/qemu-server/100.conf | wc -c)
ADD=$(python3 -c "print(sum(len(' -drive file=/dev/tn%d,if=none,id=h%d -device scsi-block,drive=h%d,bus=scsihw0.0'%(i,i,i)) for i in range(9,15)))")
echo "current=$CUR  adding=$ADD  total=$((CUR+ADD))"
```

**STOP if `total` exceeds 1200.** The documented breakage occurred at ~1254. If too long, shorten the drive IDs (`h9`→`a`, etc.) rather than pushing past the limit.

### Task 3.5: Add the six drives to the VM config

**Step 1: Append to the existing args line**

```bash
python3 - << 'PY'
p = '/etc/pve/qemu-server/100.conf'
lines = open(p).readlines()
out = []
for l in lines:
    if l.startswith('args:'):
        extra = ''.join(
            ' -drive file=/dev/tn%d,if=none,id=h%d -device scsi-block,drive=h%d,bus=scsihw0.0' % (i, i, i)
            for i in range(9, 15)
        )
        l = l.rstrip('\n') + extra + '\n'
    out.append(l)
open(p, 'w').writelines(out)
PY
```

**Step 2: Verify exactly one args line, correct length, all fourteen drives**

```bash
grep -c '^args:' /etc/pve/qemu-server/100.conf
grep '^args:' /etc/pve/qemu-server/100.conf | wc -c
grep -o 'tn[0-9]*' /etc/pve/qemu-server/100.conf | sort -V | uniq | tr '\n' ' '
```

Expected: `1`, a length matching the Task 3.4 calculation, and `tn1 tn2 ... tn14`.

**ABORT if** there is more than one args line — that is the exact failure recorded on this host previously. Restore from backup and retry.

**Rollback for Phase 3:**
```bash
cp /root/100.conf.pre-cutover-2026-08-05 /etc/pve/qemu-server/100.conf
cp /root/99-truenas-disks.rules.pre-cutover-2026-08-05 /etc/udev/rules.d/99-truenas-disks.rules
udevadm control --reload-rules && udevadm trigger
qm start 100
# then import the pool via the TrueNAS UI
```

---

## Phase 4: Bring it up and verify

### Task 4.1: Start the VM

```bash
qm start 100
qm status 100
```

Expected: `status: running`.

**If it fails to start**, read the error. `unable to parse config` means the args line broke — roll back and revisit Task 3.4 Step 2.

### Task 4.2: Confirm the guest sees fourteen drives

Run on **TrueNAS** (allow ~2 minutes for boot):
```bash
lsblk -d -o NAME,SIZE,SERIAL,MODEL | grep -E '18.2T|16.4T'
```

Expected: **fourteen rows** — eight WD, six Seagate — all with distinct serials.

**ABORT and roll back if** fewer than fourteen appear.

### Task 4.3: Import the pool — via the middleware

**Step 1: Check it is importable before importing**

Run on **TrueNAS**:
```bash
zpool import
```

Expected: `Pibbs-Horde` listed with state `ONLINE`, all twelve members present.

**Step 2: Import through the middleware**

Preferred — **TrueNAS UI**: Storage → Import Pool → `Pibbs-Horde`.

CLI equivalent:
```bash
midclt call pool.import_pool '{"guid": "<the-guid-from-Task-2.4>"}'
```

Using the middleware here is what reattaches shares and app mounts. A raw `zpool import` leaves the middleware's view stale.

**If it requires `-f`**, stop and think. That means the export was not clean. Usually safe here (the pool was exported deliberately), but confirm state first with `zpool import` output.

**Step 3: Verify identity and health**

```bash
zpool get guid Pibbs-Horde
zpool status -v Pibbs-Horde
```

Expected: the **same GUID** recorded in Task 2.4, `state: ONLINE`, both vdevs healthy, and the same error list as the Task 0.3 baseline — no new entries.

**Step 4: Verify shares came back**

```bash
systemctl status nfs-server smbd 2>/dev/null | grep -E 'Active|●'
showmount -e localhost 2>/dev/null
```

Expected: services active and the expected exports listed. If not, restart them from the TrueNAS UI — and record it, because it means the middleware import did not fully reconcile.

### Task 4.4: Verify SMART still works

> **Changed by review finding 8.** The guest's `by-id` names change completely after cutover — the drives are no longer `usb-Seagate_*`; they appear as `scsi-block` LUNs. The Task 1.2 baseline path will not resolve. Both vantages need checking, because host-side may now be the only place SMART works.

**Step 1: Run on TrueNAS (guest vantage)**

```bash
ls -l /dev/disk/by-id/ | grep -iE 'ST18000|scsi-' | grep -v part | head
smartctl -a /dev/<the-new-device> | head -20
```

Use whichever `-d` flag worked in Task 1.2.

**Step 2: Run on the Proxmox host (host vantage)**

```bash
smartctl -a /dev/sdX | head -20        # one of the six Seagates
smartctl -a -d sat /dev/sdX | head -20 # if the above fails
```

**Step 3: Record which vantage works**

- **Guest-side works:** unchanged from before; TrueNAS keeps its own monitoring.
- **Only host-side works:** a real change. TrueNAS will not alert on these drives. Record it and decide whether host-side SMART monitoring needs wiring into the existing Prometheus stack. Not a rollback trigger, but it must be a conscious decision rather than a discovery months later.
- **Neither works:** compare against Task 1.2 — if SMART already failed before, nothing regressed.

### Task 4.5: Verify data is actually readable

```bash
ls /mnt/Pibbs-Horde/media/data/media/movies | head -5
ls /mnt/Pibbs-Horde/media/data/media/movies | wc -l
dd if="$(find /mnt/Pibbs-Horde/media/data/media/movies -name '*.mkv' | head -1)" of=/dev/null bs=1M count=100
```

Expected: ~2110 movie directories, and a 100 MB read at sensible speed.

**Note:** a fast read alone does not prove health — it can be served from ARC. The `zpool status` in 4.3 is the authority.

---

## Phase 5: Make the UAS quirk persistent

Task 3.3 Step 2 applied the quirk at runtime. This makes it survive reboots. **Without this, the next host reboot silently removes Layer 1 mitigation.**

### Task 5.1: Confirm current state

Run on the **Proxmox host**:
```bash
cat /sys/module/usb_storage/parameters/quirks
cat /proc/cmdline | tr ' ' '\n' | grep -i quirks
```

Expected: the runtime quirk present, the cmdline one absent.

Also check the guest, since the quirk there is now pointless but harmless:
```bash
# on TrueNAS
cat /proc/cmdline | tr ' ' '\n' | grep -i quirks
```

Leave the guest's alone — removing it is a separate change with no benefit.

### Task 5.2: Add it to the host cmdline

```bash
proxmox-boot-tool status
```

**For systemd-boot** (Proxmox 8+):
```bash
cp /etc/kernel/cmdline /root/cmdline.pre-quirk-2026-08-05
echo "Current: $(cat /etc/kernel/cmdline)"
# append usb-storage.quirks=174c:55aa:u to the existing line, then:
proxmox-boot-tool refresh
```

**For GRUB:**
```bash
cp /etc/default/grub /root/grub.pre-quirk-2026-08-05
# append to GRUB_CMDLINE_LINUX_DEFAULT, then:
update-grub
```

### Task 5.3: Reboot and verify — INCLUDING the cluster

> **Expanded by review finding 5 (anchor 100) and finding 7.** This reboot takes down **VM 105, the entire Talos cluster**. Nothing in the earlier draft said so, and nothing verified the cluster afterwards before Phase 6 restored workloads onto it.

**Step 1: Shut down guests cleanly**

```bash
qm shutdown 100
qm shutdown 105     # THE KUBERNETES CLUSTER
qm shutdown 102 104 106
qm list             # confirm all stopped
```

**If 105 hangs**, its pods may be wedged on the now-absent NFS mounts. `qm stop 105` is safe — etcd is transactional and this cluster has survived abrupt restarts before.

**Step 2: Reboot**

```bash
reboot
```

**Step 3: After boot — verify the quirk AND that vfio did not re-steal the controller**

```bash
cat /proc/cmdline | tr ' ' '\n' | grep -i quirks
lspci -nnk -s 3a:00.0
```

Expected: quirk present; `Kernel driver in use: xhci_hcd`.

**If it shows `vfio-pci`**, a static binding survived Task 2.3 — the Seagates will be invisible and the pool will import missing `raidz2-1`. **Do not start VM 100 until this is fixed.**

**Step 4: Verify the host sees all six Seagates**

```bash
lsblk -o NAME,SIZE,SERIAL,MODEL | grep -i ST18000
ls -l /dev/tn* | wc -l
```

Expected: six Seagates; fourteen `tn*` symlinks.

**Step 5: Start VM 100 and confirm the pool**

```bash
qm start 100
```

Then on **TrueNAS**:
```bash
zpool status Pibbs-Horde
zpool get guid Pibbs-Horde
showmount -e localhost
```

Expected: pool auto-imported, ONLINE, same GUID, shares exported. **If the pool did not auto-import**, import via the UI and record it — auto-import failing is itself a finding.

**Step 6: Start and VERIFY the Kubernetes cluster**

```bash
qm start 105
```

Wait for boot, then from a workstation with cluster access:
```bash
kubectl get nodes
talosctl -n 192.168.10.167 health --wait-timeout 10m
kubectl get pods -A --no-headers | awk '{print $4}' | sort | uniq -c | sort -rn | head
kubectl get volumes.longhorn.io -n longhorn-system -o json \
  | python3 -c "import sys,json;from collections import Counter;print(Counter(v.get('status',{}).get('robustness','?') for v in json.load(sys.stdin)['items']))"
flux get kustomizations --status-selector ready=false
```

Expected: node `Ready`, Longhorn volumes attaching and reaching `healthy`, no persistently failed Kustomizations.

**Expect a slow settle.** Longhorn re-attaches ~156 volumes after a restart; this has taken 10–20 minutes historically. Do not start Phase 6 until it stabilises.

**Rollback for Phase 5:** restore the saved cmdline/grub file, `proxmox-boot-tool refresh` or `update-grub`, reboot.

**Note:** the quirk disables UAS for that chipset, falling back to slower bulk-only transport. This trades throughput for stability. Given the link is only ~1.5× oversubscribed and the failure mode is total vdev loss, that is the right trade — but expect measurably slower sequential reads and do not mistake them for a new problem.

---

## Phase 6: Soak test — the step most likely to be skipped

**Nothing is proven until the pool survives the exact workload that broke it.** A cutover that "seems fine" for an hour tells you nothing; both prior incidents were triggered by sustained multi-drive sequential reads.

### Task 6.1: Restore the cluster workload

Follow `SQ-30`. Restore the shed deployments, including `flux resume kustomization tdarr`.

Confirm the cluster is genuinely healthy first — Task 5.3 Step 6.

### Task 6.2: Run a full scrub under normal load — UNTHROTTLED

```bash
zpool scrub Pibbs-Horde
```

Monitor on the **host**:
```bash
watch -n 60 'dmesg | grep -icE "xhci|uas|HC died|reset"'
```

**Leave this scrub unthrottled deliberately.** Throttling is available (see below) and would lower the trigger odds — but a scrub you made gentler proves less about the fix. This is the test; it needs to be a real one.

**This is the real verification.** A scrub is what triggered both incidents. If it completes with the media stack running and no `HC died`, the fix is demonstrated. If the counter climbs, capture `dmesg` immediately.

**Pass / fail criteria — decide these before starting, not after:**

| outcome | verdict |
|---|---|
| Scrub completes, zero `HC died`, zero new permanent errors | **PASS.** Layer 2 was the dominant mechanism. Fix demonstrated. |
| Scrub completes, zero `HC died`, but per-device `uas_eh_device_reset` lines appear | **PASS with expected residue.** Layer 1 is still present — that is by design. Record the reset count as a baseline for future comparison. |
| Any `HC died`, or the vdev drops | **FAIL.** Passthrough was not the dominant mechanism. Do not retry. Update the research and re-rank toward Option A (split the pool) or Option B (HBA). |
| Scrub stalls at `0B issued` for over an hour | **FAIL, same as above** — that is the deadlock signature from 2026-08-04. |

**Duration:** the scrub must run to completion, not a fixed clock. Expect many hours on 117 TB. A partial scrub is not a pass — the first incident took ~2 days of scrub before it tripped, so an early clean stretch proves nothing.

### Task 6.3: Record the outcome either way

Update `docs/dr/jbod-usb-failure-class-research.md` with what happened, under a heading containing the phrase **soak-test outcome**. A negative result is as valuable as a positive one — it would mean Layer 2 was not the dominant mechanism, and the ranking in that document needs revising toward Option A or B.

---

## Final Phase: Review & Completion

**Goal:** Comprehensive review and validation before declaring the work complete.

**Step 1: Run full review**

- VM config diff against `/root/100.conf.pre-cutover-2026-08-05`
- udev rules diff against the saved copy
- Host and guest kernel cmdline changes
- Whether every rollback path is still valid

**Step 2: Address findings with the operator**

For each: present the issue, propose a fix or discuss trade-offs, implement the decision.

**Step 3: Pre-completion checklist**

- [ ] Resilver completed and spare detached before any change
- [ ] Error baseline captured from the resilver (no pre-cutover scrub run)
- [ ] Memory discrepancy about 2026-08-03 `HC died` resolved, using cross-boot journal commands
- [ ] Static vfio-pci binding checked before Phase 3 **and** re-verified after the Phase 5 reboot
- [ ] Six distinct host-side `ID_SERIAL_SHORT` values captured and used for the udev rules
- [ ] UAS quirk applied at runtime **before** first host enumeration, and made persistent in Phase 5
- [ ] Pool exported and imported through the TrueNAS middleware, shares verified back
- [ ] Pool GUID identical before and after
- [ ] `args:` line is exactly one line and under the length limit
- [ ] SMART verified from both vantages, result recorded either way
- [ ] **Kubernetes cluster verified healthy after the host reboot, before workloads restored**
- [ ] Full unthrottled scrub survived under normal cluster load with no `HC died`
- [ ] Research document updated with the soak-test outcome
- [ ] `SQ-30` restore completed, nothing left shed
- [ ] Rollback artifacts retained for at least 30 days

**Step 4: Confirm with the operator**

"All tasks complete and validated. Ready to close, or need adjustments?"

Only declare complete when the operator confirms.

---

## Available lever: I/O throttling (not used, deliberately)

The research ranks scrub/resilver I/O throttling as a free, reversible mitigation:

```
zfs_vdev_scrub_max_active     default 2 per device
zfs_scrub_min_time_ms         default 750
zfs_resilver_min_time_ms      default 1500
zfs_rebuild_vdev_limit        default 64 MiB
```

**Why it is not used here:**

- **Phase 0** no longer runs a scrub at all (finding 4), so there is nothing to throttle.
- **Phase 6** is deliberately unthrottled, because a throttled soak test is weaker evidence — surviving a scrub you made gentler proves less about whether the fix works.

**When to reach for it:** if you ever need to scrub the *unmodified* topology (before this cutover, or after a rollback), throttle first. It directly lowers the odds of tripping the Layer 1 trigger, at the cost of a longer scrub.

---

## What this plan does NOT do

Stated explicitly so nobody assumes otherwise:

- **It does not fix Layer 1.** The ASMedia UAS firmware defect remains. Per-device resets can still occur — they would just be handled by the host's mature USB stack instead of escalating.
- **It does not address the single-pool fault domain.** `Pibbs-Horde` still spans both transports, so a USB-side failure can still suspend the healthy ATA vdev. That is Option A in the research and a separate decision.
- **It does not eliminate the need for an HBA eventually.** Option B remains the only path that removes both layers. This plan buys reliability cheaply; it does not make the enclosure enterprise-grade.
- **It does not use I/O throttling.** See the section above for why, and when to reconsider.
- **It does not change anything in this repository.** There is nothing to commit, and Flux will not apply any of it.
