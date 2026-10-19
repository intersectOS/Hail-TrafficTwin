# Run cordon_center-f0.25--control

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 499764 |
| trips_completed_sampled | 124941 |
| vehicles_loaded_sampled | 124976 |
| teleports | 4787 |
| teleport_share | 0.038303 |
| mean_delay_s | 204.2 |
| mean_time_loss_s | 202.3 |
| mean_depart_delay_s | 1.9 |
| mean_duration_s | 815.4 |
| mean_trip_km | 10.35 |
| mean_speed_kmh | 45.68 |
| vkt | 5170321 |
| vht | 113191 |
| vht_delay | 28343 |
| throughput_peak_hour_trips | 53908 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1079 |
| am_peak_mean_delay_s | 262.1 |
| co2_t | 1143.4 |
| nox_kg | 641.6 |
| co2_peak_hour_t | 125.9 |
| vehicles_planned | 499904 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Muruj | 632.0 | 779.1 | 24.6 |
| Alwasita | 5880.0 | 408.8 | 31.0 |
| zone 20 | 2964.0 | 377.7 | 39.4 |
| Jawharah Alwasita | 62204.0 | 319.5 | 33.8 |
| Al Naeam | 904.0 | 307.8 | 34.8 |
| Al Bawadi | 2992.0 | 289.1 | 36.8 |
| Al Wurud | 788.0 | 286.7 | 36.3 |
| As Salam | 23664.0 | 279.3 | 38.6 |
| Al Fajr | 1332.0 | 273.5 | 43.0 |
| Samah | 3260.0 | 253.5 | 39.8 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 350093246#4 | 616.78 | 32.4 |
| 131726936#1 | 251.28 | 28.9 |
| 107430300#40 | 138.77 | 14.6 |
| 131726936#7 | 137.11 | 22.8 |
| 131726931#8 | 135.63 | 27.8 |
| 131726931#7 | 129.57 | 33.6 |
| 107434808#1 | 111.26 | 66.8 |
| 107430742#6 | 108.33 | 38.8 |
| 350093246#5 | 98.03 | 28.9 |
| 131771271#18 | 93.01 | 30.0 |

## Provenance
seed 1 | config 3ca64e9a6d7d10c6 | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

