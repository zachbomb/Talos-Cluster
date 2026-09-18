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
- **Mode is `stream`, NOT `live`** (changed 2026-09-17). Stream keeps the banned-IP list in a local cache re-synced every `updateIntervalSeconds: 60`, so LAPI is not in the per-request path.
- **Fail-open is deliberate**: `updateMaxFailure: -1`. The plugin default is `0` = block on the FIRST LAPI failure, and in `live` mode that made LAPI a hard dependency of serving any request — a LAPI outage became a 403 on every hostname. That fired on 2026-09-17 (LAPI lost 05:46–07:40Z after a node event; 403 @ 0.06/s vs 200 @ 0.03/s at 05:40Z). With stream + `-1` the bouncer keeps enforcing the last synced ban list instead of blocking everything. Tradeoff: a new ban takes ≤60s to apply.
- **Verify enforcement with a control pair, never by reading logs**: a banned IP must 403 and a control IP must 200.
  ```bash
  curl -sk -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-For: <banned-ip>' \
    --resolve "photos.${BASE_DOMAIN}:443:192.168.10.196" "https://photos.${BASE_DOMAIN}/"   # expect 403
  curl -sk -o /dev/null -w '%{http_code}\n' -H 'X-Forwarded-For: 8.8.8.8' ...                # expect 200
  ```
  This works because the LAN is in `forwardedHeaders.trustedIPs`. Get a banned IP from `cscli decisions list`.
- **The bouncer is applied at the ENTRYPOINT** (`--entryPoints.websecure.http.middlewares=traefik-bouncer@kubernetescrd`), so it covers every websecure router regardless of per-app middleware. A per-app middleware failure does NOT bypass CrowdSec.
- **`cscli bouncers list` is misleading**: auto-created `traefik-bouncer@<pod-ip>` children accumulate one per Traefik pod forever and cannot be deleted individually ("is auto-created and cannot be deleted, delete parent bouncer instead"). Stale dates there are dead pods, not a dead bouncer — check the entry whose IP matches the *live* pod.
- Debug tip: to isolate the bouncer, temporarily remove it from the entrypoint middleware list (not from `secure-chain` — it is applied at the entrypoint).
- **Startup race is benign**: right after a Traefik restart the logs burst `middleware "<ns>-<app>-...@kubernetescrd" does not exist` — the kubernetesIngress provider builds routers before kubernetesCRD finishes loading Middlewares. It self-clears within ~60s. Confirm with a positive test (are the headers on the response?) rather than by counting errors.
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
- **Traefik Bouncer** — plugin middleware, queries `crowdsec-service.crowdsec.svc.cluster.local:8080` in `stream` mode (local cache, 60s resync)
- **TLS** — bouncer↔LAPI via mTLS; certs auto-reflected to `traefik` namespace

Middlewares: `secure-chain` (use on all apps), `bouncer`, `local-whitelist`.
