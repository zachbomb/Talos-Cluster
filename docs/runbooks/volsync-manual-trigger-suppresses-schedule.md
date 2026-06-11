# VolSync: a manual trigger silently suppresses the schedule

## The gotcha (diagnosed 2026-06-10)

A VolSync `ReplicationSource` trigger is meant to be **either** `manual` **or**
`schedule`. If both are present in `spec.trigger`, **`manual` wins**: VolSync
runs once when `spec.trigger.manual != status.lastManualSync`, then the
`Synchronizing` condition goes `False / reason=WaitingForManual` and stays there
**forever** — the cron `schedule` is completely ignored until the `manual` key
changes or is removed.

There is no alert for this. The source is not "failed" — it's idle. A health
dashboard shows it green. The only signal is a stale `status.lastSyncTime`.

## How it bites

Forcing a one-off backup during recovery (e.g. after the S3 versioning-bloat fix
in `volsync-s3-versioning-bloat.md`, or a stuck-clone cleanup) is done by
patching a manual trigger:

```bash
kubectl patch replicationsource -n media <src> --type=merge \
  -p '{"spec":{"trigger":{"manual":"force-'"$(date +%s)"'"}}}'
```

That manual key **persists** in the live resource. Helm/Flux never remove it —
it isn't declared in the helm-release, so Helm's 3-way merge doesn't track it and
won't reconcile it away. The source runs once, then silently stops backing up on
schedule.

On 2026-06-10 a health sweep found **8 sources pinned** to manual triggers:
- `immich-library` + `immich-backups` — last sync **April 1**, stale 70 days.
- `bazarr`, `radarr`, `lidarr`, `emby`, `tunarr`, `paperless-ngx` — pinned that
  same day by the S3-bloat recovery work (`force-`/`recover-`/`clean-` keys).
  They had backed up once on the manual trigger but would have stopped after that.

## Detect

```bash
kubectl get replicationsource -A -o json | python3 -c "
import json,sys,datetime
d=json.load(sys.stdin)
now=datetime.datetime.now(datetime.timezone.utc)
for r in d['items']:
    tr=(r.get('spec',{}).get('trigger') or {})
    n=r['metadata']['namespace']+'/'+r['metadata']['name']
    ls=r.get('status',{}).get('lastSyncTime')
    age=''
    if ls:
        age='%.0fh' % ((now-datetime.datetime.fromisoformat(ls.replace('Z','+00:00'))).total_seconds()/3600)
    if 'manual' in tr:
        print('PINNED', n, tr, 'last='+str(ls), age)
"
# Healthy sources have trigger={'schedule':'...'} ONLY. Any 'manual' key = pinned.
```

## Fix (non-destructive — only RE-ENABLES backups)

Remove the manual key; the existing `schedule` resumes at the next cron tick:

```bash
kubectl patch replicationsource -n <ns> <src> --type=json \
  -p '[{"op":"remove","path":"/spec/trigger/manual"}]'

# verify:
kubectl get replicationsource -n <ns> <src> -o jsonpath='{.spec.trigger}'
#   -> {"schedule":"0 0 * * *"}   (no manual)
```

To force an immediate catch-up first (stale source), bump `manual` to a NEW
value, wait for the mover to finish (the `Synchronizing` condition returns to
`WaitingForManual`), THEN remove `manual`. The immich library/backups movers
took ~90s each (the data is tiny).

## Process rule

**After ANY forced VolSync backup, clear the manual key in the same session.**
Leaving it pinned converts a one-off recovery action into a permanent backup
outage. After a recovery sweep, run the detection scan above and confirm it
returns zero pinned sources.

## Severity note (immich specifically)

immich's stale `library`/`backups` exposure was LOW: its postgres is
independently backed up via CNPG -> S3 (daily 3am, 14d retention), and the
volsync `library`/`backups` PVCs are tiny (last runs were 13 B and 32 MB — the
real photos live on the NFS `media` mount plus the non-volsync `thumbs`/`video`
PVCs). The broken *config* was the issue, not imminent data loss. The 6
*arr/paperless sources were the larger latent gap.

## Related

- `volsync-s3-versioning-bloat.md` — the recovery work that set the stray manual triggers.
- `longhorn-recovery.md` — VolSync clone stalls after Longhorn engine upgrades.
