#!/usr/bin/env python3
"""Query-liveness audit for every installed Grafana dashboard.

This is the audit that found `smartctl` alive at 11% (exporter never
deployed) and `k8s-coredns` at 47% (pre-1.7 metric names) - and, worse,
wrong-content ConfigMaps that had been installed "long enough that nobody
remembered". A number on a schedule is the cure for that class, so the
one-off audit became this script. Run it whenever boards change, and
quarterly otherwise.

WHAT IT DOES
    1. Renders the BUILT artifact with `kubectl kustomize` - the source
       generators are not what ships, and the imported boards have no
       source here at all.
    2. Walks every ConfigMap labelled grafana_dashboard=1, extracts every
       panel expr (including panels nested under rows).
    3. Runs each expr as an instant query against in-cluster Prometheus,
       via `kubectl exec` into a media pod (Prometheus is not exposed
       outside the cluster).
    4. Reports, per board: % of exprs returning data, and which are dead.

READING THE REPORT - two kinds of empty (see dashlib.alert_table):
    * An expr that can NEVER return data is a dead panel - delete or fix.
    * An alert-table expr (`ALERTS{alertstate="firing"...}`) with nothing
      firing is the HEALTHY case. These are counted separately as
      "empty-is-healthy", not as dead.

Template-variable exprs from imported boards cannot be meaningfully
queried; `$__interval`/`$__rate_interval`/`$interval` are substituted with
5m so rate windows survive, and anything else containing `$` is reported
as "unqueryable ($vars)" rather than pretending a failed parse proves the
panel dead.

Usage:
    python3 tools/dashboards/validate_dashboards.py [options]
      --boards SUBSTR[,SUBSTR..]  only boards whose ConfigMap name or title
                                  contains a substring (default: all)
      --pod POD                   query pod (default: first Running bazarr-*)
      --verbose                   list every dead expr, not just counts
      --strict                    exit 1 if any generated board has a dead
                                  expr (generated = ConfigMap name starts
                                  with grafana-dashboard-media-, -storage-,
                                  -network-, -cluster-overview, -uptime-kuma)
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.normpath(os.path.join(
    HERE, "../../clusters/main/kubernetes/system/kube-prometheus-stack/app"))
ENDPOINT = ("http://kube-prometheus-stack-prometheus."
            "kube-prometheus-stack:9090/api/v1/query")

GENERATED_PREFIXES = (
    "grafana-dashboard-media-", "grafana-dashboard-storage-",
    "grafana-dashboard-network-", "grafana-dashboard-cluster-overview",
    "grafana-dashboard-uptime-kuma")

ALERT_RE = re.compile(r'ALERTS\s*\{[^}]*alertstate="firing"')
SUBST = {"$__interval": "5m", "$__rate_interval": "5m", "$interval": "5m",
         "${__interval}": "5m", "${__rate_interval}": "5m"}


def find_pod():
    out = subprocess.run(
        ["kubectl", "get", "pods", "-n", "media", "--no-headers"],
        capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        cols = line.split()
        if re.match(r"^bazarr-[0-9a-f]", cols[0]) and cols[2] == "Running":
            return cols[0]
    sys.exit("no Running bazarr-* pod found to query Prometheus through")


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates a bare `=` scalar (ScrapeConfig
    `matchType: =` in the built output), which stock YAML maps to the
    obscure `tag:yaml.org,2002:value` tag and refuses to construct."""


_Loader.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: node.value)


def walk_panels(panels):
    for p in panels or []:
        yield p
        # collapsed rows carry their children inline
        yield from walk_panels(p.get("panels"))


def collect_boards(filters):
    """-> [(cm_name, title, [(panel_title, expr), ...])]"""
    built = subprocess.run(
        ["kubectl", "kustomize", APP],
        capture_output=True, text=True, check=True).stdout
    boards = []
    for doc in yaml.load_all(built, Loader=_Loader):
        if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
            continue
        labels = (doc.get("metadata") or {}).get("labels") or {}
        if str(labels.get("grafana_dashboard")) != "1":
            continue
        cm_name = doc["metadata"]["name"]
        for key, blob in (doc.get("data") or {}).items():
            try:
                dash = json.loads(blob)
            except (ValueError, TypeError):
                print("WARNING: %s/%s is not valid JSON - that is a finding "
                      "in itself" % (cm_name, key), file=sys.stderr)
                continue
            title = dash.get("title", key)
            if filters and not any(
                    f.lower() in cm_name.lower() or f.lower() in title.lower()
                    for f in filters):
                continue
            exprs = []
            for p in walk_panels(dash.get("panels")):
                for t in p.get("targets") or []:
                    e = t.get("expr")
                    if e:
                        exprs.append((p.get("title", "?"), e))
            boards.append((cm_name, title, exprs))
    return boards


def run_queries(pod, exprs):
    """exprs: unique list -> {expr: n_series or None (unqueryable)}"""
    results = {}
    queryable = []
    for e in exprs:
        s = e
        for k, v in SUBST.items():
            s = s.replace(k, v)
        if "$" in s:
            results[e] = None
            continue
        queryable.append((e, s))
    if not queryable:
        return results
    script = ["EP='%s'" % ENDPOINT]
    for i, (_, s) in enumerate(queryable):
        b64 = base64.b64encode(s.encode()).decode()
        # trailing `echo` matters: curl output has no final newline, and the
        # next marker must start at column 0 for the parser to see it
        script.append(
            'echo "=== %d"; echo %s | base64 -d | '
            'curl -s --max-time 20 --data-urlencode query@- "$EP" || true; echo'
            % (i, b64))
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write("\n".join(script) + "\n")
        path = f.name
    try:
        with open(path) as fin:
            out = subprocess.run(
                ["kubectl", "exec", "-n", "media", "-i", pod, "--", "sh"],
                stdin=fin, capture_output=True, text=True,
                timeout=60 + 25 * len(queryable)).stdout
    finally:
        os.unlink(path)
    chunks = {}
    cur = None
    for line in out.splitlines():
        m = re.match(r"^=== (\d+)$", line)
        if m:
            cur = int(m.group(1))
            chunks[cur] = []
        elif cur is not None:
            chunks[cur].append(line)
    for i, (e, _) in enumerate(queryable):
        body = "\n".join(chunks.get(i, [])).strip()
        n = 0
        try:
            j = json.loads(body)
            if j.get("status") == "success":
                data = j.get("data", {})
                r = data.get("result", [])
                n = len(r)
            else:
                n = 0
        except ValueError:
            n = 0
        results[e] = n
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boards", default="")
    ap.add_argument("--pod", default="")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    filters = [f for f in args.boards.split(",") if f]

    boards = collect_boards(filters)
    if not boards:
        sys.exit("no dashboards matched")
    uniq = sorted({e for _, _, exprs in boards for _, e in exprs})
    pod = args.pod or find_pod()
    print("querying %d unique exprs from %d boards via %s ..."
          % (len(uniq), len(boards), pod), file=sys.stderr)
    res = run_queries(pod, uniq)

    strict_fail = False
    print("%-46s %5s %5s %5s %5s  %s"
          % ("board (ConfigMap)", "exprs", "alive", "a-ok", "$var", "alive%"))
    for cm_name, title, exprs in sorted(boards):
        alive = dead = alert_ok = unq = 0
        dead_list = []
        for ptitle, e in exprs:
            n = res.get(e)
            if n is None:
                unq += 1
            elif n > 0:
                alive += 1
            elif ALERT_RE.search(e):
                alert_ok += 1  # empty-is-healthy
            else:
                dead += 1
                dead_list.append((ptitle, e))
        denom = alive + dead  # alert-empties and $var excluded from the rate
        pct = (100.0 * alive / denom) if denom else 100.0
        print("%-46s %5d %5d %5d %5d  %5.1f%%"
              % (cm_name[:46], len(exprs), alive, alert_ok, unq, pct))
        if dead_list and (args.verbose or
                          cm_name.startswith(GENERATED_PREFIXES)):
            for ptitle, e in dead_list:
                print("    DEAD [%s] %s" % (ptitle, e[:110]))
        if dead_list and cm_name.startswith(GENERATED_PREFIXES):
            strict_fail = True
    if args.strict and strict_fail:
        sys.exit("STRICT: a generated board has a dead expr - the "
                 "no-'No data' rule is violated")


if __name__ == "__main__":
    main()
