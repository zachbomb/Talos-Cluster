# Home Assistant Dashboard Proposal

**Ticket:** SQ-110 · **Date:** 2026-08-17 · **Instance:** "Pibb's Home (Yellow)", HA Core **2026.8.2**
**Method:** All instance facts below were measured live this session via read-only REST (`/api/states`,
`/api/config`) and WebSocket (`lovelace/*`, `config/*_registry/list`, `energy/get_prefs`) calls.
Nothing was modified. Landscape facts carry source links and were gathered 2026-08-17.

**Revised by SQ-113 (same day):** the information architecture is revised to the operator's
four-axis model — **Overview · Room-based · Topic-based · Exterior** (§6). The research, card
sketches, and prerequisites of the original stand; §2.5, §6, §7.6–§7.9, §8 and parts of §5.4/§9
are new or amended. A second read-only `/api/states` pull was taken for the revision (baseline:
3,439 states, 620 unavailable, 700 unknown, watchman 38) and **every entity ID added by the
revision was verified live against it**; the original's 57 working entity IDs were re-confirmed
in the same pull (its documented-broken refs are still broken, unchanged).

This is a **design document**. Nothing in it has been applied. Every entity ID that appears in a YAML
sketch was verified to exist AND to be in a working (not `unavailable`/`unknown`) state at measurement
time, except where explicitly marked otherwise.

---

## 1. Executive summary

- The modern HA dashboard baseline (Sections view + native Tile/Heading/Area cards + per-card
  visibility conditions) covers almost everything this house needs **without new custom-card
  dependencies**. The existing Overview is already a Sections dashboard with good bones (the person
  badges with Bermuda room-level presence are genuinely well built) — it is under-filled, not
  wrongly built.
- **Step 0 is non-negotiable:** two full copies of `mushroom.js` are registered as Lovelace resources
  (`lovelace-mushroom` v5.2.2 and a stale `lovelace-mushroom-better-sliders` fork). Every
  mushroom-based card is unreliable until one is removed (§5.1). The design below keeps the six
  existing mushroom cards but adds **no new mushroom dependence** in the core views, so the house
  dashboard keeps working even if mushroom lags an HA release.
- The single highest-value new artifact is the **native Energy dashboard**, which is one configuration
  form away from existing: `energy/get_prefs` returned completely empty, while a Sense whole-home
  monitor exports a valid `total`/`energy`-class grid sensor and ~195 working per-device energy
  sensors, plus a Droplet water meter with a valid `water`-class total sensor (§5.3, §7.4).
- A fully room-centric dashboard system is **not currently buildable**: only 375/1188 devices (32%)
  have an area. **The key structural insight of the four-axis revision: topic dashboards need NO
  area assignment.** They bind to entities by what they *are* (cats, network, energy, security), not
  where they live — which is exactly how the 813 area-less devices (68%) become usable **without
  first doing 813 assignments**. Room views cover the ~375 placed devices; topic views cover
  everything. The two axes are complementary, and this is precisely why the original's "scoped area
  triage" prerequisite (§5.4) is **deferred rather than blocking**: ship topic views first (zero
  prerequisites), then room views incrementally as areas get populated, starting with the areas that
  are already rich. Groups-first still holds: 13 pre-existing light groups and a media group
  summarize the house with no area data at all.
- Recommended end state (revised, §6): **four axes** — an **Overview** landing (rework of the
  existing `lovelace` Home view), **topic dashboards** (Energy, Cats, Security & Doors,
  Network & Infra, House Ops), **room views** for the ~6 areas rich enough to carry one, and one
  **Exterior** view over the existing Outside floor. The prior three-dashboard shape (Home / Energy
  / House Ops) survives intact as a subset: Home is the overview axis; Energy and House Ops are two
  of the topic views. Still: delete the empty media dashboard, remove 6 of 10 registered frontend
  resources (§2.3). The roadmap in §8 is re-ordered so topic views land first; item 1 (dead refs +
  duplicate mushroom + cats-view rescue) still makes the current Overview honest in ~90 minutes.

---

## 2. Measured reality (this instance, 2026-08-17)

### 2.1 Scale and availability

| Metric | Measured value |
|---|---|
| Entities with state | 3,439 |
| `unavailable` right now | **621** |
| `unknown` right now | 694 (1,315 total not-working, 38%) |
| Registry entities (incl. disabled) | 12,641 |
| Devices | 1,188 (375 with an area = **32%**) |
| Areas / floors | 19 / 3 (First, Ground, Outside) |
| Areas with no floor | Gym TV, Main Bedroom, Server Room (all also empty) |
| Largest "area" | `garage`: 640 entities (500 working) — the infra dump |
| Unassigned entities (by state) | 1,734 (954 working) |
| Automations | 41 (34 on, 7 off; SQ-109 curating 22 dormant) |
| Scripts / helpers | 2 scripts (`pi_hole_enable/disable`), 1 `input_boolean`, 1 `input_text` |
| Notify usage by automations | **zero** — the dashboard is the only operator channel |
| Watchman | `sensor.watchman_missing_entities` = 39 |
| Pending updates | 26 `update.*` entities in state `on` |

The 38% not-working figure is why **conditional visibility is load-bearing here, not polish**. Any
card bound to an uncurated entity list will render broken tiles every single day.

Top integrations by registry entity count: bermuda 5,934 (mostly disabled), unifi 2,678, ibeacon 880,
mqtt 512, sense 333, unifiprotect 281, proxmoxve 208, mail_and_packages 171, hue 149, petlibro 138.

### 2.2 Current dashboards

| Dashboard | url_path | State |
|---|---|---|
| Overview | `lovelace` | 10 Sections views. `Home` view: good badge row, body = 1 thermostat + "New section" placeholder. 8 room/topic views, most with a single thin section. `Network` view: **empty stub**. A 10th **untitled** view (`path: ""`, `mdi:cat`) holds a "Household Vitals" pets section — unreachable by name, holds 4 of the 9 dead refs. |
| media | `dashboard-media` | **Empty masonry stub** (one empty "Home" view). |
| Map | `map` | Default map dashboard. Fine as-is. |

**Dead/broken refs on Overview (9 total, located per view):**

| View | Broken refs |
|---|---|
| Living Room | `select.device_cat_feeder_living_room_feeder_{white,green}_manual_feed` (missing), `binary_sensor.device_cat_feeder_living_room_feeder_{white,green}_food_level` (unavailable), `light.home_house_first_floor_hallway_device_light_overhead_center` (missing), `sensor.group_sensor_temperature`, `sensor.group_sensor_living_room_air` (both `unknown` — broken group sensors) |
| Bedroom | `fan.device_climate_fan_bedroom_fan` (unavailable) |
| Office | `sensor.group_sensor_temperature` (unknown) |
| Guest Bedroom | `light.home_house_first_floor_guest_bedroom_device_light_side_lamp_2` (unavailable) |
| Untitled cats view | both feeder `manual_feed` selects (missing), both feeder `food_level` sensors (unavailable) |

The four feeder refs are dead because the PetLibro feeder entities were renamed: the working
replacements exist under `*.living_room_cat_feeder_*` (verified: `binary_sensor.living_room_cat_feeder_food_dispenser`,
`binary_sensor.living_room_cat_feeder_food_status`, `button.living_room_cat_feeder_manual_feed`,
`sensor.living_room_cat_feeder_today_s_feeding_times`, all present; the two `problem` binary sensors
read `off` = OK).

### 2.3 Registered frontend resources (10) and whether anything can use them

| Resource | Usable today? |
|---|---|
| `lovelace-mushroom/mushroom.js` (v5.2.2) | Yes — 6 mushroom cards + 2 template badges in use. **Conflicts with ↓** |
| `lovelace-mushroom-better-sliders/mushroom.js` | **The duplicate.** Full stale copy of mushroom; both register the same custom elements → `CustomElementRegistry` double-define errors (found independently by SQ-104 and SQ-106). Remove (§5.1). |
| `mushroom-strategy` | Unused (no strategy dashboards configured). Remove. |
| `ha-floorplan/floorplan.js` | Unused today — **keep**: it is the natural renderer for SQ-107's SweetHome3D-derived dashboard. |
| `lovelace-badge-card/badge-card.js` | Unused; upstream (`thomasloven/lovelace-badge-card`) last pushed 2024-08 and native badges cover it. Remove. |
| `hassio-trash-card/trashcard.js` | **Unusable**: trash-card needs a waste calendar/schedule source and this instance has **zero `calendar.*` entities**. Upstream dormant since 2025-03. Remove (revisit only if a waste calendar is ever added). |
| `travel-time-card/travel-time-card.js` | **Unusable**: no travel-time sensors exist (no Waze/HERE integration; only the card's own `update.*` entity). Remove or add a Waze Travel Time integration first. |
| `better-miflora-card/better-miflora-card.js` | **Unusable**: zero `plant.*` entities (openplantbook is installed but exposes 1 non-plant entity). Upstream dormant since 2024-09. Remove. |
| `fr24_card/fr24_card.js` | Redundant with ↓, and upstream (`fratsloos/fr24_card`) last released 2023-11, last pushed 2025-05. Remove. |
| `flightradar24/flightradar24-card.js?v=v2.1.0` | Ships with the working `flightradar24` integration (`sensor.flightradar24_current_in_area` = 0, live). Keep — this is the one FR24 card to use on the Ops dashboard. |

So of 10 resources: **2 keep** (mushroom, flightradar24-card), **1 keep-for-SQ-107** (ha-floorplan),
**7 remove** (better-sliders is the urgent one; the other six are dead weight that will silently rot).

### 2.4 What actually works (the raw material for §7)

- **Light groups (the design's backbone):** 13 working `light.group_light_*` entities — living room,
  bedroom, kitchen (3: counter/overhead/all), office, entrance, backyard, outside, hallway, guest
  bedroom, Zach's desk, living-room MQTT. These pre-aggregate the house without needing area data.
- **Climate:** exactly one thermostat, `climate.device_climate_hallway_thermostat` (ecobee).
  Room temperature sensors that work: hallway thermostat, living-room + bedroom ecobee remote
  sensors, office presence sensor + Awair, gym presence sensor, downstairs presence sensor.
  Air quality: two Awairs (office, bedroom) with PM2.5/temp/humidity.
- **Security:** `lock.device_lock_front_door_lock`, `lock.device_lock_front_gate_lock` (both
  `locked`), door sensors for front door, front gate, garage house door. Doorbell/UniFi cameras are
  currently **unavailable** — the only working cameras are the two cat cameras.
- **Presence:** `person.zach`, `person.el`; Bermuda room-level: `sensor.zach_phone_iphone_16_pro_max_bluetooth_area`
  (= "Living Room" at measurement) and `sensor.liz_iphone_home_location_area` (= "Gym"). Bermuda
  global health: `sensor.bermuda_global_active_proxy_count` = 6, `sensor.bermuda_global_visible_device_count` = 83.
  Note: the "506 active presence entities" from the audit are dominated by per-beacon distance
  sensors; the *person-level* signal is these two `_area` sensors, already used well by the badges.
- **Energy:** Sense mains: `sensor.energy_usage_2` (W, `measurement`, live at ~1.4 kW),
  `sensor.daily_usage_2` (kWh, `device_class: energy`, `state_class: total` with `last_reset` —
  **valid Energy-dashboard grid source**), monthly/bill variants; ~195 working Sense per-device
  sensors (ML-named: "Light 1", "TV/Monitor", "Device 2"…); 3 TP-Link energy outlets with proper
  `total_increasing` kWh (microwave, water dispenser, toaster oven); 16 UniFi PDU per-outlet power
  sensors (rack gear, live values).
- **Water:** Droplet meter: `sensor.droplet_f8ec_flow_rate`, `sensor.droplet_f8ec_water`
  (`device_class: water`, `state_class: total`, gal — valid Energy-dashboard water source; note it
  read a small negative value at measurement, a known Droplet calibration wobble worth watching
  after hookup), `binary_sensor.garage_droplet_f8ec_{high,unusual}_flow_alert` (both `off`).
- **Cats:** Litter-Robot 4 (litter level 90%, waste drawer 65%, status `rdy`, pet weight 12.13 lb,
  `vacuum.…litter_box` docked) and PetLibro feeder (3 feeds today, next feed scheduled, battery
  status OK, two `problem` sensors, `button.living_room_cat_feeder_manual_feed`), plus 2 cameras.
- **Deliveries:** mail_and_packages fully working (per-carrier counts + 6 delivery cameras).
- **Ops signals:** watchman (39 missing entities), 26 pending updates, Pi-hole scripts +
  `input_boolean.pihole_blocking`, proxmoxve/nut/pi_hole sensors. Uptime Kuma binary sensors exist
  but are **all unavailable right now** (SQ-100 is restoring Uptime Kuma) — design for them, gate
  them behind visibility conditions until SQ-100 lands.

### 2.5 The spatial model and the topic clusters (SQ-113 measurement, 2026-08-17)

The four-axis IA (§6) is grounded in two live measurements taken for the revision.

**Spatial model** (area/device registries, pulled live):

| Floor (3) | Areas (19) with device counts |
|---|---|
| First Floor | Living Room 70 · Bedroom 47 · Liz's Office 37 · Kitchen 26 · Guest Bedroom 11 · Hallway 7 · Stairs 7 · Main Bathroom 2 |
| Ground Floor | **Garage 120** · Gym 16 · Downstairs Bedroom 3 · GF Living Room 3 · GF Hallway 1 |
| Outside | Entrance 14 · Backyard 9 · Roof 2 |
| *(no floor)* | Gym TV 0 · Main Bedroom 0 · Server Room 0 |

Devices with **no area: 813 of 1,188 (68%)**. Three readings that shape the design:

1. **"Outside" already exists as a floor** (Entrance/Backyard/Roof, 25 devices) — the exterior
   axis has real structure, just thin. Nothing needs creating.
2. **Garage (120 devices) is the single largest area and is an infrastructure dump, not a room.**
   Rendered as a room view it would be a wall of noise; §6 routes it to the Network & Infra topic
   view instead, with its few *physical-garage* signals (house-door lock, Droplet water meter)
   surfacing on the Security and Home views.
3. **Registry problems to resolve (flagged, not fixed — this audit is read-only):**
   **"Main Bedroom" is empty and floorless while "Bedroom" holds 47 devices** — almost certainly a
   duplicate or an incomplete rename. Same shape: **"Gym TV" (0) alongside "Gym" (16)**, and
   **"Server Room" (0)**. Which of each pair is canonical is *ambiguous from the registry alone*
   (e.g. "Main Bedroom" may be the intended final name mid-rename, or an abandoned duplicate) —
   the operator should pick; §5.4 step 1 describes the mechanics either way. Floorless empty areas
   cannot appear on any floor-organised view, and SQ-107's 3D model will bake area names in, so
   resolving them early is cheap insurance.

**Topic clusters** (second `/api/states` pull, entities matched on entity_id/friendly-name
patterns; "live" = neither `unavailable` nor `unknown`). The operator has asked for the topic
axis to be derived from what the instance actually tracks — "networks or cats or plants or any
of the topics tracked in HA" — so the clustering was measured, not assumed:

| Topic cluster | Matched | Live | Verdict for a topic view |
|---|---|---|---|
| Energy & power (sense/PDU/outlets) | 535 | 461 | **Yes** — native Energy dashboard (§5.3) + Ops rack-power section (§7.4) |
| Security & doors (locks/doors/cameras/alarms) | 357 | 227 | **Yes** (§7.7) — curated; camera bulk is unavailable UniFi Protect |
| **Cats** (feeder/litter/cat-cameras/petkit) | 274 | 183 | **Yes** (§7.3) — bigger than any room; the house's most-instrumented subject |
| Presence BLE (bermuda/ibeacon) | 492 | 216 | **Section, not dashboard** — person-level signal is 2 area sensors (on badges); the rest is per-beacon distance noise; mesh *health* lives on Ops (§7.5) |
| Network & UniFi gear (unifi/slzb/switches) | 175 | 120 | **Yes** (§7.8) — plus 321 `device_tracker` client entities (113 `home` / 135 `not_home` / 73 other) that must NOT be enumerated (see ghost caveat below) |
| Media (players/TVs/speakers) | 140 | 98 (27 live `media_player`) | **Section, not dashboard** — conditional "Now playing" on Home (§7.1); dedicated media dashboard stays rejected (§9) |
| Deliveries (mail_and_packages) | 174 | 84 | **Section** — tile(s) on Home; `sensor.imap_gmail_com_mail_packages_in_transit` verified live this pull (=1), upgrading §7.1's caveat |
| Climate & air | 69 | 58 | **Section** — one thermostat does not carry a dashboard; Home §7.1 covers it |
| Infra compute (proxmox/pihole/uptime/watchman) | 222 | 90 | **Yes, as House Ops** (§7.5) — the admin meta-topic |
| Water (Droplet) | 35 | 35 | **Folds into Energy** (§5.3) + alert tiles on Home/Security |
| Flights (FR24) | 20 | 11 | **Section** — the Ops toy corner (§7.5) |
| **Plants** (openplantbook/miflora) | 3 | 3 | **NOT BUILDABLE — do not design it.** See below. |

**Plants is a hardware/onboarding gap, not a dashboard.** All three matches are infrastructure
shells: `openplantbook.search_result` (=0), `update.openplantbook_update`,
`update.better_miflora_card_update`. There are **zero plant sensors** — the OpenPlantbook
integration and the `better-miflora-card` resource are installed with nothing reporting. This
confirms §2.3's "resources with no possible data source" finding. The operator evidently intended
plant monitoring and never completed it (or the sensors died). To light it up: actual plant
sensors (e.g. BLE Mi Flora / Xiaomi HHCC devices, or any integration exposing `plant.*` /
moisture-class sensors) must exist first — then a plants topic view becomes a candidate. Until
then a plants view would render empty, which is exactly the failure mode this audit exists to
prevent.

**PetKit caveat (SQ-104):** only 3/32 PetKit registry entities work and the integration's last
release is ~15 months old; in this pull only `update.petkit_update` and
`device_tracker.petkit_d4` are live by name. The Cats view is therefore powered by the verified
Litter-Robot, PetLibro, and Eufy cat-camera entities — **no PetKit entities are placed** (§7.3).

**UniFi ghost caveat (SQ-94):** ~172 UniFi client entities are stale (long-departed devices).
With 135 trackers reading `not_home` at measurement, a network view that enumerates clients would
be mostly ghosts. §7.8 therefore shows *infrastructure* devices individually and *clients* only
as counts (and, optionally, an `entity-filter` restricted to `state: home`).

---

## 3. Landscape: how good HA dashboards are built in 2026

### 3.1 The view system: Sections won

Sections shipped experimentally in 2024.3 and became the default view type in 2024.11
([blog](https://www.home-assistant.io/blog/2024/03/04/dashboard-chapter-1/)). It gives a 12-column
grid per section, per-card `grid_options` (columns/rows, `"full"`), `max_columns` per view for
responsive reflow across phone/tablet/desktop, **per-section and per-card `visibility` conditions**,
a badges row, and (2025.3) a heading/header card with templating
([docs](https://www.home-assistant.io/dashboards/sections/),
[2025.3 release](https://www.home-assistant.io/blog/2025/03/05/release-20253/)).
Masonry survives for legacy; Panel remains right for one full-bleed card (floor plan, map — relevant
to SQ-107); Sidebar is a niche. **Everything proposed here is Sections** — which is also what the
existing Overview already uses, so no migration is needed.

Home-screen-plus-drilldown is first-class via `subview: true`: subviews stay out of the top nav and
are reached by `navigate` tap actions, showing a back button
([views docs](https://www.home-assistant.io/dashboards/views/)).

### 3.2 Native cards have absorbed most custom-card use cases

The Tile card gained inline features, universal toggles (2025.3), then trend charts, media controls,
bar gauges, fan/valve controls (2025.9)
([2025.9 release](https://www.home-assistant.io/blog/2025/09/03/release-20259/)). The Area card was
redesigned in 2025.7 to Tile visual language with camera preview and quick controls. HA is doing this
deliberately to shrink the custom-card fragility surface (e.g. core issue
[#159553](https://github.com/home-assistant/core/issues/159553), where a core update broke casting of
HACS cards specifically). Mushroom itself has repositioned toward reusing Tile components
([mushroom #1771](https://github.com/piitaya/lovelace-mushroom/issues/1771)). On HA 2026.8.2, native
Tile covers every control this design needs. **Design rule adopted: native cards for the core; custom
cards only where a native equivalent truly doesn't exist.**

Also relevant: the experimental auto-generated **Areas dashboard** (2025.4+) builds a room-centric
dashboard from area assignments automatically — worth revisiting *after* §5.4, as a free byproduct,
not as the main dashboard.

### 3.3 Layout philosophies and known failure modes

The converging 2025–2026 community position
([representative writeup](https://www.howtogeek.com/big-mistake-on-home-assistant-dashboards/)):

- **Status-first beats room-first for the landing page** — show what is currently actionable; push
  detail one tap away (subviews). Room-centric works as the *drilldown* layer, not the entry point.
- **Split audiences into separate dashboards**, not more tabs: a lean household dashboard; a separate
  admin/system dashboard for battery levels, updates, infra. (Directly applicable: the current
  Overview mixes a Network stub into the family dashboard.)
- Documented failure modes: everything-on-one-page density; shipping the auto-generated entity dump;
  custom-card upgrade fragility (above); dashboards bound to dead entities. This instance exhibits
  the last one today, and with 38% of entities not-working it is the primary risk of any redesign.
- Conditional tooling that matters: per-card/section Visibility (native), `conditional` card
  (native), `entity-filter` card (native, state-filtered lists), and HACS `auto-entities` for
  rule-based lists with `show_empty: false`. This proposal uses only the native three; auto-entities
  is noted as an optional single add-on for the Ops dashboard (§7.5) — it is well-maintained but is
  one more moving part.

### 3.4 Kiosk / wall-panel (deferred here, but for the record)

`NemesisRE/kiosk-mode` is the community standard for chrome-stripping (see table below — the
healthiest-maintained project surveyed); Fully Kiosk Browser is the Android lockdown layer with a
first-party HA integration; iOS/iPadOS kiosk mode is now official in the Companion app (frontend
2025.2+, iOS app 2026.7+ — [docs](https://companion.home-assistant.io/docs/integrations/ios-kiosk-mode/)).
**This proposal defers all kiosk work to SQ-107**, which owns the wall/iPad surface. The 2D system
should not grow a competing wall panel.

### 3.5 Card-ecosystem maintenance evidence (checked 2026-08-17, GitHub API)

The repo has been bitten by projects alive on one metric and dead on the other, so both metrics for
everything recommended or already installed:

| Project | Last commit | Last release | Verdict |
|---|---|---|---|
| `piitaya/lovelace-mushroom` | 2026-08-14 | v5.2.2, 2026-07-31 | Alive; solo maintainer, 436 open issues (weak triage). Sections support is adaptive, with recurring sizing glitches after HA updates. **Keep at current footprint; don't expand.** |
| mushroom "better-sliders" forks | RubenKremer: 2024-04 · phischdev: 2026-05-31 | none meaningful | Forks of full mushroom **designed to replace, not coexist with, the original** — running both is the documented double-define footgun. **Remove ours.** |
| `Clooos/Bubble-Card` | 2026-08-09 | v3.2.5, 2026-07-10 | Alive, native Sections support, but breaks on nearly every major HA release (2026.3/.4/.5/.6/.8 all had incidents), patched within weeks. **Not adopting** — wrong risk profile for the only operator channel. |
| `custom-cards/button-card` | master: 2025-11-13 (dev branch 2026-06) | v7.0.1, 2025-11-13 | Stable channel stagnant ~9 months; features stuck in pre-release. **Not adopting.** |
| `thomasloven/lovelace-card-mod` | 2026-07-21 | v4.2.1, 2026-02-08 | Well-triaged (3 open issues) but by design patches frontend internals and breaks on frontend refactors. **Not adopting** — nothing here needs CSS surgery. |
| `UI-Lovelace-Minimalist/UI` | 2026-08-01 | v1.5.7, 2026-08-01 | **Officially seeking new maintainers; shutdown explicitly on the table.** Dates look alive; leadership is not. **Do not adopt.** |
| `NemesisRE/kiosk-mode` | 2026-08-17 | v14.0.2, 2026-07-25 | Exemplary: near-zero backlog, version-gated fast-follows for every breaking HA release. The one to use **when** SQ-107/kiosk work happens. |
| `thomasloven/lovelace-badge-card` | 2024-08-12 | stale | Dead; native badges superseded it. Remove resource. |
| `idaho/hassio-trash-card` | 2025-03-11 | v2.4.7, 2025-03-11 | Dormant ~17 months, 80 open issues — and unusable here (no calendars). Remove resource. |
| `fratsloos/fr24_card` | 2025-05-17 | v0.7.1, 2023-11-27 | Abandoned by release metric. Remove; keep the `flightradar24` integration's own card. |
| `roman-16/better-miflora-card` | 2024-09-30 | v1.1.1, 2024-09-30 | Dormant ~2 years, ecosystem fragmented into forks — and unusable here (no plants). Remove resource. |
| `ljmerza/travel-time-card` | 2026-08-02 | v2.0.0, 2022-04 | Code alive, releases lapsed (ships via rolling master) — but unusable here (no travel sensors). Remove unless a Waze integration is added. |

Community read on "Mushroom vs native Tile" in 2026: pragmatic split — Tile for reliability on plain
controls, Mushroom only where its look genuinely wins; the 436-issue backlog strengthens the native
case. This proposal follows that split.

---

## 4. Design position for this house

1. **Status-first landing, drilldown for detail.** Zero automations call notify, so the Home view's
   "Needs attention" section (§7.1) is the *only* proactive operator channel. It earns the top slot.
2. **Groups-first, not area-first.** 13 light groups + 1 media group already exist and work. Controls
   bind to groups; area assignment (32% coverage) stops being a blocker.
3. **Curation over enumeration.** With ~640 entities unavailable at any moment, every list is
   hand-picked from §2.4's verified inventory, and anything that can go unavailable sits behind a
   visibility condition. No card in this proposal binds to an entity that wasn't verified working.
4. **Native cards for the core; existing custom cards only at the edges.** The core Home/Energy/Ops
   views use exclusively native cards (tile, heading, thermostat, conditional, entity-filter,
   statistics-graph, picture-entity, markdown). Existing mushroom cards in room subviews stay (after
   §5.1); flightradar24-card appears only on Ops.
5. **Audience separation.** Home = household. House Ops = admin (`require_admin: true` at the
   dashboard level, and it stays out of the family's sidebar). Energy = shared but read-only by
   nature. Map stays.
6. **Complement SQ-107, don't preempt it** (§10). No wall-panel, no floorplan view in the 2D system.

---

## 5. Prerequisites (explicit, with honest effort)

### 5.1 P0 — Resolve the duplicate mushroom bundle (BLOCKER for anything mushroom)

**Problem (verified live):** both `/hacsfiles/lovelace-mushroom/mushroom.js` and
`/hacsfiles/lovelace-mushroom-better-sliders/mushroom.js` are registered resources. Better-sliders
forks are full copies of mushroom meant to *replace* it; loading both makes `CustomElementRegistry`
double-define errors, and which copy wins is load-order roulette — a 2023-era fork can silently
render your v5.2.2 cards.

**Fix (choose the modern original):**
1. HACS → Frontend → uninstall **"Mushroom better sliders"** (this removes its resource entry).
2. Settings → Dashboards → ⋮ → Resources: confirm exactly one `mushroom.js` remains. If the
   better-sliders entry lingers (orphaned manual entry), delete it there.
3. Hard-refresh clients (Ctrl-Shift-R; mobile app: Settings → Companion app → Debugging → Reset
   frontend cache).
4. Check the 6 existing mushroom cards (Living Room view + 2 template badges) still render.

**Effort: 15–30 min.** Risk: if someone specifically wanted the fork's slider behavior, those
sliders revert to stock mushroom — acceptable; the fork is unmaintained (§3.5).
**Everything else in this proposal that touches mushroom assumes this is done.**

### 5.2 P1 — Dead-ref cleanup + rescue the untitled cats view

Remove/replace the 9 broken refs (§2.2 table gives exact view locations; §7.3 gives the replacement
entities — the feeder ones have direct working equivalents). Give the untitled 10th view a real
identity: `title: Cats`, `path: cats`, `subview: true`. **Effort: 45–60 min.**

### 5.3 P2 — Configure the Energy dashboard

Settings → Dashboards → Energy:
- **Grid consumption:** `sensor.daily_usage_2` (Sense Daily Energy — verified `device_class: energy`,
  `state_class: total` with `last_reset`; auto-appears in the picker).
- **Individual devices:** start with the 3 honest TP-Link outlets
  (`sensor.device_sensor_power_{microwave,water_dispenser,toaster_oven}_outlet_today_s_consumption`)
  plus the most trustworthy Sense-detected `*_daily_energy` sensors. Add Sense devices a few at a
  time — they are ML-detected and misattribution is common; don't bulk-add all 195.
- **Water:** `sensor.droplet_f8ec_water` (verified `device_class: water`, `state_class: total`).
  Watch the first week — it read a small negative value at measurement time.
**Effort: 30–60 min, then a 24 h wait for long-term statistics to fill the graphs.**
No solar/battery/gas sources exist; leave those unset.

### 5.4 P3 (optional, scoped, **deferred**) — Area assignment triage

Full assignment of 813 area-less devices is days of tedium and **is not required by this design**.
The SQ-113 revision makes the deferral structural, not just permissible: the topic axis (§6)
needs no area data at all, so nothing in roadmap items 1–5 waits on this section. Do it when the
room axis starts expanding (roadmap item 7+). The scoped version that pays:
1. Resolve the three empty, floorless areas — **Main Bedroom (0) vs Bedroom (47)**, **Gym TV (0)
   vs Gym (16)**, **Server Room (0)**. Each empty area is almost certainly a duplicate or an
   incomplete rename, but *which name is canonical is ambiguous from the registry alone* — the
   operator should decide (keep-and-merge, or delete the empty one). Whatever the choice, end
   state: no empty floorless areas, and Server Room (if kept) gets the ground floor and the rack
   gear that currently pollutes Garage (~30 min).
2. Split `garage` (640 entities): keep vehicle/door/physical-garage devices; move rack/network/server
   devices to Server Room. Even done coarsely at the *device* level for the ~50 devices that matter,
   this is ~1–2 h.
3. Assign the ~40 remaining devices that appear on dashboards (media players, air quality, presence
   sensors currently area-less — e.g. `media_player.bedroom_kef`, `media_player.gym`). ~1 h.

Payoff: honest per-area badges, the free auto-generated Areas dashboard becomes usable, and SQ-107's
3D model gets a trustworthy area vocabulary. Do it incrementally; never as a big-bang.

---

## 6. Information architecture: four axes (revised by SQ-113)

The operator's stated IA has four axes: **(1) Overview · (2) Room-based · (3) Topic-based ·
(4) Exterior areas**. The original proposal's three dashboards are not discarded — they slot in
as a subset: *Home* is the overview axis; *Energy* and *House Ops* are two topic views. What
changes is that the topic axis becomes plural and first-class, and the exterior axis gets its own
surface instead of being a folded-away section.

**The spine of the revision (why the ordering works):** topic views bind entities by what they
are, not where they live, so they need **no area assignment** — they are how the 813 area-less
devices (68%, §2.5) become usable *today*. Room views need populated areas, so they land
*incrementally*, richest areas first. Ship the topic axis first; nothing blocks it.

### 6.1 Axis 1 — Overview (rework existing `lovelace` Home view)

Status-first landing for the household, exactly as designed in §7.1: needs-attention (the house's
only proactive operator channel — zero automations call notify), presence badges, climate, light
groups, conditional now-playing, cats summary, house vitals. Every other axis is one tap away
(topic tabs, room subviews). Verdict: **rework in place**.

### 6.2 Axis 3 — Topic-based dashboards (ship these first; no prerequisites)

Derived from the measured clusters in §2.5, not from a generic list. A topic earns a view only
when enough *live* entities exist to fill it; live counts are given so the operator can judge.

| Topic view | Live entities (cluster) | Content | Status |
|---|---|---|---|
| **Energy** (native dashboard) | 461 energy/power + 35 water | Grid via Sense `sensor.daily_usage_2`, honest per-device outlets, Droplet water | Configure, §5.3 — zero YAML |
| **Cats** | 183 | Feeder, Litter-Robot, the two Eufy cat cameras (guard mode, crying/pet detection), litter automations. **Absorbs the orphaned untitled `path: ""` view** — its rescue (§5.2) now lands here rather than as separate cleanup | Sketch §7.3 (extended) |
| **Security & Doors** | 227 matched; ~15 curated | Locks, door-open sensors, cat-camera alarm panels, water alerts. Surfaces the **garage house-door lock stuck `unknown`** (live SQ-109 finding, battery reading −100) on day one | Sketch §7.7 (new) |
| **Network & Infra** | 120 gear + client counts | UDM, switches (entrance/backyard/roof), SLZB-06 Zigbee, Pi-hole stats, Proxmox Backup Server. **This is where Garage's 120 infra devices belong** — the "Garage is not a room" answer. Client `device_tracker`s appear only as counts (ghost caveat, §2.5) | Sketch §7.8 (new) |
| **House Ops** (admin meta-topic, `require_admin`) | 90 infra-compute + watchman/updates | HA health, 26 pending updates, Uptime Kuma (visibility-gated until SQ-100), rack power (§7.4), automation liveness (SQ-109's list), Bermuda mesh health, FR24 toy | Sketch §7.5 |

Topics that are **sections, not dashboards** (real but too thin or already homed): Climate & air
(one thermostat → Home §7.1), Media (conditional Now-playing → Home; dedicated dashboard stays
rejected §9), Deliveries (tile(s) on Home), Presence (person-level = 2 badge sensors on Home;
mesh health on Ops — the 400+ per-beacon distance sensors are infrastructure, not content, though
the bermuda/ibeacon estate is clearly under-exposed and is worth a later look once SQ-112's
coverage work lands). Topic that is a **gap, not a view**: Plants (§2.5 — zero sensors; report to
operator as unfinished onboarding, do not build).

### 6.3 Axis 2 — Room-based views (incremental, richest first)

Only ~6 areas can carry a real room view today: **Living Room 70 · Bedroom 47 · Liz's Office 37 ·
Kitchen 26 · Gym 16 · Guest Bedroom 11**. These become `subview: true` drilldowns reached from
the Overview (nav bar stays ~4 tabs). Existing thin room views on the Overview consolidate per
roadmap item 7. Exemplar sketch: §7.9.

**Rooms that do NOT get their own view** (1–7 devices each), and where they surface instead:

| Area (devices) | Surfaces as |
|---|---|
| Hallway (7) | Thermostat card (§7.1 climate section — the thermostat *is* the hallway) + hallway light-group tile in the Lights section |
| Stairs (7) | Light tiles folded into the Overview Lights section |
| Main Bathroom (2) | Nothing dedicated — its devices join Bedroom's view if relevant, else Overview |
| Downstairs Bedroom (3), GF Living Room (3), GF Hallway (1) | One compact "Ground floor" section (native `area` cards) appended to the **Gym** room view — the only rich Ground Floor room |
| **Garage (120)** | **Not a room view.** Infra contents → Network & Infra topic (§7.8); physical-garage signals (house-door lock, Droplet meter/alerts) → Security (§7.7) and Home needs-attention (§7.1) |
| Gym TV (0), Main Bedroom (0), Server Room (0) | Nowhere — empty and floorless; resolve per §5.4 step 1 (ambiguity flagged in §2.5) |

This kills the "19 stub dashboards" failure mode while giving every area a stated home.

### 6.4 Axis 4 — Exterior (one view over the existing Outside floor)

"Outside" **already exists as a floor** (Entrance 14 · Backyard 9 · Roof 2 — 25 devices; §2.5).
Do not create anything; give it one consolidated **Outside** view (sketch §7.10): entrance +
backyard + outside light groups and bulbs, the sun-driven entrance automations, doorbell tiles
visibility-gated until UniFi Protect returns, and gate/entry status. Roof's two devices are a
UniFi switch (→ Network view) and the FR24 antenna (→ Ops toy corner) — the Roof "area" needs no
surface of its own. Thin but real; one view, not three.

### 6.5 Dashboard inventory after the revision

| Dashboard | Axis | Audience | Verdict |
|---|---|---|---|
| **Home** (`lovelace`) | Overview + hosts room/exterior subviews | Household | Rework in place |
| **Energy** (native) | Topic | Household | Configure (§5.3) |
| **Cats** | Topic | Household | Extend the rescued view (§7.3) |
| **Security & Doors** | Topic | Household | Build (§7.7) |
| **Network & Infra** | Topic | Zach | Build (§7.8) — may merge into House Ops as a second view if a separate dashboard feels heavy |
| **House Ops** (`require_admin`) | Topic (admin meta) | Zach | Build (§7.5) |
| **Map** | — | Household | Keep |
| media (`dashboard-media`) | — | — | **Delete** (empty stub; §9) |
| *(future)* Wall/iPad 3D | — | Wall | SQ-107 (§10) |

Note on SQ-112 (network coverage gap, in flight): its output — newly-adopted devices and possibly
new areas — slots into the Network & Infra topic view (new gear tiles) and, if it populates
areas, accelerates the room axis. Nothing here blocks on it.

---

## 7. YAML sketches (every entity verified working 2026-08-17)

Sketches are storage-mode view/card fragments, ready to paste into the raw dashboard editor or
recreate via UI. Comments mark intent.

### 7.1 Home landing view (replaces the current near-empty `Home` view)

Keeps the existing badge row verbatim (person + Bermuda-area badges with user-scoped visibility —
already the best-designed thing on the instance).

```yaml
type: sections
title: Home
icon: mdi:home
path: home
max_columns: 4
# badges: — KEEP the existing 5 badges (weather + Zach/El home-area/away pairs) unchanged.
sections:
  # ── 1. Needs attention ─────────────────────────────────────────────
  # Every card is visibility-gated; the section is invisible-but-for-the
  # heading when all is well. This is the notify channel this house
  # doesn't otherwise have.
  - type: grid
    cards:
      - type: heading
        heading: Needs attention
        heading_style: title
        icon: mdi:alert-circle-outline
      - type: tile
        entity: lock.device_lock_front_door_lock
        name: Front door unlocked
        color: red
        visibility:
          - condition: state
            entity: lock.device_lock_front_door_lock
            state_not: locked
      - type: tile
        entity: lock.device_lock_front_gate_lock
        name: Front gate unlocked
        color: red
        visibility:
          - condition: state
            entity: lock.device_lock_front_gate_lock
            state_not: locked
      - type: tile
        entity: binary_sensor.device_lock_garage_house_door_lock_open
        name: Garage house door open
        color: amber
        visibility:
          - condition: state
            entity: binary_sensor.device_lock_garage_house_door_lock_open
            state: "on"
      - type: tile
        entity: binary_sensor.garage_droplet_f8ec_high_flow_alert
        name: Water — high flow
        color: red
        visibility:
          - condition: state
            entity: binary_sensor.garage_droplet_f8ec_high_flow_alert
            state: "on"
      - type: tile
        entity: binary_sensor.living_room_cat_feeder_food_status
        name: Cat feeder — food problem
        color: amber
        visibility:
          - condition: state
            entity: binary_sensor.living_room_cat_feeder_food_status
            state: "on"
      - type: tile
        entity: sensor.device_cat_litterbox_office_litter_robot_4_waste_drawer
        name: Litter drawer nearly full
        color: amber
        visibility:
          - condition: numeric_state
            entity: sensor.device_cat_litterbox_office_litter_robot_4_waste_drawer
            above: 85
  # ── 2. Climate & air ───────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Climate & air
        icon: mdi:thermometer
      - type: thermostat
        entity: climate.device_climate_hallway_thermostat
        grid_options: {columns: 6, rows: 4}
      - type: tile
        entity: sensor.home_living_room_sensor_presence_living_room_ecobee_presence_sensor_temperature
        name: Living room
      - type: tile
        entity: sensor.device_sensor_presence_bedroom_ecobee_presence_sensor_temperature
        name: Bedroom
      - type: tile
        entity: sensor.liz_s_office_air_monitor_temperature
        name: Office
      - type: tile
        entity: sensor.device_sensor_air_quality_bedoom_awair_pm2_5
        name: Bedroom PM2.5
        features:
          - type: trend-graph   # native tile trend feature (HA ≥2025.9)
      - type: tile
        entity: fan.device_sensor_air_living_room_air_purifier_purifier
        name: Air purifier
  # ── 3. Lights (the 13 pre-built groups do the work) ────────────────
  - type: grid
    cards:
      - type: heading
        heading: Lights
        icon: mdi:lightbulb-group
      - type: tile
        entity: light.group_light_living_room_lights
        name: Living room
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_bedroom_lights
        name: Bedroom
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_kitchen_kitchen_lights
        name: Kitchen
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_office_office_lights
        name: Office
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_hallway
        name: Hallway
      - type: tile
        entity: light.group_light_guest_bedroom
        name: Guest bedroom
      - type: tile
        entity: light.group_light_entrance_entrance_lights
        name: Entrance
      - type: tile
        entity: light.group_light_outside_outside_lights
        name: Outside
      # "Lights still on" — native entity-filter card; renders nothing when all off
      - type: entity-filter
        state_filter: ["on"]
        card:
          type: glance
          title: Still on
        entities:
          - light.group_light_living_room_lights
          - light.group_light_bedroom_lights
          - light.group_light_kitchen_kitchen_lights
          - light.group_light_office_office_lights
          - light.group_light_hallway
          - light.group_light_guest_bedroom
          - light.group_light_entrance_entrance_lights
          - light.group_light_backyard_backyard_lights
          - light.group_light_outside_outside_lights
  # ── 4. Now playing (appears only while something plays) ────────────
  - type: grid
    visibility:
      - condition: or
        conditions:
          - {condition: state, entity: media_player.group_media_living_room_players, state: playing}
          - {condition: state, entity: media_player.guest_bedroom, state: playing}
          - {condition: state, entity: media_player.gym_tv, state: playing}
    cards:
      - type: heading
        heading: Now playing
        icon: mdi:play-circle
      - type: conditional
        conditions:
          - {condition: state, entity: media_player.group_media_living_room_players, state: playing}
        card:
          type: tile
          entity: media_player.group_media_living_room_players
          name: Living room
          features:
            - type: media-player-playback
            - type: media-player-volume-slider
      - type: conditional
        conditions:
          - {condition: state, entity: media_player.guest_bedroom, state: playing}
        card:
          type: tile
          entity: media_player.guest_bedroom
          features: [{type: media-player-playback}]
      - type: conditional
        conditions:
          - {condition: state, entity: media_player.gym_tv, state: playing}
        card:
          type: tile
          entity: media_player.gym_tv
          features: [{type: media-player-playback}]
  # ── 5. Cats (summary; tap through to the repaired subview §7.3) ────
  - type: grid
    cards:
      - type: heading
        heading: Cats
        icon: mdi:cat
        tap_action: {action: navigate, navigation_path: /lovelace/cats}
      - type: tile
        entity: sensor.device_cat_litterbox_office_litter_robot_4_litter_level
        name: Litter level
      - type: tile
        entity: sensor.living_room_cat_feeder_today_s_feeding_times
        name: Feeds today
      - type: tile
        entity: sensor.living_room_cat_feeder_next_feed_time
        name: Next feed
  # ── 6. House vitals snapshot ───────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: House
        icon: mdi:home-lightning-bolt
        badges:
          - type: entity
            entity: sensor.energy_usage_2       # live W, whole home
      - type: tile
        entity: sensor.energy_usage_2
        name: Power now
        features: [{type: trend-graph}]
      - type: tile
        entity: sensor.daily_usage_2
        name: Energy today
      - type: tile
        entity: sensor.droplet_f8ec_flow_rate
        name: Water flow
      - type: tile
        entity: sensor.imap_gmail_com_mail_packages_in_transit
        name: Packages inbound
```

> Entity note: `sensor.imap_gmail_com_mail_packages_in_transit` was originally the one entity above
> without an individually captured state sample. **Resolved by the SQ-113 pull:** verified live
> (state `1` at measurement). No caveat remains.

### 7.2 Pattern: making unavailability invisible

The three native mechanisms used throughout, in order of preference:

```yaml
# 1. Per-card visibility (Sections) — card renders only when meaningful
visibility:
  - {condition: state, entity: lock.device_lock_front_door_lock, state_not: locked}

# 2. Guard against the entity itself dying (the 640-unavailable problem):
visibility:
  - {condition: state, entity: binary_sensor.uptimekuma_truenas, state_not: unavailable}

# 3. entity-filter for lists — only members in the given states render, and
#    the whole card disappears when none match (see "Still on" above).
```

Rule of thumb applied in this doc: **controls** (lights, locks, thermostat) stay visible even when
unavailable — a greyed tile is honest signal that a device fell over. **Informational** cards
(Uptime Kuma rows, alerts) hide when unavailable so the dashboard never looks broken by default.

### 7.3 The Cats topic view (absorbs the untitled `path: ""` orphan)

Cats are the house's most-instrumented subject — 183 live entities (§2.5), more than any single
room. This is a first-class **topic view**, not pet-corner cleanup: the §5.2 rescue of the
orphaned untitled view folds into building this, rather than being a separate task. Powered by
Litter-Robot 4 + PetLibro + the two Eufy cat cameras; **no PetKit entities are placed** (3/32
working, §2.5 caveat). Note `sensor.living_room_cat_feeder_battery_level` read `low` at the
SQ-113 pull — the battery tile below is already earning its slot.

```yaml
type: sections
title: Cats
icon: mdi:cat
path: cats
subview: true          # reached from the Home cats section, not the nav bar
max_columns: 3
sections:
  - type: grid
    cards:
      - type: heading
        heading: Feeder
        icon: mdi:food-drumstick
      # REPLACES dead binary_sensor.device_cat_feeder_…_{white,green}_food_level:
      - type: tile
        entity: binary_sensor.living_room_cat_feeder_food_dispenser
        name: Dispenser
      - type: tile
        entity: binary_sensor.living_room_cat_feeder_food_status
        name: Food level
      - type: tile
        entity: sensor.living_room_cat_feeder_today_s_feeding_quantity_weight
        name: Fed today (g)
      - type: tile
        entity: sensor.living_room_cat_feeder_last_feed_time
        name: Last feed
      - type: tile
        entity: sensor.living_room_cat_feeder_next_feed_time
        name: Next feed
      # REPLACES dead select.device_cat_feeder_…_manual_feed:
      - type: tile
        entity: button.living_room_cat_feeder_manual_feed
        name: Feed now
        color: green
      - type: tile
        entity: sensor.living_room_cat_feeder_battery_level
        name: Feeder battery
  - type: grid
    cards:
      - type: heading
        heading: Litter-Robot
        icon: mdi:paw
      - type: tile
        entity: vacuum.device_cat_litterbox_office_litter_robot_4_litter_box
        name: Litter box
      - type: tile
        entity: sensor.device_cat_litterbox_office_litter_robot_4_litter_level
        name: Litter level
      - type: tile
        entity: sensor.device_cat_litterbox_office_litter_robot_4_waste_drawer
        name: Waste drawer
      - type: tile
        entity: sensor.device_cat_litterbox_office_litter_robot_4_pet_weight
        name: Last weight
  - type: grid
    cards:
      - type: heading
        heading: Cameras & guard
        icon: mdi:cctv
      - type: picture-entity
        entity: camera.camera_cat_room
        camera_view: auto
      - type: picture-entity
        entity: camera.camera_living_room_cat_feeder_camera
        camera_view: auto
      - type: tile
        entity: alarm_control_panel.camera_cat_room
        name: Cat room guard
      - type: tile
        entity: alarm_control_panel.camera_living_room_cat_feeder_camera
        name: Feeder cam guard
      # Detection events surface only when firing — silent otherwise:
      - type: tile
        entity: binary_sensor.camera_cat_room_crying_detected
        name: Crying detected
        color: red
        visibility:
          - {condition: state, entity: binary_sensor.camera_cat_room_crying_detected, state: "on"}
      - type: tile
        entity: binary_sensor.camera_cat_room_pet_detected
        name: Pet spotted
        visibility:
          - {condition: state, entity: binary_sensor.camera_cat_room_pet_detected, state: "on"}
  # ── Litter automations (SQ-109 companion) ──────────────────────────
  # All four are currently OFF. SQ-109 recommends deleting the three
  # duplicate light-alert automations and replacing "CLAUDE 2.0" with a
  # notification, plus adding a "litter waste ≥80%" alert. Keeping their
  # states visible here means the eventual cleanup is observable, and a
  # re-enabled survivor is obvious.
  - type: grid
    cards:
      - type: heading
        heading: Litter automations
        icon: mdi:robot
      - type: entities
        entities:
          - automation.new_litter_box
          - automation.claude_litter_box
          - automation.claude_litter_box_light
          - automation.claude_2_0_litter_box_waste_level_light_alert
```

> Domain note: `button.living_room_cat_feeder_manual_feed` reads `unknown` until first pressed —
> that is normal for the stateless `button` domain, not a broken entity (its device and siblings are
> verified live). The four automation entities above were verified present (all `off`) at the
> SQ-113 pull; after SQ-109's cleanup lands, prune this list to the survivors.

### 7.4 Energy: configuration first, then one optional view

The Energy dashboard itself is configuration, not YAML (§5.3). The `energy-*` cards only render once
prefs exist; `statistics-graph` works regardless. One optional "Power" section for House Ops (rack
power lives here, not on the family dashboard):

```yaml
- type: grid
  cards:
    - type: heading
      heading: Rack power
      icon: mdi:server
    - type: statistics-graph          # native long-term-stats chart
      title: Whole home (7d)
      chart_type: line
      period: hour
      days_to_show: 7
      stat_types: [mean, max]
      entities:
        - sensor.energy_usage_2
      grid_options: {columns: full, rows: 6}
    - type: tile
      entity: sensor.smartpower_pdu_outlet_13_outlet_power
      name: PDU 13
      features: [{type: trend-graph}]
    - type: tile
      entity: sensor.smartpower_pdu_outlet_8_outlet_power
      name: PDU 8
    - type: tile
      entity: sensor.smartpower_pdu_outlet_17_outlet_power
      name: Rack lights
    - type: tile
      entity: sensor.smartpower_pdu_outlet_11_outlet_power
      name: Garage AP PoE
```

### 7.5 House Ops dashboard (new, admin-only)

Registered as a new storage dashboard (`url_path: house-ops`, `require_admin: true`). One view to
start; the existing Overview "Network" stub retires in its favor.

```yaml
type: sections
title: House Ops
icon: mdi:wrench
max_columns: 4
sections:
  # ── HA health ────────────────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Home Assistant
        icon: mdi:home-assistant
      - type: tile
        entity: sensor.watchman_missing_entities
        name: Broken refs (watchman)
        color: red
        tap_action: {action: more-info}
      - type: markdown
        title: Pending updates
        content: >-
          {% set pending = states.update | selectattr('state','eq','on') | list %}
          **{{ pending | count }} updates pending**{% for u in pending[:15] %}

          - {{ u.name }}{% endfor %}
        grid_options: {columns: 6, rows: auto}
      - type: markdown
        title: Unavailable entities
        content: >-
          {{ states | selectattr('state','eq','unavailable') | list | count }}
          unavailable / {{ states | list | count }} total
  # ── Infra (Uptime Kuma; every row hides until SQ-100 restores it) ───
  - type: grid
    cards:
      - type: heading
        heading: Infrastructure
        icon: mdi:server-network
      - type: tile
        entity: binary_sensor.uptimekuma_truenas
        name: TrueNAS
        visibility:
          - {condition: state, entity: binary_sensor.uptimekuma_truenas, state_not: unavailable}
      - type: tile
        entity: binary_sensor.uptimekuma_proxmox
        name: Proxmox
        visibility:
          - {condition: state, entity: binary_sensor.uptimekuma_proxmox, state_not: unavailable}
      - type: tile
        entity: binary_sensor.uptimekuma_home_assistant
        name: HA (external probe)
        visibility:
          - {condition: state, entity: binary_sensor.uptimekuma_home_assistant, state_not: unavailable}
      - type: tile
        entity: binary_sensor.uptimekuma_pihole_baremetal
        name: Pi-hole
        visibility:
          - {condition: state, entity: binary_sensor.uptimekuma_pihole_baremetal, state_not: unavailable}
  # ── DNS / Pi-hole (the only two scripts in the house, put to work) ──
  - type: grid
    cards:
      - type: heading
        heading: Pi-hole
        icon: mdi:pi-hole
      - type: tile
        entity: input_boolean.pihole_blocking
        name: Blocking
      - type: tile
        entity: script.pi_hole_disable
        name: Pause blocking
        color: amber
      - type: tile
        entity: script.pi_hole_enable
        name: Resume blocking
        color: green
  # ── Automations: what is actually running (SQ-109 companion) ───────
  - type: grid
    cards:
      - type: heading
        heading: Automations
        icon: mdi:robot
      - type: markdown
        title: Liveness
        content: >-
          {% set autos = states.automation | list %}
          {% set on = autos | selectattr('state','eq','on') | list %}
          **{{ on | count }} enabled / {{ autos | count }} total**


          Recently triggered:{% for a in (on | sort(attribute='attributes.last_triggered', reverse=true))[:8] %}

          - {{ a.name }} — {{ relative_time(a.attributes.last_triggered) if
            a.attributes.last_triggered else 'never' }} ago{% endfor %}
        grid_options: {columns: 6, rows: auto}
      - type: entity-filter
        state_filter: ["off"]
        card: {type: entities, title: Disabled}
        entities:  # populate from SQ-109's dormant list once curated
          - automation.example_placeholder   # ← replace with SQ-109 output
  # ── Presence mesh health ────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Bermuda BLE mesh
        icon: mdi:bluetooth
      - type: tile
        entity: sensor.bermuda_global_active_proxy_count
        name: Active proxies
      - type: tile
        entity: sensor.bermuda_global_visible_device_count
        name: Visible devices
      - type: tile
        entity: sensor.zach_phone_iphone_16_pro_max_bluetooth_area
        name: Zach is in
      - type: tile
        entity: sensor.liz_iphone_home_location_area
        name: El is in
  # ── Toy corner: flights overhead (working integration + its card) ──
  - type: grid
    cards:
      - type: heading
        heading: Overhead
        icon: mdi:airplane
      - type: custom:flightradar24-card     # the integration-shipped card (keep);
        # remove the abandoned fratsloos fr24_card resource per §2.3
        grid_options: {columns: full, rows: auto}
```

Two flagged non-verified items in this sketch, on purpose: the `automation.example_placeholder`
(SQ-109 owns the dormant list) and the `custom:flightradar24-card` options block (card config schema
comes from its docs at build time; the integration and its sensors are verified live). If a
rule-based "all disabled automations" list is wanted instead of a maintained list, HACS
`auto-entities` is the one justified new dependency — decide at build time, not before.

### 7.6 Verification note for the SQ-113 additions

Every entity ID in §7.7–§7.10 (and the §7.3 extensions) was verified against the SQ-113
`/api/states` pull of 2026-08-17: present, and live unless the sketch explicitly gates or marks
it (the doorbell entities and the bedroom fan are the deliberate exceptions, per the §7.2
honesty rule). Where a live value was itself the finding, it is quoted (garage lock `unknown`,
feeder battery `low`, PBS memory 91.5%).

### 7.7 Security & Doors topic view (new)

The curation of the 227-live security cluster (§2.5): locks + door sensors + cat-cam guard +
water alerts. UniFi Protect cameras/doorbell are all unavailable today, so they are
visibility-gated, not omitted — they light up when Protect returns. The **garage house-door lock
is stuck `unknown`** (SQ-109's live find, battery reporting −100): per the §7.2 rule the lock
tile stays visible (greyed = honest), and a red alert tile names the condition explicitly.

```yaml
type: sections
title: Security
icon: mdi:shield-home
path: security
max_columns: 3
sections:
  # ── Attention ──────────────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Attention
        icon: mdi:alert-circle-outline
      - type: tile
        entity: lock.device_lock_garage_house_door_lock
        name: Garage house-door lock unresponsive
        color: red
        visibility:
          - {condition: state, entity: lock.device_lock_garage_house_door_lock, state: unknown}
      - type: tile
        entity: binary_sensor.garage_droplet_f8ec_high_flow_alert
        name: Water — high flow
        color: red
        visibility:
          - {condition: state, entity: binary_sensor.garage_droplet_f8ec_high_flow_alert, state: "on"}
      - type: tile
        entity: binary_sensor.garage_droplet_f8ec_unusual_flow_alert
        name: Water — unusual flow
        color: amber
        visibility:
          - {condition: state, entity: binary_sensor.garage_droplet_f8ec_unusual_flow_alert, state: "on"}
  # ── Locks (controls stay visible even when dead — §7.2 rule) ───────
  - type: grid
    cards:
      - type: heading
        heading: Locks
        icon: mdi:lock
      - type: tile
        entity: lock.device_lock_front_door_lock
        name: Front door
      - type: tile
        entity: lock.device_lock_front_gate_lock
        name: Front gate
      - type: tile
        entity: lock.device_lock_garage_house_door_lock   # unknown today; greyed = honest
        name: Garage house door
  # ── Doors & gates ──────────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Doors
        icon: mdi:door
      - type: tile
        entity: binary_sensor.device_lock_front_door_lock_open
        name: Front door
      - type: tile
        entity: binary_sensor.device_lock_front_gate_lock_open
        name: Front gate
      - type: tile
        entity: binary_sensor.device_lock_garage_house_door_lock_open
        name: Garage house door
  # ── Camera guard (the two working cameras; Protect gated below) ────
  - type: grid
    cards:
      - type: heading
        heading: Cameras
        icon: mdi:cctv
      - type: tile
        entity: alarm_control_panel.camera_cat_room
        name: Cat room guard
      - type: tile
        entity: alarm_control_panel.camera_living_room_cat_feeder_camera
        name: Feeder cam guard
      # UniFi Protect doorbell — appears only once the integration recovers:
      - type: tile
        entity: binary_sensor.device_camera_doorbell_doorbell_2
        name: Doorbell
        visibility:
          - {condition: state, entity: binary_sensor.device_camera_doorbell_doorbell_2, state_not: unavailable}
      - type: tile
        entity: binary_sensor.device_camera_doorbell_person_detected
        name: Person at door
        visibility:
          - {condition: state, entity: binary_sensor.device_camera_doorbell_person_detected, state_not: unavailable}
```

### 7.8 Network & Infra topic view (new)

Where the Garage-the-infra-dump's 120 devices actually belong (§6.3). Infrastructure devices get
individual tiles; **clients appear only as counts** — with ~172 stale UniFi client entities
(SQ-94) and 135 trackers reading `not_home` at measurement, enumerating clients renders ghosts.
Live oddity worth carrying to the view: Pi-hole's ads-blocked percentage read **0** while
`input_boolean.pihole_blocking` is `on` — the stats tiles below make that contradiction visible
instead of hiding it. PBS memory was at **91.5%** at measurement; its tile gets a color.

```yaml
type: sections
title: Network & Infra
icon: mdi:lan
path: network
max_columns: 4
sections:
  # ── Gateway ────────────────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Gateway
        icon: mdi:router-network
      - type: tile
        entity: sensor.pibbs_udm_state
        name: UDM state
      - type: tile
        entity: sensor.pibbs_udm_cpu_utilization
        name: UDM CPU
        features: [{type: trend-graph}]
      - type: tile
        entity: sensor.pibbs_udm_memory_utilization
        name: UDM memory
      - type: markdown
        title: Clients
        content: >-
          {% set t = states.device_tracker | list %}
          **{{ t | selectattr('state','eq','home') | list | count }} home** /
          {{ t | count }} tracked
          (stale-client cleanup pending — SQ-94)
  # ── Switches (the exterior trio doubles as Outside-floor infra) ────
  - type: grid
    cards:
      - type: heading
        heading: Switches
        icon: mdi:switch
      - type: tile
        entity: sensor.device_network_network_switch_entrance_network_switch_state
        name: Entrance switch
      - type: tile
        entity: sensor.device_network_network_switch_backyard_network_switch_state
        name: Backyard switch
      - type: tile
        entity: sensor.roof_switch_flex_state
        name: Roof switch
  # ── Zigbee coordinator ─────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Zigbee (SLZB-06)
        icon: mdi:zigbee
      - type: tile
        entity: binary_sensor.slzb_06_internet
        name: Internet
      - type: tile
        entity: binary_sensor.slzb_06_ethernet
        name: Ethernet
      - type: tile
        entity: sensor.slzb_06_core_chip_temp
        name: Core temp
        features: [{type: trend-graph}]
  # ── DNS (stats; the control tiles live on House Ops §7.5) ──────────
  - type: grid
    cards:
      - type: heading
        heading: Pi-hole
        icon: mdi:pi-hole
      - type: tile
        entity: sensor.server_service_pi_hole_dns_queries
        name: DNS queries today
      - type: tile
        entity: sensor.server_service_pi_hole_ads_percentage_blocked
        name: Blocked %
      - type: tile
        entity: sensor.server_service_pi_hole_seen_clients_2
        name: Clients seen
  # ── Backup server ──────────────────────────────────────────────────
  - type: grid
    cards:
      - type: heading
        heading: Proxmox Backup Server
        icon: mdi:server
      - type: tile
        entity: binary_sensor.proxmox_backup_server_status
        name: PBS up
      - type: tile
        entity: sensor.proxmox_backup_server_cpu_usage
        name: PBS CPU
      - type: tile
        entity: sensor.proxmox_backup_server_memory_usage_percentage
        name: PBS memory
        color: amber          # 91.5% at measurement — worth watching
        features: [{type: trend-graph}]
```

If a separate Network dashboard feels heavy in practice, this lands unchanged as a second view on
House Ops (`require_admin` already matches the audience) — the section content is identical
either way.

### 7.9 Room-view exemplar: Bedroom (the pattern for the ~6 rich rooms)

One worked example for the room axis; Living Room / Office / Kitchen / Gym / Guest Bedroom follow
the same shape from their own verified inventories. Rooms get: their light group, their climate
signals, their media, their oddities — and nothing imported from other rooms.

```yaml
type: sections
title: Bedroom
icon: mdi:bed
path: bedroom
subview: true
max_columns: 3
sections:
  - type: grid
    cards:
      - type: heading
        heading: Comfort
        icon: mdi:thermometer
      - type: tile
        entity: sensor.device_sensor_presence_bedroom_ecobee_presence_sensor_temperature
        name: Temperature
      - type: tile
        entity: sensor.device_sensor_air_quality_bedoom_awair_pm2_5
        name: PM2.5
        features: [{type: trend-graph}]
      # fan.device_climate_fan_bedroom_fan is a real bedroom control that is
      # unavailable today (documented broken ref, §2.2). Per the §7.2 rule it
      # MAY be placed greyed-out as honest signal; placed here commented-out
      # so the view starts clean — uncomment when the fan is fixed.
      # - type: tile
      #   entity: fan.device_climate_fan_bedroom_fan
      #   name: Ceiling fan
  - type: grid
    cards:
      - type: heading
        heading: Lights
        icon: mdi:lightbulb-group
      - type: tile
        entity: light.group_light_bedroom_lights
        name: Bedroom lights
        features: [{type: light-brightness}]
  - type: grid
    cards:
      - type: heading
        heading: Media
        icon: mdi:television
      - type: tile
        entity: media_player.bedroom_sony
        name: TV
        features: [{type: media-player-playback}]
      - type: tile
        entity: media_player.bedroom_kef
        name: KEF speakers
        features: [{type: media-player-volume-slider}]
      - type: tile
        entity: media_player.home_bedroom_media_player_appletv
        name: Apple TV
```

### 7.10 Exterior axis: the Outside view (new)

One view over the existing Outside floor (Entrance 14 · Backyard 9 · Roof 2). Roof's two devices
route elsewhere (switch → §7.8, FR24 → §7.5), so this view is Entrance + Backyard + the outside
light groups, with the dead UniFi Protect doorbell gated until it returns.

```yaml
type: sections
title: Outside
icon: mdi:tree
path: outside
max_columns: 3
sections:
  - type: grid
    cards:
      - type: heading
        heading: Lights
        icon: mdi:outdoor-lamp
      - type: tile
        entity: light.group_light_entrance_entrance_lights
        name: Entrance
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_backyard_backyard_lights
        name: Backyard
        features: [{type: light-brightness}]
      - type: tile
        entity: light.group_light_outside_outside_lights
        name: All outside
      - type: tile
        entity: light.home_outside_entrance_device_light_overhead_bulb_1
        name: Entrance bulb 1
      - type: tile
        entity: light.home_outside_entrance_device_light_overhead_bulb_2_2
        name: Entrance bulb 2
      - type: tile
        entity: light.home_outside_backyard_device_light_flood_light_2
        name: Backyard flood
  - type: grid
    cards:
      - type: heading
        heading: Gate & door
        icon: mdi:gate
      - type: tile
        entity: lock.device_lock_front_gate_lock
        name: Front gate lock
      - type: tile
        entity: binary_sensor.device_lock_front_gate_lock_open
        name: Gate open
      # UniFi Protect doorbell — gated until the integration recovers:
      - type: tile
        entity: binary_sensor.device_camera_doorbell_doorbell_2
        name: Doorbell
        visibility:
          - {condition: state, entity: binary_sensor.device_camera_doorbell_doorbell_2, state_not: unavailable}
  - type: grid
    cards:
      - type: heading
        heading: Schedules
        icon: mdi:sun-clock
      - type: tile
        entity: switch.automation_backyard_on_off
        name: Backyard schedule
      - type: entities
        title: Entrance sun automations
        entities:
          - automation.entrance_on_sun
          - automation.entrance_off_sun
          - automation.trigger_entrance_lights_switch
```

---

## 8. Ranked, incremental roadmap (revised: topic views first)

Each item is deliberately evening-sized. The revision's ordering rule: **the topic axis (items
1–5) has zero prerequisites beyond item 1's hygiene and needs no area data; the room axis (item
7+) lands incrementally as areas are populated.** Item 1 stays first not as a blocker to the
topic views (they are native-card-only) but because 90 minutes of hygiene stops the current
Overview lying.

| # | Evening | Axis | Work | Payoff |
|---|---|---|---|---|
| 1 | ~90 min | hygiene | **§5.1 mushroom dedupe** + **§5.2 dead-ref cleanup** + delete the empty `dashboard-media` stub + rescue the untitled cats view into the **Cats topic view (§7.3)** | Overview stops lying; mushroom becomes deterministic; the biggest topic (183 live entities) gets its surface the same evening |
| 2 | 30–60 min | topic | **§5.3 Energy dashboard config** (+ 24 h passive wait) | Highest-value new surface on the instance, ~zero YAML, no prerequisites |
| 3 | 2–3 h | topic | **§7.7 Security & Doors** + **§7.10 Outside** views | The garage-lock `unknown` problem becomes visible on day one; the exterior axis exists; both are pure verified-native-card builds |
| 4 | 2–3 h | overview | **§7.1 Home landing rebuild** (badges kept, six sections) | The daily-driver view; the house finally has an attention channel |
| 5 | 2–3 h | topic | **§7.5 House Ops** + **§7.8 Network & Infra** (as one dashboard with two views, or two dashboards — §7.8 note); retire the Overview "Network" stub | Admin concerns leave the family dashboard; Garage's 120 infra devices get their real home; SQ-100/SQ-109/SQ-112 outputs get somewhere to land |
| 6 | 15 min | hygiene | Resource cleanup: remove the 6 dead resources from §2.3 (keep mushroom, flightradar24-card, ha-floorplan) | Less rot; faster loads; no zombie cards to trip over later |
| 7 | 1–2 h each | room | Room views incrementally, richest first: Living Room → Bedroom (§7.9 exemplar) → Office → Kitchen, as `subview: true`; fold thin-room content per §6.3's table; nav bar settles at ~4 tabs | The room axis grows only where there is something to show — no stub views, ever |
| 8 | 1–2 h | spatial | **§5.4 area triage** steps 1–2 (resolve the empty/floorless trio per operator's canonical-name call, garage split) | Honest areas; unblocks the free auto-Areas dashboard; the area-name contract SQ-107 needs |
| 9 | ongoing | — | §5.4 step 3 + Sense device naming as Energy data accumulates; Gym + Guest Bedroom room views when worth it | Compounding accuracy |
| — | deferred | — | Kiosk/wall-panel (SQ-107), Bubble/Minimalist/button-card adoption (rejected §3.5), travel-time + trash-card revival (blocked on integrations that don't exist), full 813-device area assignment, plants view (blocked on hardware that doesn't exist, §2.5), standalone Presence view (under-exposed BLE estate; revisit after SQ-112) | — |

---

## 9. Explicitly rejected options

- **UI-Lovelace-Minimalist** — maintainers are publicly seeking replacements with shutdown on the
  table. Betting the only operator UI on it would be the exact look-alive-by-one-metric trap this
  ticket warns about.
- **Bubble Card / button-card / card-mod as new dependencies** — Bubble breaks on effectively every
  major HA release (patched fast, but this house updates monthly and has no notify channel to
  announce breakage); button-card's stable channel has stalled; card-mod is CSS surgery this design
  doesn't need. All three are fine projects; none earns a slot *here*.
- **One dashboard view per area (19 views)** — 68% of devices have no area, three areas are empty,
  and most areas have <35 working entities. It would be a hall of broken mirrors.
- **A dedicated media dashboard** — 27 working media players, but control happens on remotes/apps;
  the conditional "Now playing" section covers the dashboard-shaped need. Delete the stub.
- **trash-card / travel-time-card / better-miflora-card revival** — each is missing its data source
  entirely (no calendars, no travel sensors, no plants). Cards don't create data.
- **A Plants topic view** — explicitly requested territory, honestly not buildable: zero plant
  sensors exist; the three matching entities are integration shells (§2.5). Reported to the
  operator as a hardware/onboarding gap with what would light it up, rather than shipped as a
  guaranteed-empty view.
- **Enumerating network clients on the Network view** — ~172 stale UniFi client entities (SQ-94)
  and 135 `not_home` trackers at measurement mean a client list is mostly ghosts. Counts +
  infrastructure tiles only (§7.8) until the stale-client cleanup happens.
- **A room view for Garage** — 120 devices, single largest area, and an infrastructure dump. Its
  contents are topic material (§7.8); its physical-garage signals surface on Security (§7.7) and
  Home (§7.1).
- **mushroom-strategy auto-generation** — auto-generated dashboards from 32%-assigned areas would
  enumerate exactly the garbage this proposal exists to curate away.

## 10. Coexistence with SQ-107 (3D iPad dashboard)

The 2D system (this doc) and the 3D SweetHome3D/floorplan surface are siblings with different jobs:
2D = control + status + admin on phone/desktop; 3D = ambient spatial display on the wall/iPad.
To make SQ-107 easier, this work should:

1. **Keep `ha-floorplan` registered** (already installed; §2.3) — it is SQ-107's likely renderer.
2. **Deliver §5.4 steps 1–2** — a consistent area/floor vocabulary (no floorless areas, garage split)
   is the shared contract between the 2D badges, the auto-Areas dashboard, and the 3D model's rooms.
   Agree on area *IDs* before the SweetHome3D room names are baked in.
3. **Keep curation in group entities** (`light.group_light_*`) — the 3D surface can bind rooms to the
   same groups instead of re-curating raw entities.
4. **Not build any wall/kiosk view** — when SQ-107 lands, `NemesisRE/kiosk-mode` (§3.5, healthy) plus
   the official iOS kiosk mode are the chrome-stripping tools of choice.
5. Leave the Home "Needs attention" section as the alerting source of truth; the 3D view can mirror
   it (e.g. tint rooms with active alerts) rather than inventing a second alert model.

---

## Appendix A — measurement snapshot

Raw pulls (states, registries, lovelace configs, resources, energy prefs) were captured to the
session scratchpad on 2026-08-17 against HA 2026.8.2 via the read-only admin token
(`homeassistant-token` secret, `kube-prometheus-stack` namespace). Headline numbers: 3,439 state
entities / 621 unavailable / 694 unknown; 12,641 registry entities; 1,188 devices (375 with area);
19 areas, 3 floors; 3 dashboards; 10 Lovelace resources; energy prefs empty; watchman missing = 39;
pending updates = 26. Re-measure before executing roadmap items 3+ if more than a few weeks pass —
entity IDs on this instance have a demonstrated habit of drifting (the feeder renames of §2.2).

**SQ-113 re-measurement (2026-08-17, second read-only `/api/states` pull):** 3,439 states / 620
unavailable / 700 unknown; watchman = 38; pending updates = 26; 41 automations (34 on); 27 live
`media_player` entities. Topic-cluster counts in §2.5 come from this pull. All 57 working entity
IDs from the original doc re-verified working; every entity ID added by the revision (§7.3
extensions, §7.7–§7.10) verified present with the states quoted. The spatial model in §2.5
(floors/areas/device counts, 813/1188 area-less) was measured the same day via the WS registry
endpoints. Notable live states captured: `lock.device_lock_garage_house_door_lock` = `unknown`,
`sensor.living_room_cat_feeder_battery_level` = `low`,
`sensor.proxmox_backup_server_memory_usage_percentage` = 91.5,
`sensor.server_service_pi_hole_ads_percentage_blocked` = 0 (while
`input_boolean.pihole_blocking` = `on` — flagged on §7.8, not diagnosed here).
