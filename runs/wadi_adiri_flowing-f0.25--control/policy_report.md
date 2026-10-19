# Policy report: Matched control for wadi_adiri_flowing (same vehicles re-routed, no policy)

> **synthetic demand, uncalibrated.** Tier A (meso), policy `matched_control` on day type `weekday` compared
> with the baseline `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy matched_control vs weekday baseline [synthetic demand, uncalibrated]: mean delay -11.3 %, AM-peak delay -11.3 %, VKT +0.2 %, VHT -6.6 %, CO2 -6.2 %**


## What the policy changed
- `remote_work`: eligible_workers_with_tour 7,213, remote_today 0, tours_removed 0, person_trips_removed 0, vehicles_removed 0, induced_tours_added 0, induced_person_trips_added 0, induced_vehicles_added 0

Routing: 124,976 vehicle trips; 119,290 kept their baseline
route, 5,686 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 881.5 | 782.2 | -99.3 | -11.3 | better |
| AM peak (06-09) mean delay (s) | 328.5 | 291.4 | -37.1 | -11.3 | better |
| mean speed (km/h) | 25.0 | 26.9 | 1.8 | +7.3 | better |
| vehicle-km (VKT) (km) | 5,094,966 | 5,105,525 | 10,559 | +0.2 | worse |
| vehicle-hours (VHT) (h) | 203,551 | 190,139 | -13,412 | -6.6 | better |
| vehicle-hours of delay (h) | 122,304 | 108,555 | -13,749 | -11.2 | better |
| vehicle trips completed | 499,456 | 499,584 | 128 | +0.0 |  |
| peak-hour departures (veh/h) | 53,908 | 53,936 | 28 | +0.1 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.108 | 0.0001 | +0.1 | worse |
| CO2 (t) | 1,960.9 | 1,839.9 | -121.0 | -6.2 | better |
| CO2 in the peak hour (t) | 127.0 | 122.0 | -5.0 | -3.9 | better |
| NOx (kg) | 1,045.9 | 985.9 | -60.0 | -5.7 | better |
| mean trip length (km) | 10.2 | 10.2 | 0.02 | +0.2 |  |
| teleports (quality flag) | 22,814 | 20,554 | -2,260 | -9.9 | better |
| teleports per loaded vehicle | 0.1825 | 0.1645 | -0.0181 | -9.9 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 92,732 | 18.6% | 18.6% | 328.5 | 291.4 |
| PM peak 16-19 | 81,180 | 81,216 | 16.2% | 16.3% | 1,428.2 | 1,271.0 |
| baseline peak hour 06:00 | 53,908 | 53,936 | 10.8% | 10.8% | 307.0 | 268.4 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,460 | 47.7 | 48.0 |
| 01 | 4,448 | 4,448 | 44.1 | 44.0 |
| 02 | 2,368 | 2,368 | 40.9 | 41.0 |
| 03 | 1,840 | 1,840 | 51.4 | 52.0 |
| 04 | 2,056 | 2,056 | 60.2 | 60.0 |
| 05 | 30,920 | 30,924 | 116.0 | 102.7 |
| 06 | 53,908 | 53,936 | 307.0 | 268.4 |
| 07 | 22,672 | 22,656 | 488.0 | 448.9 |
| 08 | 16,156 | 16,140 | 176.1 | 147.3 |
| 09 | 9,512 | 9,512 | 122.3 | 98.8 |
| 10 | 7,192 | 7,192 | 42.1 | 42.1 |
| 11 | 18,448 | 18,448 | 48.7 | 48.5 |
| 12 | 44,212 | 44,212 | 215.7 | 211.2 |
| 13 | 22,116 | 22,124 | 713.8 | 717.6 |
| 14 | 17,272 | 17,264 | 968.2 | 955.0 |
| 15 | 23,976 | 23,964 | 786.6 | 753.7 |
| 16 | 20,472 | 20,480 | 1,105.9 | 1,008.9 |
| 17 | 29,848 | 29,856 | 1,348.4 | 1,172.1 |
| 18 | 30,860 | 30,880 | 1,719.3 | 1,540.5 |
| 19 | 36,596 | 36,600 | 1,651.6 | 1,513.9 |
| 20 | 30,680 | 30,716 | 2,170.4 | 1,893.9 |
| 21 | 26,924 | 26,908 | 1,853.5 | 1,524.2 |
| 22 | 22,056 | 22,000 | 1,460.6 | 1,167.1 |
| 23 | 15,464 | 15,600 | 1,094.3 | 912.9 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
59 of 61 districts with at least 1,000 trips are better
off, 2 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Khamashiyah | 1572.0 | 1572.0 | 2231.9 | 1669.6 | -562.3 |
| Al Buhayrah | 4612.0 | 4596.0 | 1390.5 | 982.6 | -407.9 |
| Sinaiyah An Nahdah | 3664.0 | 3664.0 | 2042.1 | 1642.1 | -400.1 |
| Ar Rasf | 4488.0 | 4488.0 | 1495.0 | 1148.5 | -346.4 |
| As Samra | 3140.0 | 3140.0 | 697.2 | 396.3 | -300.9 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Samah | 3256.0 | 3248.0 | 1033.0 | 1056.1 | 23.1 |
| Al Fajr | 1332.0 | 1332.0 | 456.9 | 468.2 | 11.4 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 51790.9 | 47406.1 | 259 | -4384.7 |
| طريق الملك سعود بن عبدالعزيز | 16709.5 | 13369.2 | 114 | -3340.3 |
| طريق الملك فهد بن عبد العزيز | 1935.1 | 1231.2 | 86 | -703.9 |
| طريق مشار | 2344.3 | 1914.0 | 53 | -430.3 |
| شارع الفرج | 5511.7 | 5150.6 | 24 | -361.1 |
| 1084726666 | 275.7 | 1.4 | 1 | -274.4 |
| 1084932139#11 | 274.9 | 71.4 | 1 | -203.5 |
| 1191274599#0 | 1061.9 | 910.6 | 1 | -151.3 |
| شارع طلحة بن عبيدالله | 1038.9 | 893.5 | 13 | -145.4 |
| 350093266#3 | 387.7 | 251.6 | 1 | -136.0 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| شارع جدة | 665.0 | 715.9 | 28 | 50.9 |
| شارع قرطبة | 1222.7 | 1259.0 | 18 | 36.2 |
| شارع هارون الرشيد | 99.6 | 135.1 | 21 | 35.5 |
| شارع الأمير نايف بن عبدالعزيز | 220.8 | 240.8 | 43 | 20.0 |
| 553625016#11 | 279.6 | 294.1 | 1 | 14.5 |
| شارع حمود العقلاء | 8.2 | 17.5 | 8 | 9.4 |
| 324857088#1 | 2.2 | 8.9 | 1 | 6.7 |
| 369899761#1 | 0.6 | 7.1 | 1 | 6.5 |
| -1137524140 | 31.8 | 36.4 | 1 | 4.5 |
| شارع الأمير سلطان بن عبدالعزيز | 96.3 | 100.1 | 155 | 3.8 |

## Assumptions used
- Policy: (none)
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 2a311aadeecbf810 | 4b919e6cc7c56f15 | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | 66090e81fca81412 | 6f3258ac9d2f66cd | 0 | Eclipse SUMO sumo 1.28.0 |

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

