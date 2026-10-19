# Run cordon_center-f0.25

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 489148 |
| trips_completed_sampled | 122287 |
| vehicles_loaded_sampled | 122317 |
| teleports | 12822 |
| teleport_share | 0.104826 |
| mean_delay_s | 528.1 |
| mean_time_loss_s | 517.5 |
| mean_depart_delay_s | 10.6 |
| mean_duration_s | 1150.6 |
| mean_trip_km | 10.6 |
| mean_speed_kmh | 33.17 |
| vkt | 5185180 |
| vht | 156338 |
| vht_delay | 71756 |
| throughput_peak_hour_trips | 53996 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1104 |
| am_peak_mean_delay_s | 407.0 |
| co2_t | 1532.8 |
| nox_kg | 823.1 |
| co2_peak_hour_t | 122.1 |
| vehicles_planned | 489268 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Masif | 3084.0 | 1617.3 | 16.8 |
| Al Muruj | 620.0 | 1516.7 | 23.0 |
| Aja | 65708.0 | 1137.9 | 20.0 |
| Al Jamiah | 30288.0 | 977.8 | 30.3 |
| Mashar | 1708.0 | 967.4 | 25.9 |
| Safanah | 9664.0 | 872.8 | 29.4 |
| Sadyan | 10692.0 | 857.3 | 23.9 |
| Al Fayha | 192.0 | 851.2 | 31.7 |
| An Nasiyah | 2664.0 | 754.6 | 29.8 |
| Aljathamiuh | 224.0 | 725.8 | 42.3 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 1358446140#1 | 1693.26 | 24.5 |
| 324069639#1 | 1272.32 | 34.1 |
| 107425879#8 | 996.14 | 22.5 |
| 350093246#4 | 751.53 | 28.6 |
| 1358446140#5 | 731.53 | 16.8 |
| 350093242#0 | 639.05 | 19.1 |
| 324069547#7 | 340.47 | 19.8 |
| 107430742#11 | 274.28 | 50.8 |
| 324069547#6 | 241.11 | 19.2 |
| 324069654#2 | 240.94 | 46.6 |

## Provenance
seed 1 | config 64559c1f2183dbda | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

