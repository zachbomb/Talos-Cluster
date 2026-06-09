# Etcd encryption + Audit policy — staged Talos patch

Staged on the live control-plane node via `talosctl patch mc --mode=staged`
on 2026-06-09. Takes effect at the next reboot of `k8s-control-1`
(192.168.10.89).

The same configuration exists in the SOPS-encrypted Talos patch
`clusters/main/talos/patches/encryption-config.secret.yaml` and
`clusters/main/talos/patches/audit-policy.yaml`, but a full
`talos apply` of the generated machine config would:

- reboot the node anyway (new `machine.files` aren't hot-reloadable)
- re-introduce the `scheduler.config` block that wedged the cluster
  on May 26 (memory note: it was removed via JSON patch as the live
  workaround)
- bump `install.image` v1.11.1 → v1.13.4

So the surgical strategic-merge patch below was applied directly
to the live node instead. The repo files remain authoritative for
what the EncryptionConfiguration *should* be — this is the runbook
for re-staging or re-applying it on a fresh node.

## Patch contents

```yaml
machine:
  files:
    - path: /etc/kubernetes/encryption-config.yaml
      permissions: 0o600
      op: create
      content: |
        apiVersion: apiserver.config.k8s.io/v1
        kind: EncryptionConfiguration
        resources:
          - resources:
              - secrets
            providers:
              - aesgcm:
                  keys:
                    - name: key1
                      secret: <THE-KEY-FROM-encryption-config.secret.yaml>
              - identity: {}
    - path: /etc/kubernetes/audit-policy.yaml
      permissions: 0o600
      op: create
      content: |
        apiVersion: audit.k8s.io/v1
        kind: Policy
        omitStages:
          - RequestReceived
        rules:
          - level: Metadata
            resources:
              - group: ""
                resources: ["secrets"]
          - level: None
cluster:
  apiServer:
    extraArgs:
      encryption-provider-config: /etc/kubernetes/encryption-config.yaml
      audit-policy-file: /etc/kubernetes/audit-policy.yaml
      audit-log-path: /var/log/audit/audit.log
      audit-log-maxsize: "100"
      audit-log-maxbackup: "5"
    extraVolumes:
      - hostPath: /etc/kubernetes/encryption-config.yaml
        mountPath: /etc/kubernetes/encryption-config.yaml
        readonly: true
      - hostPath: /etc/kubernetes/audit-policy.yaml
        mountPath: /etc/kubernetes/audit-policy.yaml
        readonly: true
      - hostPath: /var/log/audit
        mountPath: /var/log/audit
        readonly: false
```

## To re-stage

```bash
# Get the key from the SOPS-encrypted patch
SOPS_AGE_KEY_FILE=$PWD/age.agekey \
  sops --decrypt clusters/main/talos/patches/encryption-config.secret.yaml \
  | grep "secret:" | awk '{print $2}'

# Write the patch with the key inlined, then:
talosctl --talosconfig clusters/main/talos/generated/talosconfig --nodes 192.168.10.89 \
  patch mc -p @/tmp/encryption-audit-patch.yaml --mode=staged
```

## To check whether it's active (after reboot)

```bash
# 1. apiserver flags
kubectl get pod -n kube-system kube-apiserver-k8s-control-1 -o yaml \
  | grep -E "encryption-provider-config|audit-policy-file"

# 2. force cluster-secrets through the new provider
kubectl get secret -n flux-system cluster-secrets -o yaml | kubectl replace -f -

# 3. verify etcd ciphertext
talosctl --talosconfig clusters/main/talos/generated/talosconfig --nodes 192.168.10.89 \
  etcd snapshot /tmp/etcd.snap
go install go.etcd.io/bbolt/cmd/bbolt@latest
bbolt get /tmp/etcd.snap key /registry/secrets/flux-system/cluster-secrets | head -c 200
# Expect prefix: k8s:enc:aesgcm:v1:key1:
```

## Post-reboot fleet rewrite

After reboot + cluster-secrets verified encrypted, run the fleet rewrite
from plan Task 5.4 to bring all other Secrets through the new provider:

```bash
/tmp/fleet-rewrite-secrets.sh dry-run | tee /tmp/rewrite-dryrun.log
/tmp/fleet-rewrite-secrets.sh apply   | tee /tmp/rewrite-apply.log
```

Script body is in `.claude/plans/2026-06-09-flux-secrets-migration.md`
Task 5.4 (lines 1282–1421).
