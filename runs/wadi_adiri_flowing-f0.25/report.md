# Run wadi_adiri_flowing-f0.25

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 497096 |
| trips_completed_sampled | 124274 |
| vehicles_loaded_sampled | 124301 |
| teleports | 16950 |
| teleport_share | 0.136363 |
| mean_delay_s | 688.6 |
| mean_time_loss_s | 677.2 |
| mean_depart_delay_s | 11.4 |
| mean_duration_s | 1277.9 |
| mean_trip_km | 10.29 |
| mean_speed_kmh | 28.98 |
| vkt | 5113042 |
| vht | 176460 |
| vht_delay | 95087 |
| throughput_peak_hour_trips | 53676 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.108 |
| am_peak_mean_delay_s | 320.9 |
| co2_t | 1719.2 |
| nox_kg | 930.9 |
| co2_peak_hour_t | 128.9 |
| vehicles_planned | 499904 |
| completion_share | 0.9946 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 4423.6 | 13.4 |
| Al Khamashiyah | 1572.0 | 1303.1 | 21.7 |
| Sinaiyah An Nahdah | 3656.0 | 1254.6 | 27.3 |
| Al Buhayrah | 4744.0 | 1198.3 | 25.4 |
| Al Jamiah | 30740.0 | 1172.3 | 27.1 |
| Industrial Area | 5564.0 | 1158.2 | 35.6 |
| Al Qirawan | 132.0 | 1143.4 | 28.7 |
| Aljathamiuh | 224.0 | 1089.6 | 34.4 |
| Hail Airport | 232.0 | 1087.0 | 31.7 |
| Al Talal | 4848.0 | 1036.1 | 33.9 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 107434808#1 | 1004.87 | 32.3 |
| 298009826#3 | 876.68 | 60.9 |
| 325327519#7 | 634.27 | 23.9 |
| 324857086#0 | 476.44 | 43.2 |
| 324857086#1 | 464.81 | 39.2 |
| 325327519#5 | 414.01 | 35.2 |
| 1359711042#6 | 383.65 | 49.7 |
| 107434808#0 | 355.85 | 52.6 |
| 325327519#8 | 267.82 | 17.2 |
| 298009826#0 | 244.05 | 68.6 |

## Provenance
seed 1 | config 7727326c6bbbdc73 | population 765732190ffb2223 | network 594810cf106bb39d |
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

