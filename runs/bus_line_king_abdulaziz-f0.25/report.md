# Run bus_line_king_abdulaziz-f0.25

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 500212 |
| trips_completed_sampled | 125053 |
| vehicles_loaded_sampled | 125127 |
| teleports | 22190 |
| teleport_share | 0.17734 |
| mean_delay_s | 859.3 |
| mean_time_loss_s | 848.2 |
| mean_depart_delay_s | 11.1 |
| mean_duration_s | 1445.7 |
| mean_trip_km | 10.22 |
| mean_speed_kmh | 25.45 |
| vkt | 5111943 |
| vht | 200881 |
| vht_delay | 119405 |
| throughput_peak_hour_trips | 53952 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1079 |
| am_peak_mean_delay_s | 329.4 |
| co2_t | 1949.8 |
| nox_kg | 1056.3 |
| co2_peak_hour_t | 127.8 |
| vehicles_planned | 499692 |
| completion_share | 1.0016 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 5917.2 | 10.3 |
| Al Khamashiyah | 1564.0 | 2257.1 | 14.6 |
| Sinaiyah An Nahdah | 3660.0 | 1987.0 | 19.9 |
| Industrial Area | 5564.0 | 1752.8 | 28.1 |
| Al Talal | 4856.0 | 1521.0 | 27.0 |
| Sinaiyah Altaqadum | 2288.0 | 1475.5 | 26.6 |
| Ar Rasf | 4488.0 | 1455.1 | 21.3 |
| Al Jabal | 2624.0 | 1420.5 | 19.2 |
| Aljathamiuh | 224.0 | 1338.5 | 30.6 |
| Al Jamiah | 30764.0 | 1310.0 | 25.4 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 107434808#1 | 1083.97 | 30.6 |
| 298009826#3 | 1047.78 | 59.4 |
| 325327519#7 | 661.78 | 22.6 |
| 107434808#0 | 655.58 | 44.2 |
| 324857086#0 | 464.24 | 39.4 |
| 324857086#1 | 447.36 | 41.1 |
| 325327519#5 | 433.38 | 34.9 |
| 1359711042#6 | 398.98 | 52.5 |
| 323836222#2 | 351.05 | 66.3 |
| 1084650194#2 | 349.32 | 76.0 |

## Provenance
seed 1 | config e5e21a9522d28a6c | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

