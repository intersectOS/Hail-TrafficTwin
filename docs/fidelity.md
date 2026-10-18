# Meso-versus-micro fidelity test (PROJECT.md 9.4)

> synthetic demand, uncalibrated. Window `demo` (data/demo/demo.net.xml, network
> 25c067631a1c0364), seed 1, weekday window population routed once and
> simulated in both tiers at several demand multiples. Reproduce:
> `uv run python -m sim.fidelity --window demo --seed 1`
> (outputs in `runs/fidelity-demo-s1/`).

## Summary by demand multiple
| demand_x | trips_meso | trips_micro | travel_time_meso_s | travel_time_micro_s | delay_meso_s | delay_micro_s | speed_meso_kmh | speed_micro_kmh | peak_hour | peak_delay_meso_s | peak_delay_micro_s | teleports_meso | teleports_micro | wall_meso_s | wall_micro_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 7741 | 7741 | 104.9 | 130.3 | 0.7 | 21.9 | 55.3 | 44.7 | 6 | 1.0 | 22.5 | 0 | 0 | 0.51 | 1.93 |
| 3.0 | 23223 | 23223 | 111.7 | 139.1 | 7.6 | 32.7 | 51.9 | 41.9 | 6 | 8.0 | 37.6 | 0 | 0 | 0.92 | 5.74 |
| 6.0 | 46446 | 46446 | 118.2 | 727.0 | 16.3 | 770.8 | 49.1 | 8.0 | 8 | 13.0 | 4994.1 | 0 | 3763 | 1.54 | 58.62 |

## Hourly comparison at the highest multiple
| hour | trips meso/micro | delay s meso/micro | speed km/h meso/micro | time loss veh-h meso/micro |
|---|---|---|---|---|
| 0 | 972/972 | 16.2/42.5 | 48.3/39.4 | 2.6/9.1 |
| 1 | 480/480 | 15.9/40.3 | 48.7/40.1 | 1.2/4.3 |
| 2 | 240/240 | 14.7/37.5 | 49.8/41.2 | 0.5/1.8 |
| 3 | 228/228 | 13.1/36.5 | 50.7/41.7 | 0.5/2.0 |
| 4 | 246/246 | 14.1/35.8 | 48.2/40.1 | 0.6/1.9 |
| 5 | 2393/2389 | 19.2/112.1 | 48.1/27.3 | 7.8/48.6 |
| 6 | 4801/4529 | 19.4/1595.7 | 47.8/3.3 | 16.8/683.8 |
| 7 | 2214/1885 | 14.6/4119.6 | 50.1/1.4 | 5.2/1566.9 |
| 8 | 1565/1705 | 13.0/4994.1 | 51.0/1.4 | 3.2/1947.8 |
| 9 | 1051/1037 | 13.8/4225.8 | 50.3/1.6 | 2.3/1579.4 |
| 10 | 696/790 | 14.2/3203.4 | 50.3/3.1 | 1.6/1236.8 |
| 11 | 1583/1965 | 14.8/1700.5 | 48.8/28.0 | 3.7/207.5 |
| 12 | 3790/3791 | 15.9/57.6 | 48.8/35.5 | 10.0/50.5 |
| 13 | 1827/1829 | 15.0/44.8 | 48.9/39.0 | 4.5/19.2 |
| 14 | 1368/1367 | 15.3/43.0 | 49.2/40.0 | 3.4/12.7 |
| 15 | 1789/1783 | 15.1/45.8 | 49.9/39.6 | 4.4/18.2 |
| 16 | 2462/2467 | 15.0/46.4 | 49.4/38.9 | 5.9/25.1 |
| 17 | 2921/2920 | 15.9/60.8 | 48.6/35.0 | 7.4/33.9 |
| 18 | 3099/3097 | 16.7/65.1 | 48.7/34.9 | 8.8/54.2 |
| 19 | 2867/2868 | 18.3/63.5 | 48.9/35.6 | 9.1/43.4 |
| 20 | 3395/3386 | 17.6/75.0 | 49.0/33.4 | 10.1/60.3 |
| 21 | 2743/2751 | 16.5/53.7 | 48.9/37.4 | 7.6/34.1 |
| 22 | 2128/2132 | 14.5/44.4 | 50.0/39.7 | 5.1/21.4 |
| 23 | 1588/1589 | 14.4/43.4 | 50.9/40.6 | 3.6/15.3 |

## Caveats
- SUMO's mesoscopic model only partially follows kinematic-wave (LWR) theory, models queue
  spill-back incompletely and tends to underestimate congestion (June 2026 re-assessment of
  the Eissfeldt meso model, PROJECT.md section 2). The window test below quantifies the gap on
  Jeddah's network: x1: mean delay meso 0.7 s vs micro 21.9 s, speed 55.3 vs 44.7 km/h; x3: mean delay meso 7.6 s vs micro 32.7 s, speed 51.9 vs 41.9 km/h; x6: mean delay meso 16.3 s vs micro 770.8 s, speed 49.1 vs 8.0 km/h.
- Meso has no lane changing, no lane-level queues and no explicit junction geometry; signal
  delay is an expected-delay penalty (meso-tls-penalty, A-sim-001), so junction-level delay is
  approximate.
- The test window carries internal trips only (no through traffic), so its loads are raised
  with demand multiples; city-scale interactions are not tested.
- Consequence for reports: trust baseline-versus-policy deltas more than absolute delay and
  speed, and always state the tier a result was run on.
- Demand is synthetic and uncalibrated (no Jeddah counts or travel survey).

