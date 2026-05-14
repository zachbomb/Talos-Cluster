# SonarQube self-hosting

Component shipping the SonarSource SonarQube Community Build chart backed
by a CNPG Postgres 17 cluster. Internal-only ingress at
`https://sonarqube.sf.${BASE_DOMAIN}`.

Plan: [`docs/plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md`](../../../../docs/plans/2026-05-05-001-feat-cluster-network-roadmap-plan.md) (U10-U14).

## Resources shipped here

| File | Purpose |
|---|---|
| `namespace.yaml` | `sonarqube` namespace |
| `cnpg-cluster.yaml` | Postgres 17 CNPG cluster (`sonarqube-db`) — 10Gi, daily backup to `s3://cnpg-sonarqube/` at 03:30 UTC |
| `cnpg-barman.yaml` | S3 credentials secret + ScheduledBackup |
| `helm-release.yaml` | SonarSource chart with embedded Postgres disabled, CNPG wired via `jdbcOverwrite` |
| `sonarqube-secret.secret.yaml` | SOPS Secret with admin password + monitoring passcode (placeholder values; populate via `sops`) |
| `ingress.yaml` | Internal-only Ingress (Traefik + `internal-secure-chain` middleware + cert-manager) |

## Deploy order (handled by Flux Kustomization `sonarqube` in `ks.yaml`)

1. Namespace + secrets created first.
2. CNPG cluster + ScheduledBackup applied — `cloudnative-pg` operator (system layer dep) provisions Postgres pods.
3. HelmRelease applies once CNPG cluster reports `Ready`.
4. Ingress applies in parallel; cert-manager picks it up to issue the TLS cert.

## Pre-deploy user actions

### 1. Populate the SOPS secret

```bash
# Generate a strong admin password and a 16+ char monitoring passcode:
ADMIN_PASS=$(openssl rand -base64 24)
MON_PASS=$(openssl rand -base64 18)

# Edit the SOPS-encrypted secret in place:
sops clusters/main/kubernetes/system/sonarqube/app/sonarqube-secret.secret.yaml
# Replace REPLACE_ME_SONARQUBE_ADMIN_PASSWORD with $ADMIN_PASS
# Replace REPLACE_ME_MIN_16_CHARS_MONITORING_PASSCODE with $MON_PASS
# Save (sops re-encrypts on save).

# Stash the passwords in your password manager — you'll need ADMIN_PASS at
# first login (step 3 below).
```

### 2. Add DNS records for `sonarqube.sf.${BASE_DOMAIN}`

The hostname must resolve to Traefik (192.168.10.196) on LAN/VPN, and to
*nothing useful* externally (split-horizon — keeps the SonarQube UI off the
public internet).

- **Pi-hole .3** — admin UI → Local DNS Records → add A record:
  `sonarqube.sf.<your base domain>` → `192.168.10.196`.
- **Blocky .195** — edit `clusters/main/kubernetes/core/blocky/app/helm-release.yaml`,
  add to `customDNS.mapping.sonarqube.sf.${BASE_DOMAIN}: 192.168.10.196`.
  Commit + let Flux reconcile.
- **Cloudflare authoritative** — add A record (unproxied / DNS-only)
  `sonarqube.sf.<base>` → `192.168.10.196`. Unproxied means Cloudflare
  serves the answer but doesn't tunnel traffic — external clients get
  192.168.10.196 which they can't route to.

### 3. Verify and bootstrap (U13)

```bash
# After Flux reconciles, check the pod is up:
kubectl rollout status deploy -n sonarqube sonarqube-sonarqube --timeout=600s

# Verify the API is healthy:
kubectl exec -n sonarqube deploy/sonarqube-sonarqube -- \
  curl -s http://localhost:9000/api/system/status
# Expect: {"status":"UP"}
```

Then in a LAN browser:

1. Open https://sonarqube.sf.<base>
2. Log in with `admin / admin` (the chart's hardcoded default).
3. Change password to the value you stashed from step 1's `$ADMIN_PASS`.
4. Settings → Security → Users → Tokens → Generate Token (name `claude-cli`).
5. Stash the token value (won't be shown again).

### 4. Wire SonarQube CLI integration (U13 second half)

```bash
# Login the CLI to the new server:
sonar auth login -s https://sonarqube.sf.<base>
# Browser flow opens → paste token from step 3.5.

# Verify:
sonar auth status

# Project setup (run from the Talos-Cluster repo root):
sonar integrate claude --non-interactive
# This wires the SonarQube MCP server into ~/.claude/settings.json
# (or per-project .claude/settings.json) for autonomous Sonar queries.
```

### 5. First scan: `scripts/` baseline (U14)

```bash
# Create the project properties file (gitignored — scripts/ as a whole is gitignored):
cat > scripts/sonar-project.properties <<'EOF'
sonar.projectKey=talos-cluster-scripts
sonar.projectName=Talos Cluster Scripts
sonar.sources=.
sonar.exclusions=**/*.tar,**/*.tar.gz,**/.git/**
sonar.host.url=https://sonarqube.sf.<base>
EOF

# Run the scan:
cd scripts/ && sonar scan
cd ..

# View the result:
# https://sonarqube.sf.<base> → Projects → talos-cluster-scripts
# Triage initial findings via /sonarqube:sonar-list-issues MCP tool.
```

## Operational notes

### Resource sizing

SonarQube needs **~3 GB heap headroom** on Java init. Currently set:
`requests cpu=500m mem=2Gi`, `limits cpu=2 mem=4Gi`. If pods OOMKill on
startup, bump memory to 6 Gi.

### Talos sysctl elevations

The chart's `initSysctl` and `initFs` initContainers need privileged caps
that Talos restricts. Both are disabled here (`initSysctl.enabled: false`,
`initFs.enabled: false`). Talos's default Elasticsearch-friendly sysctls
(`vm.max_map_count=262144`) cover the requirement. If SonarQube logs
`max virtual memory areas vm.max_map_count [N] is too low`, apply a Talos
node patch to raise it.

### Backup verification

```bash
# Manual on-demand backup:
kubectl create -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: sonarqube-db-manual-$(date +%s)
  namespace: sonarqube
spec:
  cluster: { name: sonarqube-db }
  method: barmanObjectStore
EOF

# Verify backup landed in MinIO:
kubectl exec -n minio deploy/minio -- mc ls myminio/cnpg-sonarqube/
```

### Recovery

```bash
# Postgres-only recovery — restore from S3 backup to a new cluster:
# See https://cloudnative-pg.io/documentation/current/recovery/
# Then update HelmRelease's jdbcUrl to point at the recovery cluster.

# SonarQube data PVC recovery — Longhorn snapshots provide point-in-time
# recovery via the Longhorn UI. The 20Gi PVC holds Elasticsearch indices
# (regeneratable from Postgres) and configuration.
```

### Open questions / deferrals

- **`internal-secure-chain` middleware** — currently uses the basic
  `secure-chain` (CrowdSec only). Once Phase A's Cilium BGP migration
  preserves real client IPs end-to-end, swap to `internal-secure-chain`
  (bouncer + IP-allowlist) for a stricter LAN/VPN-only gate. (Deferred
  per plan rev-2 carry-forward.)
- **App-by-app scan integration** — only `scripts/` baseline is in scope
  here. Triparr-bot, Ollama, etc. are per-app follow-up work.
