# Scenario report: rain_center on window `center`

**synthetic demand, uncalibrated**. Fictional scenario parameters (PROJECT.md section 11).

Heavy rain over central Hail for 40 min. Seed 1, 0-3600 s, Tier B (micro), Eclipse SUMO sumo 1.28.0. Run `rain_center-center-s1-f5be681f`; config hash `f5be681fd73854f8`, network hash `ff661b46062e0c11`, demand hash `6adc96939f3ef10c`.

Baseline: same demand, vType mix, seed and step loop; probe events (emergency trips) only, no disruptive events.

| KPI | baseline | scenario | delta | delta % |
|---|---:|---:|---:|---:|
| vehicles inserted | 9910 | 9882 | -28 | -0.28 |
| background trips completed | 7727 | 7384 | -343 | -4.44 |
| running at end | 2183 | 2498 | - | - |
| waiting to insert at end | 51 | 46 | -5 | -9.80 |
| mean travel time (s) | 293.63 | 298.74 | 5.11 | 1.74 |
| mean delay = timeLoss (s) | 118.59 | 126.88 | 8.29 | 6.99 |
| mean insertion delay = departDelay (s) | 0.10 | 0.16 | 0.06 | 60.00 |
| mean speed (km/h) | 21.39 | 18.17 | -3.22 | -15.05 |
| VKT (veh-km) | 23,323.90 | 22,310.00 | -1,013.90 | -4.35 |
| VHT (veh-h) | 1,090.38 | 1,228.15 | 137.77 | 12.64 |
| longest queue, max (m) | 328.50 | 393.60 | 65.10 | 19.82 |
| longest queue, p95 over steps (m) | 321.70 | 353.00 | 31.30 | 9.73 |
| max halted on one edge (veh) | 103 | 153 | 50 | 48.54 |
| halted in window, p95 (veh) | 1,291.00 | 1,554.00 | 263.00 | 20.37 |
| teleports | 342 | 361 | 19 | 5.56 |
| jam teleports | 213 | 236 | - | - |
| vehicles rerouted by closures | 0 | 0 | - | - |
| gridlock (onset s) | True (1,691.00) | True (1,970.00) | | |

Gridlock rules fired in the scenario: {'sustained_halt': 2401.0, 'jam_teleports': 1970.0}.

## Top queued edges (scenario)

| edge | max queue (m) | at (s) | max halted (veh) |
|---|---:|---:|---:|
| `298009826#3` | 393.6 | 3598 | 153 |
| `107173634#27` | 330.7 | 2449 | 119 |
| `107417760#0` | 323.3 | 2856 | 32 |
| `1501371308` | 211.6 | 2386 | 28 |
| `1550792685#9` | 177.6 | 3586 | 22 |

## Event log (scenario)

| t (s) | event | action | details |
|---:|---|---|---|
| 600 | heavy_rain | start | type=rain |
| 600 | heavy_rain | weather_on | preset=heavy, vtype=normal, speedFactor=0.94, accel=2.21, decel=3.825, minGap=3.0, tau=1.12 |
| 3000 | heavy_rain | weather_off | vtype=normal, speedFactor=1.0, accel=2.6, decel=4.5, minGap=2.5, tau=1.0 |
| 3000 | heavy_rain | end | horizon=False |

Wall time: baseline 287.95 s + 27.75 s post, scenario 297.37 s + 30.48 s post, total 331.74 s (parallel).

Assumptions used (66): A-vtype-063, A-vtype-064, A-vtype-065, A-vtype-066, A-vtype-067, A-vtype-068, A-vtype-069, A-vtype-001, A-vtype-002, A-vtype-003, A-vtype-004, A-vtype-005, A-vtype-006, A-vtype-007, A-vtype-008, A-vtype-009, A-vtype-010, A-vtype-011, A-vtype-012, A-vtype-013, A-vtype-014, A-vtype-015, A-vtype-016, A-vtype-017, A-vtype-018, A-vtype-019, A-vtype-020, A-vtype-021, A-vtype-022, A-vtype-023, A-vtype-024, A-vtype-025, A-vtype-026, A-vtype-027, A-vtype-028, A-vtype-029, A-vtype-030, A-vtype-031, A-vtype-032, A-vtype-033, A-vtype-034, A-vtype-035, A-vtype-036, A-vtype-037, A-vtype-038, A-vtype-039, A-vtype-040, A-vtype-041, A-vtype-042, A-vtype-043, A-vtype-044, A-vtype-045, A-vtype-046, A-rain-006, A-rain-007, A-rain-008, A-rain-009, A-rain-010, A-kpi-001, A-kpi-002, A-kpi-003, A-kpi-004, A-kpi-005, A-kpi-006, A-kpi-007, A-sim-002 (docs/assumptions-trackB.md, docs/assumptions.md).
