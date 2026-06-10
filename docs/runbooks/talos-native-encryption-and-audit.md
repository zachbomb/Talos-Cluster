## What Talos provides natively

Discovered 2026-06-10 during the PR 5 etcd-encryption apply. After spending a full day designing, building, auditing, and applying a two-phase Talos patch for etcd encryption + audit logging, an empirical test revealed the cluster had been doing both since bootstrap.

**Encryption at rest (Secrets in etcd):**
- Cipher: `secretbox` (NaCl secretbox, NOT aesgcm)
- Key source: `cluster.secretboxEncryptionSecret` in `talsecret.yaml`, set during initial cluster bootstrap
- Effective encryption-provider-config path (in apiserver pod): `/system/secrets/kubernetes/kube-apiserver/encryptionconfig.yaml`
- Effective encryption-provider-config path (on host): bind-mounted from Talos state partition
- Provider order: `[secretbox, identity]` — writes use secretbox, identity is decrypt-fallback
- Empirical proof: 735+ `k8s:enc:secretbox:v1:key2:` prefixes in raw etcd snapshot, ZERO cleartext for probe Secret

**Audit logging:**
- Level: `Metadata` for ALL resources (not just Secrets)
- Policy path (in apiserver pod): `/system/config/kubernetes/kube-apiserver/auditpolicy.yaml`
- Output path (on host): `/var/log/audit/kube/kube-apiserver-*.log`
- Rotation: hourly file rolls
- Default apiserver flags Talos injects (cannot be overridden):
  - `--audit-log-maxage=30`
  - `--audit-log-maxbackup=10`
  - `--audit-log-maxsize=100`
  - `--audit-log-path=/var/log/audit/kube/kube-apiserver.log`
  - `--audit-policy-file=/system/config/kubernetes/kube-apiserver/auditpolicy.yaml`
  - `--encryption-provider-config=/system/secrets/kubernetes/kube-apiserver/encryptionconfig.yaml`

## What does NOT work

Trying to override the above via `cluster.apiServer.extraArgs` or `cluster.apiServer.extraVolumes` in a Talos config patch is **silently dropped**. The values pass schema validation, get accepted by `talosctl patch mc --mode=auto`, the apiserver static pod restarts — but the rendered pod spec contains Talos's own defaults for these specific flag keys, not yours. Your `extraVolumes` for the corresponding hostPath mounts don't appear in the pod either.

Gemini hallucinated a `cluster.apiServer.encryptionConfig` native field during the PR 5 audit. That specific field doesn't exist (verified by direct test: `error decoding document: unknown keys found`). The native mechanism IS real, it just lives in `talsecret.yaml`'s `secretboxEncryptionSecret`, not as a user-facing field in machine config.

## When this matters

**Customizing the audit policy:** the only path is editing `talsecret.yaml` (or whatever Talos uses to source the auditpolicy.yaml — needs investigation). Adding `apiServer.extraArgs.audit-policy-file: ...` to a config patch will not work.

**Rotating the encryption key:** rotate `secretboxEncryptionSecret` in `talsecret.yaml`, regenerate config, apply. Talos handles the rest.

**Wiring audit logs to Loki:** Alloy DaemonSet must hostPath-mount `/var/log/audit/kube/` and scrape `kube-apiserver-*.log` glob. The PR 5 attempt to redirect to `/var/log/k8s-audit/` was inert because Talos owns the log path. Fixed 2026-06-10 in PR #TBD.

## Why this was missed for so long

The original 2026-06-09 PR 5 plan assumed K8s Secrets were cleartext in etcd. That assumption was wrong — Talos has been encrypting since cluster bootstrap. The `bbolt`/etcd-snapshot verification step would have caught it immediately if it had been run BEFORE designing the migration. (Future lesson: empirically verify the "broken" state before designing the fix.)

The cluster-config ConfigMap → cluster-secrets Secret migration (PRs 2-4) WAS still important — that moved 45 credentials from a definitely-cleartext ConfigMap (which IS readable via `kubectl get configmap`) into Secrets that benefit from this native encryption. So PRs 2-4 are not wasted; PR 5 was.

Related: `genconfig-decrypts-in-place`, `forgetool-talos-apply-workflow`.
