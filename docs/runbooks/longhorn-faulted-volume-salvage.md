# Longhorn: salvage single-replica volumes faulted by a node reboot

**When to read this:** After a node reboot/upgrade, many apps stuck in
`ContainerCreating` with `FailedAttachVolume` / "volume is not ready for
workloads", and `kubectl get volumes.longhorn.io -n longhorn-system` shows a pile
of `detached / faulted` volumes that are **not** self-recovering.

## Why it happens (root cause)

This is a **single-node + single-replica + `disable-revision-counter=true`**
interaction, not data loss:

- Every volume here has one replica (`defaultReplicaCount: 1`). A node reboot
  kills the instance-manager ungracefully, so every volume's lone replica is
  marked failed (`spec.failedAt` set).
- Longhorn's **revision counter** is what lets it confirm a replica's data is
  consistent after an unclean shutdown. It was disabled (Longhorn's default since
  1.2). Without it, when all replicas of a volume are faulted, auto-salvage can't
  verify the replica is clean, so it refuses it — the manager logs
  **`"All replicas are failed, set engine salvageRequested to true"`** followed by
  **`"Bringing up 0 replicas for auto-salvage"`**, and the volume stays faulted.
- Longhorn issues [#2309](https://github.com/longhorn/longhorn/issues/2309) and
  [#7714](https://github.com/longhorn/longhorn/issues/7714) describe this exactly.

**On a single-node cluster the lone replica IS the data** — there is no other
replica to prefer — so clearing `failedAt` to force salvage is always the correct
call, not a gamble.

## The fix — clear `failedAt` on the faulted replicas

Safe, fast (~1 min for ~50 volumes), reversible (a genuinely-bad replica just
re-faults). Run against the cluster:

```bash
# Preview: how many are faulted
kubectl get volumes.longhorn.io -n longhorn-system --no-headers \
  | awk '$4=="faulted"{print $1}' | wc -l

# Salvage: clear failedAt on every faulted volume's replica(s)
for V in $(kubectl get volumes.longhorn.io -n longhorn-system --no-headers \
             | awk '$4=="faulted"{print $1}'); do
  for R in $(kubectl get replicas.longhorn.io -n longhorn-system \
               -l longhornvolume="$V" -o name 2>/dev/null); do
    kubectl patch "$R" -n longhorn-system --type=merge \
      -p '{"spec":{"failedAt":""}}'
  done
done
```

Longhorn brings the replica back up within seconds; the volume goes
`faulted → attaching → attached/healthy` and its pods finish `ContainerCreating`.

### Verify

```bash
# faulted should drain toward 0; healthy should climb
kubectl get volumes.longhorn.io -n longhorn-system --no-headers \
  | awk '{print $3"/"$4}' | sort | uniq -c | sort -rn

# instance-manager must stay Running with 0 restarts through the attach wave
kubectl get pod -n longhorn-system -l longhorn.io/component=instance-manager
```

A couple of transient `faulted` (media volsync sources) that flap are harmless.

## Permanent fix (already applied)

`disableRevisionCounter: false` is set in the Longhorn helm-release
`defaultSettings` (commit on 2026-07-03). This makes **new** volumes auto-salvage
correctly after a reboot — no manual step. **It does not retroactively apply to
existing volumes** (global settings only take effect at volume creation), so
pre-existing volumes still need this salvage on a reboot until they're rebuilt.
Run the loop above after any node reboot/upgrade until the fleet has turned over.

## Do NOT

- Don't `zpool`/delete or recreate faulted **data** volumes (DBs, app config) —
  the data is intact; salvage it. Recreate is only for regenerable cache PVCs.
- Don't blanket-clear `failedAt` on a **multi-replica** cluster without checking
  which replica has the latest data — there the choice matters. Here it doesn't
  (one replica).

Related: [[longhorn-recovery]], memory `longhorn-1-12-im-liveness-outage-2026-06`.
