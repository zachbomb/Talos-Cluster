# Maintenance Runbook: Add an Optane SLOG to fix slow etcd fsync (#158)

**Goal:** Stop the recurring control-plane lease-loss cascade by fixing the root
cause — slow synchronous-write latency on the QLC NVMe pool that backs etcd's WAL.

**When to run this:** A planned maintenance window. This requires a **full host
power-down** (see the warning below), so it is *not* a live-patch.

---

## Why (the problem this fixes)

etcd commits every write to its WAL with `fsync()` before acking. On this cluster
the pool backing the Talos VM is a **2× Sabrent Rocket Q 4 TB QLC NVMe mirror with
no SLOG**, and QLC sync-write latency is poor:

| Metric (measured 2026-06-21) | This cluster | Healthy etcd |
|---|---|---|
| WAL fsync p99, 24h median | **98 ms** | < 10 ms |
| Share of day with p99 > 100 ms | **43 %** (124/288 samples) | ~0 % |
| Peak stall under I/O load | **8.2 s** WAL fsync / 3.9 s backend commit | — |

When fsync spikes, the Kubernetes leader-election leases (kube-scheduler,
kube-controller-manager) that live *inside* etcd miss their renewal deadline. The
component yields leadership, the kubelet restarts it, and that churn recreates the
Longhorn instance-manager → mass single-replica volume re-attach storm. See
`docs/runbooks/longhorn-recovery.md` and the memory note
`project-proxmox-etcd-disk-layer`.

**What's already in place (do NOT re-do):**
- Talos `cluster.etcd.extraArgs`: `heartbeat-interval=500`, `election-timeout=5000`
  (`clusters/main/talos/patches/controlplane.yaml`) — *tolerance*, not a fix.
- VM disk `cache=writeback` (task #156) — already the fast safe option for this pool.
- Longhorn `instanceManagerPodLivenessProbeTimeout=30` — caps each spike's blast
  radius to a ~8-min self-heal, but does nothing for the spikes themselves.

A SLOG is the targeted fix: it routes etcd's synchronous ZIL writes to a
low-latency device instead of the QLC mirror.

---

## ⚠️ Blast radius — read first

- **Single control-plane node.** There is no HA. Powering off the Proxmox host =
  **total cluster API + workload outage** for the entire window. Plan for ~45–90 min.
- M.2 / PCIe Optane is **not hot-swappable** on this consumer board — budget for a
  full power-down, not a hot-add.
- Tell anyone who depends on the lab (Plex, Home Assistant, etc.) before starting.

---

## Hardware (buy before the window)

- **Intel Optane with power-loss protection.** Recommended: **Optane P1600X 118 GB
  (M.2 2280)** (~$90–130). Acceptable: Optane M10 16 GB (marginal but works — ZIL
  only needs to hold ~5 s of writes) or a 900p/905p/P4801X AIC if you have a PCIe slot.
- **Why Optane specifically:** the SLOG must have PLP, or a power loss mid-write
  corrupts the very durability the ZIL exists to guarantee. Do **not** use a spare
  consumer SSD (Kingston/Samsung EVO/QLC) as a SLOG.
- **Confirm a free slot first** — the board already has 2× 4 TB NVMe (+ GPU). If no
  M.2 slot is free, you need a PCIe Optane AIC or an M.2-to-PCIe adapter. Verify
  before purchase: `ssh root@192.168.10.30 'lspci | grep -i nvme; ls /dev/nvme*'`.
- **Mirroring the SLOG:** optional. Since ZFS ≥0.7, losing an unmirrored log device
  just falls back to in-pool ZIL (no pool loss) — only an unmirrored-SLOG failure
  *during* a power loss risks the last few seconds of writes. A single Optane is an
  accepted home-lab trade-off; mirror two if you want belt-and-suspenders.

---

## Phase 0 — Pre-window baseline (do the day before, cluster live)

Capture a "before" number so you can prove the fix worked.

```bash
# From your workstation — port-forward Prometheus and record 24h p99 fsync.
kubectl -n kube-prometheus-stack port-forward svc/kube-prometheus-stack-prometheus 9090:9090 &
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.99, sum(rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) by (le))' \
  | python3 -c 'import sys,json;print("p99 fsync now (ms):",round(float(json.load(sys.stdin)["data"]["result"][0]["value"][1])*1000,1))'
# Expect ~90–250 ms. Write it down.
```

```bash
# On the Proxmox host — baseline fsync throughput.
ssh root@192.168.10.30 'pveperf | grep FSYNCS'   # QLC mirror today: expect < 100/s
```

**Confirm a known-good etcd backup exists before touching anything:**
```bash
talosctl -n 192.168.10.89 etcd snapshot /tmp/etcd-pre-slog.db
ls -lh /tmp/etcd-pre-slog.db   # should be tens-to-hundreds of MB, non-zero
```
Also confirm recent VolSync/Longhorn backups are current (`./scripts/backup-audit -v`).

---

## Phase 1 — Identify the pool and target device (host, before power-down)

```bash
ssh root@192.168.10.30

# 1. Which zpool backs the Talos VM disk (VMID 105)?
qm config 105 | grep -E 'scsi|virtio|sata'        # note the storage ID, e.g. local-zfs:vm-105-disk-0
grep -A4 'zfspool: local-zfs' /etc/pve/storage.cfg # 'pool <NAME>' is the real zpool name
zpool status                                       # confirm <NAME> is the QLC mirror, NOT rpool/boot
```

> The SLOG must be added to the **pool that holds vm-105's disk** (the storage ID
> `local-zfs` maps to a zpool name in storage.cfg). If that turns out to be the boot
> pool, stop and reconsider — adding a log to the boot pool is fine but double-check
> you're not about to touch an HDD pool by mistake.

You'll resolve the Optane's stable `by-id` path *after* it's physically installed
(Phase 3), so it survives reboots and slot changes.

---

## Phase 2 — Graceful shutdown

```bash
# Stop the Longhorn churn first so nothing is mid-write to etcd.
# (Optional but tidy on a single node — suspend Flux so it doesn't fight you on boot.)
flux suspend kustomization --all

# Graceful etcd-safe shutdown of the Talos node, then the VM, then the host.
talosctl -n 192.168.10.89 shutdown            # waits for etcd to leave cleanly
# wait for the VM to stop:
ssh root@192.168.10.30 'qm status 105'        # -> status: stopped
ssh root@192.168.10.30 'shutdown -h now'      # power off the host
```

---

## Phase 3 — Install + add the SLOG

1. Physically install the Optane in the free M.2/PCIe slot. Power the host back on.
2. Identify the new device by stable id (do **not** use `/dev/nvmeXn1` — it renumbers):

```bash
ssh root@192.168.10.30
ls -l /dev/disk/by-id/ | grep -i nvme        # find the Optane's nvme-<MODEL>_<SERIAL> entry
# sanity: it should be the small/Optane model, NOT one of the 4TB Sabrents
nvme list
```

3. Add it as a log device to the pool (replace `<POOL>` and the by-id path):

```bash
POOL=<POOL>                                  # from Phase 1
OPTANE=/dev/disk/by-id/nvme-<OPTANE_MODEL_SERIAL>
zpool add "$POOL" log "$OPTANE"
zpool status "$POOL"                         # MUST now show a 'logs' section with the Optane ONLINE
```

> Mirrored variant (two Optanes): `zpool add "$POOL" log mirror $OPTANE_A $OPTANE_B`

4. Bring the cluster back:
```bash
ssh root@192.168.10.30 'qm start 105'        # if not set to auto-start
# wait for the API, then:
flux resume kustomization --all
```

---

## Phase 4 — Verify it's working

```bash
# 1. Sync writes are actually hitting the log device (watch a few intervals).
ssh root@192.168.10.30 "zpool iostat -v $POOL 5 3"
#    -> the 'logs' / Optane row should show write ops during cluster activity.

# 2. Host fsync throughput jumped.
ssh root@192.168.10.30 'pveperf | grep FSYNCS'        # target > 300/s (was < 100)

# 3. etcd p99 fsync dropped — the real proof. Re-run the Phase 0 Prometheus query
#    after ~1h of normal load and compare:
#       before: ~90–250 ms   ->   after: target < 10–20 ms
```

```bash
# 4. Control-plane stopped flapping. Restart counts should now hold steady over days.
kubectl get pods -n kube-system | grep -E 'kube-scheduler|kube-controller-manager'
#    (note the RESTARTS value; check again next day — it should not climb.)
kubectl get pod -n longhorn-system -l longhorn.io/component=instance-manager
#    IM age should keep growing; restarts should stay 0.
```

**Success criteria:** etcd WAL fsync p99 < ~20 ms sustained, `pveperf` FSYNCS > 300/s,
and no new kube-scheduler/KCM/instance-manager restarts over the following 24–48h.

---

## Rollback

ZFS log-device removal is **online and non-destructive** (the ZIL falls back into
the pool):

```bash
ssh root@192.168.10.30 "zpool remove <POOL> <OPTANE-by-id>"
zpool status <POOL>     # 'logs' section gone
```

If the cluster won't come back after boot, the etcd snapshot from Phase 0 restores
state — see Talos etcd recovery docs / `longhorn-recovery.md`.

---

## Notes / follow-ups

- This does **not** replace the dead `sdd` Kingston SATA SSD (100 % wearout) — that's
  a separate item, but if you're already inside the case, swap it in the same window.
- If `pveperf` FSYNCS is already > 300/s before installing (unlikely here), the disk
  layer is NOT the bottleneck — stop and re-investigate etcd-specific causes (DB
  compaction cadence, snapshot frequency, apiserver request churn).
- Leave the Talos `heartbeat/election` tuning in place; it's harmless tolerance.
- Related: `docs/runbooks/longhorn-recovery.md`, memory `project-proxmox-etcd-disk-layer`,
  `proxmox-host-memory-pressure-slog`. Task #158.
