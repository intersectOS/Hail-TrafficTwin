# Run staggered_schools_60-f0.25--control

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 499620 |
| trips_completed_sampled | 124905 |
| vehicles_loaded_sampled | 124976 |
| teleports | 18580 |
| teleport_share | 0.148669 |
| mean_delay_s | 715.5 |
| mean_time_loss_s | 707.0 |
| mean_depart_delay_s | 8.5 |
| mean_duration_s | 1304.5 |
| mean_trip_km | 10.21 |
| mean_speed_kmh | 28.19 |
| vkt | 5102907 |
| vht | 181038 |
| vht_delay | 99295 |
| throughput_peak_hour_trips | 53896 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1079 |
| am_peak_mean_delay_s | 389.4 |
| co2_t | 1759.0 |
| nox_kg | 948.7 |
| co2_peak_hour_t | 132.7 |
| vehicles_planned | 499904 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 7207.3 | 8.8 |
| Al Khamashiyah | 1572.0 | 1672.1 | 17.8 |
| Sinaiyah An Nahdah | 3664.0 | 1496.7 | 24.2 |
| Hail Airport | 768.0 | 1477.9 | 30.9 |
| Industrial Area | 5564.0 | 1310.4 | 33.3 |
| Ar Rasf | 4488.0 | 1224.1 | 23.8 |
| Al Talal | 4856.0 | 1222.9 | 30.9 |
| Al Jabal | 2624.0 | 1190.3 | 21.7 |
| Sinaiyah Altaqadum | 2292.0 | 1165.9 | 30.7 |
| Al Buhayrah | 4596.0 | 1153.1 | 21.2 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 298009826#3 | 965.21 | 60.5 |
| 107434808#1 | 691.54 | 37.9 |
| 325327519#7 | 431.39 | 30.0 |
| 324857086#0 | 397.7 | 50.0 |
| 324857086#1 | 383.54 | 46.5 |
| 253654410#1 | 314.97 | 56.8 |
| 1359711042#6 | 300.18 | 56.2 |
| 298009826#0 | 289.09 | 65.6 |
| 1191274599#0 | 277.36 | 40.3 |
| 1084650194#2 | 276.66 | 78.7 |

## Provenance
seed 1 | config 4fc090bd14afa616 | population 765732190ffb2223 | network addfcb64bedc9fa3 |
Eclipse SUMO sumo 1.28.0

## Caveats (meso fidelity, PROJECT.md 9.4)
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

