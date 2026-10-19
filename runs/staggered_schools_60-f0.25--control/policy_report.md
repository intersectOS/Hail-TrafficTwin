# Policy report: Matched control for staggered_schools_60 (same vehicles re-routed, no policy)

> **synthetic demand, uncalibrated.** Tier A (meso), policy `matched_control` on day type `weekday` compared
> with the baseline `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy matched_control vs weekday baseline [synthetic demand, uncalibrated]: mean delay -18.8 %, AM-peak delay +18.5 %, VKT +0.2 %, VHT -11.1 %, CO2 -10.3 %**


## What the policy changed
- `remote_work`: eligible_workers_with_tour 7,213, remote_today 0, tours_removed 0, person_trips_removed 0, vehicles_removed 0, induced_tours_added 0, induced_person_trips_added 0, induced_vehicles_added 0

Routing: 124,976 vehicle trips; 115,180 kept their baseline
route, 9,796 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 881.5 | 715.5 | -166.0 | -18.8 | better |
| AM peak (06-09) mean delay (s) | 328.5 | 389.4 | 60.9 | +18.5 | worse |
| mean speed (km/h) | 25.0 | 28.2 | 3.2 | +12.6 | better |
| vehicle-km (VKT) (km) | 5,094,966 | 5,102,907 | 7,941 | +0.2 | worse |
| vehicle-hours (VHT) (h) | 203,551 | 181,038 | -22,513 | -11.1 | better |
| vehicle-hours of delay (h) | 122,304 | 99,295 | -23,009 | -18.8 | better |
| vehicle trips completed | 499,456 | 499,620 | 164 | +0.0 |  |
| peak-hour departures (veh/h) | 53,908 | 53,896 | -12 | -0.0 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.1079 | 0 | +0.0 |  |
| CO2 (t) | 1,960.9 | 1,759.0 | -201.9 | -10.3 | better |
| CO2 in the peak hour (t) | 127.0 | 132.7 | 5.7 | +4.5 | worse |
| NOx (kg) | 1,045.9 | 948.7 | -97.2 | -9.3 | better |
| mean trip length (km) | 10.2 | 10.2 | 0.01 | +0.1 |  |
| teleports (quality flag) | 22,814 | 18,580 | -4,234 | -18.6 | better |
| teleports per loaded vehicle | 0.1825 | 0.1487 | -0.0339 | -18.6 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 92,728 | 18.6% | 18.6% | 328.5 | 389.4 |
| PM peak 16-19 | 81,180 | 81,236 | 16.2% | 16.3% | 1,428.2 | 914.6 |
| baseline peak hour 06:00 | 53,908 | 53,896 | 10.8% | 10.8% | 307.0 | 342.7 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,460 | 47.7 | 47.7 |
| 01 | 4,448 | 4,448 | 44.1 | 44.1 |
| 02 | 2,368 | 2,368 | 40.9 | 40.9 |
| 03 | 1,840 | 1,840 | 51.4 | 51.4 |
| 04 | 2,056 | 2,056 | 60.2 | 60.2 |
| 05 | 30,920 | 30,928 | 116.0 | 157.5 |
| 06 | 53,908 | 53,896 | 307.0 | 342.7 |
| 07 | 22,672 | 22,676 | 488.0 | 597.2 |
| 08 | 16,156 | 16,156 | 176.1 | 253.6 |
| 09 | 9,512 | 9,512 | 122.3 | 132.3 |
| 10 | 7,192 | 7,192 | 42.1 | 42.3 |
| 11 | 18,448 | 18,448 | 48.7 | 47.6 |
| 12 | 44,212 | 44,216 | 215.7 | 118.3 |
| 13 | 22,116 | 22,132 | 713.8 | 342.5 |
| 14 | 17,272 | 17,256 | 968.2 | 697.6 |
| 15 | 23,976 | 23,980 | 786.6 | 588.7 |
| 16 | 20,472 | 20,464 | 1,105.9 | 690.8 |
| 17 | 29,848 | 29,868 | 1,348.4 | 711.9 |
| 18 | 30,860 | 30,904 | 1,719.3 | 1,258.6 |
| 19 | 36,596 | 36,632 | 1,651.6 | 1,488.5 |
| 20 | 30,680 | 30,692 | 2,170.4 | 1,899.8 |
| 21 | 26,924 | 26,952 | 1,853.5 | 1,659.0 |
| 22 | 22,056 | 22,060 | 1,460.6 | 1,291.4 |
| 23 | 15,464 | 15,484 | 1,094.3 | 890.0 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
59 of 61 districts with at least 1,000 trips are better
off, 2 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Jamiah | 30764.0 | 30764.0 | 1405.2 | 733.4 | -671.8 |
| Al Khamashiyah | 1572.0 | 1572.0 | 2231.9 | 1672.1 | -559.7 |
| Sinaiyah An Nahdah | 3664.0 | 3664.0 | 2042.1 | 1496.7 | -545.5 |
| Industrial Area | 5564.0 | 5564.0 | 1813.2 | 1310.4 | -502.9 |
| Ar Rawabi | 3112.0 | 3112.0 | 899.4 | 470.6 | -428.8 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Masif | 3136.0 | 3136.0 | 325.6 | 504.4 | 178.8 |
| Al Fajr | 1332.0 | 1332.0 | 456.9 | 491.6 | 34.7 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 51790.9 | 39184.8 | 259 | -12606.1 |
| طريق الملك سعود بن عبدالعزيز | 16709.5 | 13713.4 | 114 | -2996.1 |
| شارع الفرج | 5511.7 | 3214.6 | 24 | -2297.0 |
| طريق الملك فهد بن عبد العزيز | 1935.1 | 1560.5 | 86 | -374.6 |
| شارع الشيخ محمد بن صالح العثيمين | 1930.0 | 1698.6 | 55 | -231.5 |
| 553625016#11 | 279.6 | 56.7 | 1 | -222.9 |
| شارع طلحة بن عبيدالله | 1038.9 | 820.8 | 13 | -218.1 |
| شارع الظهران | 1262.7 | 1070.5 | 19 | -192.2 |
| 1084932139#11 | 274.9 | 117.7 | 1 | -157.2 |
| 1084726666 | 275.7 | 143.5 | 1 | -132.2 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق جبة | 90.6 | 1115.8 | 48 | 1025.2 |
| طريق مشار | 2344.3 | 2622.1 | 53 | 277.7 |
| 1191274599#0 | 1061.9 | 1109.4 | 1 | 47.5 |
| 324069724#7 | 0.5 | 31.6 | 1 | 31.1 |
| 324069724#3 | 1.8 | 30.5 | 1 | 28.6 |
| 324069724#1 | 5.3 | 33.8 | 1 | 28.5 |
| شارع موسى بن نصير | 105.7 | 133.2 | 14 | 27.5 |
| 324069724#5 | 0.4 | 20.9 | 1 | 20.5 |
| شارع قرطبة | 1222.7 | 1241.7 | 18 | 19.0 |
| 131723007#3 | 29.7 | 45.3 | 1 | 15.6 |

## Assumptions used
- Policy: (none)
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 4fc090bd14afa616 | 7426f478c62298fb | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | 66090e81fca81412 | 3ab4c8e789163d38 | 0 | Eclipse SUMO sumo 1.28.0 |

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

