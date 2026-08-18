# Home Assistant battery alerting — design record (SQ-119)

**Status: implemented via Prometheus.** This is not an HA-native automation
proposal awaiting the operator to paste it into `/config` — the working rules
already live at
`clusters/main/kubernetes/system/kube-prometheus-stack/app/prometheusrule-homeassistant.yaml`
and are deployed through this repo's normal Flux/GitOps path. This document
records why that route was chosen over an HA automation, the retirement list
the thresholds were built against, and the verification evidence.

## Why this ticket exists

The garage lock's battery sensor (`sensor.device_lock_garage_house_door_lock_battery`)
reached **-100%** with nothing ever notifying anyone — the physical batteries
had been removed and the `lock.` entity dropped off Home Assistant's state
machine entirely, silently, the whole way down. Neither an HA-native
low-battery notification nor a Prometheus rule covered this before now.

**The live risk this ticket was actually filed for:** `Front Door Lock
Battery` was measured at **31%** on 2026-08-18, walking the identical decline
path the garage lock already finished. That is the case the design below is
built to catch on day one, not a hypothetical.

## Route decision: Prometheus, not an HA automation

**Chosen: Prometheus (PrometheusRule + Alertmanager), not a Home Assistant
automation.**

Argument, and what happens when each side is down:

| | Prometheus route (chosen) | HA-native automation |
|---|---|---|
| **Deploy path** | GitOps — Flux applies `prometheusrule-homeassistant.yaml` like every other alert rule in this repo. Reviewable diff, CI-tested (`promtool check/test rules`), rollback is `git revert`. | None. HA `/config` is not managed by Flux. An automation YAML has to be hand-applied by the operator through the HA UI or a file edit on the appliance — there is no repo-to-appliance pipeline for it, and this ticket's contract explicitly forbids applying config to the appliance (read-only access). |
| **If HA is down/restarting** | The whole `homeassistant` scrape target goes `up == 0`. Every rule in this file is gated `unless on() (up{job="homeassistant"} == 0)`, so the alerting stack goes silent about HA-derived facts rather than firing false positives — exactly the SQ-108/SQ-118 pattern already established for `HomeAssistantBackupStale` and `ScrapeTargetDown`. `ScrapeTargetDown` (SQ-118) is the alert that tells the operator HA itself stopped reporting. | If HA is down, the automation that would have warned about a dying lock is *also* down — with nothing external watching to say so. There's no dead-man's-switch equivalent to `ScrapeTargetDown` for HA's own automation engine. |
| **If Prometheus is down** | Meta-monitoring's `Watchdog` (constant heartbeat via uptime-kuma push, sink-independent of Alertmanager) catches a dead Prometheus/Alertmanager pipeline. | N/A — this route doesn't depend on Prometheus, but it also doesn't get any of Prometheus's existing meta-monitoring, absence-detection, or unit-testing discipline for free. |
| **Delivery** | Routes through the existing Alertmanager → Notifiarr/HITL pipeline already used for every other alert in this cluster (warning → 12h repeat, critical → 4h repeat, see `alertmanagerconfig.yaml`). One notification system to check, not two. | A second, parallel notification path (HA's own `notify:` service) that the operator has to remember exists and check separately from everything else. |
| **Testability** | `promtool test rules` unit-tests every rule against synthetic time series in CI, before merge. Regression-proof by construction. | HA automations have no equivalent unit-test harness in this repo. Correctness is "trust the YAML," verified only by watching it in production. |
| **Cost** | This rule structurally cannot see a battery event faster than the 1m scrape interval, and structurally cannot fire while the scrape itself is down (by design — see gate above). If someone wants an *instant* local HA notification (e.g. a phone push the moment a battery event happens) independent of the Prometheus pipeline, that is out of scope here and could be added as a light-weight, purely-local HA automation later without touching this file. | — |

The cost of the Prometheus route is real and stated plainly: **this rule
goes dark whenever the `homeassistant` scrape target is down**, exactly like
every other HA-dependent rule in this component. That is the accepted
trade-off, not a gap — `ScrapeTargetDown` (SQ-118, `prometheusrule-meta.yaml`)
is the rule that watches for the scrape itself going dark, so the failure
mode is covered, just by a different, more general rule, the same way it
already is for HA backups (SQ-108).

**Verified before designing**, per the ticket's explicit instruction not to
assume the exporter carries every entity: queried Prometheus directly
(`count by (__name__) ({job="homeassistant"})`, 2026-08-18) and confirmed
`homeassistant_sensor_battery_percent` exists with 17 active series, and
`homeassistant_entity_available` covers every entity regardless of domain
(sensor, binary_sensor, etc.), including ones with no numeric value. Cross-
checked against a full `/api/states` census of 27 `device_class: battery`
entities — the gap between 27 and 17 is exactly the entities currently
`unknown`/`unavailable`, which HA's Prometheus exporter never emits a numeric
sample for. That gap is *why* the Low and Unavailable rules are separate: a
missing Prometheus sample is not a zero.

## Retirement list (done first, per the contract)

Cross-referenced against SQ-120's registry-hygiene plan
(asset `tk_msy6gb3d_c2a0a4b7`) and the orchestrator's 2026-08-18
re-measurement. Every entity below is **excluded from every rule** in
`prometheusrule-homeassistant.yaml` — not thresholded down to zero risk of
firing, structurally excluded by entity name:

| Entity | Why retired/excluded | Source |
|---|---|---|
| `sensor.device_lock_garage_house_door_lock_battery` | The garage lock. Device is still reachable (42/42 available over 20.5d per SQ-120 §1.9) — the `lock.`/`_operator`/`_wake` entities are what's gone, not the hardware. The battery sensor itself is "available" but reports nonsense (-100) left over from the physical battery removal. Excluded here as a value-sanity call; SQ-120 owns the hardware-retirement decision. | SQ-120 §1.9, orchestrator 2026-08-18 comment |
| `sensor.living_room_cat_feeder_battery_ac`, `binary_sensor.living_room_cat_feeder_battery_status` | PetKit Living Room feeder (SQ-120 P7). 0%/off, `restored: true`. Operator moved to PetLibro (138 live entities). Only the two feeder devices are excluded — the `petkit` litter-box side (`cat_*_set_weight`) is live and out of this ticket's scope. | SQ-120 P7 |
| `sensor.bluetooth_bbq_thermometer_{8d39f9,f25909,cf24af,70c189,b2b164,3660dc}_h5055_batt` (6) | Govee H5055 BBQ probes discovered over Theengs/MQTT BLE. Confirmed dead — `0/42` over 20.5d, state `unknown`. | SQ-120 P11 |
| `sensor.service_data_3971fa_servicedata_batt` (1) | Same Theengs/MQTT BLE debris family as the BBQ probes above — together these 7 entities are the ticket's "7 out-of-range Govee thermometers." They currently report `unknown` rather than an out-of-range number; excluded from the numeric Low rules anyway as defense-in-depth in case a flaky BLE read ever produces a garbage percent before the integration entry is removed. | SQ-120 P11, this measurement (2026-08-18) |
| `sensor.home_house_first_floor_living_room_device_switch_wall_switch_wall_module_entry_module_battery_2` | Orphan `_2` MQTT-rediscovery duplicate (SQ-120 P10). The non-`_2` sibling (`entry_dimmer_battery`) is the live entity and is in scope. | SQ-120 P10 |

**Deliberately out of scope, not retired** — personal rechargeable
electronics (`sensor.device_phone_*` — Zach's and El's iPhones, Zach's Watch;
`sensor.max_jr_battery_level` — a pet-wearable). These cycle through "low"
daily on a charging schedule the operator already manages by hand; alerting
on them here would be pure noise, not an IoT hardware-failure signal. They
are excluded from the class regexes *and* from the catch-all, so a future
rechargeable added under the same naming pattern (`device_phone_*`) stays out
automatically.

## Full battery-sensor census (2026-08-18, `/api/states`, `device_class: battery`)

27 entities total. 11 excluded (retirement, see above), 4 out of scope
(rechargeables), **16 in scope** across three classes:

| Class | In-scope entities | Count |
|---|---|---|
| Locks | Front Door Lock Battery (31%), Front Gate Lock Battery (90%) | 2 |
| Zigbee/RF control accessories | Living Room Blind Remote (20%), Kitchen Blinds Remote (20%), Entry Dimmer (100%), Office Dimmer (100%), Kitchen Module (100%), Bedroom Module (100%), Zach Bed Dimmer (unavailable), Liz Bed (89%), Hallway Module (100%), Curtain (2/3) (22%) | 10 |
| Catch-all (future-proofing only — nothing unclassified exists today) | — | 0 |

## Per-class thresholds and why

Not one global number — the contract requires per-class thresholds, and a
lock, a Zigbee dimmer, and a phone do not fail the same way or matter the
same amount.

- **Locks — warn ≤35%, critical ≤15%.** The highest-consequence class in the
  house: a dead lock battery is a physical-access failure. The wide warning
  margin is deliberate — lock batteries decline over weeks, so 35% still
  gives a long runway, and the cost of an early warning is far lower than the
  cost of a missed one. **Front Door Lock Battery at 31% fires the warning
  immediately on deploy.** That's intentional, not a fixture artifact — it is
  the live incident this ticket exists to catch.
- **Zigbee/RF control accessories — warn ≤15%, critical ≤5%.** Losing one
  degrades a light or blind control, not security. Tighter thresholds because
  these devices are numerous and batteries are cheap/easy to swap — a wide
  warning band here would just be more numbers to ignore.
- **Catch-all — warn ≤20%, critical ≤10%.** Applies to any future battery
  sensor that matches neither class regex above, so a newly added device is
  never silently uncovered just because nobody remembered to update this
  file's classification. Moderate threshold — neither lock-level urgency nor
  full silence.
- **Personal rechargeables — no threshold, excluded entirely** (see above).

## Unavailable vs. low vs. disappeared — three distinct failure modes, three distinct rules

The contract requires "unavailable" and "low" to never share a rule, and the
orchestrator's follow-up flagged disappearance as a distinct third mode worth
designing for. All three exist in this design as genuinely separate alert
groups, matched against different metrics with different `for:` durations —
they cannot share firing state because they never evaluate the same
expression:

1. **Low** (`homeassistant-battery-low` group) — `homeassistant_sensor_battery_percent`
   crosses a per-class threshold. Structurally cannot fire for an entity with
   no numeric sample (unavailable/unknown entities never appear in this
   metric at all).
2. **Unavailable** (`homeassistant-battery-unavailable` group) —
   `homeassistant_entity_available == 0` for a battery-named entity,
   sustained `for: 4h`. The device is registered but not reporting a usable
   value. `for: 4h` is deliberately longer than most alerts in this repo:
   SQ-120 measured the PetKit feeder taking **>10h** to recover from an HA
   restart, so a short `for:` would false-positive on every restart. 4h is a
   compromise — long enough to clear a typical restart/mesh-reroute blip,
   short enough not to sit on a genuinely offline device for most of a day
   before saying anything.
3. **Disappeared** (`homeassistant-battery-disappeared` group) — the
   entity's metric series stops existing in Prometheus at all, rather than
   reporting `available == 0`. This is what actually happened to the garage
   lock's `lock.` entity. `absent()` over a multi-entity regex only fires
   when *every* matched series vanishes — one lock disappearing while
   another survives would be silently swallowed by `absent()`, the same class
   of gap SQ-108/SQ-118 exist to close elsewhere in this component. So
   `HomeAssistantLockBatteryDisappeared` uses a hardcoded expected count (2:
   front door + front gate) instead of `absent()`. If a lock is added or
   removed, both the count and the class regex must be updated in the same
   change, or this rule silently stops meaning what it says — documented
   in-file as a maintenance trap to watch for.

## Rate limiting (contract #5 — no daily alert for a threshold-hovering battery)

`for:` on each rule (1–6h depending on class/severity, see above) plus this
repo's existing Alertmanager routing already provides it: warning-severity
alerts repeat at most every 12h, critical every 4h
(`alertmanagerconfig.yaml`). A battery hovering exactly at a threshold cannot
produce more than one notification per repeat window even if it flaps
firing/resolved across evaluations. No second rate-limiting layer was added —
the existing one already does the job and a second layer would just be
redundant state to keep in sync.

## Verification

```
promtool test rules clusters/main/kubernetes/system/kube-prometheus-stack/app/promtool-tests/battery-staleness-test.yaml
```

Fixtures cover: Front Door Lock declining through the warning threshold and
firing (the live incident); the garage lock held at -100% forever, never
firing at any severity; a battery sensor going unavailable — not firing Low,
firing the separate Unavailable rule after `for: 4h`; the PetKit feeder
excluded from Unavailable too; all 7 Govee/BBQ-debris entities excluded from
Low even with a simulated out-of-range value; the catch-all firing for an
unclassified future entity; the `up == 0` scrape-down gate suppressing every
rule; and the disappearance rule distinguishing "2 locks present" from "1
present" — which an `absent()`-based rule would have missed. Each fixture was
manually confirmed to fail when its corresponding rule/exclusion/`for:` was
reverted (see the ticket's board comments for the specific reverts tested).
