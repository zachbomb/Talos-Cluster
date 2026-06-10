# Etcd encryption + Audit policy — two-phase Talos patch

**Status (2026-06-10):** revised after multi-model audit (`/tmp/audit-summary.md`). The procedure now uses two separate Talos patches applied in sequence, with explicit pre-flight assertions and pre-created hostPath directories. The previous single-patch attempt boot-wedged the cluster; the audit additionally found a kubelet hostPath auto-create race that the path move alone didn't fix.

This runbook does NOT carry a "tested in production" warranty. The whole point of the two-phase split is to limit the blast radius of either phase failing.

## Why two phases

The previous single-patch attempt combined three concerns in one reboot:
1. Writing the EncryptionConfiguration + audit-policy YAML files to disk
2. Adding apiserver `--encryption-provider-config` + audit flags
3. Adding apiserver `extraVolumes` hostPath mounts

If kubelet starts the apiserver static pod BEFORE Talos's `MachineFiles` controller writes the files, CRI auto-creates the missing hostPath sources as **empty directories**. The apiserver then reads `/etc/kubernetes/encryption-config.yaml` as a directory, fails to parse it, crashloops — and we have **no API for recovery**.

Splitting into two phases breaks this race:

| Phase | What | Reboot? | Recovery |
|---|---|---|---|
| 1 | machine.files only (write the .yaml files + a /var/log/k8s-audit/.keep sentinel) | YES (Talos requires it for machine.files) | If reboot wedges, apid stays up, JSON-patch revert via `scripts/talos-encryption-rollback.sh dry-run`. |
| 2 | apiserver extraArgs + extraVolumes only | NO (static-pod restart only) | If apiserver crashloops, JSON-patch revert hot via the same rollback script. |

Verify phase 1's files exist on the host before applying phase 2. That's the entire safety budget.

## Host vs in-pod path mapping

| Component | Host path (Talos writes here) | In-pod path (apiserver sees) |
|---|---|---|
| EncryptionConfiguration | `/var/etc/kubernetes/encryption-config.yaml` | `/etc/kubernetes/encryption-config.yaml` |
| Audit policy | `/var/etc/kubernetes/audit-policy.yaml` | `/etc/kubernetes/audit-policy.yaml` |
| Audit log output | `/var/log/k8s-audit/audit.log` | `/var/log/audit/audit.log` |
| .keep sentinel | `/var/log/k8s-audit/.keep` | (host only — ensures dir exists at apiserver start) |

Alloy DaemonSet hostPath: `/var/log/k8s-audit/` (matches apiserver-side audit log output).

## Repo files (authoritative)

- `clusters/main/talos/patches/encryption-audit-files.secret.yaml` — phase 1 (SOPS-encrypted, contains AES-GCM key)
- `clusters/main/talos/patches/encryption-audit-apiserver.yaml` — phase 2 (no secrets)
- `clusters/main/kubernetes/system/alloy/app/helm-release.yaml` — Alloy hostPath + Loki source
- `scripts/fleet-rewrite-secrets.sh` — post-reboot fleet-wide Secret rewrite
- `scripts/talos-encryption-rollback.sh` — index-computed JSON Patch revert
- `.sops.yaml` — rule for `talos/patches/*.secret.yaml`

## Pre-flight (DO BEFORE STAGING ANYTHING)

```bash
# 0a. Cluster healthy? (etcd, apiserver, no failing kustomizations)
kubectl get nodes
flux get ks -A | awk 'NR==1 || $6 != "True"'

# 0b. Take a fresh etcd snapshot — insurance.
talosctl --nodes 192.168.10.89 etcd snapshot \
  /tmp/etcd-pre-encryption-$(date -u +%Y%m%dT%H%M%S).snap

# 0c. Regenerate Talos config (will leave SOPS files decrypted in-tree;
# RESTORE them before doing anything else — feedback_genconfig_decrypts_in_place).
HEADLAMP_IP=192.168.10.206 ./clustertool-new genconfig
for f in $(git status --short | awk '{print $2}'); do
  case "$f" in
    *.secret.yaml|clusters/main/clusterenv.yaml|clusters/main/talos/generated/talsecret.yaml)
      git restore "$f"
      ;;
  esac
done

# 0d. PRE-REBOOT ASSERTION: the generated config MUST contain the
# encryption-provider-config flag AND the machine.files entry.
# If either is missing, STOP — talconfig wiring is broken.
grep -q 'encryption-provider-config: /etc/kubernetes/encryption-config.yaml' \
  clusters/main/talos/generated/main-k8s-control-1.yaml \
  || { echo "ABORT: encryption-provider-config not in generated config"; exit 1; }
grep -q 'path: /var/etc/kubernetes/encryption-config.yaml' \
  clusters/main/talos/generated/main-k8s-control-1.yaml \
  || { echo "ABORT: encryption-config.yaml machine.files entry missing"; exit 1; }
grep -q 'path: /var/log/k8s-audit/.keep' \
  clusters/main/talos/generated/main-k8s-control-1.yaml \
  || { echo "ABORT: audit log dir sentinel missing"; exit 1; }
echo "✓ generated config contains all expected entries"
```

## Phase 1 — write files only

Build a patch containing ONLY the phase-1 entries from the generated config:

```bash
# Extract just the phase-1 machine.files entries from the generated config.
# Easier to apply the encryption-audit-files.secret.yaml patch directly:
SOPS_AGE_KEY_FILE=$PWD/age.agekey \
  sops --decrypt clusters/main/talos/patches/encryption-audit-files.secret.yaml \
  > /tmp/phase1.yaml

# CRITICAL GATE: dry-run with auto mode. Will report "Applied configuration
# with a reboot" — that's expected (machine.files are never hot-reloadable).
# What matters: the diff should ONLY add the 3 machine.files entries,
# nothing else. Visually inspect.
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  patch mc -p @/tmp/phase1.yaml --mode=auto --dry-run | tee /tmp/phase1-dryrun.log

# If the diff looks right, stage it for the next reboot you initiate:
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  patch mc -p @/tmp/phase1.yaml --mode=staged

# Trigger the reboot during a chosen quiet window:
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig reboot

# Wait for apiserver to return (single-CP outage ~3-5 min):
until kubectl get --raw=/livez >/dev/null 2>&1; do
  printf "  %s — down\n" "$(date -u +%H:%M:%SZ)"
  sleep 20
done
echo "  ✓ apiserver back"

# VERIFY PHASE 1 WORKED: files must exist on host before phase 2.
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  read /var/etc/kubernetes/encryption-config.yaml | head -10
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  read /var/etc/kubernetes/audit-policy.yaml | head -10
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  read /var/log/k8s-audit/.keep
# If any of the above 404, PHASE 1 FAILED — stop here. Do NOT proceed
# to phase 2. The rollback is: scripts/talos-encryption-rollback.sh apply
```

## Phase 2 — wire the apiserver

```bash
# Phase 2 patch is plain YAML (no secrets):
PHASE2=clusters/main/talos/patches/encryption-audit-apiserver.yaml

# CRITICAL GATE 2: dry-run should report "no reboot required" or
# "Applied configuration without a reboot". Static-pod restart only.
# If it says "with a reboot", STOP — something is wrong.
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  patch mc -p "@$PHASE2" --mode=auto --dry-run | tee /tmp/phase2-dryrun.log

# Apply hot (apiserver static-pod restart, ~10-30s outage):
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  patch mc -p "@$PHASE2" --mode=auto

# Wait for apiserver to be back through the restart:
sleep 30
until kubectl get --raw=/livez >/dev/null 2>&1; do sleep 5; done
echo "  ✓ apiserver back"
```

## Post-apply verification (each step is mandatory)

```bash
# 1. apiserver actually has the encryption-provider-config flag mounted
kubectl exec -n kube-system kube-apiserver-k8s-control-1 -- \
  cat /etc/kubernetes/encryption-config.yaml | head -5
# Expect: aesgcm provider with key1.

# 2. NEW Secret encryption: create a probe Secret, fetch from etcd
kubectl create secret generic encryption-probe \
  --from-literal=value=this-should-be-encrypted

talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  etcd snapshot /tmp/etcd-post-encryption.snap

# Requires bbolt: go install go.etcd.io/bbolt/cmd/bbolt@latest
bbolt get /tmp/etcd-post-encryption.snap key /registry/secrets/default/encryption-probe \
  | head -c 24
# Expect prefix: k8s:enc:aesgcm:v1:key1:
# If you see "this-should-be-encrypted" → ENCRYPTION IS OFF, rollback.

kubectl delete secret encryption-probe   # cleanup

# 3. Fleet rewrite: forces every existing Secret through the new provider.
# Uses kubectl annotate --overwrite (NOT get|replace — see audit-summary.md
# correctness finding #4 for why).
scripts/fleet-rewrite-secrets.sh dry-run | tee /tmp/rewrite-dryrun.log
scripts/fleet-rewrite-secrets.sh apply   | tee /tmp/rewrite-apply.log
# Script samples 5 random Secrets at the end and verifies they're now
# ciphertext via bbolt. If any sample fails, encryption is partial.

# 4. Audit log is actually flowing
# 4a. Trigger an audit-worthy event:
kubectl get secret -n flux-system cluster-secrets >/dev/null

# 4b. Audit log on host actually grew (NOT just Alloy startup log):
talosctl --nodes 192.168.10.89 \
  --talosconfig clusters/main/talos/generated/talosconfig \
  read /var/log/k8s-audit/audit.log | tail -5
# Expect: JSON lines with verb, user, objectRef.resource:"secrets"

# 4c. Audit events reaching Loki (the actual goal — NOT an Alloy startup
# log grep, which would be a false positive per audit finding #5):
# In Grafana, query: {audit_resource="secrets"}
# Or via logcli:
logcli query '{audit_resource="secrets"}' --limit 5
# Expect: at least 1 entry within the last minute.

# 5. No regressions: all Flux kustomizations reconciling, all CNPG
# clusters healthy.
flux get all --status-selector ready=false
kubectl get cluster.postgresql.cnpg.io -A
```

## Rollback (use ONLY the computed-index script, NEVER hard-coded indices)

```bash
# Dry-run shows the computed JSON Patch BEFORE applying:
scripts/talos-encryption-rollback.sh dry-run

# Apply if it looks right:
scripts/talos-encryption-rollback.sh apply
# This will prompt for confirmation. The patch may trigger a reboot
# if machine.files are being removed.
```

The script reads the live machineconfig, finds entries by VALUE (path / hostPath / extraArgs key), builds the JSON Patch in reverse index order so removals don't shift remaining positions, and applies it. **Never copy hardcoded indices from any older docs** — they will silently amputate the wrong entries if config has changed.

## Audit findings addressed

This runbook revision (2026-06-10) closes all 7 fixes from `/tmp/audit-summary.md`:

1. ✅ Two-phase commit (Gemini's recommendation) — phase 1 files, phase 2 apiserver
2. ✅ `/var/log/k8s-audit/.keep` sentinel pre-creates the audit log dir
3. ✅ `kubectl annotate --overwrite` (in `fleet-rewrite-secrets.sh`) replaces `get|replace`
4. ✅ Real Loki query (and `talosctl read` on host) replaces fake Alloy log grep
5. ✅ Computed rollback indices in `scripts/talos-encryption-rollback.sh`
6. ✅ Pre-reboot assertion in step 0d
7. ✅ Fleet rewrite script committed (was previously TODO)
