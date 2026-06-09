# Homepage Config Backup

## Why this exists

Homepage's runtime config lives at `/app/config/*.yaml` on a Longhorn PVC
(`homepage-config` PVC in the `networking` namespace), NOT in git. If the
PVC is ever lost/corrupted/restored from an old backup, all user-edited
widget customization disappears.

This directory holds **safe-to-commit snapshots** of those config files
as a disaster-recovery aid and a starting point for migrating to
GitOps-managed config.

## What's here

- `settings.yaml` — the polish settings (statusStyle, useEqualHeights,
  maxGroupColumns, hideVersion, disableIndexing). No secrets. Synced
  to the running pod via `kubectl cp` on 2026-06-09.

## What's NOT here (and why)

- `services.yaml` (~107 lines): contains plaintext API keys for Prowlarr,
  PiHole, UniFi, Proxmox, TrueNAS, CrowdSec, etc. Cannot be committed
  safely until they're migrated to `{{HOMEPAGE_VAR_*}}` placeholders.
- `bookmarks.yaml` (~98 lines): may contain bookmarklets with embedded
  tokens; deferred review.
- `widgets.yaml`: low-risk but deferred for consistency.

## Migration plan to get services.yaml into git

This is a follow-up project — DO NOT attempt without finishing the
cluster-secrets migration first (`.claude/plans/2026-06-09-flux-secrets-migration.md`),
because the providers approach is meaningfully cleaner with the Secret
substitution infrastructure in place.

Steps once the prerequisite is met:

1. For each external service that has a credential in services.yaml,
   add the credential to clusterenv.yaml (or directly to cluster-secrets):
   - `PROWLARR_API` (external Prowlarr, IP 192.168.10.10)
   - `PIHOLE_KEY` (external Pi-hole, IP 192.168.10.3)
   - `UNIFI_PASS` (UDM web UI)
   - `PVE_TOKEN_VALUE` (Proxmox API token)
   - `TRUENAS_API` (the JWT) + `TRUENAS_PASS` (web UI)
   - `CROWDSEC_HP_KEY` (homepage-specific bouncer key — created 2026-06-09
     via `cscli bouncers add homepage-monitor`; not retrievable from etcd
     so document the recovery procedure)
2. Add env vars to the homepage HelmRelease container spec:
   ```yaml
   env:
     HOMEPAGE_VAR_PROWLARR_API: ${PROWLARR_API}
     HOMEPAGE_VAR_PIHOLE_KEY: ${PIHOLE_KEY}
     # ... etc
   ```
3. In settings.yaml's `providers:` block, map each env var to a friendly name:
   ```yaml
   providers:
     prowlarr-api: HOMEPAGE_VAR_PROWLARR_API
     # ... etc
   ```
4. Replace the plaintext value in services.yaml with `{{HOMEPAGE_VAR_*}}`
   references.
5. Sanitize-verify (no plaintext secrets remain), commit services.yaml to
   `docs/homepage-config-backup/services.yaml`.
6. Find the TrueCharts homepage chart's mechanism for overriding the
   `homepage-config` ConfigMap (it has a default placeholder one but
   exposes a way to inject content — investigate `configmap:` block or
   similar in the chart's values schema).
7. Wire the customConfig + subPath volume mount so the chart-managed
   `homepage-config` ConfigMap overlays the PVC for these specific files.
8. Verify the running pod reads from the ConfigMap (not the PVC).
9. Remove the live PVC files (or leave them — the subPath mount wins
   regardless).

## Operational notes

- The current live services.yaml on the PVC is the source of truth until
  step 8 above lands.
- If you make user-visible changes to widgets via Homepage's web UI, those
  go to the PVC and silently diverge from this backup until you re-snapshot.
- The settings.yaml in this directory IS the source of truth — synced to
  the PVC on 2026-06-09. If you change settings, update both.
