# JBOD USB/Thunderbolt Failure Class — Research (SQ-32) — REVISED per operator reframing

*Produced by the SQ-32 research executor under a read-only dispatch; landed here verbatim apart
from this note. Read-only research only* — no ZFS commands run, no config changed, no
I/O added to `Pibbs-Horde` during its resilver.

**Revision note:** this supersedes an earlier draft that treated USB-hub bandwidth oversubscription and
the ASMedia UAS bridge bug as the whole story. The operator relayed direct dmesg evidence
(`xhci_hcd 0000:00:1b.0: xHCI host controller not responding, assume dead` / `HC died; cleaning up`)
that the prior draft's source (project memory) had summarized as "no HC died" — that discrepancy is
unresolved and flagged in §6. Treating the operator-relayed raw lines as authoritative for this pass,
the analysis below is restructured around a **two-layer mechanism**: a bandwidth/firmware TRIGGER plus a
**PCI-passthrough AMPLIFIER**, with the controlled WD-vs-Seagate comparison as central evidence. This
changes the ranked recommendation: the first move is a **config-only reconfiguration**, not a hardware
purchase.

## 0. System under study

- Host: Proxmox bare-metal, QNAP TVS-H1288X (Xeon W-1250, 3 PCIe slots: 10GbE NIC / GPU→Talos VM / TB3
  card→TrueNAS VM).
- TrueNAS = Proxmox VM 100. JBOD = QNAP TL-R1200C-RP, 6× Seagate ST18000NE000, behind an Intel JHL6540
  Alpine Ridge chip's **USB xHCI function** (PCI `0000:3a:00.0` — confirmed by prior incident analysis
  that the enclosure speaks USB/UAS, not TB PCIe tunnelling, so only the xHCI function is in play, not
  the full TB tunnel/DP functions), **whole-function PCI passthrough via `hostpci2`** → internal 6:1
  QNAP USB hub tree (3 cascade levels) → 6× ASMedia `174c:55aa` UAS bridges, one per drive.
- Pool `Pibbs-Horde` = ONE pool, two vdevs: `raidz2-0` (6–8× WD WD201KFGX 20TB, **ATA-attached to the
  Proxmox host, passed into the guest per-disk as `scsi-block` LUNs** — `-drive file=/dev/tn1..tn8
  -device scsi-block,...`) + `raidz2-1` (the 6 USB/UAS Seagate drives, reached only through the fully
  passed-through xHCI controller above). 138 TiB usable.
- **The controlled comparison is the central fact of this investigation:** same host, same VM, same
  night, same workload (a scrub/resilver reading both vdevs). The WD/ATA/scsi-block side was completely
  unaffected in both prior incidents. The Seagate/USB/whole-controller-PCI-passthrough side lost all 6
  drives at once, twice. **The two vdevs differ in TWO variables simultaneously — transport (SATA vs.
  USB/UAS) AND virtualization method (per-disk LUN passthrough vs. whole-controller PCI passthrough) —
  and this research could not fully separate which variable dominates without live testing (explicitly
  out of scope here — no I/O may be added during the active resilver). Both are independently
  documented as plausible contributors; §1 explains why the evidence favors treating passthrough as the
  AMPLIFIER of a UAS-class trigger, not a replacement explanation for it.**

## 1. The bandwidth arithmetic, done explicitly (operator instruction)

- JHL6540's USB function: USB 3.1 Gen 2, 10 Gbps signaling, **~1 GB/s practical** after protocol
  overhead (confirmed by `lsusb -t` showing `10000M` in the prior incident capture).
- 6× Seagate ST18000NE000 (Exos X18-class) sustained sequential: **~250 MB/s each** (vendor-typical
  figure for this drive class) → 6 × 250 MB/s = **~1.5 GB/s** desired aggregate during a full-vdev
  scrub/resilver read.
- **Oversubscription ratio ≈ 1.5×, not 6×.** The "6:1" language in this project's prior incident notes
  describes the **hub fan-out topology** (six physical downstream ports cascading through a 3-level hub
  tree into one upstream link) — it does NOT mean 6× the bandwidth demand. That prior phrasing is
  imprecise and should not be read as "the enclosure is drastically oversubscribed." **1.5× is a mild,
  ordinary oversubscription ratio.** It is enough to cause **queuing and reduced per-drive throughput**
  (each drive effectively rate-limited to ~1000/6 ≈ 166 MB/s during a synchronized full read, well below
  its own 250 MB/s capability) — this is a real, measurable performance cost of the topology. **It is
  not, on its own, sufficient to explain a total host-controller death event** (`HC died`). Queuing
  produces slower throughput; it does not produce a controller-wide unresponsive-hardware condition.
  This is the operator's core correction, and the evidence supports it: **the "the JBOD/hub was simply
  overloaded" framing, taken alone, is an incomplete/likely-wrong explanation for why the WHOLE
  CONTROLLER died** rather than one drive slowing down or one bridge resetting.

## 2. Q1, revised — why does ZFS's OWN recovery (scrub/resilver) amplify this failure class?

**Direct answer: a two-layer mechanism. Layer 1 (trigger) is the well-documented, chip-family-level
ASMedia `174c:55aa` UAS firmware defect, which independent kernel-list/bugzilla reports describe as
wedging "under heavy I/O" / "under stress" — a condition a scrub/resilver's synchronized, sustained,
near-saturating multi-drive read reliably produces and ordinary bursty media-streaming I/O does not.
Layer 2 (amplifier) is that the ENTIRE xHCI PCI function is passed through to the TrueNAS guest via
vfio-pci, so recovery from that one drive's transient UAS timeout depends on a virtualized
interrupt/DMA path that is independently documented as fragile for exactly this class of device —
turning what should be a per-device reset into a controller-wide `HC died`, killing all 6 drives at
once. Layer 2 is what the earlier draft was missing.**

### Layer 1 — the trigger (unchanged from the first draft, now correctly scoped to "mild oversubscription increases the odds of hitting a known firmware bug," not "the link is overloaded")
- RAIDZ healing-resilver reads (nearly) the whole vdev's surviving members for every stripe
  reconstructed — RAIDZ vdevs are restricted to the slower "healing" resilver (only dRAID/mirror qualify
  for the lighter "sequential" resilver): "For dRAID a sequential resilver is started, while a healing
  resilver must be used for raidz" ([OpenZFS dRAID
  docs](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/dRAID%20Howto.html)). So every
  scrub/resilver on `raidz2-1` drives sustained, synchronized, near-max reads across all 6 Seagates for
  hours — the Jul 26 scrub ran ~21h before the first fault; the Aug 5 resilver in progress at ticket-open
  runs until ~23:00.
- The ASMedia `174c:55aa` UAS defect is independently, primary-source documented: a Linux-USB mailing
  list thread on this exact USB ID
  ([spinics.net/lists/linux-usb/msg188272](https://www.spinics.net/lists/linux-usb/msg188272.html))
  describes "repeated abort handler errors and device reset cycles… triggered during read operations
  after the device becomes active" — matching this environment's captured signature
  (`uas_eh_device_reset_handler … err -19`). Red Hat/Fedora Bugzilla
  [#1230336](https://bugzilla.redhat.com/show_bug.cgi?id=1230336) documents the same chip family
  ("asm1051e") causing driver hangs/resets/lockups without the UAS-disabling quirk. This is a
  chip-family-level defect independent of this rig.
- Confirmed twice on this exact hardware, both during a scrub, both with zero SMART/checksum errors on
  the drives themselves (ruling out media failure): Jul 26–30 (2 Seagates + 1 WD spare DEGRADED/UNAVAIL
  together, 3 days at zero `raidz2-1` redundancy) and Aug 3 (all 6 Seagates vanish simultaneously, pool
  SUSPENDED).

### Layer 2 — the amplifier (new; directly answers the operator's reframing)
- **The controlled comparison is the strongest single piece of evidence in this whole investigation.**
  The WD vdev uses per-disk `scsi-block` LUN passthrough — the Proxmox HOST owns the SATA/AHCI
  controller and does all device-level error recovery using the host's mature, non-virtualized
  xhci_hcd/AHCI driver stack; the guest only ever sees a virtio-scsi block device. The Seagate vdev
  instead passes the **entire USB xHCI PCI function** into the guest — the guest's own kernel owns
  100% of USB enumeration, command issuance, AND error recovery for all 6 drives, through a device whose
  interrupt/DMA path is remapped by vfio-pci/IOMMU. Same host, same night, same workload: only the
  passthrough side died.
- Whole-controller PCI passthrough of xHCI devices into KVM/QEMU guests is independently documented as
  fragile, and specifically fragile in ways matching this incident's signature:
  - Generic reports of `xHCI host controller not responding, assume dead` / `HC died; cleaning up`
    recur across kernel-mailing-list and community threads
    ([pop-os/pop#575](https://github.com/pop-os/pop/issues/575),
    [Arch Linux forum threads](https://bbs.archlinux.org/viewtopic.php?id=303985)), and the standard
    recovery is unbind/rebind of the xhci_hcd driver or a full reboot — not a graceful in-place reset.
  - Proxmox's own community forum documents a case where **USB controller passthrough instability
    correlated specifically with backup operations (i.e., sustained heavy I/O)**
    ("[Kernel 6.8.12 breaks USB controller passthrough in a weird
    way](https://forum.proxmox.com/threads/kernel-6-8-12-breaks-usb-controller-passthrough-in-a-weird-way.152508/)":
    "a separate report documented the host USB subsystem becoming unstable… correlating with backup
    operations triggering the issue") — the same I/O-shape (sustained, heavy, multi-hour) as a
    scrub/resilver.
  - Kernel-list discussion of xhci MSI/MSI-X interrupt loss ("MSI interrupt for xhci still lost…" —
    [lkml.kernel.org thread](https://lkml.kernel.org/lkml/20200505201616.GA15481@otc-nc-03/T/)) shows
    this is a known, recurring class of bug for xHCI controllers specifically, not USB storage devices
    generally — consistent with a controller-level (not per-device) fault.
  - Recovery from these states frequently requires **more than a guest-level action** — Proxmox forum
    threads on PCI passthrough devices "falling off the bus" document needing `remove`+`rescan` cycles
    on the HOST's `/sys/bus/pci` tree, and in some cases a full host reboot before the device will
    rebind to vfio-pci at all. This matches the detail relayed by the operator (a `pci_rescan_bus` stack
    trace during recovery, device not rebinding to vfio-pci until a full host reboot) — a materially
    more severe recovery path than the host-owned WD vdev has ever required.
- **Mechanism, stated as a chain:** (1) sustained scrub/resilver read saturates all 6 drives near the
  ~1.5× oversubscribed link → queuing latency rises → (2) one ASMedia bridge misses a command-completion
  window, a documented `174c:55aa` firmware weak point independent of this rig → (3) UAS/SCSI error
  recovery (`uas_eh_abort_handler`/`uas_eh_device_reset_handler`) issues a low-level reset to the xHCI
  controller for that ONE device → (4) because the guest owns the whole PCI function via vfio-pci, that
  reset's completion travels through a virtualized interrupt/DMA path independently documented as
  fragile under sustained I/O → (5) the completion is lost/delayed past the guest xhci_hcd driver's
  watchdog, which then declares the **entire controller**, not just the one device, dead — explaining
  why all 6 drives vanish together rather than just the one with the original transient fault → (6)
  recovery requires host-level intervention disproportionate to what a single transient device error
  should need.

**Bottom line for Q1 (revised):** the amplification is real but is not simply "the JBOD can't handle
the I/O" — the bandwidth math (§1) rules that out as a sufficient standalone explanation for a
controller-wide death. The more complete explanation is that ZFS's own repair mechanism is the one
operation that reliably produces the sustained-I/O condition needed to trip a known per-device UAS
firmware bug, and this specific rig's whole-controller PCI-passthrough architecture turns that
recoverable per-device event into a total, hard-to-recover controller failure — a severity increase the
host-owned WD vdev, doing the identical workload, never experiences.

## 3. Answering the operator's specific research questions

**(1) Is vfio-pci passthrough of a USB xHCI controller into a KVM/QEMU guest known to be fragile under
sustained heavy I/O, and does passthrough deprive the setup of host-driver error recovery?** Yes to
both, per the evidence in §2 Layer 2. Passthrough hands 100% of the controller — including all
low-level error-recovery command issuance and interrupt/DMA handling — to the guest kernel, operating
through a virtualized (IOMMU-remapped) path. The host kernel's own well-tested USB error-recovery logic
is entirely bypassed for these 6 drives; only the guest's kernel, running atop the added virtualization
layer, gets a chance to recover, and multiple independent reports show that layer specifically losing
interrupts / stalling command rings under sustained load.

**(2) Known issues with Thunderbolt-attached xHCI (Alpine Ridge) specifically under vfio-pci?** Partial
evidence: general Thunderbolt-controller passthrough is documented as reset/hotplug-fragile
("Thunderbolt controllers might not reset properly (or not work with passthrough at all)"; hotplug
events cause devices to disappear from the VM — Proxmox forum threads). No source found that isolates
JHL6540 by exact part number under this specific failure signature — this remains **circumstantial, not
individually confirmed** for this chip. Since only the xHCI *function* (not the TB PCIe-tunnel/DP
functions) is passed through here, the more directly relevant evidence is the generic xHCI-under-vfio
fragility in §2, which is well corroborated; the added TB hotplug/link-training layer beneath the passed
xHCI function is a plausible additional risk factor but is **not independently verified** in this pass.

**(3) Is there a cheaper fix than an HBA — mount the six Seagates on the Proxmox HOST and pass them into
TrueNAS as `scsi-block`, exactly like the eight WDs?** Yes, this is assessed as the strongest immediate
option — see Option 0 in §5. Key findings:
  - **SMART/identity:** TrueNAS's own community guidance officially prefers whole-HBA-controller
    passthrough over individual `scsi-block` disk passthrough, precisely because per-disk passthrough
    means "TrueNAS is still working with virtual disks, not the real physical disks… only PVE can
    monitor SMART" (Proxmox forum synthesis from multiple threads on TrueNAS+Proxmox disk passthrough).
    **However, this environment already deviates from that guidance for the WD vdev** (which uses
    `scsi-block`, not whole-HBA passthrough) and that vdev has had zero incidents — meaning the
    theoretical downside is not showing up as a practical one in this exact environment, at least for
    ATA drives. Untested for USB-bridged drives specifically — SAT/SMART passthrough through ASMedia
    bridges has independently **mixed** reports (`smartmontools` issue threads show some ASMedia chips
    fail even `-d sat`, needing `-d sntasmedia` or failing entirely) — **verify empirically before
    cutover, not assumed.**
  - **Device identity stability:** TrueNAS community threads document USB-SATA bridges that **fake or
    duplicate reported serial numbers**, causing "Disks have duplicate serial numbers" pool-creation
    failures, and official guidance to "avoid making a pool with multiple disks attached via USB…
    regardless of how many USB disk enclosures that requires." This is a real risk to check **before**
    migrating: does the host's `/dev/disk/by-id/` show 6 genuinely distinct identifiers for the 6
    Seagates? (Non-destructive read-only check, not performed in this research pass per the no-I/O
    constraint during the active resilver — should be the first verification step before adopting this
    option.) Note this risk is orthogonal to which side (host or guest) owns enumeration — it is a
    bridge-firmware property — but the CURRENT guest-side pool already works, which is reassuring
    evidence the bridges are not colliding today; migrating ownership should not change bridge-reported
    identity, but must still be confirmed.
  - **Write-barrier/flush semantics:** `scsi-block` LUN passthrough forwards SCSI commands (including
    SYNCHRONIZE CACHE/flush) directly to the underlying host block device — this is the same mechanism
    already in continuous use for the WD vdev with no reported correctness issues, so no reason to
    expect this specific concern for the Seagates. TRIM is not applicable (spinning HDDs).
  - **Does it remove the failure mode or relocate it?** It removes the **Layer 2 amplifier** specifically
    (host-owned xhci_hcd regains normal, mature, non-virtualized error-recovery paths — the same paths
    the WD vdev already relies on successfully). It does **not** remove **Layer 1** (the ASMedia UAS
    firmware defect itself, or the mild bandwidth oversubscription) — a per-device UAS reset could still
    occur under this design, but would now be handled by the host's well-tested USB stack instead of
    triggering a guest-side, passthrough-fragile controller death. This is a genuine risk reduction, not
    a complete elimination of Layer 1's trigger.
  - **Reconfiguration risk:** Config-only (Proxmox VM 100 definition change: drop `hostpci2`, add 6
    `scsi-block` drives referenced by `/dev/disk/by-id/...`), but it is a one-time, disruptive cutover
    (pool must be exported cleanly from the guest, device ownership changed at the hypervisor level,
    pool re-imported) — should be scheduled as a planned maintenance window, not attempted live, and
    never attempted during an active resilver.

**(4) Does the passthrough hypothesis change the ranking — is the HBA recommendation solving the wrong
problem?** The evidence best supports treating **PCI-passthrough architecture as the dominant amplifier**
of an underlying, real, but on-its-own-insufficient UAS/bandwidth trigger. An HBA (Option, formerly
ranked #2, now #4 — see §5) is not "wrong" — it still fixes Layer 1 as well as Layer 2, and is the only
option that removes the UAS bug class entirely — but it is **not the correct first step**, because it
requires new hardware, a free PCIe slot this host does not currently have, and a full enclosure
replacement, when a config-only change plausibly captures most of the risk reduction by directly
targeting the mechanism the evidence points to as dominant (§2 Layer 2, §3.1).

**Does vfio-pci passthrough defeat the `usb-storage.quirks=174c:55aa:u` kernel quirk?** No — confirmed
not defeated, and this closes the operator's question. Under the CURRENT topology, the entire xHCI PCI
function is bound to `vfio-pci` on the Proxmox **host** (the host kernel's `xhci_hcd`/`usb-storage`
drivers never attach to it at all), so a host-side quirk would indeed do nothing, as the operator
suspected — but that is not what was done. The quirk was applied on the **guest's** kernel cmdline
(TrueNAS VM's own GRUB, per the prior incident record's description of "reboot" referring to the
TrueNAS VM and TrueNAS's own GRUB write), which is the kernel that actually owns and enumerates these
USB devices under whole-function passthrough. The quirk is therefore genuinely in effect where it needs
to be. **If Option 0 (§5) is adopted, the quirk placement must move to the HOST's kernel cmdline**, since
host-owned enumeration would then require the host's `usb-storage` driver to carry the quirk instead.

## 4. Q3 — why is having both vdevs in ONE pool itself part of the risk? (unchanged from first draft, still valid)

**Direct answer: OpenZFS's fault domain is the whole pool, not the vdev — an unrecoverable `raidz2-1`
failure destroys the entire 138 TiB pool, including the completely independent, reliable, ATA-attached
`raidz2-0` (WD) vdev, which shares no hardware (and, per §2, no virtualization architecture) with the
failure-prone Seagate/USB/passthrough path at all.**

- OpenZFS describes non-redundant configurations as "strongly discouraged" because "a single case of
  bit corruption can render some or all of your data unavailable"
  ([zpoolconcepts(7)](https://openzfs.github.io/openzfs-docs/man/master/7/zpoolconcepts.7.html)) — the
  same logic scales up: ZFS stripes pool-wide metadata/free space across all top-level vdevs, so a pool
  is only as available as its least-reliable vdev; there is no per-vdev containment once a vdev goes
  UNAVAIL beyond its redundancy budget.
- This repo's own memory already states the permanence: "RAIDZ vdevs can't be removed once added"
  (`reference_infrastructure_architecture`) — this is not temporary.
- Concretely: `raidz2-1` already ran with **zero remaining redundancy for 3 days** in July. A third
  simultaneous fault during that window (plausible — the trigger was still active) would have taken
  `raidz2-1` UNAVAIL, which propagates to the **whole pool** — the WD vdev's ~73 TiB of independently
  healthy, ATA-attached data included, even though nothing was wrong with that vdev or its (entirely
  separate) virtualization path.

**Bottom line for Q3:** the single-pool design converts a contained, already-identified, high-risk
transport+virtualization combination into an existential risk for data that shares neither the
transport nor the passthrough architecture that is actually implicated in §2. This is additive to Q1:
Q1/§2 explains why `raidz2-1` faults happen and how badly; Q3 explains why, when one eventually goes
uncontained, the blast radius is the whole array.

## 5. Incident evidence table

| Date | Trigger | Symptom | Drives affected | Duration exposed w/o redundancy | Root cause proof |
|---|---|---|---|---|---|
| Jul 26–30 2026 | Scheduled Sunday scrub (~21h in) | 2× Seagate DEGRADED + 1 WD spare UNAVAIL, simultaneous | 3 | 3 days, raidz2-1 at 0 redundancy | Zero SMART/cksum errors on all 3; disks reported live temps; `zpool clear` fully restored |
| Aug 3 2026 | Forced scrub (threshold=0) | All 6 Seagate drives vanish at once; pool SUSPENDED; xHCI controller reported unresponsive per operator-relayed dmesg (`HC died; cleaning up`) — see §6 discrepancy note | 6 | Full pool outage, ~30min to recovery (guest-level); operator notes host-level PCI rebind complications during recovery not captured in the project-memory summary | Zero drive errors; the operator-relayed raw dmesg is a controller-level fault signature (`xHCI host controller not responding, assume dead`), distinct from the purely per-device UAS reset signature the project-memory summary emphasized |

## 6. Evidence discrepancy — flagged, not resolved

This project's stored incident memory (`project_jbod_uas_link_collapse_2026_08_03`) states explicitly:
**"No `HC died` — the xHCI controller stayed healthy."** The operator relayed different raw dmesg lines
for what appears to be the same or a related incident: `xhci_hcd 0000:00:1b.0: xHCI host controller not
responding, assume dead` / `HC died; cleaning up`, plus a `pci_rescan_bus` stack trace during recovery
and a claim that the device would not rebind to vfio-pci without a full host reboot — none of which
appear in the stored memory's recovery procedure (which describes only `qm stop 100` forced, enclosure
power-cycle, `qm start 100`, no host reboot mentioned).

This research pass could not reconcile the two records — it had no read access to raw host dmesg/journal
logs (repo-read-only executor, and explicitly barred from touching the live pool during its active
resilver). **This is treated as the single most important open item from this research**: before acting
on §2's ranked recommendation, whoever has raw log access should confirm (a) which incident (Aug 3, or a
separate undocumented event) produced the `HC died` lines, (b) whether host-level PCI rebind actually
failed short of a full reboot, and (c) update `project_jbod_uas_link_collapse_2026_08_03` accordingly.
If the `HC died`/host-reboot-required details are confirmed, they **strengthen** §2's passthrough-
amplifier conclusion (a controller-level fault with host-level recovery failure is stronger evidence for
"amplified by passthrough" than a purely per-device UAS reset would be). If they turn out to belong to a
different, unrelated event, §2's Layer 2 argument should be revisited and marked more speculative.

## 7. Ranked option space (revised order)

### Option 0 — Host-owned USB enumeration + per-disk `scsi-block` passthrough for the 6 Seagates (NEW, RECOMMENDED FIRST STEP)
**What:** Remove `hostpci2` (whole xHCI-function passthrough); let the Proxmox host enumerate the 6
USB-attached Seagates normally; pass each into the TrueNAS guest as an individual `scsi-block` LUN,
mirroring the already-proven WD pattern exactly.
**Evidence:** §2 Layer 2, §3(3) — directly targets the mechanism this research identifies as the
dominant amplifier; zero-incident track record already exists for this exact virtualization pattern on
this exact host (the WD vdev).
**Cost:** Config-only, no new hardware. One planned, disruptive cutover window (pool export/reconfig/
reimport) — not a live change, never during an active resilver.
**Residual/failure mode:** Does not remove Layer 1 (ASMedia UAS firmware defect, mild oversubscription)
— per-device UAS resets can still occur, now handled by the host's mature stack instead of the guest's
passthrough-fragile one. Two real pre-flight risks must be checked first: (a) do the 6 Seagates present
genuinely distinct serials to the host (`/dev/disk/by-id`) — documented bridge-chip failure mode
elsewhere, not yet checked here; (b) does SAT/SMART passthrough work adequately for monitoring once the
guest is one layer further from the physical device — independently mixed for ASMedia bridges, verify
empirically. Quirk placement must move from guest to host cmdline (§3, quirk-defeat answer).

### Option A — Split into two pools (partition by reliability/virtualization domain)
**What:** Move the WD vdev to its own pool; keep (or migrate) the Seagate vdev as a second, separately-
scoped pool.
**Evidence:** Directly answers Q3 (§4) — OpenZFS fault domain is per-pool.
**Cost:** Full data migration, one-time I/O/downtime window (not during resilver). No new hardware.
**Residual/failure mode:** Does nothing for Q1/§2 — the JBOD-only pool can still SUSPEND on its own;
best paired with Option 0 or B.

### Option D — Throttle scrub/resilver I/O (mitigation layer, cheap, complementary)
**What:** OpenZFS module parameters capping concurrent scrub/resilver I/O per leaf vdev —
`zfs_vdev_scrub_max_active` (default 2 per device), `zfs_rebuild_vdev_limit` (default 64 MiB concurrent
per leaf for sequential rebuilds), pacing via `zfs_resilver_min_time_ms` (1500ms)/`zfs_scrub_min_time_ms`
(750ms). Source: [OpenZFS zfs(4) module
parameters](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Module%20Parameters.html).
**Evidence:** Reduces how close a scrub/resilver pushes the ~1.5× oversubscribed link toward the
queuing-latency regime that increases odds of tripping the Layer 1 UAS bug (§1, §2).
**Cost:** Free, config-only, reversible; needs empirical tuning (not attempted now — active resilver).
**Residual/failure mode:** Only softens Layer 1's trigger probability; does nothing for Layer 2 (§2) or
Q3. Slower scrubs/resilvers mean more total exposure time even if lower risk per unit time.

### Option B — Replace the JBOD with a SAS HBA (IT mode) + true SAS/SATA JBOD chassis (gold-standard, highest cost)
**What:** Eliminate USB/UAS AND whole-controller virtualization risk entirely: LSI/Broadcom SAS HBA in
IT mode, external SAS-expander JBOD chassis, whole-HBA-controller passthrough (the pattern TrueNAS's own
community explicitly endorses for HBAs, unlike USB xHCI controllers).
**Evidence:** "The Broadcom 3008 in IT mode is the de facto standard for ZFS builds in the Proxmox,
TrueNAS… communities." TrueNAS's own hardware guidance and community consensus discourage USB for
reliable storage generally.
**Cost:** Highest. **This host has no free PCIe slot** (3 total: NIC / GPU / TB3 card) — adopting this
means removing the TB3 card and replacing the whole JBOD chassis (the existing QNAP TL-R1200C-RP is
USB-only and cannot be repurposed). Realistic spend: SAS HBA (~$100–250) + SAS-capable JBOD/DAS
enclosure with its own PSU/expander (~$400–1500+), comparable to or above the original $880 JBOD spend.
**Residual/failure mode:** Removes both Layer 1 and Layer 2 entirely — this is the only option that does.
SAS HBA passthrough is community-endorsed specifically (unlike xHCI passthrough); still a single
HBA/cable SPOF for that vdev, but enterprise-hardened hardware, not a consumer 6:1 USB hub tree. Does
not address Q3 alone — pair with Option A.

### Option C — Thunderbolt-native (PCIe-tunneled, non-USB) DAS enclosure, reuse existing TB3 card
**What:** Replace the JBOD chassis with a TB DAS presenting a native SATA/SAS controller over the TB3
PCIe tunnel instead of USB/UAS bridging — e.g. OWC ThunderBay (JMicron JMB-585 SATA controller card,
same Intel JHL-6540 chip already in this host's TB3 card) or Areca ARC-8050T3 (native SAS-3/SATA-III,
RAID-on-chip). Confirms the current TB3 passthrough investment (`hostpci2`) is not itself implicated —
only the downstream USB/UAS bridge layer is being replaced.
**Cost:** Moderate (~$700–1500+ for 8-bay), no PCIe slot change (reuses existing TB3 port/cable).
**Residual/failure mode:** The SAME host-vs-guest ownership question from §2/§3(3) applies here too —
whether to pass the whole SATA/AHCI controller through (more mature/less fragile under vfio than xHCI,
per general community experience, but not independently verified for this device) or use per-disk
`scsi-block`. No incident-report evidence found either way for this exact multi-device-cascade failure
mode on JMicron/Areca TB DAS products — thinner evidence base than B, and lacks Option 0's "already
proven on this exact host" advantage.

### Option E — Keep current mitigation only (quirk + monitoring), accept residual risk
**What:** Status quo since Aug 3: `usb-storage.quirks=174c:55aa:u` (confirmed correctly placed on the
guest, §3) + the shipped `TrueNASDiskCountDrop` Prometheus alert + disabled scheduled scrub (id=4).
**Evidence:** The quirk measurably fixed the Aug 3 disconnect signature in this environment's own
recovery; independent RPi/ODROID reports show it is not universally durable under heavy I/O elsewhere,
but note: **there is no confirmed second local incident since the quirk was applied on Aug 3** — the
current resilver (in progress, outcome unknown at ticket-open) is the first live test of the quirk under
this exact sustained-I/O condition.
**Cost:** Zero additional.
**Residual/failure mode:** Addresses Layer 1's specific UAS-vs-BOT driver choice only; does nothing for
Layer 2 (§2) or Q3. This is a monitoring/detection posture, not a fix.

### Ranking summary
1. **Option 0 (host-owned USB + `scsi-block`)** — targets the mechanism the evidence best supports as
   dominant (§2 Layer 2), zero hardware cost, reuses an already-proven pattern on this exact host. Do
   this first, but only after the two pre-flight checks in Option 0's residual-risk note.
2. **Option A (split pools)** — cheap, directly kills Q3's blast-radius risk regardless of which
   transport fix is chosen; do independent of and alongside Option 0.
3. **Option D (throttle scrub/resilver I/O)** — free, complementary, softens Layer 1's trigger
   probability further.
4. **Option B (SAS HBA + true JBOD)** — the only option that removes Layer 1 (the UAS bug class) AND
   Layer 2 entirely; highest cost/effort because of the PCIe-slot constraint; the right long-term
   destination if Option 0 doesn't fully resolve recurrence.
5. **Option C (TB-native SAS/SATA DAS)** — comparable risk-removal potential to B for less hardware
   disruption, but thinner evidence base; price against B before committing.
6. **Option E (status quo)** — acceptable only as a bridge; per §2 this research now attributes
   significant responsibility for incident severity to the passthrough architecture, which the quirk
   alone does not touch.

## 8. Remaining uncertainty
- **§6's dmesg discrepancy is the top open item** — must be reconciled with raw logs before treating
  §2 Layer 2 as fully proven rather than well-corroborated-but-partially-inferred.
- No vendor (ASMedia) firmware fix specific to the `174c:55aa` UAS defect was found post-2023.
- Option C's reliability track record for this exact failure mode is not independently documented.
- Whether the ASMedia bridges report unique serials to the Proxmox **host** kernel (as opposed to the
  guest, where the pool already works) is unverified — required pre-flight check for Option 0, not
  performed here (no-I/O constraint, active resilver).
- SAT/SMART passthrough reliability for these specific bridges under host ownership is unverified —
  independently reported as chip/firmware-revision-dependent.
- PSU and cable-rating hypotheses for the existing JBOD, flagged as "still unfalsified" in the Aug 3
  incident memory, were not re-tested here.
- No live `zpool status`/`zpool get` was pulled during this pass (explicit ticket instruction not to add
  I/O to the pool during its active resilver); all rig-specific evidence is drawn from prior incident
  telemetry already captured in project memory plus the operator-relayed dmesg lines, not fresh
  measurement.

## Sources consulted
- Linux-USB kernel mailing list: [msg188272](https://www.spinics.net/lists/linux-usb/msg188272.html),
  [msg132563](https://www.spinics.net/lists/linux-usb/msg132563.html)
- Red Hat/Fedora Bugzilla [#1230336](https://bugzilla.redhat.com/show_bug.cgi?id=1230336)
- OpenZFS docs: [zpoolconcepts(7)](https://openzfs.github.io/openzfs-docs/man/master/7/zpoolconcepts.7.html),
  [dRAID Howto](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/dRAID%20Howto.html),
  [Module Parameters / zfs(4)](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Module%20Parameters.html)
- [cr0x.net ZFS resilver explainer](https://cr0x.net/en/zfs-resilver-rebuild-speedup/)
- TrueNAS Hardware Guide + community threads on USB JBOD reliability, duplicate serial numbers, and
  Proxmox `scsi-block` vs whole-HBA passthrough guidance
  ([truenas.com/docs](https://www.truenas.com/docs/scale/gettingstarted/tnhardwareguide/),
  [practicalzfs.com](https://discourse.practicalzfs.com/t/zfs-on-usb-drives-i-know-its-a-bad-idea-but-how-bad-is-it-really/437),
  [Proxmox forum: Pass-through hard drives to TrueNAS](https://forum.proxmox.com/threads/how-to-correctly-passthrough-hard-drives-to-either-unraid-or-truenas-vms.130860/))
- xHCI/vfio-pci passthrough fragility: [pop-os/pop#575](https://github.com/pop-os/pop/issues/575),
  [Proxmox forum: kernel 6.8.12 breaks USB controller
  passthrough](https://forum.proxmox.com/threads/kernel-6-8-12-breaks-usb-controller-passthrough-in-a-weird-way.152508/),
  [xhci MSI interrupt loss, LKML](https://lkml.kernel.org/lkml/20200505201616.GA15481@otc-nc-03/T/),
  [Proxmox forum: PCIe card falls off bus after VM
  reboot](https://forum.proxmox.com/threads/pcie-card-falls-off-the-bus-after-vm-reboot-how-can-i-automatically-reset-it.122917/)
- Vendor specs: OWC ThunderBay (JMicron JMB-585 + Intel JHL-6540), Areca ARC-8050T3
- smartmontools issue tracker on ASMedia SAT-passthrough reliability
  ([smartmontools/smartmontools#160](https://github.com/smartmontools/smartmontools/issues/160))
- This project's own memory: `project_jbod_uas_link_collapse_2026_08_03`,
  `project_truenas_degraded_pool_scrub_2026_07`, `reference_infrastructure_architecture` (primary
  telemetry/incident evidence for this specific rig — see §6 for the unresolved discrepancy against
  operator-relayed raw dmesg)
- Operator-relayed raw dmesg evidence (not independently re-verified in this pass — see §6)