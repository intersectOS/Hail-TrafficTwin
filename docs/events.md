# Focus windows, tier link and events (M5)

**Synthetic demand, uncalibrated.** Window demand is the M1 Tier A smoke route set (random trips,
one hour) cut into the window; Track A's population routes replace it through the same link CLI.
All event files are **fictional** (PROJECT.md section 11): times, durations and the motorcade route
are invented and ship on the Tahlia window only.

## Commands

```bash
# windows: cut from the city net (ids = Tier A) + graft service roads from OSM
uv run python -m sim.link window --name tahlia            # also kaia_corridor, al_balad, kau_faisaliyah, obhur
# Tier A exit times (meso re-run of a Tier A route file with --vehroute-output.exit-times)
uv run python -m sim.link tier-a --routes runs/source-smoke-A/routes.rou.xml --seed 1
# cutRoutes with exit times -> data/windows/<w>/<w>.rou.xml, plus Webster-retimed signals
uv run python -m sim.link cut --window tahlia --tier-a runs/tierA-exit-2f1822b7-cc34910d/
# 9.3 acceptance: window micro flows vs Tier A flows -> runs/link-<w>/flow_comparison.{json,md}
uv run python -m sim.link check --window tahlia --tier-a runs/tierA-exit-2f1822b7-cc34910d/ --seed 1
# scenario vs window baseline (same seed) -> runs/<id>/scenario_report.{json,md}
uv run python -m sim.runner --scenario accident_tahlia --window tahlia --seed 1
uv run python -m sim.scenarios validate sim/scenarios/*_tahlia.yaml
```

## Windows (PROJECT.md 9.3)

| window | area km2 | edges (with service roads) | junctions | TLS | cut Tier A vehicles | flow check |
|---|---:|---:|---:|---:|---:|---|
| tahlia | 23.8 | 10,074 | 3,888 | 7 | 4,597 | PASS: GEH<5 on 90.2 % of 420 edges, total ratio 0.910 |
| kaia_corridor (polygon) | 21.9 | 3,311 | 1,490 | 3 | 3,647 | PASS: 100 % of 188, 0.992 |
| al_balad | 17.0 | 3,305 | 1,419 | 6 | 3,191 | PASS: 100 % of 175, 0.995 |
| kau_faisaliyah | 19.7 | 5,795 | 2,494 | 0 | 3,362 | PASS: 100 % of 240, 0.997 |
| obhur (polygon, Track I) | 24.8 (about 4 of it water) | 2,339 | 1,014 | 0 | 2,757 | PASS: 100 % of 91, 1.000 |

Tolerance (A-link-005/006): GEH < 5 on at least 85 % of window edges with Tier A flow >= 50 veh/h
over the hour, and total flow within 10 %. It is a model-to-model check (micro window vs meso city),
so it tests the link, not realism.

- Windows are cut from `data/jeddah/jeddah.net.xml`, so every Tier A edge id survives; service and
  living-street roads (dropped in Tier A) are grafted from OSM by splitting the city edges they join
  (`<id>` keeps the first part, `<id>.s<k>` the rest) with an edge map for the route rewrite.
- Tahlia failed first (79.3 %, ratio 0.637): the netconvert-default program at the signalled level of
  the Madinah Rd / Tahlia interchange gave the main right turn 6 s of 90 s, while Tier A meso only
  adds a red-time penalty. Tier B windows now load Webster-retimed programs (A-link-009,
  `<w>.tls.add.xml`); the city net is untouched. Tahlia passes with a thin margin; a reviewed program
  with separate right-turn phases for that cluster is the real fix (open).
- `kau_faisaliyah` covers KAU / Al Jamiah only: Al Faisaliyyah is about 9 km away in OSM.

## Vehicle types (PROJECT.md 9.5)

`sim/vtypes/types.yaml`: normal, slow, aggressive, truck, bus, emergency (`vClass=emergency`,
bluelight device, rejected for Tier A), convoy (`vClass=vip`). Default mix in
`sim/vtypes/mix_default.yaml`; scenarios may override with `vtype_mix`. Parameters: A-vtype-001..069
(SUMO defaults read back from SUMO 1.28 or stated assumptions; register in
`docs/assumptions-trackB.md`).

## Events (PROJECT.md 9.7)

| event | implementation (TraCI, Tier B only) | demo file |
|---|---|---|
| accident | close N lanes or the edge for a duration; optional rubbernecking speed cut on the opposite carriageway | `accident_tahlia.yaml` |
| rain | light / heavy / storm presets scale speedFactor, accel, decel, minGap, tau of all types; restored at the end (A-rain-*) | `rain_tahlia.yaml` |
| flood | storm preset + closure of reviewed sites from `data/jeddah_flood_sites.yaml` inside the window (OSM way match, else radius) | `flood_tahlia.yaml` |
| motorcade | convoy of `vip` vehicles; rolling junction holds from convoy ETA - 120 s until the last vehicle passed + 30 s | `motorcade_tahlia.yaml` |
| emergency_trip | emergency vehicle A to B at T; travel time vs free flow and vs baseline; `strategist: true` recorded for M6 | `emergency_tahlia.yaml` |
| evacuation | reserved in the schema, rejected at run time (M7) | - |

Baseline = same demand, vType mix, seed and step loop, with probe events (emergency trips) only.

## Results on the Tahlia window (seed 1, 0-3600 s, measured 2026-10-16)

Window baseline: 3,652 vehicles inserted, mean delay 97.8 s, mean speed 44.7 km/h, VHT 247.2 h,
longest queue 161.8 m (p95 152.4 m), 13 teleports (8 jam, 0.34 % of loaded vehicles), no gridlock. Each run (baseline
and scenario in parallel) takes about 190-205 s wall (emergency 119 s); the same command twice gives identical KPIs.

| scenario | event | mean delay s (base -> scen) | mean speed km/h | VHT h | queue max / p95 m | teleports (jam) | gridlock | specific |
|---|---|---|---|---|---|---|---|---|
| accident_tahlia | both lanes of `44795819#33` closed 600-1800 s, rubbernecking | 97.8 -> 103.5 (+5.7 %) | 44.7 -> 43.3 | 247.2 -> 253.2 | 162 / 155 | 13 (8) -> 12 (6) | no | edge flow 816 -> 515; 300 vehicles rerouted |
| rain_tahlia | heavy rain 600-3000 s | 97.8 -> 120.6 (+23.3 %) | 44.7 -> 39.3 | 247.2 -> 274.5 | 195 / 155 | 13 (8) -> 14 (8) | no | normal type restored exactly at 3000 s |
| flood_tahlia | storm 600-3300 s, sites FS-008/009/010 closed 1200-3300 s (13 edges) | 97.8 -> 218.9 (+123.8 %) | 44.7 -> 28.4 | 247.2 -> 357.1 | 202 / 197 | 13 (8) -> 54 (18) | no (halted share peaks at 0.49, threshold 0.5) | 192 fewer vehicles inserted |
| motorcade_tahlia | 6-vehicle convoy at 900 s, 24 junctions held | 97.8 -> 86.9 (-11.2 %) | 44.7 -> 46.8 | 247.2 -> 237.0 | 160.5 / 152.7 | 13 (8) -> 12 (6) | no | convoy 6/6, 85.0 s vs 66.5 s free flow; mean hold 82.7 s, max 127 s; all closures lifted |
| emergency_tahlia | ambulance at 900 s through a one-lane crash (600-1800 s) | 95.2 -> 99.8 (+4.8 %) | 45.7 -> 44.7 | 243.2 -> 246.2 | 162 / 153 | 13 (4) -> 17 (11) | no | ambulance 94 s vs 70 s baseline vs 47.3 s free flow (2.0x free flow, 1.34x baseline) |

Reading the table
- Run-to-run perturbation: adding one ambulance to the baseline moved mean delay by 2.7 %, so window
  deltas below about 3 % are noise from changed vehicle interactions, not event effects.
- The motorcade delta is negative and not interpretable yet: the current random-trip demand barely
  uses Tahlia Street, so the holds mostly meter cross traffic into the congested Madinah Rd cluster.
  Revisit with population demand; per-vehicle delay of held traffic is the right KPI (open).
- Gridlock rules (A-kpi-001..007) did not fire in any demo. The flood comes closest (49 % halted).
- Flood closures are only as good as the reviewed site list (25 sites, 11 high confidence).

Full per-scenario reports: `runs/<id>/scenario_report.md` (gitignored; regenerated by the commands).
