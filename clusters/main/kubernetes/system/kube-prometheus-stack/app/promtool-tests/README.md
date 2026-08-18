# promtool unit tests for PrometheusRules

This directory holds `promtool test rules` fixtures that exercise the rule files
in this component. The CI guard at `.github/workflows/prometheus-rules-ci.yaml`
runs every fixture in this directory on PRs that touch the alerting stack.

## Format

Each fixture is a YAML file with:
- `rule_files:` — the `*-extracted.yaml` rule files in this directory. These are
  the `.spec` of a PrometheusRule CRD, which is what promtool understands; handing
  it the CRD itself fails with `field apiVersion not found in type rulefmt.RuleGroups`.
  They are **committed**, so a fixture runs in a plain checkout — see below.
- `evaluation_interval:` — synthetic evaluation cadence.
- `tests:` — array of test cases, each with:
  - `interval:` — series sample cadence.
  - `input_series:` — synthetic time-series.
  - `alert_rule_test:` or `promql_expr_test:` — assertions.

See https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/.

## Fixtures here

| Fixture | Rule file | Source PrometheusRule |
|---|---|---|
| `crowdsec-availability-test.yaml` | `prometheusrule-crowdsec-extracted.yaml` | `../prometheusrule-crowdsec.yaml` |
| `storage-test.yaml` | `prometheusrule-storage-extracted.yaml` | `../prometheusrule-storage.yaml` |
| `truenas-scrub-test.yaml` | `prometheusrule-truenas-extracted.yaml` | `../../../truenas-exporter/app/prometheusrule.yaml` |
| `unifi-staleness-test.yaml` | `prometheusrule-network-extracted.yaml` | `../prometheusrule-network.yaml` |
| `ha-backup-staleness-test.yaml` | `prometheusrule-storage-extracted.yaml` | `../prometheusrule-storage.yaml` (SQ-108: `homeassistant-backups` group) |
| `scrape-target-down-test.yaml` | `prometheusrule-meta-extracted.yaml` | `../prometheusrule-meta.yaml` (SQ-118: `ScrapeTargetDown` job-set audit) |
| `battery-staleness-test.yaml` | `prometheusrule-homeassistant-extracted.yaml` | `../prometheusrule-homeassistant.yaml` (SQ-119: battery low/unavailable/disappeared alerting) |

## Why the extracts are committed

They were generated only inside CI until 2026-08-11. That made every fixture
**silently unrunnable** anywhere else: promtool treats a missing `rule_files:`
entry as a WARNING, not an error, so it loads zero rules and every
`alert_rule_test` returns `got:[]`. The run then looks like a set of genuine test
failures. "The rules are broken" and "the rules never loaded" produce identical
output — which is exactly the failure class SQ-72 exists to remove from the
alerting stack, reproduced in the tooling meant to guard it.

Committing generated files trades that for drift risk, so CI pays the other half:
the `Extracted rule files match their source (drift guard)` step regenerates each
extract and fails the build if it differs from the committed copy. The comparison
is semantic — both sides are normalized through the same `yq` — so a formatting
difference between yq releases does not fail, but any real change to rules,
expressions, or labels does.

**After editing a PrometheusRule, regenerate its extract and commit it:**

```bash
yq eval '.spec' <source-prometheusrule>.yaml > <name>-extracted.yaml
```

> **Note:** `prometheusrule-bgp.yaml` (with the `bgp_flap_active` rule and the
> `BGPSessionDown` / `BGPSessionFlapping` alerts) was removed 2026-07 alongside
> the Cilium BGP retirement — L2 announcements carry every LB IP on-subnet, so
> the eBGP peering to the UDM was redundant (see #187). Any future fixtures go
> here for whatever rule files remain in this component.

## Running locally

```bash
promtool test rules clusters/main/kubernetes/system/kube-prometheus-stack/app/promtool-tests/<fixture>.yaml
```
