# RESTORE CHECKLIST — Pibbs-Horde JBOD link loss, 2026-08-03 ~15:03 PDT

Load-shed applied to stop 78 media pods blocking in D-state on a dead NFS mount
(node load1 was 32.8 on 8 vCPU). Everything below MUST be undone after the pool
is back. Leaving any of it is the recurring "scale-to-0 drift" failure.

## What was changed (in this order)
1. `flux suspend helmrelease --all -n media`  -> 29 HelmReleases suspended
2. `kubectl scale deploy --all -n media --replicas=0`  -> 34 deployments
3. `kubectl scale statefulset --all -n media --replicas=0`  -> immich-redis, notifiarr
4. 28 media Kustomizations patched `suspend: true`
5. **`flux-entry` (ROOT kustomization) suspended** — this one blocks ALL cluster
   reconciliation, not just media. Highest priority to undo.

Original replica counts: `.incident-restore-2026-08-03.json` (36 workloads, all were >0).

## Restore order (do NOT just unsuspend everything at once)
1. Confirm pool healthy: status ONLINE, all 6 JBOD disks enumerated, `zpool clear` done.
2. Verify NFS actually serves reads from a test pod BEFORE scaling anything up.
3. Resume `flux-entry`:  `flux resume kustomization flux-entry`
4. Resume media kustomizations: `flux resume kustomization <28 names>`
5. Resume HelmReleases:  `flux resume helmrelease --all -n media`
6. Let Flux restore replicas from git (it owns them) — verify against the JSON file.
7. Bring back in SMALL BATCHES (~5-8), not all at once. Mass simultaneous
   reattach is what caused the Jul 4 and Jul 23 instance-manager death spirals.

## Verify nothing was left behind
    kubectl get deploy -A | grep 0/0
    kubectl get kustomization -A | grep -i true   # suspended column
    kubectl get helmrelease -A | grep -i true
