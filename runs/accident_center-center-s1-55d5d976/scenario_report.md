# Scenario report: accident_center on window `center`

**synthetic demand, uncalibrated**. Fictional scenario parameters (PROJECT.md section 11).

Serious crash closes all three southbound lanes of King Abdulaziz Rd in central Hail for 20 min. Seed 1, 0-3600 s, Tier B (micro), Eclipse SUMO sumo 1.28.0. Run `accident_center-center-s1-55d5d976`; config hash `55d5d9760a6bb8f3`, network hash `ff661b46062e0c11`, demand hash `6adc96939f3ef10c`.

Baseline: same demand, vType mix, seed and step loop; probe events (emergency trips) only, no disruptive events.

| KPI | baseline | scenario | delta | delta % |
|---|---:|---:|---:|---:|
| vehicles inserted | 9910 | 9823 | -87 | -0.88 |
| background trips completed | 7727 | 8158 | 431 | 5.58 |
| running at end | 2183 | 1665 | - | - |
| waiting to insert at end | 51 | 138 | 87 | 170.59 |
| mean travel time (s) | 293.63 | 327.13 | 33.50 | 11.41 |
| mean delay = timeLoss (s) | 118.59 | 146.85 | 28.26 | 23.83 |
| mean insertion delay = departDelay (s) | 0.10 | 0.09 | -0.01 | -10.00 |
| mean speed (km/h) | 21.39 | 23.45 | 2.06 | 9.63 |
| VKT (veh-km) | 23,323.90 | 24,525.80 | 1,201.90 | 5.15 |
| VHT (veh-h) | 1,090.38 | 1,045.98 | -44.40 | -4.07 |
| longest queue, max (m) | 328.50 | 328.60 | 0.10 | 0.03 |
| longest queue, p95 over steps (m) | 321.70 | 324.10 | 2.40 | 0.75 |
| max halted on one edge (veh) | 103 | 123 | 20 | 19.42 |
| halted in window, p95 (veh) | 1,291.00 | 863.00 | -428.00 | -33.15 |
| teleports | 342 | 219 | -123 | -35.96 |
| jam teleports | 213 | 152 | - | - |
| vehicles rerouted by closures | 0 | 774 | - | - |
| gridlock (onset s) | True (1,691.00) | True (2,476.00) | | |

Gridlock rules fired in the scenario: {'sustained_halt': 2825.0, 'jam_teleports': 2476.0}.

## Vehicles entering event edges

| edge | baseline | scenario |
|---|---:|---:|
| `1358424025#6` | 1139 | 297 |

## Top queued edges (scenario)

| edge | max queue (m) | at (s) | max halted (veh) |
|---|---:|---:|---:|
| `107173634#27` | 328.6 | 2221 | 123 |
| `107417760#0` | 323.2 | 2838 | 43 |
| `132154199#6` | 185.4 | 3370 | 25 |
| `-369685230#2` | 170.3 | 1735 | 20 |
| `107418926#0` | 164.2 | 2003 | 21 |

## Event log (scenario)

| t (s) | event | action | details |
|---:|---|---|---|
| 600 | crash_king_abdulaziz_sb | start | type=accident |
| 600 | crash_king_abdulaziz_sb | close_lanes | lanes=['1358424025#6_2', '1358424025#6_1', '1358424025#6_0'], verified_disallowed=3, full_closure=True, rerouted=130, rubbernecking_lanes... |
| 1800 | crash_king_abdulaziz_sb | reopen_lanes | lanes=['1358424025#6_2', '1358424025#6_1', '1358424025#6_0'], verified_reopened=3 |
| 1800 | crash_king_abdulaziz_sb | end | horizon=False |

Wall time: baseline 302.76 s + 30.35 s post, scenario 306.27 s + 28.6 s post, total 339.65 s (parallel).

Assumptions used (64): A-vtype-063, A-vtype-064, A-vtype-065, A-vtype-066, A-vtype-067, A-vtype-068, A-vtype-069, A-vtype-001, A-vtype-002, A-vtype-003, A-vtype-004, A-vtype-005, A-vtype-006, A-vtype-007, A-vtype-008, A-vtype-009, A-vtype-010, A-vtype-011, A-vtype-012, A-vtype-013, A-vtype-014, A-vtype-015, A-vtype-016, A-vtype-017, A-vtype-018, A-vtype-019, A-vtype-020, A-vtype-021, A-vtype-022, A-vtype-023, A-vtype-024, A-vtype-025, A-vtype-026, A-vtype-027, A-vtype-028, A-vtype-029, A-vtype-030, A-vtype-031, A-vtype-032, A-vtype-033, A-vtype-034, A-vtype-035, A-vtype-036, A-vtype-037, A-vtype-038, A-vtype-039, A-vtype-040, A-vtype-041, A-vtype-042, A-vtype-043, A-vtype-044, A-vtype-045, A-vtype-046, A-event-002, A-event-003, A-event-001, A-kpi-001, A-kpi-002, A-kpi-003, A-kpi-004, A-kpi-005, A-kpi-006, A-kpi-007, A-sim-002 (docs/assumptions-trackB.md, docs/assumptions.md).
