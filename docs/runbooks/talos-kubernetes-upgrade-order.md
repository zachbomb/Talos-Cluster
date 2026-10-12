# Talos and Kubernetes upgrade order

Talos minor first, then Kubernetes minor. Never the other way round.

Each Talos release pins the newest Kubernetes it can run as
`DefaultKubernetesVersion` in `pkg/machinery/constants/constants.go` (for example
Talos v1.13.10 -> 1.36.3, v1.14.2 -> 1.37.1). A Kubernetes minor above that
ceiling makes `talosctl upgrade-k8s` roll the control plane onto a kubelet and
apiserver the node's Talos cannot run.

## The two pins

Both files must carry the same values; CI fails if they drift apart.

| File | Keys | Consumed by |
|------|------|-------------|
| `clusters/main/kubernetes/flux-system/flux/upgradesettings.yaml` | `TALOS_VERSION`, `KUBERNETES_VERSION` | Flux substitution into the system-upgrade plans |
| `clusters/main/talos/talconfig.yaml` | `talosVersion`, `kubernetesVersion` | `forgetool cluster genconfig` / talhelper |

Renovate bumps both files; its Talos/kubelet rule attaches `do-not-merge`, so a
human merges them.

## The CI guard

`.github/workflows/talos-k8s-compat.yaml` runs
`.github/scripts/check-talos-k8s-compat.sh` on every PR touching either pin
file. It fails when:

- the two files disagree,
- `KUBERNETES_VERSION`'s minor is newer than the pinned Talos tag's
  `DefaultKubernetesVersion` minor (the message names the Talos minor needed),
- the upstream `constants.go` cannot be fetched or parsed (fails closed).

On failure it adds the `do-not-merge` label, which `automerge.yaml`'s
`!do-not-merge` rule hard-blocks. The label is not auto-removed: clear it by
hand after fixing the PR.

Run it locally before pushing a bump:

```bash
.github/scripts/check-talos-k8s-compat.sh            # this checkout
.github/scripts/check-talos-k8s-compat.sh /path/to/repo
```

## Why one PR bumping both self-orders

The two system-upgrade plans in
`clusters/main/kubernetes/core/system-upgrade-controller-plans/app/` select nodes
by the `feature.node.kubernetes.io/system-os_release.VERSION_ID` label:

- `talos` plan: `VERSION_ID NotIn [${TALOS_VERSION}]` -> runs on nodes still on
  the old Talos, upgrades them to `TALOS_VERSION` (reboot).
- `kubernetes` plan: `VERSION_ID In [${TALOS_VERSION}]` -> matches a node only
  after it reports the new Talos version, then runs
  `talosctl upgrade-k8s --to=${KUBERNETES_VERSION}`.

So a single PR that raises both `TALOS_VERSION` and `KUBERNETES_VERSION` is
safe: the kubernetes plan has no eligible node until the talos plan has finished
on it. Bumping only Kubernetes past the ceiling is the failure mode the CI guard
exists for, because the kubernetes plan would match immediately.

Still check the Talos release notes for the target minor before merging; the
guard only proves the Kubernetes minor is runnable, not that the Talos upgrade
itself is safe (see `docs/runbooks/talos-native-encryption-and-audit.md` and the
forgetool apply notes for past surprises).

## Watching the plans run

After Flux reconciles the merged PR:

```bash
# Both plans and their current target versions
kubectl -n system-upgrade get plans -o wide

# Talos plan job first (node reboots onto the new Talos), kubernetes plan job after
kubectl -n system-upgrade get jobs -w
kubectl -n system-upgrade logs -l upgrade.cattle.io/plan=talos --tail=50
kubectl -n system-upgrade logs -l upgrade.cattle.io/plan=kubernetes --tail=50

# Node reports the new Talos VERSION_ID, then the new kubelet version
kubectl get nodes -o custom-columns='NODE:.metadata.name,TALOS:.metadata.labels.feature\.node\.kubernetes\.io/system-os_release\.VERSION_ID,KUBELET:.status.nodeInfo.kubeletVersion'
talosctl version --nodes <node-ip>
```

Expected sequence: the `talos` job completes and the node comes back with the
new `VERSION_ID`; only then does a `kubernetes` job appear. If the kubernetes
job never appears, confirm the node's `VERSION_ID` label equals `TALOS_VERSION`
exactly (node-feature-discovery must have re-labelled after the reboot).
