# Home Assistant ↔ uptime-kuma integration: 401 recovery

**Symptom:** every `binary_sensor.uptimekuma_*` / `sensor.uptimekuma_*` entity in Home
Assistant is `unavailable`, while the uptime-kuma pod is `1/1 Running` and its own
monitors are green.

**This is the watchdog failing silently.** uptime-kuma is what watches the Cloudflare
tunnel, Traefik and Home Assistant itself. When the HA integration to it dies, nothing
in the household notices that the watchdog stopped reporting — the pod is healthy, the
dashboards in uptime-kuma's own UI are correct, and only the HA side is dark. It was
dark for at least three weeks before anyone looked (2026-08, SQ-100), straddling the
2026-08-14 public-access outage that those monitors existed to catch.

## Topology

| Piece | Where |
|---|---|
| uptime-kuma | `monitoring/uptime-kuma`, LoadBalancer `192.168.10.245:3001`, v1.23.17 |
| Home Assistant | bare metal `192.168.10.191:8123` (NOT in-cluster) |
| HA integration | core `uptime_kuma`, polls `GET /metrics` with the API key as HTTP basic-auth **password** |
| Prometheus | scrapes the same `/metrics` via `ServiceMonitor uptime-kuma-metrics` + secret `monitoring/uptime-kuma-auth` |

Two independent consumers hit the *same* endpoint with *different* API keys. That is
what makes this diagnosable without guessing: if Prometheus is scraping and HA is not,
the endpoint is fine and only HA's credential is bad.

## Diagnosis (read-only, ~2 minutes)

Do **not** restart the pod, delete it, or re-add the integration "to see if that fixes
it" — that destroys the evidence and this is a live household service.

1. Get HA's own error text. This is authoritative; do not infer it.

   ```bash
   TOKEN=$(kubectl get secret -n kube-prometheus-stack homeassistant-token -o jsonpath='{.data.token}' | base64 -d)
   curl -s -H "Authorization: Bearer $TOKEN" \
     http://192.168.10.191:8123/api/config/config_entries/entry \
     | python3 -c "import sys,json;[print(json.dumps(e,indent=2)) for e in json.load(sys.stdin) if e['domain']=='uptime_kuma']"
   ```

   A revoked key looks like:

   ```
   "state":  "setup_retry",
   "reason": "Request for 'http://192.168.10.245:3001/metrics' failed with status code '401'"
   ```

   > `/api/error_log` was removed in HA 2026.8 (returns 404). The config-entry `reason`
   > field is the error source now.

2. Confirm the endpoint itself is healthy — i.e. that this is a credential problem and
   not an outage. Prometheus authenticates to the same URL with its own key:

   ```bash
   # expect: up{job="uptime-kuma"} == 1
   ```

   If that is 1, `/metrics` is serving and API-key basic auth works.

3. Confirm uptime-kuma is rejecting a specific key, on HA's retry cadence (~600s):

   ```bash
   kubectl logs -n monitoring deploy/uptime-kuma --tail=200 | grep -i api-auth
   # [API-AUTH] WARN: Failed API auth attempt: invalid API Key
   ```

4. Inspect the key table (read-only; the DB is ~1.6 GB, this query is cheap):

   ```bash
   kubectl exec -n monitoring deploy/uptime-kuma -- \
     sqlite3 -readonly /app/data/kuma.db \
     "SELECT id,name,active,expires,created_date FROM api_key; SELECT * FROM sqlite_sequence WHERE name='api_key';"
   ```

   `sqlite_sequence` is the number of keys ever created (the column is `AUTOINCREMENT`,
   so ids are never reused). A gap between that number and the rows returned means a key
   was **deleted** — and if every surviving key is `active=1` with a NULL `expires`, the
   key HA is presenting is the deleted one.

### Why the log line does not tell you *which* failure it was

`/app/server/auth.js` in 1.23.x emits the identical `invalid API Key` warning for a
missing id, a hash mismatch, an inactive key and an expired key:

```js
let index = key.substring(2, key.indexOf("_"));      // uk<id>_<secret>
let hash  = await R.findOne("api_key", " id=? ", [ index ]);
if (hash === null) { return false; }
if (expiry.diff(current) < 0 || !hash.active) { return false; }
```

So the `api_key` table in step 4, not the log line, is what distinguishes revoked from
expired from disabled.

## Fix — operator action in two UIs, NOT a repo change

Nothing in `clusters/main/kubernetes/system/uptime-kuma/` is wrong. The credential lives
in Home Assistant's config entry, which is not managed by this repo.

1. **uptime-kuma** (`http://192.168.10.245:3001`) → profile menu → **Settings → API Keys
   → Add API Key**.
   - Name it `home-assistant` so the next person can tell the consumers apart.
   - Leave **Don't expire** checked. Every other key in this instance has a NULL
     `expires`; an expiry date here re-arms exactly this silent failure on a date nobody
     has written down.
   - Copy the `uk<id>_…` value. It is shown once.

2. **Home Assistant** → Settings → Devices & services → **Uptime Kuma**.
   - The entry reports `supports_reconfigure: false` and sits in `setup_retry` (HA's
     state for a *retryable* error) rather than `setup_error` (its state for
     `ConfigEntryAuthFailed`), so **HA will retry the dead key forever and never prompt
     you**. There is no self-healing path.
   - If the UI does offer *Reconfigure* / *Reauthenticate*, use it — it is the lighter
     path and preserves entity IDs.
   - Otherwise **delete the entry, then re-add** Uptime Kuma with URL
     `http://192.168.10.245:3001`, the new API key, and SSL verification **off** (plain
     http).
   - Delete the old entry **first**. Adding a second entry alongside the dead one gives
     every entity a `_2` suffix, which silently breaks dashboards and automations that
     reference the original IDs.

3. Do **not** clean up the other uptime-kuma API keys while you are in there. `uk3_…`
   (`prometheus-scraper`) is live in `monitoring/uptime-kuma-auth` and deleting it takes
   the Grafana uptime-kuma dashboard and the ServiceMonitor down the same way.

## Verification

Expect one `binary_sensor` **and** one `sensor` per active uptime-kuma monitor — 56 of
each at time of writing (57 monitors, `DizqueTV` inactive), i.e. 112 entities total.

```bash
# all 56 back to available, within ~2 minutes (HA scrape interval is 1m)
count(homeassistant_entity_available{entity=~"binary_sensor.uptimekuma_.*"} == 1)
```

```bash
kubectl logs -n monitoring deploy/uptime-kuma --tail=50 | grep -i api-auth   # silent
```

## The alert that now catches this

`homeassistant-telemetry-health` in
`clusters/main/kubernetes/system/kube-prometheus-stack/app/prometheusrule-meta.yaml`
fires `UptimeKumaHAIntegrationDown` when every uptimekuma binary_sensor reports
unavailable for 15 minutes while the Home Assistant scrape target is still up.

Prometheus already scrapes HA's `/api/prometheus` (`ScrapeConfig homeassistant`), which
exports `homeassistant_entity_available{entity="…"}` for all ~3400 entities. The data to
catch this had been sitting in Prometheus, unqueried, for the entire outage.

The rule is deliberately scoped to the uptimekuma entities: ~640 of HA's 3437 entities
are `unavailable` at any given moment (dead Zigbee devices, unreachable buttons, and so
on), so a blanket "an HA entity is unavailable" alert is unusable.

## Still open

Nothing alerts if **HA's own backups** stop. The signal exists and is already in
Prometheus — `homeassistant_sensor_timestamp_seconds{entity="sensor.backup_last_successful_automatic_backup"}`,
a unix timestamp, with backups on a daily schedule (verified live 2026-08-18: last
successful 2026-08-17T12:16:43Z, next scheduled 2026-08-18T12:35:39Z). A staleness rule
on it — fire above ~36h, which tolerates exactly one missed daily run — is the same
shape as the rule above. It was deliberately **not** built here: HA backup work is
already open on its own tickets, and two rules landing on the same signal from two
directions is worse than one landing late.
