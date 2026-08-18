# Cloudflare tunnel DNS rebind — operator actions (SQ-99, 2026-08-18)

Public access through the Cloudflare tunnel has been broken since at least
2026-08-14 22:56Z. Two independent faults (found by SQ-93, verified end-to-end by
SQ-99). **Fault A is fixed in the repo** (Traefik TLSStore change, same commit as
this doc). **Fault B is Cloudflare-side and needs the actions below** — it cannot
be fixed from this repo.

Live tunnel: `edadc32f-50d8-45c3-8a9e-375fcef8dca3` (healthy, 4 connections,
connector in `cloudflared` namespace). Zone: `wethecommon.com`.

## Fault A (fixed in repo) — Traefik rejected the tunnel's SNI

Every tunnel ingress rule presents `originServerName: wethecommon.com`
(cloudflared remote config v24, pushed 2026-08-14T22:18Z). Traefik has
`sniStrict: true`, and the wildcard cert (SANs `wethecommon.com`,
`*.wethecommon.com`) was only the TLS store's *default* certificate — with
`sniStrict` the default cert is never consulted for SNI matching, so every
tunnel handshake died with `tls: unrecognized name` (710 errors/24h in
cloudflared logs).

Fix: register the wildcard cert as a *named* TLS store certificate
(`tlsStore.default.certificates`) so its SANs enter the SNI match pool.
`sniStrict` stays on — unknown SNI is still rejected; we only made the name the
tunnel already presents (and already holds a cert for) recognizable. Proof of
mechanism: `discord-hitl.sf` (the one hostname whose `originServerName` matches
a cert in the pool) traverses tunnel → Traefik fine today (fast 404), while
`sf` apex / `flux-webhook.sf` (originServerName not in pool) 502 at TLS.

## Fault B (operator) — DNS records not bound to the live tunnel

Verified from zone DNS (read-only API list, 2026-08-18): only **3** hostnames
CNAME to the live tunnel. The other 20 hostnames in the tunnel's ingress config
resolve via `CNAME → wethecommon.com` → `A 23.93.109.64` (WAN IP, proxied
origin-pull). Inbound WAN is ISP-blocked (see WAN MAC-spoof incident, Jul 2026),
so Cloudflare's edge times out → 522, and the request **never reaches
cloudflared** (confirmed: 522 probes leave no cloudflared log entry; control
probes to tunnel-bound hosts do).

### Required change

For each hostname below, in the Cloudflare dashboard (DNS → Records) or API,
replace the existing record with:

```
CNAME <hostname> → edadc32f-50d8-45c3-8a9e-375fcef8dca3.cfargotunnel.com  (Proxied: ON)
```

Currently `CNAME → wethecommon.com` (proxied), all confirmed 522 or
Access-302-then-dead:

| hostname (.sf.wethecommon.com) | probe 2026-08-18 |
|---|---|
| emby, overseerr, photos, roon, tautulli, notifiarr, calibre, calibre-web, cwa, shelfmark, homeassistant, homebridge, tandoor, triparr, external | 522 (~19.5s), absent from cloudflared logs |
| tools, search, paperless, pdf | 302 (Cloudflare Access wall at edge) — still need rebinding; after Access auth the edge pulls the same dead WAN origin |

Already correct (leave alone): `sf`, `flux-webhook.sf`, `discord-hitl.sf`.

Note: the Zero Trust dashboard "Public Hostnames" tab will NOT do this for you
retroactively — the routes already exist in the tunnel config (v24); it's only
the zone DNS records that were never migrated (Cloudflare refuses to overwrite
pre-existing records when a public hostname is added).

### Special cases — decide, don't blindly rebind

- **`plex.sf`**: currently *unproxied* `A → 23.93.109.64` (direct WAN, no CF).
  Dead externally today (ISP inbound block), but tunneling Plex video through
  Cloudflare strains CF ToS and adds latency. Options: leave direct-WAN and fix
  at the ISP/ONT (per WAN incident runbook), or accept tunnel routing. The
  tunnel ingress rule for it already exists either way.
- **Stale wildcard**: `CNAME *.wethecommon.com → 7142103e-af9d-4e08-b2a6-fb93fe91266a.cfargotunnel.com`
  points at an OLD tunnel ID (not the live connector). Any first-level
  `x.wethecommon.com` name without an explicit record 530s. Cleanup candidate:
  delete or repoint to `edadc32f-...cfargotunnel.com`.
- **Split-horizon (SQ-93 F3)**: LAN clients using the router (.1) as DNS get
  Cloudflare IPs for these names (no local override; Blocky/Pi-hole clients get
  192.168.10.196 and work). Fixing fault B fixes router-DNS clients too — no
  separate action needed unless you want a UDM-local override.
- **Hygiene (no action needed)**: ~35 *unproxied* A records in the public zone
  point at `192.168.10.196` (RFC1918) — public disclosure of the internal
  service inventory. Blocky/Pi-hole already resolve these locally; consider
  pruning them from the public zone in a separate pass.

## Verification (after Flux applies the Traefik change AND DNS is rebound)

LAN split-horizon DNS masks the public path — pin the edge IP:

```sh
EDGE=$(dig +short @1.1.1.1 homeassistant.sf.wethecommon.com A | head -1)
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" \
  --resolve homeassistant.sf.wethecommon.com:443:$EDGE \
  https://homeassistant.sf.wethecommon.com/
# expect 200 (HA login) in <1s; control: same probe against sf.wethecommon.com
# (already tunnel-bound) must stop 502ing once the Traefik change is live.
kubectl logs -n cloudflared deploy/cloudflared --since=5m | grep -c "unrecognized name"
# expect 0 new entries
```
