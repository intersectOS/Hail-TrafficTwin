# Scenario report: emergency_center on window `center`

**synthetic demand, uncalibrated**. Fictional scenario parameters (PROJECT.md section 11).

Ambulance from Al Wasita to King Khalid Hospital while a crash blocks one of four lanes on its route. Seed 1, 0-3600 s, Tier B (micro), Eclipse SUMO sumo 1.28.0. Run `emergency_center-center-s1-4426008c`; config hash `4426008c943c999f`, network hash `ff661b46062e0c11`, demand hash `6adc96939f3ef10c`.

Baseline: same demand, vType mix, seed and step loop; probe events (emergency trips) only, no disruptive events.

| KPI | baseline | scenario | delta | delta % |
|---|---:|---:|---:|---:|
| vehicles inserted | 9918 | 9914 | -4 | -0.04 |
| background trips completed | 7465 | 7709 | 244 | 3.27 |
| running at end | 2452 | 2204 | - | - |
| waiting to insert at end | 44 | 48 | 4 | 9.09 |
| mean travel time (s) | 278.93 | 283.80 | 4.87 | 1.75 |
| mean delay = timeLoss (s) | 106.37 | 108.82 | 2.45 | 2.30 |
| mean insertion delay = departDelay (s) | 0.09 | 0.12 | 0.03 | 33.33 |
| mean speed (km/h) | 19.32 | 21.53 | 2.21 | 11.44 |
| VKT (veh-km) | 22,470.50 | 23,303.50 | 833.00 | 3.71 |
| VHT (veh-h) | 1,163.23 | 1,082.45 | -80.78 | -6.94 |
| longest queue, max (m) | 344.10 | 323.30 | -20.80 | -6.04 |
| longest queue, p95 over steps (m) | 320.20 | 322.60 | 2.40 | 0.75 |
| max halted on one edge (veh) | 128 | 87 | -41 | -32.03 |
| halted in window, p95 (veh) | 1,563.00 | 1,343.00 | -220.00 | -14.08 |
| teleports | 456 | 374 | -82 | -17.98 |
| jam teleports | 297 | 236 | - | - |
| vehicles rerouted by closures | 0 | 0 | - | - |
| gridlock (onset s) | True (1,684.00) | True (1,964.00) | | |

Gridlock rules fired in the scenario: {'sustained_halt': 2544.0, 'jam_teleports': 1964.0}.

## Emergency trips

| vehicle | free flow (s) | baseline TT (s) | scenario TT (s) | TT / free flow | TT / baseline | strategist |
|---|---:|---:|---:|---:|---:|---|
| ev.ambulance_1.0 | 148.84 | 207.00 | 205.00 | 1.38 | 0.99 | requested (M6, not applied) |

## Vehicles entering event edges

| edge | baseline | scenario |
|---|---:|---:|
| `131718901#12` | 38 | 38 |

## Top queued edges (scenario)

| edge | max queue (m) | at (s) | max halted (veh) |
|---|---:|---:|---:|
| `107417760#0` | 323.3 | 3560 | 28 |
| `107173634#27` | 322.9 | 3573 | 84 |
| `298009826#3` | 235.8 | 3595 | 87 |
| `1501371308` | 209.3 | 3083 | 27 |
| `107418926#0` | 161.9 | 1863 | 21 |

## Event log (scenario)

| t (s) | event | action | details |
|---:|---|---|---|
| 600 | crash_imam_st | start | type=accident |
| 600 | crash_imam_st | close_lanes | lanes=['131718901#12_3'], verified_disallowed=1, full_closure=False, rerouted=0, rubbernecking_lanes=8 |
| 900 | ambulance_1 | start | type=emergency_trip |
| 900 | ambulance_1 | dispatch | vehicles=['ev.ambulance_1.0'], route_edges=42, ff_s=148.8, strategist=True |
| 1106 | ambulance_1 | arrived | vehicle=ev.ambulance_1.0 |
| 1106 | ambulance_1 | end | horizon=False |
| 1800 | crash_imam_st | reopen_lanes | lanes=['131718901#12_3'], verified_reopened=1 |
| 1800 | crash_imam_st | end | horizon=False |

Wall time: baseline 301.21 s + 30.67 s post, scenario 298.75 s + 28.74 s post, total 336.89 s (parallel).

Assumptions used (72): A-vtype-063, A-vtype-064, A-vtype-065, A-vtype-066, A-vtype-067, A-vtype-068, A-vtype-069, A-vtype-001, A-vtype-002, A-vtype-003, A-vtype-004, A-vtype-005, A-vtype-006, A-vtype-007, A-vtype-008, A-vtype-009, A-vtype-010, A-vtype-011, A-vtype-012, A-vtype-013, A-vtype-014, A-vtype-015, A-vtype-016, A-vtype-017, A-vtype-018, A-vtype-019, A-vtype-020, A-vtype-021, A-vtype-022, A-vtype-023, A-vtype-024, A-vtype-025, A-vtype-026, A-vtype-027, A-vtype-028, A-vtype-029, A-vtype-030, A-vtype-031, A-vtype-032, A-vtype-033, A-vtype-034, A-vtype-035, A-vtype-036, A-vtype-037, A-vtype-038, A-vtype-039, A-vtype-040, A-vtype-041, A-vtype-042, A-vtype-043, A-vtype-044, A-vtype-045, A-vtype-046, A-vtype-047, A-vtype-048, A-vtype-049, A-vtype-050, A-vtype-051, A-vtype-052, A-vtype-053, A-vtype-054, A-event-002, A-event-003, A-event-001, A-kpi-001, A-kpi-002, A-kpi-003, A-kpi-004, A-kpi-005, A-kpi-006, A-kpi-007, A-sim-002 (docs/assumptions-trackB.md, docs/assumptions.md).
