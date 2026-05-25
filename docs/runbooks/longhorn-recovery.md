# Longhorn Recovery Runbook

**When to read this:** Apps stuck in `ContainerCreating`, "FailedAttachVolume" events, Longhorn volumes in `faulted` / `detaching` / stuck `attaching` states.

**Cluster context:** Single-node Talos, Longhorn 1.11.2, single-replica volumes, CSI sidecars at 2 replicas (post-CM-1).

---

## Quick triage (5 minutes)

```bash
# 1. What's the volume state distribution?
kubectl get volumes.longhorn.io -n longhorn-system -o json | python3 -c "
import sys, json
d = json.load(sys.stdin)
counts = {}
for v in d['items']:
    s = v['status']; key = f\"{s.get('state')}/{s.get('robustness')}\"
    counts[key] = counts.get(key, 0) + 1
for k, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  {k}: {n}')
"

# 2. Which apps are stuck?
kubectl get pods -A | grep -E "ContainerCreating|Init:0"

# 3. Which volumes are problematic?
kubectl get volumes.longhorn.io -n longhorn-system | grep -E "faulted|detaching|attaching"
```

If counts show **only** `attached/healthy` and `detached/unknown`: Longhorn is fine, problem is elsewhere (DNS, RBAC, image pull).

If any volumes are `faulted` or stuck `detaching/attaching`: continue below.

---

## Symptom 1: Volumes `faulted` or stuck `detaching`

**Most common cause (verified 2026-05-25):** instance-manager iSCSI target ID desync.

### Diagnose

```bash
# Check longhorn-manager logs for iSCSI cleanup errors
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=200 | grep tgtadm

# Look for: "tgtadm: can't find the logical unit: exit status 22"
# If present: instance-manager iSCSI state is stuck → use Recovery A

# Also check for orphan engine image references
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=200 | grep "engineimage.*not found"

# Look for: 'failed to get engine image ... engineimage.longhorn.io "ei-XXXX" not found'
# If present: orphan EngineImage CRD → see Recovery B
```

### Recovery A: Restart instance-manager (iSCSI desync)

```bash
# 1. Find the instance-manager pod
POD=$(kubectl get pods -n longhorn-system -l longhorn.io/component=instance-manager -o jsonpath='{.items[0].metadata.name}')
echo "Will restart: $POD"

# 2. Check pod age — if < 24h something else is wrong; investigate before restarting
kubectl get pod -n longhorn-system $POD -o jsonpath='{.status.startTime}'; echo

# 3. Delete the pod (graceful 60s — matches CronJob/rotation, drains iSCSI cleanly)
kubectl delete pod -n longhorn-system $POD --grace-period=60

# 4. Wait for new instance-manager to be Ready (typically 30-60s)
until kubectl get pods -n longhorn-system -l longhorn.io/component=instance-manager 2>/dev/null | grep -q "1/1.*Running"; do sleep 5; done

# 5. Watch volumes recover (typically 1-3 min for all stuck volumes)
watch -n 5 'kubectl get volumes.longhorn.io -n longhorn-system | grep -E "faulted|detaching|attaching" | wc -l'
```

**Expected side-effect:** ALL Longhorn-backed apps see a 5-30s IO pause while engines respawn with fresh iSCSI state. Apps using `attached/healthy` volumes recover automatically; previously-stuck volumes converge to `attached/healthy` over 1-3 min.

### Recovery B: Orphan EngineImage CRD

If logs show `engineimage.longhorn.io "ei-XXXX" not found`:

```bash
# 1. Identify which engines reference the orphan
ORPHAN_HASH="ei-XXXX"  # replace with the actual hash from logs
kubectl get engines.longhorn.io -n longhorn-system -o json | \
  jq -r ".items[] | select(.spec.image | contains(\"$ORPHAN_HASH\")) | .metadata.name"

# 2. Two paths:
#    Path 1 (preferred): upgrade engines to current image
#      via Longhorn UI → Volume → Upgrade Engine (per-volume; do during maintenance)
#    Path 2 (workaround): create placeholder EngineImage CRD pointing at the missing version
#      (only do this if upgrade isn't possible right now)
```

---

## Symptom 2: CSI sidecars restarting in lockstep

**Cause:** Upstream kube-apiserver/etcd disruption causing CSI leader-lease loss. Today (post-CM-1) with 2 replicas this should NOT cascade into volume detachment — the surviving replica holds the lease.

### Diagnose

```bash
# 1. Confirm restart pattern
kubectl get pods -n longhorn-system -o wide | grep csi-

# 2. Look at apiserver/etcd health
kubectl logs -n kube-system kube-apiserver-k8s-control-1 --tail=200 | grep -iE "warn|error|slow"

# 3. Check resource pressure on the node
kubectl top node
kubectl top pod -A --sort-by=memory | head -20

# 4. Verify CSI sidecars are still at 2 replicas (CM-1)
kubectl get deploy -n longhorn-system | grep csi-
# Each should show 2/2 READY
```

### Recovery

- If volumes remain attached/healthy: monitor, no immediate action needed
- If volumes start to detach: follow Symptom 1 recovery
- If kube-apiserver itself is unhealthy: investigate upstream (etcd, control-plane resource pressure)

---

## Symptom 3: `volsync-src-*` pod stuck in ContainerCreating for hours

**Cause:** Stale clone PVC from a previous failed VolSync run holding the source volume.

### Recovery

```bash
# 1. Find the stuck volsync-src pod (filter by app you care about)
APP=plex  # or sonarr, radarr, etc.
kubectl get pods -n media | grep "volsync-src-$APP" | head

# 2. Force-delete the stuck pod
kubectl delete pod -n media volsync-src-$APP-config-config-XXXX --grace-period=0 --force

# 3. Check if there's a stuck clone PVC blocking the volume
kubectl get pvc -A | grep volsync.*clone

# 4. If a clone PVC is stuck Terminating, clear its finalizer
kubectl patch pvc <name> -n <ns> -p '{"metadata":{"finalizers":null}}' --type=merge
```

---

## Post-recovery verification

```bash
# All volumes should be attached/healthy or detached/unknown — nothing else
kubectl get volumes.longhorn.io -n longhorn-system -o json | python3 -c "
import sys, json
d = json.load(sys.stdin); bad = []
for v in d['items']:
    s = v['status']
    if s.get('robustness') == 'faulted' or s.get('state') in ('attaching', 'detaching'):
        bad.append((v['metadata']['name'], s.get('state'), s.get('robustness')))
print(f'Problem volumes: {len(bad)}')
for n, st, rob in bad: print(f'  {n}: {st}/{rob}')
"

# All previously-affected apps Running
kubectl get pods -A | grep -E "ContainerCreating|0/[0-9]+\s+Init"
```

---

## Permanent fixes already in place (post-2026-05-25)

| Mitigation | Where | Effect |
|---|---|---|
| CSI sidecars at 2 replicas | `clusters/main/kubernetes/system/longhorn/app/helm-release.yaml` | Apiserver blip no longer cascades to mass CSI restart |
| Weekly instance-manager rotation | `instance-manager-rotation-cronjob.yaml` | Bounds iSCSI state accumulation to 7 days |
| PrometheusRules | `prometheus-rules.yaml` | Faulted/stuck/restart-storm alerts within 2-5 min |
| This runbook | `docs/runbooks/longhorn-recovery.md` | Diagnostic path no longer tribal |

---

## Reference incidents

| Date | Trigger | Resolution time | Doc |
|---|---|---|---|
| 2026-03-16 → 22 | Renovate auto-bumped Longhorn 1.11.0→1.11.1; Kyverno digest mutation broke upgrade detection | 6 days | `~/.claude/projects/-Users-zachbaum-dev-Talos-Cluster/memory/project_longhorn_1_11_recovery.md` |
| 2026-05-25 | etcd/apiserver disruption caused CSI lease-loss + iSCSI desync | ~2.5 hours (incident) + analysis | `.rootcause/a3_longhorn_recurring_csi_lease_cascade.md` (gitignored, summary below) |

## A3 key findings — 2026-05-25 (inline summary)

(Self-contained reference for cold context; the full A3 lives at `.rootcause/a3_longhorn_recurring_csi_lease_cascade.md`)

**What happened:** At 02:16Z all 4 CSI sidecars (attacher/provisioner/resizer/snapshotter) restarted within 4 seconds when kube-apiserver hit etcd timeouts. Their leader leases dropped simultaneously. The 44h-old instance-manager had accumulated stale iSCSI target IDs; on re-attach the engine startup failed with `tgtadm: can't find the logical unit: exit status 22`. 11 volumes ended up stuck in `detaching/faulted`. Apps (sonarr, radarr, plex, sabnzbd, lidarr, readarr, recyclarr, tunarr, tautulli, pihole, grafana, prometheus, chrome-cdp) were in ContainerCreating for ~2.5 hours until manual instance-manager restart.

**5 root causes identified:**
1. CSI sidecars single-replica — no peer to absorb apiserver hiccups
2. Instance-manager accumulates stale iSCSI target IDs over uptime
3. Orphan EngineImage CRD (`ei-ff1cedad`, v1.11.0) referenced by 58 stuck-deleting engines since March 2026 incident — generated continuous log spam
4. No Longhorn monitoring/alerting — cascade detected ~2 hours late via app failures
5. Recovery procedure was tribal knowledge

**Mitigations applied:** CSI 2 replicas, weekly instance-manager rotation CronJob, PrometheusRules with 5 alerts, this runbook, orphan engines cleaned (58 force-finalized).

**Open follow-up:** Upstream etcd fsync at 90ms (3.6× healthy) is the trigger source. Patched Talos `cluster.etcd.extraArgs` with `heartbeat-interval: 500`, `election-timeout: 5000` to tolerate slow disk; will take effect on next etcd process restart. Real fix is in the Proxmox VM disk layer (cache mode / underlying pool migration) — pending separate investigation.
