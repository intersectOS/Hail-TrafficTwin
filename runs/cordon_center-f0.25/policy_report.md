# Policy report: Cordon charge SAR 10 around central Hail, 07:00-19:00 (indicative)

> **synthetic demand, uncalibrated.** Tier A (meso), policy `cordon_center` on day type `weekday` compared
> with the baseline `cordon_center-f0.25--control` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy cordon_center vs weekday baseline [synthetic demand, uncalibrated]: mean delay +158.6 %, AM-peak delay +55.3 %, VKT +0.3 %, VHT +38.1 %, CO2 +34.1 %**


> **Compared with a matched control** (TA-018): `cordon_center-f0.25--control` is the baseline with the same
> 24,644 baseline vehicles re-routed (one-shot, at their baseline
> times, no policy). One-shot routes beat the baseline's 3-step assignment, so comparing with the
> raw baseline would credit the policy with that routing gain.

<details><summary>Against the raw baseline (includes the routing gain)</summary>

| KPI | raw baseline | policy | delta % |
|---|---|---|---|
| mean delay per trip | 881.5 | 528.1 | -40.1 |
| AM peak (06-09) mean delay | 328.5 | 407.0 | +23.9 |
| vehicle-km (VKT) | 5,094,966 | 5,185,180 | +1.8 |
| vehicle-hours (VHT) | 203,551 | 156,338 | -23.2 |
| CO2 | 1,960.9 | 1,532.8 | -21.8 |

</details>

## What the policy changed
- `road_pricing`: charged_edges 261, charged_vehicles 26,395, charged_tours 18,226, suppressed_share 0.096, tours_retimed_out_of_hours 520, vehicles_retimed 756, dropped_tours_removed 1,206, dropped_person_trips_removed 2,534, dropped_vehicles_removed 2,659, vehicles_rerouted_with_penalty 23,888, penalty_s 900.0

Routing: 122,317 vehicle trips; 97,673 kept their baseline
route, 24,644 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 204.2 | 528.1 | 323.9 | +158.6 | worse |
| AM peak (06-09) mean delay (s) | 262.1 | 407.0 | 144.9 | +55.3 | worse |
| mean speed (km/h) | 45.7 | 33.2 | -12.5 | -27.4 | worse |
| vehicle-km (VKT) (km) | 5,170,321 | 5,185,180 | 14,859 | +0.3 | worse |
| vehicle-hours (VHT) (h) | 113,191 | 156,338 | 43,147 | +38.1 | worse |
| vehicle-hours of delay (h) | 28,343 | 71,756 | 43,413 | +153.2 | worse |
| vehicle trips completed | 499,764 | 489,148 | -10,616 | -2.1 |  |
| peak-hour departures (veh/h) | 53,908 | 53,996 | 88 | +0.2 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.1104 | 0.0025 | +2.3 | worse |
| CO2 (t) | 1,143.4 | 1,532.8 | 389.4 | +34.1 | worse |
| CO2 in the peak hour (t) | 125.9 | 122.1 | -3.8 | -3.0 | better |
| NOx (kg) | 641.6 | 823.1 | 181.5 | +28.3 | worse |
| mean trip length (km) | 10.3 | 10.6 | 0.25 | +2.4 |  |
| teleports (quality flag) | 4,787 | 12,822 | 8,035 | +167.8 | worse |
| teleports per loaded vehicle | 0.0383 | 0.1048 | 0.0665 | +173.7 | worse |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 90,876 | 18.6% | 18.6% | 262.1 | 407.0 |
| PM peak 16-19 | 81,256 | 77,912 | 16.3% | 15.9% | 259.2 | 962.0 |
| baseline peak hour 06:00 | 53,908 | 53,996 | 10.8% | 11.0% | 298.5 | 266.1 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,412 | 47.7 | 47.1 |
| 01 | 4,448 | 4,420 | 44.1 | 45.2 |
| 02 | 2,368 | 2,328 | 40.9 | 42.0 |
| 03 | 1,840 | 1,792 | 51.4 | 49.7 |
| 04 | 2,056 | 1,972 | 60.2 | 59.5 |
| 05 | 30,920 | 30,364 | 116.0 | 99.3 |
| 06 | 53,908 | 53,996 | 298.5 | 266.1 |
| 07 | 22,700 | 21,592 | 297.5 | 586.9 |
| 08 | 16,128 | 15,288 | 90.8 | 650.9 |
| 09 | 9,512 | 9,156 | 51.0 | 582.1 |
| 10 | 7,192 | 6,840 | 41.6 | 439.8 |
| 11 | 18,448 | 17,772 | 46.5 | 272.0 |
| 12 | 44,212 | 42,836 | 57.2 | 248.8 |
| 13 | 22,136 | 21,356 | 64.2 | 587.8 |
| 14 | 17,256 | 16,260 | 91.9 | 725.8 |
| 15 | 23,988 | 22,924 | 102.2 | 509.5 |
| 16 | 20,448 | 19,520 | 135.8 | 843.8 |
| 17 | 29,860 | 28,660 | 285.9 | 1,064.6 |
| 18 | 30,948 | 29,732 | 315.0 | 940.6 |
| 19 | 36,676 | 38,020 | 236.6 | 643.8 |
| 20 | 30,868 | 30,532 | 336.3 | 692.2 |
| 21 | 27,044 | 27,084 | 375.7 | 707.3 |
| 22 | 21,936 | 21,912 | 399.0 | 548.7 |
| 23 | 15,412 | 15,380 | 292.7 | 375.1 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
1 of 61 districts with at least 1,000 trips are better
off, 60 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Qfaar | 7752.0 | 7668.0 | 153.4 | 145.3 | -8.1 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Masif | 3136.0 | 3084.0 | 102.8 | 1617.3 | 1514.4 |
| Aja | 66664.0 | 65708.0 | 183.6 | 1137.9 | 954.3 |
| Al Jamiah | 30764.0 | 30288.0 | 113.3 | 977.8 | 864.5 |
| Mashar | 1724.0 | 1708.0 | 119.1 | 967.4 | 848.2 |
| Safanah | 9752.0 | 9664.0 | 117.2 | 872.8 | 755.6 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 3411.3 | 2764.9 | 259 | -646.4 |
| شارع أمير المؤمنين عمر بن الخطاب | 1034.3 | 568.8 | 86 | -465.5 |
| طريق الملك سعود بن عبدالعزيز | 770.2 | 594.2 | 114 | -175.9 |
| شارع البراري | 544.0 | 369.6 | 4 | -174.4 |
| شارع الظهران | 2187.6 | 2041.5 | 19 | -146.2 |
| شارع أبي العلاء المعري | 188.9 | 130.2 | 12 | -58.7 |
| شارع الشيخ محمد بن صالح العثيمين | 126.4 | 73.8 | 55 | -52.6 |
| شارع قرطبة | 1412.8 | 1377.6 | 18 | -35.2 |
| 132087647#0 | 107.6 | 78.5 | 1 | -29.1 |
| شارع الأمير عبدالعزيز بن سعد بن عبدالعزيز | 208.6 | 180.1 | 107 | -28.6 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| شارع جدة | 514.5 | 11415.9 | 28 | 10901.4 |
| طريق جبة | 165.5 | 9090.1 | 48 | 8924.6 |
| طريق مشار | 316.4 | 4946.4 | 53 | 4630.1 |
| شارع أحمد بن سعيد الأندلسي | 20.2 | 2562.9 | 18 | 2542.7 |
| شارع النعمان بن عمرو | 3618.4 | 5497.6 | 43 | 1879.2 |
| طريق مكة المكرمة | 1251.8 | 3033.8 | 85 | 1782.0 |
| 324069547#7 | 290.3 | 1361.9 | 1 | 1071.6 |
| 324069547#6 | 99.8 | 964.5 | 1 | 864.6 |
| 324069547#5-AddedOnRampEdge | 17.7 | 819.6 | 1 | 801.9 |
| شارع أمير المؤمنين علي بن أبي طالب | 14.6 | 780.2 | 30 | 765.6 |

## Assumptions used
- Policy: A-pol-040, A-pol-041, A-pol-042
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 64559c1f2183dbda | 01cacc8b7370cbba | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | 879ce9bdffef4627 | 89097f2e67942372 | 0 | Eclipse SUMO sumo 1.28.0 |

## Caveats
- Incremental routing (TA-014, A-pol-090): vehicles whose trip the policy does not touch keep their
  baseline route; new, re-timed, re-moded or affected vehicles get a one-shot shortest path on the
  starting baseline's congested travel times. There is no re-equilibration, so drivers who would
  re-route into freed (or away from added) congestion do not: deltas are first-order.
- The city baseline is gridlock-affected in both peaks (TA-011, docs/status/trackA.md): teleports
  are reported as a quality flag; read deltas in peak hours with care.
- Results are for one seed and a 10 % population sample with capacity scaling (A-sim-101,
  unvalidated); differences of a few percent are within the run-to-run noise of meso gridlock.

### Meso fidelity (PROJECT.md 9.4)
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

