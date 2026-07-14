# VolSync Batched Resume

**When to use:** after VolSync has been *suspended* (an incident load-shed), to bring
backups back **without** the catch-up clone storm.

## Why a plain resume is dangerous (single-node)

After VolSync is suspended for more than a few hours, every ReplicationSource is
schedule-overdue. A plain `flux resume` + `scale controller=1` fires **all ~51 sources
at once** → 51 Longhorn clone volumes create+attach simultaneously → the single-node
instance-manager can't start that many engines → clones **and the source volumes being
cloned** fault. Observed 2026-07-13: a bulk resume faulted 94 real volumes (worse than
the incident it was recovering from). The etcd **SLOG keeps the IM alive** through it
(`restarts=0`), but the storm still faults volumes and knocks apps offline.

**The Longhorn throttle (`concurrentReplicaRebuildPerNodeLimit` /
`snapshotHeavyTaskConcurrentLimit = 2`, commit `dcc127e0d`) does NOT prevent this** — it
caps rebuild/heavy-snapshot, not the clone-volume *create+attach* that actually faults.
Keep it (harmless, helps other cases) but do not rely on it for resume safety.

## The mechanism

VolSync fires a source when the controller is **up AND the source is schedule-overdue**.
Sources are **chart-generated** (the `volsync:` block in each app's helm-release), so Flux
owns their triggers and reverts live edits on its reconcile interval. The safe resume:

1. **Capture & park** — save each source's real trigger; patch all to a never-fire
   schedule (`0 5 31 12 *` = Dec 31, valid cron, won't fire mid-op). Do this while the
   controller is DOWN so nothing fires.
2. **Resume controller & verify** — scale controller up; **confirm 0 movers spawn**
   (proves the park held). If any fire → abort + shed. Critical safety gate.
3. **Batch-sync** — fire N sources at a time via `manual` trigger → wait for their movers
   to Complete → **gate on node CPU + IM restarts** → re-park the batch. A **re-park sweep**
   re-parks any source Flux reverted mid-run.
4. **Restore** — patch each source back to its saved real trigger. Each *just synced*, so
   `lastSyncTime` is fresh → **not overdue → no burst**. Normal nightly cadence resumes.

The keystone is step 4: a source that synced during its batch is no longer "due", so
restoring its real schedule hands back to normal operation instead of re-bursting.

## Usage

```bash
# ALWAYS dry-run first (also confirms the cluster is idle enough to start):
DRY_RUN=true ./scripts/volsync-resume 5

# real run (batch size 5; smaller = gentler). Preflight aborts if node CPU>65%,
# IM has restarts, or any real volume is faulted.
./scripts/volsync-resume 5
```

Preconditions: run it **from the post-shed state** — controller at `replicas=0`,
`ks`/`hr` volsync suspended, cluster idle (`node cpu <65%`, `IM restarts=0`,
`real_faulted=0`). If a batch trips a gate it pauses; if it stays unhealthy it exits
leaving the remaining sources parked (safe to re-run — it's idempotent).

## Manual fallback (if the script is unavailable)

```bash
PARK='0 5 31 12 *'
# 1. capture + park all (controller already down)
for s in $(kubectl get replicationsource -A --no-headers | awk '{print $1"/"$2}'); do
  ns=${s%%/*}; nm=${s##*/}
  kubectl get replicationsource -n $ns $nm -o jsonpath='{.spec.trigger}'; echo "  <- $s (save this)"
  kubectl patch replicationsource -n $ns $nm --type=merge -p "{\"spec\":{\"trigger\":{\"schedule\":\"$PARK\"}}}"
done
# 2. controller up, verify 0 movers over ~35s
flux resume hr -n volsync volsync; flux resume ks volsync; kubectl scale deploy -n volsync volsync --replicas=1
# 3. per batch of 5: fire, wait, re-park
kubectl patch replicationsource -n <ns> <nm> --type=merge -p '{"spec":{"trigger":{"manual":"resume-1"}}}'
#    ...watch node/IM, wait for status.lastManualSync=="resume-1", then re-park each with $PARK...
# 4. restore each saved trigger:
kubectl patch replicationsource -n <ns> <nm> --type=merge -p '{"spec":{"trigger":{"schedule":"<orig>"}}}'
```

## The script (`scripts/volsync-resume`, gitignored — canonical copy here)

The executable lives at `scripts/volsync-resume`. If lost, recreate it from the copy in
this runbook's git history (the script file was authored 2026-07-14). Key safety
properties: (a) preflight refuses to start on a busy/unhealthy cluster; (b) Phase-2
park-verification aborts before any batch if sources fire; (c) per-batch CPU + IM-restart
gates; (d) `DRY_RUN=true` plans without mutating.

## Related

- Incident + why bulk-resume fails: memory `volsync-operational-procedures`,
  `longhorn-mass-salvage-im-deathspiral-2026-07`
- The salvage side (recovering already-faulted volumes): clear replica `failedAt` in
  batches of ~8, gate on IM restarts (not CPU — app-startup legitimately pins CPU high
  once the SLOG is in). See `salvage.sh` pattern in the same memory.
- Root storage fix (why the IM survives now): `proxmox-etcd-disk-layer` (the SLOG).
