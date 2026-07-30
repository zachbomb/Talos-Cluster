# promtool unit tests for PrometheusRules

This directory holds `promtool test rules` fixtures that exercise the rule files
in this component. The CI guard at `.github/workflows/prometheus-rules-ci.yaml`
runs every fixture in this directory on PRs that touch the alerting stack.

## Format

Each fixture is a YAML file with:
- `rule_files:` — paths to PrometheusRule files to load (use the `.spec` extracts
  written to `/tmp/rules/` by the CI step, or copy rules inline).
- `evaluation_interval:` — synthetic evaluation cadence.
- `tests:` — array of test cases, each with:
  - `interval:` — series sample cadence.
  - `input_series:` — synthetic time-series.
  - `alert_rule_test:` or `promql_expr_test:` — assertions.

See https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/.

## Fixtures here

(none currently)

> **Note:** `prometheusrule-bgp.yaml` (with the `bgp_flap_active` rule and the
> `BGPSessionDown` / `BGPSessionFlapping` alerts) was removed 2026-07 alongside
> the Cilium BGP retirement — L2 announcements carry every LB IP on-subnet, so
> the eBGP peering to the UDM was redundant (see #187). Any future fixtures go
> here for whatever rule files remain in this component.

## Running locally

```bash
promtool test rules clusters/main/kubernetes/system/kube-prometheus-stack/app/promtool-tests/<fixture>.yaml
```
