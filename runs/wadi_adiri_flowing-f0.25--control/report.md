# Run wadi_adiri_flowing-f0.25--control

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 499584 |
| trips_completed_sampled | 124896 |
| vehicles_loaded_sampled | 124976 |
| teleports | 20554 |
| teleport_share | 0.164464 |
| mean_delay_s | 782.2 |
| mean_time_loss_s | 771.6 |
| mean_depart_delay_s | 10.7 |
| mean_duration_s | 1370.1 |
| mean_trip_km | 10.22 |
| mean_speed_kmh | 26.85 |
| vkt | 5105525 |
| vht | 190139 |
| vht_delay | 108555 |
| throughput_peak_hour_trips | 53936 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.108 |
| am_peak_mean_delay_s | 291.4 |
| co2_t | 1839.9 |
| nox_kg | 985.9 |
| co2_peak_hour_t | 122.0 |
| vehicles_planned | 499904 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 3848.4 | 15.0 |
| Al Khamashiyah | 1572.0 | 1669.6 | 18.3 |
| Industrial Area | 5564.0 | 1660.2 | 29.0 |
| Sinaiyah An Nahdah | 3664.0 | 1642.1 | 22.7 |
| Al Talal | 4856.0 | 1367.8 | 28.9 |
| Al Jamiah | 30764.0 | 1314.0 | 25.4 |
| Sinaiyah Altaqadum | 2292.0 | 1290.2 | 29.0 |
| Al Jabal | 2624.0 | 1265.7 | 20.8 |
| Aljathamiuh | 224.0 | 1244.8 | 31.9 |
| Barzan | 1640.0 | 1179.9 | 17.8 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 107434808#1 | 1006.03 | 33.0 |
| 298009826#3 | 998.01 | 59.9 |
| 325327519#7 | 621.13 | 25.5 |
| 324857086#0 | 482.86 | 43.2 |
| 1359711042#6 | 459.65 | 46.9 |
| 324857086#1 | 453.68 | 40.7 |
| 325327519#5 | 413.23 | 35.2 |
| 107434808#0 | 385.17 | 55.3 |
| 298009826#0 | 315.82 | 64.5 |
| 1459444604#3 | 265.33 | 75.9 |

## Provenance
seed 1 | config 2a311aadeecbf810 | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

