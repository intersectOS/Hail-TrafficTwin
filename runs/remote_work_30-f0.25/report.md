# Run remote_work_30-f0.25

> **synthetic demand, uncalibrated.** Tier A (meso), day type `weekday` (2026-10-18), seed 1, population sample
> 25.0 % with capacity scaling x4. Totals are scaled to the full city.

| KPI | value |
|---|---|
| trips_completed | 491564 |
| trips_completed_sampled | 122891 |
| vehicles_loaded_sampled | 122967 |
| teleports | 19198 |
| teleport_share | 0.156123 |
| mean_delay_s | 754.3 |
| mean_time_loss_s | 746.3 |
| mean_depart_delay_s | 8.0 |
| mean_duration_s | 1342.2 |
| mean_trip_km | 10.17 |
| mean_speed_kmh | 27.28 |
| vkt | 4998794 |
| vht | 183266 |
| vht_delay | 102998 |
| throughput_peak_hour_trips | 52920 |
| peak_hour | 6 |
| peak_spreading_top_hour_share | 0.1077 |
| am_peak_mean_delay_s | 259.1 |
| co2_t | 1775.0 |
| nox_kg | 954.1 |
| co2_peak_hour_t | 112.2 |
| vehicles_planned | 491868 |
| completion_share | 1.0 |

## Per district (top 10 by mean delay)
| name_en | trips | mean_delay_s | mean_speed_kmh |
|---|---|---|---|
| Al Sahab | 16.0 | 3811.9 | 15.2 |
| Al Khamashiyah | 1568.0 | 1504.9 | 19.1 |
| Al Qirawan | 128.0 | 1498.3 | 24.7 |
| Al Jamiah | 30524.0 | 1469.7 | 23.6 |
| Hail Airport | 768.0 | 1404.4 | 32.0 |
| Aljathamiuh | 220.0 | 1349.0 | 30.0 |
| Sinaiyah An Nahdah | 3664.0 | 1307.5 | 26.2 |
| Industrial Area | 5160.0 | 1270.9 | 33.8 |
| Al Buhayrah | 4516.0 | 1195.3 | 21.7 |
| Al Jabal | 2584.0 | 1157.2 | 22.1 |

## Most delayed edges (sampled vehicle-hours of time loss)
| edge_id | time_loss_veh_h_sampled | mean_speed_kmh |
|---|---|---|
| 107434808#1 | 995.57 | 34.3 |
| 298009826#3 | 903.34 | 62.0 |
| 107434808#0 | 665.52 | 51.3 |
| 325327519#7 | 637.94 | 21.0 |
| 324857086#0 | 463.37 | 45.9 |
| 324857086#1 | 443.86 | 42.3 |
| 1359711042#6 | 425.59 | 50.2 |
| 325327519#5 | 387.21 | 36.0 |
| 325327519#8 | 281.25 | 17.1 |
| 325045178#2 | 279.82 | 72.9 |

## Provenance
seed 1 | config 812285a180a42888 | population 765732190ffb2223 | network addfcb64bedc9fa3 |
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

