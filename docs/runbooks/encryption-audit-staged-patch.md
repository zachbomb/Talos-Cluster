# Etcd encryption + Audit policy — staged Talos patch

**Status:** repo files updated 2026-06-09 to use `/var/etc/kubernetes/` host paths after the original `/etc/kubernetes/` paths boot-wedged the cluster. Patch has NOT yet been applied/staged to the live node — that's a separate operation pending a quiet maintenance window.

## Background — what changed

The 2026-06-09 first attempt used host paths under `/etc/kubernetes/` (matching what the K8s docs typically show as the apiserver-side encryption-config location). That triggered a boot wedge:

```
error writing kubelet PKI: open /etc/kubernetes/bootstrap-kubeconfig: read-only file system
```

Talos mounts `/etc/kubernetes/` read-only during early boot (before the `machine.files` controller runs) so the kubelet `KubeletServiceController` controller can lay down its bootstrap kubeconfig safely. Declaring our own `machine.files` entries under `/etc/kubernetes/` confused the mount ordering — the directory came up RO before kubelet bootstrap could write to it.

**The fix in this PR:** move host-side paths to `/var/etc/kubernetes/` (same area Talos already uses for `nfsmount.conf`). Keep the in-pod `mountPath` at `/etc/kubernetes/` so the apiserver still finds its files where it expects them.

## Host vs in-pod path mapping

| Component | Host path | In-pod path (apiserver) |
|---|---|---|
| EncryptionConfiguration | `/var/etc/kubernetes/encryption-config.yaml` | `/etc/kubernetes/encryption-config.yaml` |
| Audit policy | `/var/etc/kubernetes/audit-policy.yaml` | `/etc/kubernetes/audit-policy.yaml` |
| Audit log output | `/var/log/k8s-audit/audit.log` | `/var/log/audit/audit.log` |

Alloy DaemonSet mounts host `/var/log/k8s-audit/` → in-pod `/var/log/audit/` so its `loki.source.file "audit"` config can keep targeting `/var/log/audit/audit.log` unchanged.

## Repo files (authoritative)

- `clusters/main/talos/patches/encryption-config.secret.yaml` (SOPS-encrypted)
- `clusters/main/talos/patches/audit-policy.yaml`
- `clusters/main/kubernetes/system/alloy/app/helm-release.yaml`
- `.sops.yaml` (rule for talos patches/*.secret.yaml)

## Apply procedure (DEFERRED — requires hands-on maintenance window)

The apply path is the same as the prior attempt, just with the new host paths:

```bash
# 1. Generate Talos config (needs HEADLAMP_IP set in clusterenv per b9741b40b)
./clustertool-new genconfig

# 2. Restore any decrypt-in-place artifacts (feedback_genconfig_decrypts_in_place)
git status --short  # check for unintended .secret.yaml diffs
for f in $(git status --short | awk '{print $2}'); do
  case "$f" in
    *.secret.yaml|clusters/main/clusterenv.yaml|clusters/main/talos/generated/talsecret.yaml)
      git restore "$f" ;;
  esac
done

# 3. CRITICAL: dry-run BEFORE staging. Must report "no reboot required" — if it
# still says "Applied configuration with a reboot", DO NOT proceed. Investigate
# whether the new host paths trigger different filesystem semantics.
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 \
  apply-config --file clusters/main/talos/generated/main-k8s-control-1.yaml --dry-run

# 4a. If dry-run is clean, stage for next maintenance reboot:
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 \
  patch mc -p @clusters/main/talos/generated/main-k8s-control-1.yaml --mode=staged

# 4b. Then reboot during a planned window:
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 etcd snapshot /tmp/etcd-pre-reboot-$(date -u +%Y%m%dT%H%M%S).snap
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 reboot
```

## Post-reboot verification

```bash
# 1. apiserver back?
until kubectl get --raw=/livez >/dev/null 2>&1; do sleep 5; done

# 2. encryption-config file present on host AND in apiserver pod?
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 \
  read /var/etc/kubernetes/encryption-config.yaml | head -5
kubectl exec -n kube-system kube-apiserver-k8s-control-1 -- ls -la /etc/kubernetes/encryption-config.yaml

# 3. Force-replace cluster-secrets so it's encrypted via the new provider
kubectl get secret -n flux-system cluster-secrets -o yaml | kubectl replace -f -

# 4. Verify etcd-side encryption (bbolt)
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 etcd snapshot /tmp/etcd.snap
go install go.etcd.io/bbolt/cmd/bbolt@latest  # if not installed
bbolt get /tmp/etcd.snap key /registry/secrets/flux-system/cluster-secrets | head -c 200
# Expect prefix: k8s:enc:aesgcm:v1:key1:

# 5. Audit log flowing into Loki via Alloy
kubectl logs -n loki -l app.kubernetes.io/name=alloy --tail=20 | grep audit
# In Grafana: {audit_resource="secrets"}

# 6. Fleet-wide Secret rewrite (resolves Decision A2). Script from plan Task 5.4.
/tmp/fleet-rewrite-secrets.sh dry-run | tee /tmp/rewrite-dryrun.log
/tmp/fleet-rewrite-secrets.sh apply   | tee /tmp/rewrite-apply.log
```

## Rollback (symmetric)

If something goes wrong, the recovery from 2026-06-09 demonstrated the working pattern:

```bash
# Remove the apiserver bits via JSON patch (apid is reachable even when apiserver isn't)
cat > /tmp/revert-patch.json <<'EOF'
[
  {"op": "remove", "path": "/cluster/apiServer/extraArgs/encryption-provider-config"},
  {"op": "remove", "path": "/cluster/apiServer/extraArgs/audit-policy-file"},
  {"op": "remove", "path": "/cluster/apiServer/extraArgs/audit-log-path"},
  {"op": "remove", "path": "/cluster/apiServer/extraArgs/audit-log-maxsize"},
  {"op": "remove", "path": "/cluster/apiServer/extraArgs/audit-log-maxbackup"},
  {"op": "remove", "path": "/cluster/apiServer/extraVolumes/2"},
  {"op": "remove", "path": "/cluster/apiServer/extraVolumes/1"},
  {"op": "remove", "path": "/cluster/apiServer/extraVolumes/0"},
  {"op": "remove", "path": "/machine/files/3"},
  {"op": "remove", "path": "/machine/files/2"}
]
EOF
talosctl --talosconfig clusters/main/talos/generated/talosconfig \
  --endpoints 192.168.10.89 --nodes 192.168.10.89 \
  patch mc -p @/tmp/revert-patch.json --mode=auto
# Talos will reboot once into a clean config.
```

NOTE: the array indices in `/machine/files/N` and `/cluster/apiServer/extraVolumes/N` depend on the current config state. Use `talosctl get machineconfigs -o yaml` to confirm indices before running the revert.
