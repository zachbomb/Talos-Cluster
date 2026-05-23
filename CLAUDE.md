# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a **Talos Linux Kubernetes cluster** managed through **GitOps** using:
- **Talos Linux** - Immutable Kubernetes OS (version in `clusters/main/talos/talconfig.yaml`)
- **Flux CD** - GitOps continuous delivery
- **ClusterTool** - Cluster lifecycle management (binary at repo root, gitignored)

The repository contains declarative infrastructure-as-code for a production home lab cluster running ~70+ applications including a comprehensive media automation stack.

## Essential Commands

### Cluster Management (ClusterTool)

```bash
# ForgeTool (successor to ClusterTool, same config format)
./forgetool cluster genconfig   # Generate Talos machine configurations
./forgetool cluster init        # Initialize new cluster (first time setup)
./forgetool info                # Print forgetool binary info
./forgetool talos apply         # Apply Talos config to nodes
./forgetool talos upgrade       # Upgrade Talos + Kubernetes
./forgetool talos health        # Health check
./forgetool encrypt             # Encrypt all files per .sops.yaml
./forgetool decrypt             # Decrypt all files per .sops.yaml
./forgetool checkcrypt          # Verify encryption compliance

# Legacy ClusterTool (still works, same config)
./clustertool genconfig         # Generate Talos machine configurations
./clustertool init              # Initialize new cluster (first time setup)
./clustertool info              # Print clustertool binary info
```

### Secrets Management (SOPS)

```bash
sops clusters/main/clusterenv.yaml                    # Decrypt for editing (re-encrypts on save)
sops --decrypt clusters/main/clusterenv.yaml           # Decrypt to view only
sops --encrypt --in-place clusters/main/clusterenv.yaml  # Re-encrypt after editing
```

**Critical:** `.sops.yaml` defines encryption rules with `encrypted_regex` patterns. For `values.yaml` and `.secret.yaml` files, only fields matching the regex are encrypted (e.g., `password`, `secret`, `key`, `token`, `data`, `stringData`), not the entire file. For `clusterenv.yaml` and `talsecret.yaml`, the entire file is encrypted.

### Flux Operations

```bash
flux get all --status-selector ready=false             # View failed resources
flux reconcile kustomization <component> --with-source # Force reconcile
flux suspend kustomization <component>                 # Suspend deployment
flux resume kustomization <component>                  # Resume deployment
flux reconcile source git cluster                      # Fetch latest git changes
```

### Development Workflow

1. Edit manifests in appropriate layer
2. Commit and push to main branch
3. Flux auto-reconciles within 30 minutes (or force with `flux reconcile`)
4. Check status: `flux get all --status-selector ready=false`

For Talos config changes: edit `talconfig.yaml` or patches, run `./clustertool genconfig`, commit generated files.

## Architecture

### Deployment Layers (Initialization Order)

Manifests live in `clusters/main/kubernetes/` organized in 6 dependency layers:

1. **flux-system** - Flux CD bootstrap, secrets
2. **kube-system** - CNI (Cilium), metrics-server, device plugins
3. **system** - Storage (Longhorn, OpenEBS), monitoring (Prometheus), cert-manager, MetalLB
4. **core** - ClusterIssuers, Kyverno policies, Traefik ingress, CrowdSec IPS, DNS services
5. **networking** - NGINX ingress controllers (legacy, being decommissioned), Homepage dashboard, external services
6. **apps** - User applications (media stack in `apps/media/`, plus `apps/home/`, `apps/ollama/`, etc.)

### GitOps Flow

```
Git Push → Flux GitRepository (30m poll) → flux-entry.yaml
  → Loads repositories/* (Helm/Git/OCI repos)
  → SOPS decryption + variable substitution from clusterenv.yaml
  → Layer-by-layer deployment
  → HelmReleases/Kustomizations applied
```

All manifests use `${VARIABLE}` syntax. Variables come from `cluster-config` ConfigMap (generated from SOPS-decrypted `clusterenv.yaml`). Common: `${BASE_DOMAIN}`, `${VIP}`, `${S3URL}`, `${S3KEY}`, per-app `${APP_IP}` and `${APP_API}`.

### Standard Component Structure

```
<component>/
├── ks.yaml                  # Flux Kustomization (points to app/)
└── app/
    ├── kustomization.yaml   # Lists all resources
    ├── helm-release.yaml    # HelmRelease with chart + values
    └── [optional files]     # namespace.yaml, ingress.yaml, runtime.yaml
```

**ks.yaml pattern** (note: no `./` prefix on path, no `wait: true` unless needed):
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <app-name>
  namespace: flux-system
spec:
  interval: 10m
  path: clusters/main/kubernetes/<layer>/<app-name>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: cluster
```

Each layer has a `kustomization.yaml` that references components via `- ./<component>/ks.yaml`.

### Key System Components

- **Longhorn** - Distributed block storage, **OpenEBS** - Local PV provisioner
- **VolSync** - Backup/restore to S3 (MinIO) via Restic
- **Cilium** - CNI with eBPF, **MetalLB** - LoadBalancer (192.168.10.193-254)
- **Traefik** (192.168.10.196) - Primary ingress controller for all apps
- **CrowdSec** - Intrusion prevention, Traefik bouncer middleware blocks malicious IPs
- **NGINX Internal** (.193) / **External** (.194) - Legacy, pending decommission (only Flux webhook on external)
- **cert-manager** - TLS via Let's Encrypt, **Kyverno** - Policy engine

## Important Patterns

Detailed patterns auto-load via scoped rules in `.claude/rules/`:
- **`truecharts.md`** — HelmRelease patterns, VolSync config, PVC sizing, TrueCharts/VolSync gotchas (loads for `helm-release.yaml`)
- **`traefik-crowdsec.md`** — Traefik v39+ and CrowdSec bouncer details (loads for traefik/crowdsec files)
- **`networking.md`** — Cilium, MetalLB, Longhorn/cert-manager CRDs (loads for kube-system/system/core files)

### Recovery Procedures

**Failed Helm release (never succeeded):**
```bash
helm uninstall <name> -n <namespace> --no-hooks
flux suspend kustomization <name>
flux resume kustomization <name>
```

**Stuck PVC in Terminating state:**
```bash
kubectl patch pvc <name> -n <ns> -p '{"metadata":{"finalizers":null}}' --type=merge
# Then uninstall/reinstall the Helm release - flux reconcile alone won't recreate deleted PVCs
```

**Helm adopt pre-existing resources:**
Add label `app.kubernetes.io/managed-by: Helm` and annotations `meta.helm.sh/release-name: <name>`, `meta.helm.sh/release-namespace: <ns>`.

## Operational Scripts

Located in `scripts/` (gitignored). Run from repo root:

```bash
./scripts/cluster-status          # Overall cluster dashboard (nodes, pods, Flux, Helm, storage, certs)
./scripts/media-status            # Media stack health (Sonarr/Radarr/SABnzbd APIs, NFS, Plex)
./scripts/backup-audit [-v]       # VolSync backup staleness detection
./scripts/volsync-check [--fix]   # VolSync health: stuck pods, PVCs, snapshots
./scripts/longhorn-cleanup [--fix] # Orphaned volumes, stuck clones, stale snapshots
./scripts/resource-report [--ns X] # CPU/memory actual vs requested, OOM proximity
./scripts/helm-debug [release]     # Failed HelmRelease diagnosis with suggested fixes
./scripts/queue-check [--clean]    # Sonarr/Radarr queue health, auto-remove failed items
./scripts/storage-check           # Longhorn volume health, PVC capacity, NFS mounts
./scripts/flux-diff               # Flux failed/suspended resources
./scripts/ip-audit                # MetalLB IP assignments, conflicts, missing annotations
./scripts/app-logs <app-name>     # Quick app log access by name
```

## Critical Files

- **clusters/main/clusterenv.yaml** - All cluster variables (SOPS encrypted, single source of truth)
- **clusters/main/talos/talconfig.yaml** - Talos cluster definition (versions, nodes, patches)
- **clusters/main/kubernetes/flux-entry.yaml** - Root Flux Kustomization
- **.sops.yaml** - Encryption rules (DO NOT MODIFY without careful consideration)
- **age.agekey** - Encryption key (NEVER COMMIT, gitignored)

## Network Configuration

All IPs defined in `clusterenv.yaml`:
- VIP: 192.168.10.167 (Control plane), Gateway: 192.168.10.1
- MetalLB Range: 192.168.10.193-254
- Traefik: .196 (primary ingress), Blocky DNS: .195
- NGINX Internal: .193, External: .194 (legacy, pending decommission)
- Pod CIDR: 172.16.0.0/16, Service CIDR: 172.17.0.0/16

DNS resolution: Blocky uses k8sgateway which reads Kubernetes Ingress status IPs. Traefik's `publishedservice` automatically updates Ingress status to .196, so DNS resolves all `*.${BASE_DOMAIN}` hostnames to Traefik.

## Repository Conventions

1. **ks.yaml pattern** - Every component has `ks.yaml` pointing to `app/` subdirectory
2. **Variable substitution** - Use `${VARNAME}` for all environment-specific values
3. **SOPS for secrets** - Never commit plaintext sensitive data
4. **Renovate comments** - Track versions with `# renovate: datasource=... depName=...`
5. **3 retries** - Standard for HelmRelease install/upgrade remediation
6. **Namespace per app** - Each app in its own namespace
7. **LoadBalancer IP pre-assignment** - All IPs in clusterenv.yaml, always set `metallb.io/loadBalancerIPs` annotation
8. **Homepage integration** - Include homepage annotations for dashboard visibility
