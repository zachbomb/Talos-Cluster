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

- `flap-test.yaml` (added in U10) — covers the BGP flap-classification rule.
  Three cases: 4 firing edges in 10 m → flap_active=1; 3 edges → not active;
  4 edges spread across 31 m → not active at minute 31 (window-edge case).

## Running locally

```bash
promtool test rules clusters/main/kubernetes/system/kube-prometheus-stack/app/promtool-tests/flap-test.yaml
```
