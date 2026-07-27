# Single-Node Cluster — Disaster Recovery Runbook

**Purpose:** Rebuild the cluster after Talos-node loss or full host disaster. This is a **single-node cluster by design** (no HA, no equipment for it) — recovery is **rebuild-from-backups**, not failover. The whole point of the GitOps + VolSync + SOPS setup is that the node is *disposable* as long as the recovery artifacts survive.

## The recovery artifacts — know where each lives (order = dependency order)
| # | Artifact | Location | Without it… |
|---|---|---|---|
| 1 | **SOPS age key** | **1Password** ("Talos cluster SOPS age key") | git is an encrypted brick — **nothing** is recoverable. Get this FIRST. |
| 2 | Manifests + talconfig + encrypted secrets | GitHub `zachbomb/Talos-Cluster` | no cluster definition |
| 3 | ClusterTool binary | re-download: trueforge-org/clustertool **v4.0.0** (`clustertool_4.0.0_darwin_all.tar.gz`) | can't genconfig/init (v1.13.5 needs 4.0) |
| 4 | App configs/DBs | MinIO/S3 on the **TrueNAS VM** (WD pool) | app state lost (media is separate, see below) |
| 5 | Media (the bulk) | TrueNAS/WD pool, mounted via NFS | — (not on the Talos node; survives node loss) |
| 6 | **Proxmox VM 105 spec** | ⚠️ **NOT in git** — capture it (see Action Items) | must reconstruct disk/GPU/NIC layout from memory |
| 7 | etcd snapshot | ⚠️ manual only, no automation yet | slower rebuild (Flux+git rebuilds without it) |

**Truly offsite = only #1 (1Password) and #2 (GitHub).** #4/#5 are same-host as the node (TrueNAS VM on the same Proxmox box) → survive node death, NOT a site disaster.

## Which scenario are you in?
- **A — Talos VM lost, Proxmox host + disks intact** (VM corruption, fat-finger delete, the common case). Longhorn data (D3-S4510) and possibly the STATE partition survive → fastest path, often no data restore needed.
- **B — Full disaster** (host gone, disks gone) → rebuild everything from git + MinIO.

---

## Scenario A — VM lost, disks intact (fast path)
1. age key from 1Password → `age.agekey` on the workstation; clone the repo.
2. Recreate VM 105 from the saved spec (`dr/vm-105.conf`): same system disk, D3-S4510 passthrough (Longhorn data), GPU passthrough, NIC/MAC, CPU/RAM.
3. **If the system disk STATE partition survived** → boot; the node rejoins with etcd + config intact. Verify health, done.
4. **If the system disk is gone but the D3-S4510 (Longhorn) survived** → do Scenario B steps 3–6 to reinstall Talos, then Longhorn re-discovers its replicas on the D3-S4510 and re-attaches volumes — **apps come back with their data, no VolSync restore needed.**

---

## Scenario B — Full rebuild
1. **Workstation prep:**
   - Get `age.agekey` from 1Password.
   - `git clone https://github.com/zachbomb/Talos-Cluster && cd Talos-Cluster`; place `age.agekey` at the repo root.
   - Download ClusterTool v4.0.0 → `./clustertool`. Install: `talosctl`, `kubectl`, `sops`, `flux`, `age`.
2. **Proxmox:** recreate VM 105 from `dr/vm-105.conf` — system disk (new; must match `installDiskSelector: size <= 2400GB`), D3-S4510 passthrough (if it survived, Longhorn data is on it), GPU passthrough (i915 + A4000), NIC on vmbr0 with the MAC, 8 cores / 48 GB / cpuunits=4096.
3. **Render config:** `./clustertool genconfig` (decrypts `clusterenv.yaml` + `talsecret.yaml` via `age.agekey`). ⚠️ genconfig decrypts SOPS files in place even on success — `./clustertool encrypt && ./clustertool checkcrypt`, `git status` before any commit.
4. **Install Talos + bootstrap the control plane:**
   - `./clustertool init` (installs Talos to the system disk, bootstraps etcd, bootstraps Flux with the SOPS `sops-age` secret from `age.agekey`).
   - **If you have an etcd snapshot** (once the CronJob exists): recover it instead of a fresh bootstrap — `talosctl bootstrap --recover-from-snapshot <db>` — to restore exact state. Otherwise fresh etcd + Flux rebuild (below) is fine for GitOps.
5. **Flux reconciles everything from git** → namespaces + apps deploy (empty data). Watch `flux get kustomizations --status-selector ready=false`. Expect the layered bring-up (kube-system → system → core → networking → apps).
6. **Restore app data (VolSync):** ReplicationDestinations pull each app's restic backup from MinIO → repopulate configs/DBs. See the VolSync operational-procedures memory for manual restore (dest.enabled apps, clone flow, the manual-trigger gotcha). Media needs no restore (it's on TrueNAS NFS).
7. **Verify:** node Ready; etcd HEALTH OK; `flux get all` green; VolSync sources synced; NFS `/var/mnt` reachable; Plex/apps functional.

---

## Immediate ACTION ITEMS (do these now, before you need the runbook)
1. **Capture the VM spec** (it's the one recovery artifact not in git):
   ```bash
   # on pibbthecat:
   qm config 105 > /root/dr-vm-105.conf   # then copy into the repo at docs/dr/vm-105.conf, or store with backups
   ```
   Re-capture after any VM change (disk add, GPU change). Low-sensitivity (MAC/UUID only) — fine to commit to the private repo.
2. **Build the etcd-snapshot CronJob** → MinIO (the accelerator; makes step 4 restore exact state and captures non-git bits).
3. **Dry-run this runbook** on a throwaway VM someday — DR you haven't rehearsed isn't DR. Especially validate the `clustertool init` + `--recover-from-snapshot` flow.

## Known gaps / residual risk (honest)
- **Same-site backups:** MinIO (app data) + the Proxmox host are one physical box. A site disaster (fire/theft/flood) loses app-config backups; only git + the 1Password key are offsite. Media is re-acquirable. Consider offsite MinIO replication for the highest-value config buckets if warranted.
- **No automated etcd snapshot yet** → rebuild loses non-git state (recreated by Flux/VolSync anyway), just slower.
- **The `clustertool init` rebuild flow is unvalidated** for a from-scratch DR — hence the dry-run action item.
- Keep the VolSync S3 bucket **versioning OFF** (restic bloat — see memory).
