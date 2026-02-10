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
./clustertool genconfig   # Generate Talos machine configurations
./clustertool init        # Initialize new cluster (first time setup)
./clustertool info        # Print clustertool binary info
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
4. **core** - ClusterIssuers, Kyverno policies, Traefik ingress, DNS services
5. **networking** - NGINX ingress controllers, Homepage dashboard, external services
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
- **NGINX Internal** (192.168.10.193) / **External** (192.168.10.194) - Ingress controllers
- **Traefik** (192.168.10.196) - Alternative ingress
- **cert-manager** - TLS via Let's Encrypt, **Kyverno** - Policy engine

## Important Patterns

### TrueCharts HelmRelease Values

Most apps use TrueCharts charts. Key patterns in `spec.values`:

**Service with MetalLB** - always set both `loadBalancerIP` and the annotation:
```yaml
service:
  main:
    type: LoadBalancer
    loadBalancerIP: ${APP_IP}
    annotations:
      metallb.io/loadBalancerIPs: ${APP_IP}
```

**Ingress with NGINX internal + cert-manager:**
```yaml
ingress:
  main:
    enabled: true
    hosts:
      - host: app.${BASE_DOMAIN}
        paths:
          - path: /
            pathType: Prefix
    integrations:
      nginx:
        enabled: true
        ingressClassName: internal
      traefik:
        enabled: false
      certManager:
        enabled: true
        certificateIssuer: wethecommon-prod-cert
      homepage:
        enabled: true
        name: App Name
        group: Group Name
```

**S3 credentials** (required for VolSync):
```yaml
credentials:
  s3:
    type: s3
    url: ${S3URL}
    bucket: "${S3PREFIX}-<app>"
    accessKey: ${S3ID}
    secretKey: ${S3KEY}
    encrKey: ${S3KEY}
```

### VolSync Backup Configuration

VolSync is configured via TrueCharts' `persistence.*.volsync` list. **Critical: `volsync` must be at the TOP LEVEL of the persistence entry, as a sibling of the volume definition, NOT nested under a sub-key.**

```yaml
persistence:
  config:
    enabled: true
    mountPath: /config
    volsync:                          # CORRECT: top-level sibling
      - name: config
        type: restic
        credentials: s3
        dest:
          enabled: true              # Creates ReplicationDestination (restore on fresh install)
        src:
          enabled: true              # Creates ReplicationSource (scheduled backups)
          trigger:
            schedule: "40 0 * * *"   # Optional: custom cron (default: midnight)
```

**Wrong** (silently ignored - no secrets, no replication resources created):
```yaml
persistence:
  config:
    main:
      enabled: true
    volsync:        # WRONG: nested under config but not a sibling of the volume
```

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

## Known Gotchas

### VolSync lchown Failures

VolSync mover drops ALL capabilities including CAP_CHOWN. Apps running as root that back up root-owned files will fail `lchown` during restore. **Fix:** set `dest.enabled: false`, let the app install with a fresh PVC, then optionally re-enable dest later. Affected apps include calibre, calibre-web, tdarr, tunarr, ollama, deluge. Apps with non-root users (e.g., bazarr with UID 1000) work fine.

**PVC immutability:** You cannot remove `dataSourceRef` from an existing PVC. If VolSync dest created a PVC with a dataSourceRef, you must delete the PVC entirely and recreate it.

### TrueCharts Issues

- **Container registry**: TrueCharts migrated from `tccr.io` (DEAD, returns NXDOMAIN) to `oci.trueforge.org`. Override images to official sources (e.g., `docker.io/library/traefik`) if needed.
- **Traefik middleware chicken-and-egg**: The common library does `lookup()` for `chain-basic` middleware during template rendering, but the middleware is created by the same chart. Fix: temporarily disable ingress, install chart, then re-enable ingress.
- **`readOnlyRootFilesystem: true` default**: Some apps need writable root FS. Override: `securityContext.container.readOnlyRootFilesystem: false`.

### MetalLB IP Conflicts

When many apps install simultaneously, MetalLB auto-assigns IPs from the pool to services missing the `metallb.io/loadBalancerIPs` annotation, potentially stealing IPs reserved for infrastructure. Fix: delete the conflicting services to free the IPs.

### Longhorn/cert-manager CRDs

Both have CRDs in `templates/crds.yaml` (not `crds/` directory). Flux `crds: CreateReplace` only works for CRDs in `crds/`. Missing CRDs must be applied manually via `helm template`. For cert-manager, ensure `installCRDs: true` in values.

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
- NGINX Internal: .193, External: .194, Blocky DNS: .195, Traefik: .196
- Pod CIDR: 172.16.0.0/16, Service CIDR: 172.17.0.0/16

## Repository Conventions

1. **ks.yaml pattern** - Every component has `ks.yaml` pointing to `app/` subdirectory
2. **Variable substitution** - Use `${VARNAME}` for all environment-specific values
3. **SOPS for secrets** - Never commit plaintext sensitive data
4. **Renovate comments** - Track versions with `# renovate: datasource=... depName=...`
5. **3 retries** - Standard for HelmRelease install/upgrade remediation
6. **Namespace per app** - Each app in its own namespace
7. **LoadBalancer IP pre-assignment** - All IPs in clusterenv.yaml, always set `metallb.io/loadBalancerIPs` annotation
8. **Homepage integration** - Include homepage annotations for dashboard visibility
