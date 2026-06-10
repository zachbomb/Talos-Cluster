## Gotcha 1: CNPG operator blocked by NetworkPolicy

**Symptom:** CNPG `Cluster.status` shows `Instance Status Extraction Error: HTTP communication issue`, and any helm release that waits on the CNPG cluster (immich, paperless-ngx, anything with an embedded `cnpg:` block) fails its reconcile with:

```
Helm upgrade failed for release media/immich:
  timeout waiting for: [Cluster/media/immich-cnpg-main status: 'InProgress']
```

**Root cause:** The CloudNativePG operator (in the `cloudnative-pg` namespace) scrapes each PostgreSQL instance pod's status endpoint at `https://<pod-ip>:8000/pg/status` to populate `Cluster.status.instances`. Operator log:

```
Cannot extract Pod status ... error: Get "https://172.16.0.211:8000/pg/status": dial tcp 172.16.0.211:8000: i/o timeout
```

The March 2026 NetworkPolicy rollout (8 app namespaces, ingress-only default-deny) added rules for Traefik/Prometheus/Kuma/intra-namespace but NOT for the CNPG operator. Namespaces WITHOUT netpols (tools, sonarqube, goodmem) had healthy CNPG clusters; namespaces WITH netpols (media, triparr-bot, ollama) all showed the communication error.

**Fix:** Add a `cloudnative-pg` namespaceSelector ingress rule to each affected netpol:

```yaml
# CNPG operator → instance pod :8000/pg/status
- from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: cloudnative-pg
```

Files: `clusters/main/kubernetes/apps/network-policies/app/{media,triparr-bot,ollama}-netpol.yaml`. Shipped in PR #4278 (2026-06-10).

**Detection:** to find all CNPG clusters that are silently degraded:
```bash
kubectl get cluster.postgresql.cnpg.io -A | grep -i "communication issue\|Extraction Error"
```

**Proactive check:** any future namespace that (a) has an ingress-only NetworkPolicy AND (b) hosts a CNPG cluster needs this rule. Grep all netpols for `cloudnative-pg` and cross-reference against `kubectl get cluster.postgresql.cnpg.io -A`.

## Gotcha 2: StatefulSet volumeClaimTemplates is immutable

**Symptom:** A helm release that creates a StatefulSet (Loki single-binary, anything with embedded PVC templates) fails helm upgrade forever after you bump a PVC `size:` value:

```
Helm upgrade failed for release loki/loki:
  server-side apply failed for object loki/loki apps/v1, Kind=StatefulSet:
  StatefulSet.apps "loki" is invalid: spec: Forbidden: updates to statefulset spec
  for fields other than 'replicas', 'ordinals', 'template', 'updateStrategy',
  'revisionHistoryLimit', ... are forbidden
```

The forbidden field is `spec.volumeClaimTemplates` — Kubernetes does not allow in-place edits to a StatefulSet's PVC templates.

**Fix:** Orphan-delete the StatefulSet (keeps the pod + PVC running), then re-reconcile so helm recreates the StatefulSet object with the new template. The new StatefulSet adopts the existing pod and PVC (which Longhorn already expanded):

```bash
# 1. Orphan-delete — pod and PVC survive
kubectl delete statefulset -n loki loki --cascade=orphan

# 2. Re-reconcile so helm recreates the StatefulSet
flux suspend hr loki -n loki && flux resume hr loki -n loki
# or: flux reconcile hr loki -n loki
```

The PVC itself can be expanded online separately (Longhorn `allowVolumeExpansion: true`) via `kubectl patch pvc ... -p '{"spec":{"resources":{"requests":{"storage":"60Gi"}}}}'` — that's NOT blocked, only the StatefulSet template edit is. So the full sequence for "grow a StatefulSet's PVC" is: patch the live PVC → bump the helm values → orphan-delete the STS → reconcile.

## Bonus: Prometheus stuck replaying WAL after disk-full

If Prometheus CrashLoopBackOffs with `no space left on device` and then, after you expand the PVC, sits in `1/2 Running` replaying WAL for hours:

- The WAL lives at `/prometheus/prometheus-db/wal/` (NOT `/prometheus/wal/`)
- `walCompression: true` makes it compact but replay is still slow (~18s/segment when cold)
- A 50GB+ WAL = multi-hour replay
- The long-term compacted blocks live in `/prometheus/prometheus-db/01XXXXX...` dirs — those are SAFE, nuking the WAL only loses the most recent (already-lost-anyway) samples

**Fast recovery:** scale Prometheus to 0 via the CR (`kubectl patch prometheus -n kube-prometheus-stack kube-prometheus-stack --type=merge -p '{"spec":{"replicas":0}}'`), mount the PVC in an alpine debug pod, `rm -rf /prometheus/prometheus-db/{wal,chunks_head,chunk_snapshot.*,lock,queries.active}`, scale back to 1. Ready in ~30s instead of 3 hours.

Related: `longhorn-recovery` (if it exists), `post-recovery-crashloop-sweep`.
