## The failure mode (diagnosed 2026-06-10)

24 VolSync ReplicationSources had been stuck for up to 2 months (April 6 cohort). Three linked symptoms, one root cause:

1. **`Bucket quota exceeded`** (radarr): `config-radarr` had a 10 GiB hard quota and was at exactly 10 GiB *counting all versions*.
2. **`no space left on device` on `/cache`** (lidarr, emby, tunarr, paperless): restic mover couldn't fit the repo index in the cache PVC.
3. **`failed to take snapshot of the volume ... engine is upgrading to v1.11.1`** (bazarr, calibre, cwa, emby, etc.): stuck Longhorn VolumeSnapshots from the April 1.11 engine upgrade (separate but concurrent — see `VolSync Clone Stuck After Longhorn Upgrade` note in MEMORY.md).

**Root cause for #1 and #2: S3 bucket versioning was enabled on all 40 backup buckets.** restic is content-addressed and immutable — it never overwrites pack files, it writes new ones and `prune` deletes old ones. With S3 versioning ON, every prune-deleted object becomes a *noncurrent version* retained forever. Result: repos bloated 5-30×:
- plex: 15 GiB current → 481 GiB versioned (466 GiB of dead pack files)
- emby: 12 → 226 GiB
- lidarr: 11 → 63 GiB
- ollama: 82 → 139 GiB

This bloat (a) filled the radarr quota and (b) made restic's repo index too big for the small cache PVCs (2-5 GiB).

## The fix

```bash
# MinIO client via a throwaway pod (note: minio/mc busybox lacks awk/sed/grep —
# parse output in a local python, not in the pod shell)
MC_HOST_tn=http://$S3ID:$S3KEY@192.168.10.122:9000

# 1. Remove the hard quota that's actively blocking
mc quota clear tn/config-radarr

# 2. Suspend versioning on ALL backup buckets (restic never needs it)
for b in $(mc ls tn | ...); do mc version suspend tn/$b; done

# 3. ILM rule to auto-expire noncurrent versions (durable mechanism)
for b in ...; do mc ilm rule add tn/$b --noncurrent-expire-days 1; done

# 4. Immediate purge of existing noncurrent versions (restic-SAFE — these are
#    pack files restic already prune-deleted; current versions are the live repo)
for b in ...; do mc rm --recursive --force --versions --non-current tn/$b; done

# 5. Bump cache PVCs for large repos (helm-release volsync.*.cacheCapacity),
#    delete the undersized cache PVCs so volsync recreates at new size
#    lidarr 3→10Gi, emby 5→12Gi, tunarr 3→8Gi, paperless 2→8Gi
```

For the stuck Longhorn snapshots (#3): delete the `readyToUse=false` `-src` VolumeSnapshots + their `-src` clone PVCs + stuck mover pods; VolSync recreates fresh snapshots on the next cycle (per the existing Longhorn-upgrade-stuck-clone note).

## Results

- MinIO usage: 1.5 TiB → 824 GiB and dropping (ILM still purging)
- 17 of 24 stuck sources re-synced within hours; remaining 4 (big-repo cache issue) clear on next scheduled sync with bigger caches
- 40 → 38 buckets (deleted orphans config-dizquetv + config-calibre-web)

## Why save this

S3 versioning + restic is a silent time bomb: it works fine for months, then repos cross the quota/cache thresholds simultaneously and ALL backups for an app silently stop. The "successful" last-mover-status masks it — the *condition* wedges at SyncInProgress while `lastSyncStartTime > lastSyncTime`. **Detection:** `kubectl get replicationsource -A` and look for sources whose lastSyncTime is days/weeks old while reason=SyncInProgress. **Prevention:** never enable S3 versioning on a restic/VolSync bucket. If MinIO defaults buckets to versioned, suspend it + add the ILM rule at bucket-creation time.

Related: `cnpg-netpol-and-immutable-sts`, `post-recovery-crashloop-sweep`.
