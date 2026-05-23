---
paths:
- clusters/**/helm-release.yaml
---

# TrueCharts HelmRelease Patterns

## Service with MetalLB
Always set BOTH `loadBalancerIP` and the annotation — MetalLB requires both:
```yaml
service:
  main:
    type: LoadBalancer
    loadBalancerIP: ${APP_IP}
    annotations:
      metallb.io/loadBalancerIPs: ${APP_IP}
```

## Ingress with Traefik + CrowdSec + cert-manager
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
        enabled: false
        ingressClassName: internal
      traefik:
        enabled: true
        entrypoints:
          - websecure
        middlewares:
          - name: secure-chain
            namespace: traefik
      certManager:
        enabled: true
        certificateIssuer: wethecommon-prod-cert
      homepage:
        enabled: true
        name: App Name
        group: Group Name
```
`secure-chain` = CrowdSec bouncer → local-whitelist. Use on ALL apps.

## S3 Credentials (required for VolSync)
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

## VolSync Backup Configuration
`volsync` must be at TOP LEVEL of the persistence entry — sibling of the volume definition, NOT nested under a sub-key (silently ignored if wrong):
```yaml
persistence:
  config:
    enabled: true
    size: 2Gi
    mountPath: /config
    volsync:                          # CORRECT: top-level sibling
      - name: config
        type: restic
        credentials: s3
        dest:
          enabled: true
        src:
          enabled: true
          trigger:
            schedule: "40 0 * * *"
```

## PVC Sizing
**ALWAYS specify explicit `size:`** — TrueCharts defaults to 100Gi if omitted, which wastes Longhorn storage and creates oversized VolSync clone PVCs. NFS mounts and emptyDir do not need `size:`.

## VolSync: lchown Failures
VolSync mover drops ALL capabilities including CAP_CHOWN. Apps running as root fail `lchown` during restore. Fix: `dest.enabled: false`. Affected: calibre, calibre-web, tdarr, tunarr, ollama, deluge, tinymediamanager, mylar.

**PVC immutability:** Cannot remove `dataSourceRef` from existing PVC — must delete PVC entirely and recreate it.

## TrueCharts Gotchas
- **Container registry**: `tccr.io` is DEAD (NXDOMAIN). Override images to official sources (`docker.io/...`) or `oci.trueforge.org`.
- **Traefik middleware chicken-and-egg**: `lookup()` for `chain-basic` fails during install. Fix: disable ingress, install chart, re-enable ingress.
- **`readOnlyRootFilesystem: true` default**: Override with `securityContext.container.readOnlyRootFilesystem: false` when app needs writable root FS.
- **CrowdSec `secretTemplate: null`**: Chart v0.22.1 renders null in agent Certificate. Fix: set `tls.certManager.secretTemplate.annotations` to a **non-empty** value — empty `{}` is falsy in Go templates and doesn't fix it.
- **Label length limit**: TrueCharts concatenates ALL persistence entry names into one label (≤63 bytes). Keep names short.
- **Secondary services and MetalLB**: Secondary services (e.g. `deluge-torrent`) may not get `loadBalancerIP` annotation. Verify with `kubectl get svc`. When sharing an IP: add `metallb.io/allow-shared-ip: "<app>"` annotation on ALL services sharing that IP.
