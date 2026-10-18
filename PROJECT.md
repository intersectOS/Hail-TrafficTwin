# TrafficTwin Jeddah: Open-Source City Traffic Digital Twin, Policy Lab and Emergency Decision Support

> Working name. This file is the project brief for building with Claude Code.
> Put it in the repo root and build milestone by milestone. `CLAUDE.md` holds the engineering rules from section 10.
> Version 2 (15 Oct 2026): city = all of Jeddah; adds the policy lab (remote work, staggered hours, calendars, public transport, pricing); demand moves from random trips to an activity-based synthetic population.

## 1. What we are building

An open-source **traffic digital twin of Jeddah** that:

1. Simulates a full **24-hour day** of traffic for the whole city on a real road network, with demand generated from a **synthetic population** (people, households, jobs, schools) rather than random trips.
2. Answers **policy questions** by changing the population's daily plans or the network and re-running the day: *what if 30% of office workers work from home three days a week? what if school and government hours are staggered? what does a Ramadan weekday look like? what if a bus line or a congestion cordon is added?*
3. Lets a user inject **events** (accident, rain and flooding, motorcade, evacuation) into a **microscopic focus window** (a district simulated at the individual-vehicle level) and see the impact.
4. Acts as a **strategist**: generates and ranks candidate response plans (emergency-vehicle routes, signal preemption, closures, evacuation phasing) by testing them in the simulator.
5. Shows everything in an interactive **3D (2.5D) web view** with a time slider and baseline-versus-scenario comparison.

The AI **recommends**; a human **approves** high-impact actions. Every recommendation is explainable and logged.

## 2. Why two tiers (the key architecture decision)

Policy questions are city-wide; emergency questions are street-level. One engine serves both, at two resolutions:

| Tier | Scope | Engine mode | Used for | Output granularity |
|---|---|---|---|---|
| **A: City** | All of Jeddah (urban area, roughly 1,500 km²) | SUMO **mesoscopic** (`--mesosim`), up to ~100x faster than microscopic per the SUMO docs | 24-hour baseline, policy what-ifs, day-type calendars, network-wide KPIs | Edge speeds, flows and densities every 5 minutes; per-trip travel times |
| **B: Focus window** | Any district of 3 to 25 km², cut out of Tier A | SUMO **microscopic** | Accidents, rain, motorcade, emergency routing, evacuation, strategist | Individual vehicles at 1 s |

The two tiers are linked by SUMO's own tools: Tier A produces city routes; `cutRoutes.py` keeps every route that touches the window and computes entry times, so the window sees realistic through-traffic without simulating the rest of the city. A saved Tier B state is the starting point for the strategist's what-ifs.

Two caveats to design around from day one:

- **Meso fidelity.** A June 2026 paper revisiting SUMO's mesoscopic model (Eissfeldt 2004) finds it only partially follows LWR kinematic-wave theory, models queue spillback incompletely, and tends to *underestimate* congestion. Policy deltas (baseline vs policy) are more trustworthy than absolute values. M2 therefore includes a **meso-versus-micro fidelity test** on one district, and every policy report states the tier it was run on.
- **Compute budget.** Rough sizing: Jeddah's 2022 census population is 3,712,917 (GASTAT); at an assumed 1.2 to 1.5 vehicle trips per person per day that is 4.5 to 5.5 million vehicle trips. Tier A runs the full population in meso if a 24-hour run fits in about 1 to 2 hours on an Apple-silicon laptop; otherwise it runs a 25% population sample with `--scale` and capacity scaling (standard practice in MATSim-style models). Measure in M2; do not assume.

Full-city **microscopic** simulation is a stretch goal, not a requirement.

## 3. Goals (v1)

- G1: A 24-hour Tier A baseline for all of Jeddah runs end to end from one command and produces KPIs.
- G2: Any policy from the library can be applied in YAML and its impact reported against the baseline: peak-hour delay, vehicle-kilometres, vehicle-hours, mean speed, peak spreading, CO2, per-district effects.
- G3: Any event from the library can be injected at a chosen time into a focus window, with impact shown against the window baseline.
- G4: For an emergency-vehicle trip, the system returns the top 3 strategies with predicted travel time and a plain-language reason for each.
- G5: The 3D viewer plays back Tier A (city flow heatmap) and Tier B (vehicles) with a time slider and baseline-versus-scenario comparison.
- G6: Everything runs locally on a laptop with open-source dependencies and public data only.

## 4. Non-goals (v1)

- Calibration to real counts. No Jeddah count or OD data is available yet; v1 is synthetic and **clearly labelled as such**. The calibration path (M8) is built but idle.
- Live control of real traffic signals or any real-world actuation. Simulation only.
- Photorealistic 3D (CARLA, Unreal). Optional CARLA bridge later.
- Commercial traffic APIs (Google, TomTom, HERE). Their data cannot be redistributed; v1 ships adapters only.
- Full mode-choice modelling. v1 uses simple fixed or logit mode shares; a proper discrete-choice model is P2.
- Pedestrian microsimulation and freight logistics. P2.

## 5. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Simulator | **Eclipse SUMO 1.28+** (released 8 Oct 2026; `pip install eclipse-sumo`) | Mesoscopic for Tier A, microscopic for Tier B. EPL-2.0 dependency; not vendored. |
| Control API | **TraCI** / **libsumo** | Event injection, `saveState` / `loadState`, strategist forks. Check each TraCI call used in Tier B also behaves in meso before using it in Tier A. |
| Network | **OpenStreetMap** (Geofabrik Saudi Arabia extract, clipped to a Jeddah polygon) + `netconvert` | ODbL; attribute in NOTICE. Expect missing lane counts and one-way tags; keep a reviewed fix list in `data/osm/fixes/`. |
| Population and demand | **Own Python module `sim/population/`**: synthetic population + activity chains + policy transforms, emitting SUMO trips/plans | SUMO's `activitygen` is too limited; ActivitySim and MATSim are heavier than v1 needs. MATSim remains the P2 option if a full activity-based model with replanning is wanted. |
| Routing | `duarouter` with iterative assignment (`duaIterate.py`) for the baseline; time-dependent `routeSampler.py` for calibration later | Deterministic with `--seed`. |
| Backend | **Python 3.11+, FastAPI**, WebSocket streaming | Runs, scenarios, policies, strategies, results. |
| Strategist | Python: candidate generator + parallel what-if runs (`multiprocessing`) | Optional RL later (Gymnasium wrapper). |
| Frontend | **React + deck.gl + MapLibre** | `PathLayer`/`LineLayer` coloured by speed for Tier A; `TripsLayer` for Tier B vehicles; extruded OSM buildings. |
| Config | YAML: scenarios, policies, day types, vTypes | One file per scenario or policy; sources for every behavioural assumption. |
| Storage | Parquet (trajectories, edge data), DuckDB (queries), SQLite (runs, decision log) | No server database in v1. |
| Packaging | Docker Compose + `uv` for Python | One command to run the stack. |
| Licence | **Apache-2.0** for code; demo data under ODbL/CC-BY as inherited | Add a NOTICE file (OSM, GASTAT open data terms, SUMO). |

## 6. Jeddah model: data and day types

### 6.1 Public data sources (v1, synthetic demand)

| Need | Source | Status |
|---|---|---|
| Road network, buildings, land use, POIs, bus route relations | OpenStreetMap (Geofabrik `saudi-arabia-latest.osm.pbf`) | Public |
| City and district population | GASTAT 2022 census (Jeddah 3,712,917); district breakdown from Jeddah Municipality / open.data.gov.sa where published | Public; district level to verify |
| Employment by sector, labour-force participation | GASTAT labour force survey; GLMM tables | Public, regional not district: distribute by OSM land use |
| Schools and universities | OSM `amenity=school/university` + MoE lists if open | Public |
| Public transport | Jeddah bus network: 14 routes, 91 new buses, operated by Jeddah Transport Company with SAPTCO (May 2025); marine taxi pilot | OSM relations / manual GTFS-like YAML; check for an official GTFS feed |
| Prayer times (drive timing of mosque trips and the Friday peak) | Computed (e.g., `adhan` library) for the simulated date | Public |
| Calendar (Ramadan, Eid, Hajj, school terms) | Umm al-Qura calendar + MoE academic calendar | Public |

Everything not sourced is an **assumption** and lives in YAML with a `source:` or `assumption:` field so it can be replaced when real data arrives.

### 6.2 Synthetic population (`sim/population/`)

1. **Zones:** Jeddah districts (hay) as TAZs, with population from the census, jobs from OSM land use and POI density, school seats from OSM schools.
2. **Persons:** age group, status (worker / student / homemaker / other), sector (government, private office, retail and hospitality, health, education, industrial and port, logistics and ride-hail), car availability, household.
3. **Activity chains:** home-work-home, home-school-home, home-work-other-home, shopping and leisure tours (evening-heavy), mosque trips keyed to prayer times, airport trips. Start times drawn from per-segment distributions.
4. **Mode:** car (own, driven), ride-hail or taxi, bus (where a route exists within 500 m of both ends), walk for short trips. Fixed shares by segment in v1; logit in P2.
5. **Output:** SUMO trips with departure time, origin and destination edge, vType; plus a Parquet table of persons and plans so policies can be applied to *people*, not to trips.

### 6.3 Day types (Jeddah-specific time-of-day profiles)

| Day type | Key behaviours (assumptions to encode and tune) |
|---|---|
| Regular weekday (Sun-Thu) | Early school start (about 06:30-07:00) creates the sharpest morning peak; government hours roughly 07:30-14:30; private offices 08:00/09:00-17:00/18:00; retail split shifts with a long evening peak; malls and Corniche busy until midnight; Thursday evening heavier. |
| Friday | No school; prayer-time surge around midday; afternoon and evening leisure travel; Corniche and Tahlia peaks. |
| Saturday | Weekend leisure; retail evening peak. |
| Ramadan weekday | Reduced work hours (government about 10:00-15:00); pre-iftar rush (about 60-90 min before maghrib); late-night activity until suhoor; morning peak flattened. |
| Umrah / Hajj season | Added inbound flows: KAIA airport, Makkah highway, Haram-bound coaches; hotel districts near the Corniche and Al Balad busier. |
| Rain / flood day | Overlay: rain presets plus closure of known flood-prone underpasses and wadis (Jeddah's 2009 and 2011 floods are the reference events). |

## 7. Policy lab (`sim/policies/`)

A policy is a YAML file that declares **transforms** applied to the population, plans or network *before* the run. Policies compose (a Ramadan day with 30% remote work and a new bus line is one scenario). Each run reports KPIs against the matching baseline day type.

| Policy | Transform | Parameters | Notes and realism caveats |
|---|---|---|---|
| **Remote / hybrid work** | Remove the work tour for a share of workers in eligible sectors on the simulated day; optionally add an induced non-work tour with probability *p* (remote workers still make trips) | share by sector, days per week, eligible sectors, induced-trip probability | Report peak-hour delay, VKT and CO2 change; "induced trips" parameter matters and is documented |
| **Staggered hours** | Shift start-time distributions per segment (schools, government, private, retail) by a signed offset or spread | offsets in minutes, spread | Models the school-peak question directly |
| **Calendar day type** | Select the day-type profile (section 6.3) | day type, date (prayer times computed) | Ramadan and Friday are policies in the sense that they re-time the whole population |
| **Public transport line** | Add a bus line (stops, headway, hours) via `ptlines2flows.py`; shift a share of car trips within the catchment to bus | route geometry, headway, catchment radius, shift share | Fixed shift share in v1; no mode-choice model |
| **Road pricing (cordon)** | Polygon cordon; crossing trips get a routing penalty (edge weights) and a demand elasticity (share suppressed or re-timed) | polygon, charge, hours, elasticity | Simplified; label as indicative |
| **Network change** | Permanent closure, lane add or removal, new link, signal-plan change | edge IDs, lanes, timing | Uses `netconvert` edits or additional files |
| **Ride-hail / taxi share** | Change the ride-hail share and empty-cruising factor | share, deadhead factor | Jeddah has a large ride-hail fleet; empty kilometres are an assumption |

**Policy report (per run):** city KPIs (mean delay, mean speed, VKT, VHT, throughput, peak-hour and daily CO2 from SUMO's emission output), **peak spreading** (share of trips in the top hour), **per-district** winners and losers (equity view), and the ten most-relieved and most-worsened corridors. Baseline-versus-policy on the same seed.

**Parameter sweeps (P1):** `python -m sim.policies.sweep --policy remote_work --param share=0.1:0.5:0.1` runs the grid in parallel and plots the response curve ("what remote share halves the morning peak?").

## 8. Repository layout

```
traffictwin/
├── PROJECT.md                   # this file
├── CLAUDE.md                    # engineering rules (section 10)
├── LICENSE                      # Apache-2.0
├── NOTICE                       # OSM (ODbL), GASTAT, SUMO attributions
├── docker-compose.yml
├── pyproject.toml               # uv-managed
├── data/                        # gitignored except data/demo and data/osm/fixes
│   ├── osm/                     # raw extracts + fixes/ (reviewed OSM corrections, committed)
│   ├── census/                  # GASTAT and municipal tables (public, committed if licence allows)
│   ├── counts/                  # detector or count CSVs (private; never committed)
│   └── demo/                    # small open demo window + demand (committed)
├── sim/
│   ├── network/                 # build_city.py (OSM -> Jeddah .net.xml), build_window.py (cut a focus window), fixes.py
│   ├── population/              # zones.py, synthesize.py, activities.py, modes.py, export_trips.py
│   ├── daytypes/                # YAML profiles + prayer-time + calendar helpers
│   ├── policies/                # YAML policies, transforms.py, sweep.py
│   ├── vtypes/                  # driver and vehicle type distributions
│   ├── scenarios/               # YAML scenario definitions (events) + loader
│   ├── events/                  # accident.py, weather.py, flood.py, motorcade.py, evacuation.py, emergency.py
│   ├── runner.py                # run baseline / policy / scenario at tier A or B; save outputs
│   ├── link.py                  # Tier A -> Tier B handoff (cutRoutes wrapper, state save)
│   ├── fidelity.py              # meso-vs-micro comparison on a window
│   └── metrics.py               # KPIs, policy report, emissions
├── strategist/
│   ├── candidates.py            # generate candidate plans
│   ├── evaluate.py              # fork from saved state, run what-ifs in parallel
│   ├── rank.py                  # score + rank + explanation strings
│   └── decision_log.py          # append-only, hash-chained log
├── api/                         # FastAPI app (runs, policies, scenarios, stream, strategies)
├── web/                         # React + deck.gl viewer
├── docs/                        # architecture, assumptions register, data notes
└── tests/
```

## 9. Core features and acceptance criteria

### 9.1 City network builder (P0)

- Input: the Geofabrik Saudi Arabia PBF plus a Jeddah polygon; output: a SUMO network with traffic lights, lane counts and speed limits, a buildings GeoJSON, and a zone (district) GeoJSON.
- `netconvert` options to start from: `--geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.discard-simple --roundabouts.guess --keep-edges.by-vclass passenger,bus,emergency,truck --remove-edges.isolated`. Drop service roads and parking aisles in Tier A; keep them in Tier B windows.
- A fix list (`data/osm/fixes/*.yaml`) applies reviewed corrections (missing lanes, wrong one-way, broken ramps) reproducibly. Upstream real fixes to OSM when confident.
- **Done when:** `python -m sim.network.build_city` produces a `.net.xml` that SUMO loads without errors, a meso smoke run of random trips finishes with teleports below 0.5% of vehicles, and the viewer shows roads, districts and buildings.

### 9.2 Synthetic population and 24-hour demand (P0)

- As in section 6.2, with day types from 6.3. Deterministic for a given seed.
- Baseline assignment: `duaIterate.py` for a fixed number of iterations on Tier A; routes cached by (network hash, population hash, day type, seed).
- **Done when:** a 24-hour Tier A baseline for a regular weekday finishes in the measured budget, trip-length and departure-time distributions are plotted and sanity-checked against published Saudi travel-survey ranges (documented in `docs/assumptions.md`), and the run is reproducible bit for bit with the same seed.

### 9.3 Focus windows and the tier link (P0)

- `python -m sim.network.build_window --name tahlia --polygon ...` cuts a window network; `sim/link.py` runs `cutRoutes.py` with the Tier A routes and exit times so through-traffic enters the window at realistic times.
- Default windows shipped as YAML: Tahlia / Al Andalus / Al Hamra (commercial core), KAIA-to-city corridor (Madinah Road, Prince Majid Road), Al Balad and southern Corniche (narrow streets, flood-prone), KAU / Al Faisaliyah (school peaks).
- **Done when:** a window baseline runs microscopically from a Tier A route set, and the window's edge flows match Tier A's for the same edges within a stated tolerance.

### 9.4 Meso fidelity test (P0, small)

- `python -m sim.fidelity --window tahlia` runs the same window in meso and micro and reports delay, speed and queue differences by hour.
- **Done when:** the report exists and its caveats are quoted in the policy report template.

### 9.5 Driver and vehicle mix (P0)

- vType distributions for normal, slow, aggressive, trucks, buses, emergency (`vClass=emergency`, bluelight device: Tier B only) and convoy vehicles. Mix percentages per scenario YAML.

### 9.6 Policies (P0)

- Section 7. Each policy has a YAML schema, a transform with unit tests on the demo population, and a demo file.
- **Done when:** `python -m sim.runner --policy remote_work_30 --daytype weekday` produces the policy report against the baseline, and `remote_work`, `staggered_hours`, `daytype`, `pt_line` and `network_change` all have demo files; `road_pricing` and `ridehail_share` may land in P1.

### 9.7 Scenario events (P0, Tier B)

| Event | Implementation |
|---|---|
| Accident | Close N lanes (or the edge) for a duration; optional rubbernecking slowdown opposite |
| Rain | Scale speed factor, accel and decel, min gap and reaction time across vTypes; light, heavy and storm presets with sources |
| Flood | Storm preset plus closure of flood-prone underpasses and wadi crossings from a reviewed list |
| Motorcade | Rolling closures along a route plus a convoy of priority vehicles |
| Evacuation | Mass departures from a zone polygon to exit points; optional contraflow; phased release |
| Emergency trip | Emergency vehicle A to B at time T, with or without strategist support |

- **Done when:** each event has a demo YAML and `python -m sim.runner --scenario X --window Y` outputs KPIs against the window baseline.

### 9.8 Metrics (P0)

- City (Tier A): mean delay, mean speed, VKT, VHT, throughput, peak spreading, CO2 and NOx (SUMO HBEFA emission classes), per-district KPIs, top corridors.
- Window (Tier B): plus queue lengths, gridlock detection, emergency travel time versus free-flow and versus no-strategy baseline, evacuation clearance times (50%, 90%, 100%) and bottleneck edges.
- Saved per run as JSON and Parquet, with seed, config hash and SUMO version.

### 9.9 Strategist (P0, Tier B)

Given a situation (saved window state, event, objective):

1. **Generate candidates:** k-shortest routes with time-dependent travel times, signal preemption along each, optional short closures, rescue-lane enforcement; for evacuations, phasing orders and contraflow sets.
2. **Evaluate:** fork from the saved state (`saveState` / `loadState`) and run each candidate in parallel for a horizon.
3. **Rank:** by the objective with side-effect penalties (network delay added elsewhere).
4. **Explain:** plain-language reasons, for example "Route B is 4.2 min faster because junction J-112 is gridlocked; preempting 6 signals adds 38 vehicle-hours of delay elsewhere."
5. **Classify actions:** auto-eligible (reversible, low impact) versus approval required (closures, evacuation orders).

- **Done when:** for the demo accident, 3 ranked options return within 60 s on a laptop and the best beats the no-strategy baseline.

### 9.10 Decision log (P0)

- Append-only records: situation snapshot ID, candidates, scores, recommendation, human decision, timestamp, and a hash of the previous record.

### 9.11 3D viewer (P0)

- MapLibre base map, extruded buildings, district boundaries.
- Tier A: edges coloured by speed or delay, animated by 5-minute bins; district choropleth for policy effects; baseline-versus-policy toggle and difference mode.
- Tier B: animated vehicles (`TripsLayer`) coloured by type and speed; events and closures as overlays.
- Time slider over 24 hours, play, pause, speed; strategist panel with approve button.
- **Scale:** Tier A streams aggregated edge bins (not vehicles), so the city view stays light; Tier B plays back Parquet trajectories.

### 9.12 Data adapters (P1)

- Interfaces for count CSVs (`detector_id, edge_id, hour, count`), travel-time CSVs, and stubbed commercial API adapters for calibration only. Private data never committed.

### 9.13 Future (P2)

- MATSim as an alternative Tier A engine with proper activity replanning and mode choice.
- RL agent for signal control and preemption (Gymnasium wrapper).
- CARLA co-simulation bridge for street-level 3D.
- Pedestrians, freight and port traffic (Jeddah Islamic Port), live data ingestion.

## 10. Engineering rules (copy into `CLAUDE.md`)

- Python 3.11+, type-hinted, linted with ruff, tested with pytest; TypeScript strict in `web/`. Dependencies via `uv`.
- Every module has a CLI entry point (`python -m ...`) and a test on the small demo window; city-scale runs are never part of CI.
- Determinism: every run takes a `seed`; outputs record seed, config hash, population hash, network hash and SUMO version.
- Every behavioural assumption (start times, rain factors, induced-trip probability, mode shares) lives in YAML with a `source:` or `assumption:` field and is listed in `docs/assumptions.md`. No magic numbers in code.
- Keep simulation (`sim/`), decision logic (`strategist/`) and presentation (`api/`, `web/`) separate. Policies act on the population and network, never on the simulator at runtime; events act through TraCI at runtime.
- Prefer SUMO built-ins (`cutRoutes.py`, `duaIterate.py`, `routeSampler.py`, `ptlines2flows.py`, bluelight device, `saveState`) over reimplementations.
- Anything that only works in microscopic mode (sublane, opposite-direction driving, lane-area detectors, lane-level outputs) is confined to Tier B and asserted at config load.
- Label every result "synthetic demand, uncalibrated" until M8 says otherwise.
- No secrets in the repo or URLs; `.env` gitignored; no private or partner data committed; `data/` gitignored except `data/demo/`, `data/osm/fixes/` and licensed public tables.

## 11. Safety and publication policy

- Code, methods, the Jeddah network build, the synthetic population generator and the policy lab are **public**.
- Real-city emergency, evacuation and motorcade scenario files (specific routes, timings, critical sites) stay **private** and are shared only with the relevant authorities; the public repo ships these only on the demo window with fictional parameters.
- Simulation and decision support only; never actuates real infrastructure.
- High-impact recommendations always require human approval; every decision is logged.
- Policy results are published with their assumptions register and the "synthetic, uncalibrated" label until calibrated.

## 12. Milestones (build in this order)

1. **M0 Skeleton:** repo, `uv`, Docker, CI, licence and NOTICE, `CLAUDE.md`, demo window extract (one small district) with a tiny synthetic population.
2. **M1 Jeddah network:** city build from Geofabrik, fix list, districts GeoJSON, meso smoke run, viewer shows the city.
3. **M2 Population and baseline:** synthetic population, activity chains, regular-weekday baseline on Tier A, runtime measured, sampling decision made, meso fidelity test on one window.
4. **M3 Viewer:** Tier A edge-bin playback with a time slider; Tier B trajectory playback on the demo window.
5. **M4 Policy lab:** remote work, staggered hours, day types (Friday, Ramadan), network change, bus line; policy report; sweep tool.
6. **M5 Focus windows and events:** window cutting, tier link, accident, rain, flood, driver mix, motorcade.
7. **M6 Emergency strategist:** candidates, parallel what-ifs, ranking, explanations, decision log, viewer panel.
8. **M7 Evacuation:** zone evacuation, contraflow, phasing, clearance metrics, evacuation strategies.
9. **M8 Calibration (when data arrives):** `routeSampler.py` with counts or travel times, GEH report; stays dormant otherwise.
10. **M9 Docs and release:** README, architecture diagram, assumptions register, contribution guide, demo video.

Each milestone ends with passing tests and a runnable demo command in the README.

## 13. Open questions

- District-level population and employment: is a per-hay table published (Jeddah Municipality, open.data.gov.sa)? Fallback: distribute census totals by OSM residential building footprint area. (Data; affects M2 quality, not progress.)
- Is there an official GTFS feed for the Jeddah bus network? Fallback: OSM route relations. (Data; M4 `pt_line`.)
- Trips per person per day and mode shares for Jeddah: any published travel survey? Until found, use documented assumptions and expose them in the sweep tool. (Data; M2.)
- Remote-work eligibility by sector: which sectors count, and what induced-trip probability? (Stakeholder; defaults acceptable for M4.)
- Strategist objective weights (emergency time vs network delay)? (Stakeholder; defaults acceptable for M6.)
- Later data partner (Jeddah Municipality, Transport General Authority, Civil Defence)? (Blocking for M8 only.)

## 14. First prompt for Claude Code

> Read PROJECT.md. Set up milestones M0 and M1: create the repo structure in section 8, `uv` and Docker setup, CI, `CLAUDE.md` with the engineering rules from section 10, NOTICE with OSM and SUMO attribution, and a demo window extract. Implement `sim.network.build_city` for Jeddah from the Geofabrik Saudi Arabia extract with a Jeddah polygon, the reproducible OSM fix-list mechanism, the districts GeoJSON, and a meso smoke run with random trips that reports teleports and runtime. Add tests on the demo window and a README command that builds the city network and runs the smoke test. Stop after M1 and summarise what was built, the measured runtime and network size, and what is next.
