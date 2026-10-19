# Policy report: Matched control for cordon_center (same vehicles re-routed, no policy)

> **synthetic demand, uncalibrated.** Tier A (meso), policy `matched_control` on day type `weekday` compared
> with the baseline `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy matched_control vs weekday baseline [synthetic demand, uncalibrated]: mean delay -76.8 %, AM-peak delay -20.2 %, VKT +1.5 %, VHT -44.4 %, CO2 -41.7 %**


## What the policy changed
- `remote_work`: eligible_workers_with_tour 7,213, remote_today 0, tours_removed 0, person_trips_removed 0, vehicles_removed 0, induced_tours_added 0, induced_person_trips_added 0, induced_vehicles_added 0

Routing: 124,976 vehicle trips; 100,332 kept their baseline
route, 24,644 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 881.5 | 204.2 | -677.3 | -76.8 | better |
| AM peak (06-09) mean delay (s) | 328.5 | 262.1 | -66.4 | -20.2 | better |
| mean speed (km/h) | 25.0 | 45.7 | 20.6 | +82.5 | better |
| vehicle-km (VKT) (km) | 5,094,966 | 5,170,321 | 75,355 | +1.5 | worse |
| vehicle-hours (VHT) (h) | 203,551 | 113,191 | -90,360 | -44.4 | better |
| vehicle-hours of delay (h) | 122,304 | 28,343 | -93,961 | -76.8 | better |
| vehicle trips completed | 499,456 | 499,764 | 308 | +0.1 |  |
| peak-hour departures (veh/h) | 53,908 | 53,908 | 0 | +0.0 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.1079 | 0 | +0.0 |  |
| CO2 (t) | 1,960.9 | 1,143.4 | -817.5 | -41.7 | better |
| CO2 in the peak hour (t) | 127.0 | 125.9 | -1.1 | -0.9 | better |
| NOx (kg) | 1,045.9 | 641.6 | -404.3 | -38.7 | better |
| mean trip length (km) | 10.2 | 10.3 | 0.15 | +1.5 |  |
| teleports (quality flag) | 22,814 | 4,787 | -18,027 | -79.0 | better |
| teleports per loaded vehicle | 0.1825 | 0.0383 | -0.1442 | -79.0 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 92,736 | 18.6% | 18.6% | 328.5 | 262.1 |
| PM peak 16-19 | 81,180 | 81,256 | 16.2% | 16.3% | 1,428.2 | 259.2 |
| baseline peak hour 06:00 | 53,908 | 53,908 | 10.8% | 10.8% | 307.0 | 298.5 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,460 | 47.7 | 47.7 |
| 01 | 4,448 | 4,448 | 44.1 | 44.1 |
| 02 | 2,368 | 2,368 | 40.9 | 40.9 |
| 03 | 1,840 | 1,840 | 51.4 | 51.4 |
| 04 | 2,056 | 2,056 | 60.2 | 60.2 |
| 05 | 30,920 | 30,920 | 116.0 | 116.0 |
| 06 | 53,908 | 53,908 | 307.0 | 298.5 |
| 07 | 22,672 | 22,700 | 488.0 | 297.5 |
| 08 | 16,156 | 16,128 | 176.1 | 90.8 |
| 09 | 9,512 | 9,512 | 122.3 | 51.0 |
| 10 | 7,192 | 7,192 | 42.1 | 41.6 |
| 11 | 18,448 | 18,448 | 48.7 | 46.5 |
| 12 | 44,212 | 44,212 | 215.7 | 57.2 |
| 13 | 22,116 | 22,136 | 713.8 | 64.2 |
| 14 | 17,272 | 17,256 | 968.2 | 91.9 |
| 15 | 23,976 | 23,988 | 786.6 | 102.2 |
| 16 | 20,472 | 20,448 | 1,105.9 | 135.8 |
| 17 | 29,848 | 29,860 | 1,348.4 | 285.9 |
| 18 | 30,860 | 30,948 | 1,719.3 | 315.0 |
| 19 | 36,596 | 36,676 | 1,651.6 | 236.6 |
| 20 | 30,680 | 30,868 | 2,170.4 | 336.3 |
| 21 | 26,924 | 27,044 | 1,853.5 | 375.7 |
| 22 | 22,056 | 21,936 | 1,460.6 | 399.0 |
| 23 | 15,464 | 15,412 | 1,094.3 | 292.7 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
61 of 61 districts with at least 1,000 trips are better
off, 0 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Khamashiyah | 1572.0 | 1572.0 | 2231.9 | 195.8 | -2036.1 |
| Sinaiyah An Nahdah | 3664.0 | 3664.0 | 2042.1 | 208.7 | -1833.5 |
| Industrial Area | 5564.0 | 5564.0 | 1813.2 | 252.8 | -1560.5 |
| Sinaiyah Altaqadum | 2292.0 | 2292.0 | 1545.3 | 198.5 | -1346.7 |
| Al Talal | 4856.0 | 4856.0 | 1523.6 | 199.6 | -1324.0 |

Losers
(none)

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 51790.9 | 3411.3 | 259 | -48379.6 |
| طريق الملك سعود بن عبدالعزيز | 16709.5 | 770.2 | 114 | -15939.3 |
| شارع الفرج | 5511.7 | 28.0 | 24 | -5483.6 |
| طريق مشار | 2344.3 | 316.4 | 53 | -2028.0 |
| طريق الملك فهد بن عبد العزيز | 1935.1 | 17.6 | 86 | -1917.4 |
| شارع الشيخ محمد بن صالح العثيمين | 1930.0 | 126.4 | 55 | -1803.6 |
| شارع طلحة بن عبيدالله | 1038.9 | 31.4 | 13 | -1007.5 |
| شارع الملك خالد | 919.3 | 70.8 | 43 | -848.5 |
| 1191274599#0 | 1061.9 | 270.4 | 1 | -791.5 |
| 298009837 | 595.5 | 1.6 | 1 | -593.9 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| شارع النعمان بن عمرو | 689.5 | 3618.4 | 43 | 2929.0 |
| شارع الظهران | 1262.7 | 2187.6 | 19 | 924.9 |
| طريق مكة المكرمة | 632.4 | 1251.8 | 85 | 619.5 |
| شارع أمير المؤمنين عمر بن الخطاب | 598.6 | 1034.3 | 86 | 435.7 |
| شارع جرير | 188.3 | 543.4 | 49 | 355.1 |
| شارع البراري | 289.0 | 544.0 | 4 | 255.0 |
| 324069547#7 | 54.9 | 290.3 | 1 | 235.4 |
| شارع قرطبة | 1222.7 | 1412.8 | 18 | 190.1 |
| شارع محمد بن عبدالوهاب | 224.2 | 358.3 | 15 | 134.0 |
| شارع أبي العلاء المعري | 76.8 | 188.9 | 12 | 112.1 |

## Assumptions used
- Policy: (none)
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 3ca64e9a6d7d10c6 | 2782b40fd601ca48 | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | 66090e81fca81412 | b2c54f6afd03637a | 0 | Eclipse SUMO sumo 1.28.0 |

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

