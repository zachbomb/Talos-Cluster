# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a **Talos Linux Kubernetes cluster** managed through **GitOps** using:
- **Talos Linux v1.11.5** - Immutable Kubernetes OS
- **Kubernetes v1.34.2** - Container orchestration
- **Flux CD v2.7.5** - GitOps continuous delivery
- **ClusterTool v2.0.6** - Cluster lifecycle management

The repository contains declarative infrastructure-as-code for a production home lab cluster running ~70+ applications including a comprehensive media automation stack.

## Essential Commands

### Cluster Management (ClusterTool)

```bash
# Generate Talos machine configurations
./clustertool genconfig

# Initialize new cluster (first time setup)
./clustertool init

# Print information about the clustertool binary
./clustertool info
```

**Note:** ClusterTool is a universal binary (arm64/x86_64) located at repository root. The binary is gitignored and must be downloaded separately.

### Secrets Management (SOPS)

```bash
# Encrypt a file
sops --encrypt --age age1xuryc2afg7fh6tg2d85mydr05rh93xf8dhrcq4xata7ec33t8uvs6kl3yw file.yaml > file.secret.yaml

# Decrypt for editing
sops clusters/main/clusterenv.yaml

# Encrypt clusterenv.yaml after editing
sops --encrypt --in-place clusters/main/clusterenv.yaml

# Decrypt to view
sops --decrypt clusters/main/clusterenv.yaml
```

**Critical:** The `.sops.yaml` configuration defines encryption rules. Files matching these patterns are automatically encrypted:
- `clusters/**/kubernetes/**/*.secret.yaml`
- `clusters/**/kubernetes/**/values.yaml` (only sensitive fields)
- `clusterenv.yaml`
- `talsecret.yaml`

### Flux Operations

```bash
# Check Flux system status
flux check

# Reconcile all Kustomizations immediately
flux reconcile kustomization flux-system --with-source

# Reconcile specific component
flux reconcile kustomization <component> --with-source

# Suspend/resume deployments
flux suspend kustomization <component>
flux resume kustomization <component>

# View Flux logs
flux logs --follow --all-namespaces
```

### Kubernetes Operations

```bash
# Get all Kustomizations
kubectl get kustomizations -A

# Get all HelmReleases
kubectl get helmreleases -A

# View failed resources
flux get all --status-selector ready=false

# Force reconcile a HelmRelease
flux reconcile helmrelease <name> -n <namespace>
```

### Development Workflow

When making changes to Kubernetes manifests:

1. **Edit manifests** in appropriate layer (`system/`, `core/`, `networking/`, `apps/`)
2. **Commit and push** to main branch
3. **Flux auto-reconciles** within 30 minutes (or force with `flux reconcile`)
4. **Check status** with `kubectl get kustomizations -A` or `flux get all`

When modifying Talos configuration:

1. **Edit** `clusters/main/talos/talconfig.yaml` or patches in `clusters/main/talos/patches/`
2. **Generate configs:** `./clustertool genconfig`
3. **Commit generated files** in `clusters/main/talos/generated/`
4. **Push to Git** - Changes will be applied by system-upgrade-controller

## Architecture

### Repository Structure

```
.
├── clustertool              # Binary for cluster management
├── clusters/main/           # Main cluster configuration
│   ├── clusterenv.yaml      # Encrypted environment variables (SOPS)
│   ├── talos/               # Talos OS configurations
│   │   ├── talconfig.yaml   # Cluster definition
│   │   ├── patches/         # Configuration patches
│   │   │   ├── all.yaml     # Applied to all nodes
│   │   │   ├── controlplane.yaml
│   │   │   ├── worker.yaml
│   │   │   └── gpu.yaml     # NVIDIA/Intel GPU support
│   │   └── generated/       # Auto-generated configs
│   └── kubernetes/          # Kubernetes manifests (6 layers)
│       ├── flux-entry.yaml  # Root Flux Kustomization
│       ├── flux-system/     # Layer 1: Flux CD bootstrap
│       ├── kube-system/     # Layer 2: K8s infrastructure
│       ├── system/          # Layer 3: Cluster services
│       ├── core/            # Layer 4: Configuration
│       ├── networking/      # Layer 5: Network services
│       └── apps/            # Layer 6: Applications
├── repositories/            # Helm/Git/OCI repository definitions
└── .sops.yaml               # SOPS encryption configuration
```

### Deployment Layers (Initialization Order)

The cluster manifests are organized in 6 layers representing dependencies:

1. **flux-system** - Flux CD itself, bootstrap configs, secrets
2. **kube-system** - CNI (Cilium), metrics-server, device plugins
3. **system** - Storage (Longhorn, OpenEBS), monitoring (Prometheus), cert-manager, MetalLB
4. **core** - ClusterIssuers, Kyverno policies, Traefik ingress, DNS services
5. **networking** - NGINX ingress controllers, Homepage dashboard, external service integrations
6. **apps** - User applications including extensive media automation stack

Each layer depends on the previous layer being ready before deployment.

### GitOps Flow

```
Git Push → Flux GitRepository (30m poll) → flux-entry.yaml
  → Loads repositories/* (Helm/Git/OCI repos)
  → Processes clusters/main/kubernetes/*
  → SOPS decryption + variable substitution
  → Layer-by-layer deployment (flux-system → kube-system → system → core → networking → apps)
  → HelmReleases/Kustomizations applied
```

**Variable Substitution:** All manifests can use `${VARIABLE}` syntax. Variables are sourced from the `cluster-config` ConfigMap (generated from `clusterenv.yaml`).

### Standard Component Structure

Every Kubernetes component follows this pattern:

```
<component>/
├── ks.yaml                  # Flux Kustomization (points to app/)
└── app/
    ├── kustomization.yaml   # Lists all resources
    ├── helm-release.yaml    # HelmRelease with chart + values
    ├── namespace.yaml       # Namespace definition
    └── [optional files]     # ingress.yaml, runtime.yaml, etc.
```

**Layer kustomization.yaml pattern:**
Each layer (system/, core/, networking/, apps/) has a `kustomization.yaml` that references all components via their `ks.yaml` files:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./component1/ks.yaml
  - ./component2/ks.yaml
```

### Key System Components

**Storage:**
- **Longhorn** - Distributed block storage with replication
- **OpenEBS** - Local PV provisioner
- **VolSync** - Backup/restore to S3 (MinIO)

**Networking:**
- **Cilium** - CNI with eBPF dataplane
- **MetalLB** - LoadBalancer for bare metal (IP range: 192.168.10.193-254)
- **NGINX Internal** - LAN-only ingress (192.168.10.193)
- **NGINX External** - WAN ingress (192.168.10.194)
- **Traefik** - Alternative ingress controller (192.168.10.196)

**Security & Policies:**
- **Kyverno** - Policy engine (enforce image digests, pod mutations)
- **cert-manager** - TLS certificate automation (Let's Encrypt)
- **CrowdSec** - Security monitoring

**Monitoring:**
- **kube-prometheus-stack** - Prometheus, Grafana, Alertmanager
- **metrics-server** - Resource metrics

**Automation:**
- **system-upgrade-controller** - Automated Talos/K8s upgrades
- **kubernetes-reflector** - Secret/ConfigMap replication across namespaces

## Important Patterns

### SOPS Encryption

Always encrypt sensitive values:
- API tokens, passwords, certificates
- Entire `clusterenv.yaml` file
- Files ending in `.secret.yaml`
- Specific fields in `values.yaml` (per regex in `.sops.yaml`)

The encryption key is stored in:
- **Local:** `age.agekey` (gitignored)
- **Cluster:** `sops-age` Secret in `flux-system` namespace

### HelmRelease Pattern

All applications use this standardized HelmRelease structure:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <app>
  namespace: <namespace>
spec:
  interval: 15m
  timeout: 20m
  maxHistory: 3
  install:
    createNamespace: true
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  chart:
    spec:
      chart: <chart-name>
      version: <version>
      sourceRef:
        kind: HelmRepository
        name: <repo>
        namespace: flux-system
```

### Variable Substitution from clusterenv.yaml

The `clusterenv.yaml` file is the single source of truth for cluster configuration. After SOPS decryption, variables are available as `${VARNAME}`:

**Common variables:**
- `${VIP}` - Virtual IP for control plane
- `${METALLB_RANGE}` - LoadBalancer IP pool
- `${DOMAIN_0}`, `${BASE_DOMAIN}` - Domain configuration
- `${PLEX_IP}`, `${RADARR_API}` - Per-service IPs and API keys
- `${S3URL}`, `${S3KEY}` - Backup storage credentials

### GPU Support

The cluster supports both NVIDIA and Intel GPUs:

**NVIDIA:**
- Talos extensions: `nonfree-kmod-nvidia-lts`, `nvidia-container-toolkit-lts`
- RuntimeClass: `nvidia` (use in pod spec for GPU access)
- Device plugin deployed via HelmRelease

**Intel:**
- Kernel module: `i915`
- intel-device-plugins operator
- Supports iGPU transcoding for Plex/media apps

### Dependency Management

Use `dependsOn` in Kustomizations/HelmReleases to enforce ordering:

```yaml
spec:
  dependsOn:
    - name: parent-component
      namespace: flux-system
```

Example: `intel-device-gpu` depends on `intel-device-plugins`

### Renovate Integration

Version tracking is automated via Renovate bot. Look for comments like:

```yaml
# renovate: datasource=docker depName=ghcr.io/siderolabs/installer
talosVersion: v1.11.5

# renovate: datasource=helm depName=longhorn
version: 1.7.2
```

Renovate creates PRs for version updates automatically.

## Common Workflows

### Adding a New Application

1. Choose the appropriate layer (`system/`, `core/`, `networking/`, `apps/`)
2. Create directory structure:
   ```bash
   mkdir -p clusters/main/kubernetes/<layer>/<app-name>/app
   ```
3. Create `ks.yaml`:
   ```yaml
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: <app-name>
     namespace: flux-system
   spec:
     interval: 10m
     path: ./clusters/main/kubernetes/<layer>/<app-name>/app
     prune: true
     sourceRef:
       kind: GitRepository
       name: cluster
     wait: true
   ```
4. Create `app/kustomization.yaml` listing all resources
5. Create `app/helm-release.yaml` with chart configuration
6. Add IP assignment to `clusterenv.yaml` (if needs LoadBalancer)
7. Reference in parent layer's `kustomization.yaml`
8. Commit and push

### Modifying Existing Application

1. Find the component in `clusters/main/kubernetes/<layer>/<app>/`
2. Edit `app/helm-release.yaml` values section
3. Commit and push (Flux reconciles automatically)
4. Force immediate reconcile: `flux reconcile kustomization <app> --with-source`

### Troubleshooting Failed Deployments

```bash
# Find failed resources
flux get all --status-selector ready=false

# Check specific HelmRelease
kubectl describe helmrelease <name> -n <namespace>

# View Helm release history
helm history <name> -n <namespace>

# Check pod logs
kubectl logs -n <namespace> <pod-name>

# Suspend failing component
flux suspend kustomization <name>

# After fixing, resume
flux resume kustomization <name>
```

### Updating Talos/Kubernetes Version

1. Edit `clusters/main/talos/talconfig.yaml`:
   ```yaml
   talosVersion: v1.X.X  # Update version
   kubernetesVersion: v1.X.X  # Update version
   ```
2. Update `clusters/main/kubernetes/flux-system/flux/upgradesettings.yaml`
3. Generate new configs: `./clustertool genconfig`
4. Commit generated files
5. The `system-upgrade-controller` will orchestrate the upgrade automatically

### Managing Secrets

**Adding a new secret:**
1. Create YAML file with secret data
2. Encrypt: `sops --encrypt --age <key> file.yaml > file.secret.yaml`
3. Commit the `.secret.yaml` file
4. Reference in HelmRelease or Kustomization

**Rotating secrets:**
1. Edit encrypted file: `sops clusters/main/clusterenv.yaml`
2. Update value
3. Save (automatically re-encrypted)
4. Commit and push
5. Force reconcile affected components

### Backup and Restore

The cluster uses **VolSync** with Restic backend (S3/MinIO):

**Configure backup for an app:**
```yaml
persistence:
  config:
    enabled: true
    storageClass: longhorn
    size: 10Gi
    annotations:
      volumesync.home.arpa/enabled: "true"
      volumesync.home.arpa/repository: "s3:${S3URL}/${S3PREFIX}-<app>"
```

**Restore from backup:**
1. Create ReplicationDestination resource
2. Point new PVC to restored data
3. Update app to use new PVC

## Critical Files

- **clusters/main/clusterenv.yaml** - All cluster configuration variables (SOPS encrypted, single source of truth)
- **clusters/main/talos/talconfig.yaml** - Talos cluster definition
- **clusters/main/kubernetes/flux-entry.yaml** - Root Flux Kustomization that bootstraps all layers
- **clusters/main/kubernetes/flux-system/flux/clustersettings.secret.yaml** - Generated ConfigMap from clusterenv.yaml
- **repositories/flux-entry.yaml** - Loads all Helm/Git/OCI repository definitions
- **.sops.yaml** - Encryption rules (DO NOT MODIFY without careful consideration)
- **age.agekey** - Encryption key (NEVER COMMIT, gitignored)

## Network Configuration

**Fixed IPs from clusterenv.yaml:**
- VIP: 192.168.10.167 (Control plane)
- MASTER1IP: 192.168.10.89
- Gateway: 192.168.10.1
- MetalLB Range: 192.168.10.193-254
- NGINX Internal: 192.168.10.193
- NGINX External: 192.168.10.194
- Blocky DNS: 192.168.10.195
- Traefik: 192.168.10.196

**Network CIDRs:**
- Pod Network: 172.16.0.0/16
- Service Network: 172.17.0.0/16

## Special Considerations

### Avoid Over-Engineering

This cluster is production but follows simple patterns:
- Don't add complexity for hypothetical scenarios
- Use existing patterns (TrueCharts, bjw-s charts) rather than creating custom solutions
- Keep configurations declarative and straightforward

### Testing Changes

Before applying to production:
1. Use `flux diff kustomization <name>` to preview changes
2. Consider temporarily setting `spec.suspend: true` on Kustomization
3. Test in isolated namespace when possible
4. Monitor `kubectl get events -n <namespace>` during rollout

### Helm Chart Sources

Primary chart repositories:
- **truecharts** - Most applications use TrueCharts (common library)
- **bjw-s** - Alternative common library for simpler apps
- **prometheus-community**, **jetstack**, **metallb** - System components

Always reference existing HelmRepository resources in `repositories/helm/`.

## Performance Optimizations

The cluster includes several performance tunings:

**Flux CD:**
- Concurrent reconciliations: 12
- API QPS: 500, Burst: 1000
- In-memory kustomize builds

**Network:**
- BBR congestion control
- TCP window scaling for 10Gb/s
- NFS optimizations (nfsvers=4.2, nconnect=16)

**Storage:**
- Longhorn replication for critical data
- OpenEBS for high-performance local storage
- Spegel for P2P image distribution

## Repository Conventions

1. **Always use ks.yaml pattern** - Flux Kustomizations point to `app/` subdirectory
2. **Variable substitution everywhere** - Use `${VARNAME}` for all environment-specific values
3. **SOPS for all secrets** - Never commit plaintext sensitive data
4. **Renovate comments** - Track all version dependencies
5. **3 retries standard** - HelmRelease install/upgrade retries
6. **Namespace per app** - Isolate applications in dedicated namespaces
7. **LoadBalancer IP pre-assignment** - All IPs defined in clusterenv.yaml
8. **Dependency declarations** - Use `dependsOn` for strict ordering
9. **Homepage integration** - Include homepage annotations for dashboard
10. **Documentation in comments** - Inline YAML comments explain non-obvious config
