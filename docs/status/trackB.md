# Track B status (windows, events, strategist, evacuation)
All results: **synthetic demand, uncalibrated**.

## M5 Focus windows and events — in progress (2026-10-16)
Decisions (taken without questions, per prompts/_common.md):
- B-D-001 `sim/network/build_window.py` is not a Track B file. The service-road window build lives in
  `sim/link.py` (`python -m sim.link window --name <w>`): it calls `build_window.cut_window` on the
  city net (edge ids identical to Tier A), then grafts the window's service / living-street roads
  from OSM (window type map `sim/network/types/window.typ.xml`) by splitting the city edges they
  attach to. Split parts get deterministic ids (`<city id>` keeps the first part, `<city id>.s<k>`
  the rest) and an edge map `<w>.edgemap.json` (city edge -> window edge sequence) so cut Tier A
  routes are rewritten exactly. Integration may fold this into `build_window` later.
- B-D-002 Tier A routes for the link: the M1 smoke route set (`runs/smoke-A-s1-5b8a19d3-ab76d081`,
  random trips, 0-3600 s) re-simulated in meso with `--vehroute-output.exit-times` so `cutRoutes.py`
  uses Tier A exit times. Track A's population routes replace it later through the same CLI.
- B-D-003 Window artefacts (gitignored): `data/windows/<w>/<w>.net.xml`, `<w>.rou.xml` (cut routes,
  sorted by depart), `<w>.edgemap.json`, `<w>.window.json`. The committed `demo` window keeps
  `data/demo/demo.net.xml` + `demo.trips.xml` (random trips) so tests stay offline.
- B-D-004 `sim/schemas.py` is Track A's; scenario and vType pydantic models live in
  `sim/scenarios/schema.py` and `sim/vtypes/schema.py`; validation CLI `python -m sim.scenarios validate <file>`.
- B-D-005 `data/` is gitignored; `data/jeddah_flood_sites.yaml` (asked for by the brief) is
  force-added (`git add -f`), it is public literature only.
- B-D-006 PROJECT.md section 11: event files ship only with fictional parameters (times, durations,
  motorcade route) on the Tahlia window and are labelled so.
- B-D-007 Flood sites: `data/jeddah_flood_sites.yaml` has 25 sites (13 underpasses, 5 wadi
  crossings, 7 road segments; 11 high, 6 medium, 8 low confidence) from public press and papers on
  the 2009, 2011, 2015 and 2017 floods; locations checked against OSM. Only FS-001 (King Abdullah
  Rd / Madinah Rd tunnel) is pinned exactly for the reference events. These are publicly reported
  locations, not a critical-site inventory, so the file is committed (PROJECT.md section 11 read
  as covering response plans and non-public sites). Its `radius_m` defaults are assumption
  A-event-flood-radius (registered in docs/assumptions-trackB.md).
- B-D-008 Tahlia bbox east edge moved to lon 39.190 (23.8 km2 measured) to contain FS-009, the King Fahd
  Rd / Tahlia St underpass (flooded 2017), so the flood demo closes a high-confidence site.
- B-D-009 Windows (`python -m sim.link window|cut|tls|check`): tahlia 23.8 km2, kaia_corridor 21.9
  (polygon), al_balad 17.0, kau_faisaliyah 19.7 (covers KAU / Al Jamiah only: OSM puts Al
  Faisaliyyah about 9 km from KAU, beyond one 3-25 km2 window; a separate window can be added).
- B-D-010 Tahlia first failed the 9.3 flow check (GEH<5 on 79.3 % of 420 edges, total ratio 0.637)
  because the netconvert-default program at the signalled at-grade level of the Madinah Rd / Tahlia
  interchange (OSM: Madinah Rd on a bridge, Tahlia in a tunnel, links signalled) gives the main right
  turn 6 s of a 90 s cycle, while Tier A meso only adds a red-time penalty. Decision: Tier B windows
  load Webster-retimed programs (`tlsCycleAdaptation.py`, A-link-009) from `<w>.tls.add.xml`; the
  city net is untouched. Result: all four windows pass (tahlia 90.2 % / 0.910, narrow margin;
  kaia_corridor 100 % / 0.992; al_balad 100 % / 0.995; kau_faisaliyah 100 % / 0.997). A reviewed
  program for that cluster (separate right-turn phases) is the real fix; left open.
- B-D-011 Tier A exit-time run (meso, seed 1, run to 14,400 s so every vehicle finishes): 18,001
  vehicles, 35.9 s wall, 26 teleports in the demand hour (0.14 %) but 202 over the whole run
  (1.12 %, mostly hour 2); hot spots `:cluster_2191210167_...`, `:6178528486`, `:9556669830` are
  fix-list candidates for the network owner.
- B-D-012 Scenario baseline = same demand, vType mix, seed and step loop, keeping probe events
  (emergency trips) and dropping disruptive events, so an emergency trip is compared with the same
  trip without the incident (emergency_tahlia: 94 s vs 70 s baseline vs 47.3 s free flow).
- B-D-013 Gridlock rules: jam teleports count only as >= 10 in one 300 s bin (A-kpi-004), and the
  sustained-halt share is a halted majority (A-kpi-001 raised 0.3 -> 0.5), because the tahlia baseline
  (a normal loaded hour) already reaches 0.44 halted at signals and queues (highest single reading). No demo scenario trips
  it; the flood peaks at 0.49. Detector margin is small; revisit with population demand.
- B-D-014 Motorcade closures are junction holds (all other movements disallowed except vip and
  emergency) from convoy ETA - 120 s to last vehicle + 30 s; closing route edges trapped vehicles
  already on the corridor. Convoy vClass `vip`. Both runs use `--collision.mingap-factor 0`.
- B-D-015 `sim/link.py` writes repo-relative paths even under the symlinked `data/jeddah`; window
  and Tier A outputs built before this fix still carry absolute paths (gitignored, regenerated on
  the next build).

### M5 summary — 2026-10-16
Built: four windows (tahlia, kaia_corridor, al_balad, kau_faisaliyah) with service roads grafted onto
the city cut (`sim/link.py window`); Tier A exit-time run and cutRoutes link with edge-map rewrite
and Webster-retimed window signals (`tier-a`, `cut`, `tls`); flow check (`check`); vType library and
mixes (`sim/vtypes/`); scenario schema, validator and assumption-register generator
(`sim/scenarios/`); TraCI events accident, rain, flood, motorcade, emergency_trip (`sim/events/`);
`python -m sim.runner --scenario <id> --window <w> --seed <n>` (additive) with baseline + scenario
in parallel, FCD/tripinfo/edgeData/timeseries to Parquet (FCD XML deleted), window KPIs (delay,
speed, VKT, VHT, queues, gridlock, emergency TT vs free flow and vs baseline, convoy) and
`runs/<id>/scenario_report.{json,md}`; `data/jeddah_flood_sites.yaml` (25 sourced sites);
`docs/events.md`; register `docs/assumptions-trackB.md` (114 rows).
Measured: flow check pass on all four windows (tahlia GEH<5 90.2 % of 420 edges, total ratio 0.910;
others 100 %, 0.99+). Tahlia window 10,074 edges / 3,888 junctions / 7 TLS, 4,597 cut vehicles;
baseline 3,652 inserted, mean delay 97.8 s, 13 teleports (0.34 % of 3,855 loaded). Scenario mean delay deltas:
accident +5.7 %, heavy rain +23.3 %, flood +123.8 %, motorcade -11.2 % (not interpretable),
emergency +4.8 % with the ambulance at 2.0x free flow. About 190-205 s wall per scenario (emergency 119 s)
(baseline and scenario in parallel). accident_tahlia run twice (lead and verifier): identical KPIs.
Tests: 79 pass (about 30-60 s on the shared machine); ruff clean.
Could not verify: rain-effect citations (Agarwal et al. 2005, Rakha et al. 2008, HCM 2010
Exhibit 10-15) and AASHTO wet deceleration, quoted from memory and marked unverified; flood-site
locations beyond OSM matching; gridlock detection on a real gridlocked run (unit-tested only).
Open: reviewed signal program for the Madinah Rd / Tahlia cluster (tahlia link margin is thin);
motorcade KPI for held traffic; link_assumptions.yaml is kept in step with link.yaml by hand;
Tier A exit run 1.12 % teleports over 4 h (hot spots for the network owner); an Al Faisaliyyah
window; fold the service-road graft into build_window at integration.
Next: M6 Emergency strategist — (1) save Tier B state at the emergency dispatch time and fork
what-ifs with loadState; (2) candidates: k-shortest time-dependent routes, signal preemption along
each, rescue-lane enforcement; (3) rank against the no-strategy baseline from `emergency_tahlia`.
M5: done

## M6 Emergency strategist — 2026-10-16
Decisions (taken without questions, per prompts/_common.md; details in docs/strategist.md):
- B-D-016 Window clock: t=0 is 08:00 of the weekday demo hour, so `emergency_tahlia_0830` dispatches
  at 1800 s. The scenario lives in `strategist/scenarios/` (sim/scenarios is read-only in M6);
  `strategist.run` resolves ids there first, then in `sim/scenarios/`. Fictional: crash on
  `44795819#33` (1 of 2 lanes, from 1500 s, 20 min), ambulance `44795819#21` -> `44796463#1`.
  One lane, not both, so rerouting, preemption and rescue lane all compete (no strategy 173 s,
  3.7x free flow).
- B-D-017 Snapshot = scenario events without the strategist trip, run to T, `saveState` with
  `--save-state.rng`; cached under `runs/strategist/snapshots/<key>` (key = event plans, window,
  seed, T, vTypes, options, net/demand/additional hashes). Measured on SUMO 1.28: the state keeps
  vehicles, TraCI-added routes, RNG and signal program/phase, and loses lane permissions, lane
  speeds and vType changes, so events active at T are re-dispatched after `loadState` and the
  closed lane is asserted. Active rain/flood/motorcade/other emergency trips at T are refused.
- B-D-018 Candidates: Yen k=3 routes (overlap <= 60 %, cost <= 3x best) on ambulance free-flow time
  x congestion measured over the 300 s before T ("time-dependent" = measured at T, no forecast);
  per route: route only / + preemption / + preemption + rescue lane; one side-entry hold option
  (approval_required); no-strategy = default fastest route, no interventions. 9 what-ifs on tahlia.
- B-D-019 Preemption: from 250 m before the stop line, 3 s yellow, then the ambulance's links green,
  program and phase restored after. Rescue lane is a proxy (leftmost continuing lane reserved for
  vClass emergency where >= 2 lanes stay open), not SUMO's bluelight corridor, which needs the
  sublane model the state was not built with.
- B-D-020 Horizon 300 s (not arrived = 2x horizon). Score = 1/s ambulance + 10 s per added
  background veh-h + 5 s per held junction + 1 s per preempted signal (`strategist/weights.yaml`,
  `--weights`). Top 3 takes the best option per distinct route first.
- B-D-021 Classification: rerouting auto_eligible; preemption / rescue lane auto_eligible while
  added delay <= 2 veh-h and <= 6 signals; closures always approval_required. Nothing is applied by
  `strategist.run`; `strategist.approve` is the only path (auto_eligible is a label, not auto-apply).
- B-D-022 Explanations: only measured facts (each number registered with its source field);
  "because" only when the option is measured faster, and an action is named as a cause only when
  the same route without it was measured slower (its own saving is quoted). Added after the
  verifier noted the rescue lane was credited loosely.
- B-D-023 Decision log: `runs/strategist/decisions.sqlite`, sha256 over canonical JSON with
  `prev_hash` (genesis = 64 zeros), UPDATE/DELETE blocked by triggers; `python -m strategist.log
  verify|show`; one decision per recommendation; approve refuses a broken chain or changed state.
- B-D-024 M6 assumptions (A-strat-001..024) are a generated, test-checked block at the end of
  `docs/strategist.md` (`python -m strategist.register --check`), because
  `docs/assumptions-trackB.md` is regenerated byte for byte by `sim/scenarios/register.py`.
  Integration: add `strategist/strategist.yaml` and `strategist/weights.yaml` to its `SOURCES`.
- B-D-025 No `sim/runner.py` or `sim/events/emergency.py` change was needed.

### M6 summary — 2026-10-16
Built: `strategist/` (snapshot, fork, graph/Yen, candidates, controllers for preemption, rescue lane
and holds, parallel evaluate, rank, classify, explain, decision log, register); CLIs
`python -m strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1`,
`python -m strategist.approve <recommendation_id> [--option n] [--actor a] [--reject]`,
`python -m strategist.log verify|show`; `docs/strategist.md`; 25 strategist tests.
Measured (tahlia, seed 1, M3 Pro, load average 50-60 from other tracks): cold 29.9 s (warm-up to
1800 s 13.3 s + save 2.5 s); from the saved state 10.1-13.5 s total, evaluation of 9 what-ifs
6.6-9.1 s; within the 60 s budget. No strategy 173 s (free flow 47.4 s; 77 s of it on
`444771953#1`). Top 3: Route A + rescue lane 68 s (-105 s), Route B + preemption + rescue lane
89 s (-84 s), Route C only 95 s (-78 s); all auto_eligible; background delay changes <= 0.22 of
~27.7 veh-h (noise level). Best beats no strategy: yes. Determinism: three runs + verifier's two
runs identical (fingerprint c345c0094c51cc15); approve reproduced 68.0 s; log verify OK.
Tests: 104 pass (about 80 s under load); ruff clean. Verifier: 12/12 PASS (before the B-D-022
wording fix; full suite, CLI, approve and verify rerun after it).
Could not verify: preemption and rescue-lane parameters (no Jeddah specification found); bluelight
device behaviour without the sublane model (identical in every candidate).
Open: each what-if is one run from one state, so options close in time (ranks 2 and 3: Route C
passes the 77 s signal in 4 s on arrival timing alone) are not robustly ordered — add repeated
runs with varied RNG and report the spread; merge A-strat rows into the Track B register;
weather/motorcade re-application after load; snapshot rebuild race between concurrent runs; the
log cannot detect deletion of its newest records without an external head hash; the side-entry
hold had no measurable effect here.
Next: M7 Evacuation (zone evacuation, contraflow, phasing, clearance metrics, evacuation strategies).
M6: done

## M7 Evacuation — 2026-10-16
Decisions (taken without questions, per prompts/_common.md; details in docs/evacuation.md):
- B-D-026 The M5 schema accepts `type: evacuation` loosely and the M5 registry rejects it; neither
  file is owned by M7. `sim/events/evacuation.py` validates the event with its own strict model
  (`EvacSpec`), resolves the other events through the registry, and registers its event class in
  the worker processes it starts. `sim.runner --scenario evac_*` therefore still refuses; the M7
  commands are `python -m sim.events.evacuation run` and `python -m strategist.evacuation run`.
  Integration: map `evacuation` in `registry.EVENT_CLASSES` / `resolve_events` and route
  `sim.runner --scenario evac_*` to `sim.events.evacuation.run`. No `sim/runner.py` change.
- B-D-027 Contraflow = network edit + lane-direction trick: once per scenario the window net gets
  the reversed inbound lanes as extra median-side lanes on each corridor edge, with explicit lane
  connections (netconvert keeps loaded connections, so new lanes are otherwise unreachable),
  signals Webster-retimed on the edited net (`sim.link.retime_tls`); the extra lanes are closed
  from t = begin in every run of the scenario and opened (inbound carriageway closed to all but
  emergency, inbound traffic rerouted) after a 10 min setup. Edited nets are
  `data/windows/<w>/<w>.evac-<hash>.net.xml`; city and window nets untouched.
- B-D-028 Strategy what-ifs are full window runs from begin with light outputs, not forks of a
  saved state (flood/weather cannot be re-applied after loadState, M6 B-D-017; the strategy acts
  on vehicles that do not exist yet at the order).
- B-D-029 Candidates: screening design (each lever against no strategy, then combinations with
  balanced guidance); plan-identical candidates are dropped as equivalent.
- B-D-030 "Al Hamra window" = the `tahlia` window (its definition: Tahlia / Al Andalus / Al Hamra
  commercial core); the zone is a generic box over the Al Hamra waterfront car parks and street grid (2.06 km2 since
  B-D-036). Al
  Balad flood day uses the reviewed flood-site list unchanged: only FS-002 (King Abdullah Rd /
  King Fahd Rd underpass, 2 edges) lies inside the window; no fictional flood sites were added.
- B-D-031 M7 assumptions (A-evac-001..038, sim/scenarios/evac_settings.yaml) are a generated,
  test-checked block at the end of docs/evacuation.md (`python -m sim.events.evacuation register`)
  because docs/assumptions-trackB.md is regenerated byte for byte from a fixed source list.
  Integration: add sim/scenarios/evac_settings.yaml to `sim.scenarios.register.SOURCES`.
- B-D-032 Scale set after measuring: the first Al Hamra run (3,000 vehicles, end 5,400 s) got
  only 1,373 out in 75 min with 699 evacuee jam teleports (all to one exit through one-lane
  car-park aisles), so no clearance level was measurable. Both demos now use 2,000 vehicles and
  end 7,200 s.
- B-D-033 README is not a Track B file: the M7 demo commands are in docs/evacuation.md and below;
  integration copies them to the README.
- B-D-034 Contraflow corridors never include or close an edge inside the zone: in the first
  contraflow runs 159 evacuees starting on the inbound carriageway inside the zone could never be
  inserted. Evacuees are private cars (passenger-class members of the mix, A-evac-034): with the
  full mix 51 truck/bus evacuees could not enter car-park service roads.
- B-D-035 Noise band from one replicate of the no-strategy run (SUMO seed + 1000); background
  delay is a penalty only, and only beyond the band (A-evac-029, A-evac-035). Before this, near
  identical options differed by up to 75 veh-h and the ranking followed the noise.
- B-D-037 Publication (PROJECT.md 11): the brief asks for Al Hamra and Al Balad demos, so both
  scenario files ship with generic boxes, invented crowd sizes, timings and orders and
  `fictional: true`; docs/evacuation.md publishes their synthetic results, which name real streets
  (corridors, bottlenecks). Flag for the release review: move the city result tables to private
  notes if the authority asks; the demo-window scenario is the only fully neutral one.
- B-D-038 After the verifier: corridor-matching thresholds registered (A-evac-036..038, values
  unchanged), A-evac-035 recorded in outputs, the T90/T100 noise band reported as n/a where neither
  run reaches the level, the score header reads the weights; city demos and strategists rerun so
  every output lists the full assumption set.
- B-D-036 Al Hamra zone widened from the car parks only (39.140-39.150 E) to car parks + street
  grid (39.145-39.160 E, 21.530-21.542 N): the first box had 143 service-road origins and a single
  one-lane egress, so no exit-side strategy could matter (T50 ~ 1 h for every option).

### M7 summary — 2026-10-16
Built: `sim/events/evacuation.py` (zone origins, auto exits, reverse free-flow trees, seeded
evacuee sampling, nearest / balanced assignment, simultaneous / near-first / far-first release,
contraflow corridor detection + netconvert edit + Webster retime, run-time contraflow and signal
plan, clearance T50/T90/T100, bottleneck edges, background delay; `run`, `validate`, `net`,
`register` CLIs); `strategist/evacuation.py` (screening candidates, parallel what-ifs + noise
replicate, score, classification, explanations, explicit recommendation, decision log, `approve`);
`sim/scenarios/evac_settings.yaml` (A-evac-001..038), `evac_demo.yaml`, `evac_corniche_hamra.yaml`,
`evac_flood_balad.yaml`; `docs/evacuation.md` (method, contraflow mechanics, results tables,
register block); 42 tests in `tests/test_evacuation.py` and `tests/test_evacuation_run.py`.
Commands:
`uv run python -m sim.events.evacuation run --scenario evac_corniche_hamra --seed 1`,
`uv run python -m sim.events.evacuation run --scenario evac_flood_balad --seed 1`,
`uv run python -m strategist.evacuation run --scenario <id> --seed 1`,
`uv run python -m strategist.evacuation approve <recommendation_id> --option 1`.
Measured (seed 1, SUMO 1.28.0, load average 30-50 from other tracks):
- Al Hamra (tahlia window; 2,000 vehicles, zone 2.06 km2, 6 exits, 3 corridors 7.3 lane-km):
  as written T50 1,264 s, T90 2,399 s, T100 3,004 s, 2,000/2,000 out, 214 teleports (125
  evacuees), background +90.1 veh-h versus the reference (537.4); bottleneck Hail Street
  (`-1486721509#7.s5`, 16.2 halted veh-h). Demo command 292-308 s wall. Strategist: 11 what-ifs (incl.
  no strategy) + replicate in 540-631 s; noise band T90 +/-3 s, T100 +/-19 s, delay +/-8.1 veh-h; recommendation
  **no strategy** (no option beats it on score); fastest = contraflow cf1+cf2 (T90 -90 s, T100
  -258 s, +25.3 veh-h, 5.3 lane-km, score 2,857 vs 2,702). Three strategist runs: same fingerprint
  cac0abd33e53160d (log records 12, 14, 17; final rec-20261016T053046Z-750c78f4).
- Al Balad flood day (al_balad window; storm + FS-002 closed; 2,000 vehicles, 0.92 km2, 6 exits,
  3 corridors 10.6 lane-km): as written only 1,755/2,000 out by the run end, T50 2,768 s, T90 not
  reached, 602 teleports (503 evacuees); background +291.8 veh-h. Demo command 197-221 s wall.
  Strategist: 11 what-ifs + replicate in 310-353 s; noise band T90/T100 n/a (neither run reaches
  them), delay
  +/-13.3 veh-h; recommendation **balanced exit guidance + evacuation signal plan** (auto_eligible):
  T90 4,493 s, T100 5,212 s, 2,000/2,000 out, score 4,860 vs 8,550. Approved in the log
  (final: dec-20261016T054527Z-939a23de on rec-20261016T053643Z-624adbd0); `strategist.log verify`
  OK, 19 records. Three strategist runs: same fingerprint ff134cd308b9f3e9 (records 13, 15, 18).
- Demo window (`evac_demo`, 150 vehicles): T50 383 s, T90 642 s, T100 733 s (verifier, twice, and
  the strategist's no-strategy run); 5-15 s per command.
- The demo command and the strategist's no-strategy what-if gave identical clearance on all three
  windows; light and FCD run paths identical on the demo window (test).
- Contraflow net edit: netconvert + retime 6-37 s per scenario (cached by hash).
Could not verify: every evacuation parameter (no Jeddah evacuation, event-parking or contraflow
data; HCM saturation flow quoted from memory, A-evac-011); the inbound-carriageway match is
geometric (checked by name in the corridor tables, not against imagery); why contraflow moves the
Al Balad bottleneck to Dhahab Street; clearance is flattered by jam teleports (125-503 evacuee
teleports in the as-written runs).
Open: one noise replicate is a crude band (more replicates would firm up close rankings); the
reversed lanes have no crossover geometry and copy the corridor speed; evacuation is not wired into
`sim.runner --scenario` (registry and schema are M5 files: B-D-026); the A-evac rows live in
docs/evacuation.md until integration adds evac_settings.yaml to the register SOURCES (B-D-031);
README commands to copy at integration (B-D-033); superseded recommendation records from the
earlier Al Hamra runs (before B-D-032/034/035/036) remain in the append-only log as records 8-11
(rec-20261016T034544Z-092be3ed, ...T040041Z-b087e28c, ...T041245Z-aa5f90d0, ...T042644Z-cbb10229);
records 12-15 are the final simulation code before reporting-only changes and match the final
records 17 (Al Hamra, rec-20261016T053046Z-750c78f4) and 18 (Al Balad, rec-20261016T053643Z-624adbd0);
record 16 approves record 15, record 19 approves record 18.
Next: M8 Calibration (Track A) — Track B's next work is integration: registry/runner wiring for
evacuation, register merge, README commands.
Disk: the shared volume was at 99 % (about 1-6 GB free) during M7 and the verifier's first test
run failed on a full disk; M7 outputs under runs/ are about 0.7 GB (superseded strategist run dirs
are kept because decision-log records point at them). Long city runs by any track can hit this.
Tests: 146 pass (full suite, about 1.5 min under load); 42 of them M7; ruff clean.
Verifier: first pass FAIL on documentation accuracy (stale status numbers), an unregistered
threshold and a missing assumption id in outputs; all fixed (B-D-038), city demos and strategists
rerun with unchanged fingerprints; second pass PASS on all items except one stale register range
in this block, fixed in the same commit as this line.
M7: done
