# Internal vs External Service Lockdown — Plan

**Date:** 2026-05-05
**Goal:** Stop accidentally exposing admin UIs (Pi-hole, Proxmox, Longhorn, *arr admins, Grafana, etc.) to the public internet via Cloudflare tunnel + Traefik.

## Current state (the problem)

1. **Every `*.sf.wethecommon.com` is publicly resolvable** via a Cloudflare CNAME → `wethecommon.com` (proxied) → Cloudflare tunnel → cluster Traefik.
2. **Only 2 of 53 ingresses use `secure-chain` middleware** (`goodmem`, `n8n`). The other 51 use `<app>-tc-basic-secure-headers` only — no IP allowlist, no CrowdSec bouncer.
3. **Even `secure-chain` wouldn't actually block tunnel traffic**:
   - `local-whitelist` allowlist includes `172.16.0.0/16` (pod CIDR).
   - Cloudflared pod IP is `172.16.0.62`, so tunnel-originated requests pass the allowlist.
   - Traefik has no `forwardedHeaders` config, so it can't see the real client IP from `X-Forwarded-For`.

## Categorization (from user input 2026-05-05)

### Public — keep externally accessible (24 services)

Streaming/media: `plex emby overseerr photos roon tautulli notifiarr`
Sharing: `calibre calibre-web cwa shelfmark`
Home: `homeassistant homebridge tandoor`
Tools: `it-tools searxng paperless stirling-pdf`
Webhooks/bots: `flux-webhook triparr`

### Internal — LAN/VPN only (29 services)

Admin: `pihole pihole-k8s proxmox truenas minio longhorn grafana uptime homepage code`
Media admin: `sonarr radarr lidarr lidarr-flac lidarr-liz readarr bazarr prowlarr kapowarr mylar`
Downloaders: `sabnzbd nzbget deluge`
Media management: `tunarr tunarr-code dizquetv tdarr tinymediamanager`
Sidekick code editors: `doplarr notifiarr-code sabnzbd-code tautulli-code homepage-code`
Compute/data: `n8n ollama goodmem`

Any service not in either list defaults to **Internal** (safer fail-closed).

## Phased approach

### Phase 1 — DNS lockdown (low risk, high value, do first)

For each Internal service:
1. Add local A record `<svc>.sf.wethecommon.com → 192.168.10.196` in:
   - Pi-hole `.3` (bare-metal) via API
   - Pi-hole `.244` (k8s) via nebula-sync mirror, OR direct API
   - Blocky helm-release `customDNS.mapping`
2. Verify LAN resolution returns `192.168.10.196`.
3. Delete the Internal service's CNAME from Cloudflare zone `wethecommon.com`.
4. Verify public DNS now returns NXDOMAIN (or whatever upstream returns).
5. Verify LAN access still works.

After Phase 1, internal services are **not publicly findable** but still work for LAN/VPN clients (because Traefik still routes by Host header, just from a different DNS path).

**Risk:** if Cloudflare DDNS or other automation references those CNAMEs, it'll break. None known.

### Phase 2 — Traefik forwardedHeaders trust (prereq for Phase 3)

Configure Traefik to trust `X-Forwarded-For` from:
- The cloudflared pod IP/CIDR (so it can extract the real external client IP for tunneled traffic)
- Optionally MetalLB / kube-proxy node IPs

Helm value path (upstream traefik chart):
```yaml
ports:
  websecure:
    forwardedHeaders:
      trustedIPs:
        - 172.16.0.0/16  # cloudflared pod
        - 10.0.0.0/8     # broad — narrow later
      insecure: false
```

After this, Traefik logs + middleware can see the **real client IP** for tunnel-originated traffic.

### Phase 3 — Internal-only middleware (proper IP gating)

Once Phase 2 is in place, replace `<app>-tc-basic-secure-headers` with a new
chain on Internal services. Two new middleware:

```yaml
# internal-allowlist: real-IP based, no pod CIDR
spec:
  ipAllowList:
    sourceRange:
      - 192.168.3.0/24    # VPN
      - 192.168.8.0/24    # Travel
      - 192.168.9.0/24    # Travel
      - 192.168.10.0/24   # LAN
      - 192.168.20.0/24   # other VLANs
      - 192.168.30.0/24   # IoT (if you want admin UIs reachable from there)
    ipStrategy:
      depth: 1            # use last X-Forwarded-For (real client)

# internal-secure-chain: bouncer + internal-allowlist
spec:
  chain:
    middlewares:
      - name: bouncer
        namespace: traefik
      - name: internal-allowlist
        namespace: traefik
```

For each Internal service ingress: replace
`<app>-tc-basic-secure-headers@kubernetescrd`
with
`traefik-internal-secure-chain@kubernetescrd`.

### Phase 4 — Public-chain for external services (optional hardening)

For Public services, keep them reachable from anywhere but apply CrowdSec bouncer
(real-IP via Phase 2 forwardedHeaders) so banned IPs are blocked. Optionally
apply Cloudflare Access policies on highly-sensitive ones.

```yaml
# public-chain: bouncer only, no allowlist
spec:
  chain:
    middlewares:
      - name: bouncer
        namespace: traefik
```

## Open issues / gotchas

- **MetalLB + externalTrafficPolicy=Cluster** SNATs LAN traffic to node IPs.
  Memory note in CLAUDE.md: switching to Local breaks Cilium on single-node.
  Without forwardedHeaders config + correct ipStrategy, allowlists can't see real LAN IPs either.
- **Some `*-external-service` ingresses** (proxmox, truenas, homeassistant) point
  to non-cluster services. They'd need the same middleware treatment.
- **Cert-manager DNS-01 challenges** continue to work after DNS removal because
  cert-manager creates `_acme-challenge.X.sf.wethecommon.com` TXT records on Cloudflare
  directly, independent of the A/CNAME records.
- **Wildcard CNAME `*.wethecommon.com`** still exists and points to a different
  cfargotunnel ID. Records under `sf.wethecommon.com` are explicit, so deleting them
  won't be caught by the wildcard (Cloudflare wildcards are single-label).

## Verification commands

```bash
# After Phase 1:
dig @192.168.10.3 +short pihole.sf.wethecommon.com           # → 192.168.10.196 (good)
dig @192.168.10.195 +short pihole.sf.wethecommon.com         # → 192.168.10.196 (good)
dig @1.1.1.1 +short pihole.sf.wethecommon.com                # → empty/NXDOMAIN (good — public CAN'T find it)

# From LAN client browser:
https://pihole.sf.wethecommon.com   # works, hits Traefik via 192.168.10.196

# From phone on LTE (no VPN):
https://pihole.sf.wethecommon.com   # fails to resolve — that's the point
```

## Open questions before running Phase 1

- The `*-external-service` ingresses route to physical hosts on LAN (proxmox, truenas,
  homeassistant, homebridge, minio). Their backend is reached over LAN — currently
  fine. Do **not** delete those CNAMEs if any external integration depends on them
  (e.g., Home Assistant Companion app, Homebridge external access for HomeKit hub).
  → User said homeassistant + homebridge stay PUBLIC, so they remain on Cloudflare.
