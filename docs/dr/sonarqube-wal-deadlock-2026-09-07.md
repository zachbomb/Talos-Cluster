# SonarQube CNPG: four-month WAL deadlock

**Date:** 2026-09-07 · **Duration:** archiving broken 2026-05-14 → 2026-09-07 (~116 days);
database down 2026-09-05 01:09Z → 2026-09-07 21:16Z
**Impact:** SonarQube unavailable ~2.5 days. **No usable backup existed for four months.**

---

## The one-line cause

`barman-cloud-check-wal-archive` refuses to archive into a non-empty archive belonging to a
previous cluster incarnation:

```
ERROR: WAL archive check failed for server sonarqube-db: Expected empty archive
```

The cluster was re-bootstrapped **2026-06-29**, but S3 still held **47 WAL objects from
2026-05-14** written by the previous incarnation. Archiving therefore never started.

---

## The deadlock

It is self-sustaining, which is why it never recovered on its own:

```
archive check fails (stale objects present)
   -> PostgreSQL cannot archive a WAL segment
   -> PostgreSQL MAY NOT RECYCLE an unarchived segment
   -> WAL accumulates on the DATA volume (no separate walStorage)
   -> volume hits 100%  (2026-09-05)
   -> "Not enough WAL disk space, avoid starting PostgreSQL"
   -> PostgreSQL will not start
   -> it cannot archive
   -> WAL never drains  ---------------------------------------+
                                                               |
   <-----------------------------------------------------------+
```

Proportions at the point of failure — the database was never the problem:

```
pg_wal   9.7 GB   (99.3%)
base      66 MB   (0.7%)   <- the actual SonarQube database
volume   10.81 GB used / 10.74 GB provisioned = 101% FULL
```

---

## Ruled out with evidence (do not re-chase)

The obvious suspects were all wrong, and checking them first was cheap:

| Suspect | Verdict | Evidence |
|---|---|---|
| MinIO down | NO | health endpoint 200 in 0.26s |
| Bucket missing | NO | `cnpg-sonarqube` exists, created 2026-05-14 22:36 |
| Credentials bad | NO | same creds list all buckets fine |
| S3 endpoint wrong | NO | goodmem-db, triparr-db, immich-cnpg-main all archive to the SAME endpoint with `ContinuousArchiving=True` |

**Three sibling clusters archiving successfully to the same MinIO is what proved the fault was
cluster-specific rather than infrastructural.** Always check whether a peer works before
blaming shared infrastructure.

I also had the causality backwards at first — assuming archiving failed *because* the disk was
full. The log settles it: `"Not enough WAL disk space, avoid starting PostgreSQL"`. Archiving
broke on 2026-05-14; the disk did not fill until 2026-09-05. **Archiving was cause, disk-full
was effect.** The `ContinuousArchiving=False since 2026-05-14` condition timestamp is what
disambiguates, and it is worth reading before theorising.

---

## Repair sequence (order matters)

Each step revealed the next. None would have worked alone.

**1. Expand the volume 10Gi → 20Gi** — breaks the start-up deadlock so PostgreSQL can run.
The CNPG operator does NOT resize the PVC itself; it logs
`"Insufficient disk space detected in a pod. PostgreSQL cannot proceed until the PVC group is
enlarged"` and waits. Patch the PVC to match `spec.storage.size` (longhorn storageclass has
`allowVolumeExpansion: true`, so it is online):

```
kubectl patch pvc -n sonarqube sonarqube-db-1 \
  -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
```

**2. Clear the stale WAL archive** — preserve first, then delete, so it is reversible:

```
aws s3 cp s3://cnpg-sonarqube/sonarqube-db/wals/ \
          s3://cnpg-sonarqube/ORPHANED-pre-20260629-bootstrap/wals/ --recursive
# verify 47 copies exist, THEN
aws s3 rm s3://cnpg-sonarqube/sonarqube-db/wals/ --recursive
```

Safe because there was **no `base/` prefix** — WAL without a base backup cannot restore
anything, so those 47 objects had exactly zero recovery value. Verify that before deleting.

Archiving resumed within seconds: `ContinuousArchiving=True / ContinuousArchivingSuccess`.

**3. ⚠ Delete the WEDGED Backup object** — this is the step that is easy to miss:

```
sonarqube-db-daily-20260904170330   phase=walArchivingFailing   <- holds the backup lock
```

Operator log: `"A backup is already in progress or waiting to be started, retrying"`.
A Backup stuck in a non-terminal phase blocks EVERY subsequent backup indefinitely, including
manual ones. **Fixing the root cause is not enough — the wedged object must be deleted or the
queue stays blocked forever.** This is the same shape as
[[restic-lock-staleness-and-job-wedge]]: lock is the cause, the wedged job blocks self-healing.

Find them with:

```
kubectl get backups.postgresql.cnpg.io -A -o json | \
  jq '.items[] | select(.status.phase != "completed" and .status.phase != "failed")
      | {ns:.metadata.namespace, name:.metadata.name, phase:.status.phase}'
```

**4. Take a base backup.** Until one exists the archive is not a recovery point.

---

## Result

```
                    before              after
volume              101% full           4% full (707MB / 20GB)
pg_wal              9.7 GB              641 MB
ContinuousArchiving False (116 days)    True
base backups        0 (ever)            2
archived WAL        47 (frozen in May)  626
backups             118 objects, 0 completed / 117 failed   -> completed
sonarqube app       CrashLoopBackOff    1/1 Running
```

---

## Recurrence fix applied

`walStorage: 8Gi` added (commit alongside this doc). Without a separate WAL volume, unarchivable
WAL grows on the DATA volume until PostgreSQL cannot start. With it, the same failure fills only
the WAL volume — PostgreSQL still stops, but the failure is isolated and legible instead of
terminal. 8Gi is sized against the real observed worst case (9.7GB over four months), not 2Gi,
which fills in days.

**Verified with `kubectl apply --dry-run=server`** (runs the CNPG validating webhook) before
committing. Adding walStorage to a live cluster provisions a new PVC and recycles the instance,
so expect a brief outage on reconcile.

---

## ⚠ Two things this exposed that are NOT fixed

**1. Nothing alerted for four months.** 117 consecutive backup failures and a database with no
recovery point produced no signal anybody acted on. The fix here is worth less than closing
that gap — a backup system that fails silently is indistinguishable from no backup system.
A useful alert is not "a backup failed" but **"`LastBackupSucceeded=False` for > 48h"** or
**"no `base/` object newer than N days"**, both of which would have fired in May.

**2. `spec.backup.barmanObjectStore` is DEPRECATED.** Surfaced by the dry-run webhook:

> *Native support for Barman Cloud backups and recovery is deprecated and will be completely
> removed in CloudNativePG 1.31.0. Found usage in: spec.backup.barmanObjectStore. Please
> migrate existing clusters to the new Barman Cloud Plugin.*

Operator is currently **1.30.0** — one minor release away. This affects **every** CNPG cluster
here (sonarqube, goodmem, triparr-db, immich-cnpg-main), not just this one. Plan the migration
before upgrading the operator, or backups break cluster-wide.

Also flagged: `spec.monitoring.enablePodMonitor` is deprecated.

**3. ~~No other CNPG cluster has `walStorage`.~~ CORRECTED 2026-09-07 — and the error is worth
keeping, because it came from a parsing bug rather than from the cluster.**

```
spec.walStorage.size            <- goodmem / triparr / sonarqube
spec.walStorage.pvcTemplate...  <- what the immich HELM CHART generates
```

Probing `.get('size')` returns `None` for a pvcTemplate-style spec, so immich reported
`walStorage=None` when it in fact had one all along. **A None from a field probe means "not
found at that path", never "not configured"** — check the alternate representation before
concluding absence.

All four verified and now standardised:

```
sonarqube/sonarqube-db   walStorage 8Gi          (added 2026-09-07)
goodmem/goodmem-db       walStorage 8Gi          (added 2026-09-07)
triparr-bot/triparr-db   walStorage 8Gi          (added 2026-09-07)
media/immich-cnpg-main   walStorage 2Gi -> 8Gi   (ALREADY isolated; resized)
```

immich's real problem was never absence, it was SIZING: 2Gi measured 609MB and 593MB used
across its two instances — **~32% full at steady state**, against 8% for the others. Under an
archiving failure that fills in days, not months.
