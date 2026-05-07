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

### Why no flap-test.yaml?

The BGP flap-classification rule (`bgp_flap_active` in `prometheusrule-bgp.yaml`)
is fundamentally hard to fixture-test in promtool. The rule depends on
`ALERTS{alertstate="firing"}` — a series that only EXISTS while the alert
is firing, then disappears. promtool's input_series can't cleanly synthesize
a series that "exists then doesn't" the same way Prometheus tracks alert
state internally.

Behavioral correctness for the flap rule is validated by:

1. The PromQL is reviewed manually against `prometheus-operator` and
   upstream Prometheus rule patterns for "alert firing N times in window".
2. The brainstorm gameday includes step "manually induce 4+ flaps in 30
   minutes; verify BGPSessionFlapping fires (warning) instead of
   BGPSessionDown (critical)".
3. Future work: add a synthetic continuous indicator series
   (`bgp_session_firing` recording rule) that toggles 0/1 deterministically,
   then test the flap rule against THAT. This is a refactor of the rule
   itself, deferred to a follow-up PR.

## Running locally

```bash
promtool test rules clusters/main/kubernetes/system/kube-prometheus-stack/app/promtool-tests/flap-test.yaml
```
