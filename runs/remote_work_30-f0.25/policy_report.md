# Policy report: 30 % hybrid work (government + private office), 3 remote days/week

> **synthetic demand, uncalibrated.** Tier A (meso), policy `remote_work_30` on day type `weekday` compared
> with the baseline `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy remote_work_30 vs weekday baseline [synthetic demand, uncalibrated]: mean delay -14.4 %, AM-peak delay -21.1 %, VKT -1.9 %, VHT -10.0 %, CO2 -9.5 %**


## What the policy changed
- `remote_work`: eligible_workers_with_tour 13,219, remote_today 2,359, tours_removed 2,359, person_trips_removed 5,104, vehicles_removed 2,967, induced_tours_added 847, induced_person_trips_added 1,694, induced_vehicles_added 958

Routing: 122,967 vehicle trips; 122,009 kept their baseline
route, 958 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 881.5 | 754.3 | -127.2 | -14.4 | better |
| AM peak (06-09) mean delay (s) | 328.5 | 259.1 | -69.4 | -21.1 | better |
| mean speed (km/h) | 25.0 | 27.3 | 2.2 | +9.0 | better |
| vehicle-km (VKT) (km) | 5,094,966 | 4,998,794 | -96,172 | -1.9 | better |
| vehicle-hours (VHT) (h) | 203,551 | 183,266 | -20,285 | -10.0 | better |
| vehicle-hours of delay (h) | 122,304 | 102,998 | -19,306 | -15.8 | better |
| vehicle trips completed | 499,456 | 491,564 | -7,892 | -1.6 |  |
| peak-hour departures (veh/h) | 53,908 | 52,920 | -988 | -1.8 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.1077 | -0.0002 | -0.2 | better |
| CO2 (t) | 1,960.9 | 1,775.0 | -185.9 | -9.5 | better |
| CO2 in the peak hour (t) | 127.0 | 112.2 | -14.8 | -11.7 | better |
| NOx (kg) | 1,045.9 | 954.1 | -91.8 | -8.8 | better |
| mean trip length (km) | 10.2 | 10.2 | -0.03 | -0.3 |  |
| teleports (quality flag) | 22,814 | 19,198 | -3,616 | -15.8 | better |
| teleports per loaded vehicle | 0.1825 | 0.1561 | -0.0264 | -14.5 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 87,704 | 18.6% | 17.8% | 328.5 | 259.1 |
| PM peak 16-19 | 81,180 | 78,360 | 16.2% | 15.9% | 1,428.2 | 1,050.0 |
| baseline peak hour 06:00 | 53,908 | 52,920 | 10.8% | 10.8% | 307.0 | 224.1 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,528 | 47.7 | 46.2 |
| 01 | 4,448 | 4,460 | 44.1 | 44.4 |
| 02 | 2,368 | 2,368 | 40.9 | 41.1 |
| 03 | 1,840 | 1,840 | 51.4 | 52.4 |
| 04 | 2,056 | 2,056 | 60.2 | 61.2 |
| 05 | 30,920 | 30,920 | 116.0 | 92.1 |
| 06 | 53,908 | 52,920 | 307.0 | 224.1 |
| 07 | 22,672 | 20,072 | 488.0 | 422.7 |
| 08 | 16,156 | 14,712 | 176.1 | 161.6 |
| 09 | 9,512 | 9,464 | 122.3 | 110.9 |
| 10 | 7,192 | 7,688 | 42.1 | 40.9 |
| 11 | 18,448 | 18,880 | 48.7 | 51.6 |
| 12 | 44,212 | 44,548 | 215.7 | 241.3 |
| 13 | 22,116 | 22,128 | 713.8 | 785.9 |
| 14 | 17,272 | 16,016 | 968.2 | 970.1 |
| 15 | 23,976 | 22,680 | 786.6 | 711.9 |
| 16 | 20,472 | 19,132 | 1,105.9 | 829.1 |
| 17 | 29,848 | 28,700 | 1,348.4 | 871.1 |
| 18 | 30,860 | 30,528 | 1,719.3 | 1,356.6 |
| 19 | 36,596 | 36,852 | 1,651.6 | 1,471.7 |
| 20 | 30,680 | 31,088 | 2,170.4 | 1,879.7 |
| 21 | 26,924 | 27,200 | 1,853.5 | 1,625.0 |
| 22 | 22,056 | 22,180 | 1,460.6 | 1,281.0 |
| 23 | 15,464 | 15,604 | 1,094.3 | 931.9 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
58 of 61 districts with at least 1,000 trips are better
off, 3 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Sinaiyah An Nahdah | 3664.0 | 3664.0 | 2042.1 | 1307.5 | -734.6 |
| Al Khamashiyah | 1572.0 | 1568.0 | 2231.9 | 1504.9 | -727.0 |
| Sinaiyah Altaqadum | 2292.0 | 2296.0 | 1545.3 | 995.2 | -550.1 |
| Industrial Area | 5564.0 | 5160.0 | 1813.2 | 1270.9 | -542.4 |
| Al Talal | 4856.0 | 4524.0 | 1523.6 | 1038.4 | -485.2 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| An Nasiyah | 2684.0 | 2660.0 | 870.5 | 951.9 | 81.5 |
| Al Jamiah | 30764.0 | 30524.0 | 1405.2 | 1469.7 | 64.5 |
| Ar Rawabi | 3112.0 | 3120.0 | 899.4 | 934.3 | 34.9 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 51790.9 | 44574.6 | 259 | -7216.3 |
| طريق الملك سعود بن عبدالعزيز | 16709.5 | 12308.9 | 114 | -4400.6 |
| طريق مشار | 2344.3 | 1756.4 | 53 | -588.0 |
| شارع طلحة بن عبيدالله | 1038.9 | 453.6 | 13 | -585.3 |
| طريق الملك فهد بن عبد العزيز | 1935.1 | 1366.0 | 86 | -569.1 |
| شارع الفرج | 5511.7 | 5239.5 | 24 | -272.2 |
| 1084726666 | 275.7 | 39.4 | 1 | -236.3 |
| 1084932139#11 | 274.9 | 92.7 | 1 | -182.2 |
| شارع الملك خالد | 919.3 | 762.6 | 43 | -156.7 |
| 350093266#3 | 387.7 | 236.1 | 1 | -151.6 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| 553625016#11 | 279.6 | 586.7 | 1 | 307.1 |
| 553625016#10 | 8.9 | 170.0 | 1 | 161.1 |
| 553625016#7 | 13.4 | 92.9 | 1 | 79.5 |
| 553625016#13 | 64.2 | 136.9 | 1 | 72.7 |
| 107434755 | 36.8 | 107.1 | 1 | 70.3 |
| شارع جدة | 665.0 | 717.6 | 28 | 52.6 |
| 553625016#14 | 50.9 | 94.0 | 1 | 43.0 |
| 107434743#1 | 70.8 | 101.5 | 1 | 30.7 |
| 1191274601#2-AddedOnRampEdge | 67.9 | 94.3 | 1 | 26.4 |
| 844332859#6 | 45.0 | 68.6 | 1 | 23.6 |

## Assumptions used
- Policy: A-pol-001, A-pol-002
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 812285a180a42888 | 951e7175a9e93e34 | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | caa66550344dd218 | 94ec9f89edb7b147 | 0 | Eclipse SUMO sumo 1.28.0 |

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

