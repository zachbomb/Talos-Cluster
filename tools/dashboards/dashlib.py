"""Shared design system for this cluster's Grafana dashboards.

WHY THIS EXISTS
---------------
An audit on 2026-08-06 of the 44 dashboards then installed found:

  * 4 dashboards with ZERO queries, 31 panels of nothing. Three of them were
    the wrong dashboard entirely - the ConfigMap named `uptime-kuma` contained
    a dashboard titled "Solar PV System", `crowdsec` contained "Rclone Backup
    Dashboard", and `graphite` contained "Environment".
  * `smartctl` alive at 11% (1 of 9 metrics exist - the exporter is not
    deployed), `k8s-coredns` at 47% (references pre-1.7 CoreDNS metric names).
  * Dashboards for AIX and macOS on an all-Talos cluster.
  * The media stack - 18 scrape targets, ~250 metric families across sonarr,
    radarr, lidarr, readarr, bazarr, sabnzbd, nzbget, deluge, plex, emby,
    tunarr - represented by ONE dashboard titled "Sonarr v3", 7 panels.

Those are two different failures. The dead ones are hygiene. The media gap is
the real one: the metrics were there the whole time and nothing surfaced them.

THE ORGANISING IDEA
-------------------
Most imported dashboards are organised by METRIC CATEGORY - CPU, memory,
network, disk. That is the exporter author's mental model. An operator does
not arrive asking "how is memory". They arrive asking, in this order:

    1. IS IT BROKEN?      alerts firing for this scope, right now
    2. IS IT DOING ITS JOB?   the service's PURPOSE metric
    3. IS IT KEEPING UP?      throughput, backlog, latency
    4. CAN IT KEEP GOING?     capacity - disk, memory, quota

Every dashboard here is laid out in that order, top to bottom. Urgency of the
QUESTION, not category of the metric.

Question 2 is what makes a dashboard service-relevant, and it is different for
every service. It is the thing the service exists to do:

    Plex / Emby     active streams, and how many are transcoding
    Sonarr / Radarr missing + cutoff-unmet  (library completeness)
    Bazarr          subtitles missing
    SABnzbd/NZBGet  queue depth and rate
    Deluge          active torrents and rate
    Tunarr          channels serving
    Longhorn        volume robustness
    TrueNAS         pool health

A dashboard that shows a service's CPU but not its purpose metric tells you the
process is alive, not that it works. Plex can sit at 3% CPU with every stream
failing.

ENVIRONMENT vs SERVICE
----------------------
An ENVIRONMENT dashboard (e.g. Media) aggregates the PURPOSE metrics of its
member services to answer "is the experience working". It is not a pile of
per-pod charts. A SERVICE dashboard drills into one service's own four
questions. Environment links down to its services; every dashboard links back
to the overview.

HARD RULES
----------
* No `No data` panels. Every expr is validated against live Prometheus before
  commit. `or vector(0)` is allowed ONLY on a metric confirmed to exist, where
  it turns "empty because nothing is wrong" into a green zero - never on an
  unverified metric, where it manufactures a reassuring lie.
* No `$` anywhere in generated JSON. Fixed windows, hardcoded datasource uid.
  Flux's postBuild envsubst runs over these ConfigMaps; undefined vars pass
  through today, but a future cluster-config key could collide with a Grafana
  token. Avoiding `$` removes the class.
* Units are always declared. A raw 66286290731008 is not an answer.
* Semantic colour is fixed and separate from decoration: green ok, orange
  degraded, red broken. A "count of bad things" tile uses background colour so
  it reads across the room; a healthy inventory count uses plain value colour
  so the board is not a wall of green blocks.
"""

DS = {"type": "prometheus", "uid": "prometheus"}

# Fixed geometry so every board lines up on the same grid.
H_STAT = 4
H_GAUGE = 4
H_TS = 8
W_STAT = 4
W_GAUGE = 5

GREEN, ORANGE, RED = "green", "orange", "red"


def _target(expr, legend=None, instant=True, fmt=None, ref="A"):
    t = {"datasource": DS, "expr": expr, "refId": ref}
    if instant:
        t["instant"] = True
    if legend:
        t["legendFormat"] = legend
    if fmt:
        t["format"] = fmt
    return t


def _thresholds(steps):
    return {"mode": "absolute", "steps": steps}


def stat(title, expr, x, y, w=W_STAT, h=H_STAT, unit="none", desc="",
         bad_above=None, warn_above=None, decimals=0):
    """Single number.

    bad_above=N paints the whole tile red above N - use for counts of broken
    things, so they are visible without reading. Omit it for inventory counts
    (library size, channels, protected PVCs); painting those green makes the
    board a wall of colour and the real problems stop standing out.
    """
    steps = [{"color": GREEN, "value": None}]
    if warn_above is not None:
        steps.append({"color": ORANGE, "value": warn_above + 1})
    if bad_above is not None:
        steps.append({"color": RED, "value": bad_above + 1})
    coloured = bad_above is not None or warn_above is not None
    return {
        "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": _thresholds(steps),
            "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {
            "colorMode": "background" if coloured else "value",
            "graphMode": "none", "justifyMode": "auto", "textMode": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                              "values": False}},
        "targets": [_target(expr)],
    }


def stat_floor(title, expr, x, y, w=W_STAT, h=H_STAT, warn_below=None,
               crit_below=None, unit="none", desc="", decimals=0):
    """Single number where LOW is bad - days remaining, free space, headroom.

    Grafana threshold steps apply from their value upward, so an inverted
    scale is expressed by starting red and stepping UP into orange then green.
    Getting this backwards paints a healthy 67-days-remaining tile red, which
    is worse than no colour at all because it trains people to ignore it.
    """
    steps = [{"color": RED, "value": None}]
    if crit_below is not None:
        steps.append({"color": ORANGE, "value": crit_below})
    if warn_below is not None:
        steps.append({"color": GREEN, "value": warn_below})
    return {
        "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": _thresholds(steps),
            "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"colorMode": "background", "graphMode": "none",
                    "justifyMode": "auto", "textMode": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False}},
        "targets": [_target(expr)],
    }


def table(title, expr, x, y, w=12, h=H_TS, desc="", exclude=None):
    """Plain instant table - for 'which ones', where a count is not enough."""
    ex = {"Time": True, "Value": True, "__name__": True, "endpoint": True,
          "instance": True, "job": True, "service": True, "container": True,
          "namespace": True, "pod": True}
    ex.update(exclude or {})
    return {
        "type": "table", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "custom": {"align": "auto", "filterable": True},
            "thresholds": _thresholds([{"color": GREEN, "value": None}])},
            "overrides": []},
        "options": {"showHeader": True},
        "targets": [_target(expr, fmt="table")],
        "transformations": [{"id": "organize", "options": {
            "excludeByName": ex, "indexByName": {}, "renameByName": {}}}],
    }


def gauge(title, expr, x, y, w=W_GAUGE, h=H_GAUGE, warn=0.80, crit=0.90,
          unit="percentunit", desc="", mn=0, mx=1):
    return {
        "type": "gauge", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit, "min": mn, "max": mx, "decimals": 1,
            "thresholds": _thresholds([
                {"color": GREEN, "value": None},
                {"color": ORANGE, "value": warn},
                {"color": RED, "value": crit}]),
            "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"showThresholdLabels": False, "showThresholdMarkers": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False}},
        "targets": [_target(expr)],
    }


def timeseries(title, series, x, y, w=12, h=H_TS, unit="none", desc="",
               stack=False, fill=12):
    """series: list of (expr, legend)."""
    return {
        "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit,
            "custom": {"drawStyle": "line", "lineWidth": 2,
                       "fillOpacity": fill, "showPoints": "never",
                       "spanNulls": True,
                       "stacking": {"mode": "normal" if stack else "none",
                                    "group": "A"}},
            "color": {"mode": "palette-classic"},
            "thresholds": _thresholds([{"color": GREEN, "value": None}])},
            "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom",
                               "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": [_target(e, lg, instant=False, ref=chr(65 + i))
                    for i, (e, lg) in enumerate(series)],
    }


def bargauge(title, series, x, y, w=12, h=H_TS, unit="none", desc="",
             warn=None, crit=None):
    """Horizontal comparison across named things - the right shape for
    'which of these is worst', e.g. per-*arr backlog."""
    steps = [{"color": GREEN, "value": None}]
    if warn is not None:
        steps.append({"color": ORANGE, "value": warn})
    if crit is not None:
        steps.append({"color": RED, "value": crit})
    return {
        "type": "bargauge", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": 0,
            "thresholds": _thresholds(steps),
            "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"displayMode": "gradient", "orientation": "horizontal",
                    "showUnfilled": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False}},
        "targets": [_target(e, lg) for e, lg in series],
    }


def alert_table(title, expr, x, y, w=16, h=H_TS, desc=""):
    """Question 1, always. Scoped ALERTS beat any curated metric: on
    2026-08-06 three CRITICALs ran for ~9 hours while health was reported
    green from hand-picked series.

    ON THE EMPTY STATE - there are two kinds of empty and they are NOT the
    same, though Grafana renders both as "No data":

      * a query that can NEVER return data (e.g. filtering a metric whose
        source emits a -1 sentinel). That panel is dead and must be deleted.
      * an alert table with nothing firing. That is the HEALTHY case, and the
        panel comes alive the moment something breaks.

    Conflating them once cost a working panel. So `noValue` is set here: the
    empty state reads as a statement instead of looking like a broken query,
    which is what made the distinction hard to see in the first place.
    """
    return {
        "type": "table", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "custom": {"align": "auto", "filterable": True},
            "noValue": "No alerts firing - nothing is broken right now",
            "thresholds": _thresholds([{"color": GREEN, "value": None}])},
            "overrides": [{
                "matcher": {"id": "byName", "options": "severity"},
                "properties": [
                    {"id": "custom.cellOptions",
                     "value": {"type": "color-background"}},
                    {"id": "mappings", "value": [{"type": "value", "options": {
                        "critical": {"color": RED, "index": 0},
                        "warning": {"color": ORANGE, "index": 1},
                        "info": {"color": "blue", "index": 2}}}]}]}]},
        "options": {"showHeader": True,
                    "sortBy": [{"displayName": "severity", "desc": False}]},
        "targets": [_target(expr, fmt="table")],
        "transformations": [{"id": "organize", "options": {
            "excludeByName": {
                "Time": True, "Value": True, "__name__": True,
                "alertstate": True, "endpoint": True, "instance": True,
                "job": True, "service": True, "container": True,
                "prometheus": True, "prometheus_replica": True, "uid": True},
            "indexByName": {"alertname": 0, "severity": 1, "namespace": 2},
            "renameByName": {}}}],
    }


def row(title, y):
    return {"type": "row", "title": title, "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


# The four questions, in fixed order and fixed wording. Using the same row
# titles everywhere is most of what "visually cohesive" means in practice -
# a reader learns the shape once and then knows where to look on every board.
Q1 = "1 - Is it broken right now?"
Q2 = "2 - Is it doing its job?"
Q3 = "3 - Is it keeping up?"
Q4 = "4 - Can it keep going?"


def dashboard(title, uid, panels, tags, refresh="1m", time_from="now-6h",
              links=None):
    dash = {
        "title": title, "uid": uid, "tags": tags, "timezone": "browser",
        "schemaVersion": 39, "version": 1, "editable": True,
        "refresh": refresh, "time": {"from": time_from, "to": "now"},
        "templating": {"list": []}, "annotations": {"list": []},
        "panels": panels,
        "links": links or [{
            "type": "dashboards", "title": "Related", "tags": tags[:1],
            "asDropdown": True, "includeVars": False, "keepTime": True,
            "targetBlank": False, "icon": "external link"}],
    }
    return dash


def emit_configmap(dash, cm_name, json_key, header_comment):
    """Render the ConfigMap text. Fails loudly on malformed JSON here rather
    than silently in Grafana."""
    import json
    body = json.dumps(dash, indent=2)
    json.loads(body)
    if "$" in body:
        raise SystemExit("refusing to emit: '$' in JSON would risk an "
                         "envsubst collision (see module docstring)")
    indented = "\n".join("    " + ln for ln in body.split("\n"))
    return (header_comment.rstrip("\n") + "\n"
            + "apiVersion: v1\nkind: ConfigMap\nmetadata:\n"
            + "  name: %s\n" % cm_name
            + "  namespace: kube-prometheus-stack\n"
            + "  labels:\n    grafana_dashboard: \"1\"\n"
            + "data:\n  %s: |-\n" % json_key
            + indented + "\n")
