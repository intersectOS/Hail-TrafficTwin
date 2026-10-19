# Run staggered_schools_60-f0.25

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 499640 |
| trips_completed_sampled | 124910 |
| vehicles_loaded_sampled | 124976 |
| teleports | 18492 |
| teleport_share | 0.147964 |
| mean_delay_s | 732.9 |
| mean_time_loss_s | 722.9 |
| mean_depart_delay_s | 9.9 |
| mean_duration_s | 1320.9 |
| mean_trip_km | 10.22 |
| mean_speed_kmh | 27.84 |
| vkt | 5104097 |
| vht | 183320 |
| vht_delay | 101712 |
| throughput_peak_hour_trips | 44176 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.0884 |
| am_peak_mean_delay_s | 327.9 |
| co2_t | 1778.1 |
| nox_kg | 961.4 |
| co2_peak_hour_t | 115.4 |
| vehicles_planned | 499904 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 7031.4 | 9.0 |
| Al Khamashiyah | 1572.0 | 1892.7 | 16.5 |
| Sinaiyah An Nahdah | 3664.0 | 1644.2 | 22.7 |
| Hail Airport | 768.0 | 1444.1 | 31.2 |
| Industrial Area | 5564.0 | 1420.5 | 31.8 |
| Al Talal | 4856.0 | 1299.8 | 29.8 |
| Al Buhayrah | 4672.0 | 1274.8 | 21.2 |
| Ar Rasf | 4488.0 | 1213.0 | 24.0 |
| Al Qirawan | 132.0 | 1198.9 | 28.2 |
| Sinaiyah Altaqadum | 2292.0 | 1190.0 | 30.4 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 298009826#3 | 969.02 | 60.5 |
| 107434808#1 | 684.57 | 39.7 |
| 325327519#7 | 486.61 | 26.6 |
| 324857086#1 | 365.42 | 48.2 |
| 324857086#0 | 363.84 | 52.0 |
| 253654410#1 | 317.04 | 57.0 |
| 298009826#0 | 304.48 | 65.2 |
| 1359711042#6 | 297.3 | 58.8 |
| 1084650194#2 | 284.28 | 78.4 |
| 323836222#2 | 280.94 | 68.3 |

## Provenance
seed 1 | config 95b8b5e7d01aa814 | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

