# Run baseline-weekday-f0.25-s1-addfcb64-76573219-d30875

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 499456 |
| trips_completed_sampled | 124864 |
| vehicles_loaded_sampled | 124976 |
| teleports | 22814 |
| teleport_share | 0.182547 |
| mean_delay_s | 881.5 |
| mean_time_loss_s | 870.4 |
| mean_depart_delay_s | 11.1 |
| mean_duration_s | 1467.2 |
| mean_trip_km | 10.2 |
| mean_speed_kmh | 25.03 |
| vkt | 5094966 |
| vht | 203551 |
| vht_delay | 122304 |
| throughput_peak_hour_trips | 53908 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1079 |
| am_peak_mean_delay_s | 328.5 |
| co2_t | 1960.9 |
| nox_kg | 1045.9 |
| co2_peak_hour_t | 127.0 |
| vehicles_planned | 499904 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 5700.0 | 10.8 |
| Al Khamashiyah | 1572.0 | 2231.9 | 14.4 |
| Sinaiyah An Nahdah | 3664.0 | 2042.1 | 19.5 |
| Industrial Area | 5564.0 | 1813.2 | 27.4 |
| Hail Airport | 768.0 | 1651.4 | 29.1 |
| Sinaiyah Altaqadum | 2292.0 | 1545.3 | 25.9 |
| Al Talal | 4856.0 | 1523.6 | 27.1 |
| Ar Rasf | 4488.0 | 1495.0 | 20.9 |
| Al Jabal | 2624.0 | 1416.7 | 19.2 |
| Al Jamiah | 30764.0 | 1405.2 | 24.3 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 298009826#3 | 1056.41 | 58.8 |
| 107434808#1 | 1037.79 | 32.4 |
| 325327519#7 | 650.52 | 23.5 |
| 107434808#0 | 516.44 | 52.2 |
| 324857086#0 | 514.23 | 41.7 |
| 324857086#1 | 468.22 | 39.9 |
| 1359711042#6 | 448.08 | 47.7 |
| 325327519#5 | 447.0 | 34.8 |
| 323836222#2 | 356.86 | 66.2 |
| 298009826#0 | 344.12 | 63.4 |

## Provenance
seed 1 | config d3087540b097137a | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

