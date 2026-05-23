---
paths:
- clusters/main/kubernetes/core/traefik/**
- clusters/main/kubernetes/core/crowdsec/**
---

# Traefik (Upstream Chart v39+)
- **Chart source**: Upstream `traefik/traefik` (v39+). IngressClass `traefik` is default.
- **Container ports**: 8000 (web), 8443 (websecure), 8080 (dashboard/API) — NOT 80/443/9000. Use container ports in NetworkPolicies.
- **Plugin storage**: Use `experimental.plugins` chart values to auto-create `/plugins-storage` volume. `additionalArguments` alone does not create the volume.
- **Middlewares**: Standalone CRD manifests in `clusters/main/kubernetes/core/traefik/app/middleware-*.yaml`, not via Helm values.
- **`externalTrafficPolicy: Cluster`** (not Local — Local breaks with Cilium on single-node).

# CrowdSec + Traefik Bouncer
- **TLS port**: With `tls.enabled: true`, LAPI serves HTTPS on port **8080** (not 8443). The service doesn't expose 8443.
- **Bouncer scheme**: Must use `crowdsecLapiScheme: https` + `crowdsecLapiTLSInsecureVerify: true` (self-signed cert from CrowdSec internal CA).
- **Fail-closed**: In `live` mode, bouncer can't reach LAPI → ALL traffic blocked with 403. Debug: temporarily remove bouncer from `secure-chain`.
- **CrowdSec `secretTemplate: null`**: Chart v0.22.1 bug — set `tls.certManager.secretTemplate.annotations` to a non-empty value.

# Traffic Security Architecture
```
Client → Traefik (.196) → secure-chain middleware → App
                              ↓
                     bouncer (live IP check vs CrowdSec LAPI)
                              ↓
                     local-whitelist (trusted network bypass)
```
- **CrowdSec Agent** — monitors Traefik access logs via `crowdsecurity/traefik` collection
- **CrowdSec LAPI** — central decision engine, enrolled in CrowdSec Console
- **Traefik Bouncer** — plugin middleware, queries `crowdsec.crowdsec.svc.cluster.local:8443` in `live` mode
- **TLS** — bouncer↔LAPI via mTLS; certs auto-reflected to `traefik` namespace

Middlewares: `secure-chain` (use on all apps), `bouncer`, `local-whitelist`.
