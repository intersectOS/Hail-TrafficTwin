# Policy report: Wadi Al-Adiri running: all at-grade crossings closed for the day (bridges open)

> **synthetic demand, uncalibrated.** Tier A (meso), policy `wadi_adiri_flowing` on day type `weekday` compared
> with the baseline `wadi_adiri_flowing-f0.25--control` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy wadi_adiri_flowing vs weekday baseline [synthetic demand, uncalibrated]: mean delay -12.0 %, AM-peak delay +10.1 %, VKT +0.1 %, VHT -7.2 %, CO2 -6.6 %**


> **Compared with a matched control** (TA-018): `wadi_adiri_flowing-f0.25--control` is the baseline with the same
> 5,686 baseline vehicles re-routed (one-shot, at their baseline
> times, no policy). One-shot routes beat the baseline's 3-step assignment, so comparing with the
> raw baseline would credit the policy with that routing gain.

<details><summary>Against the raw baseline (includes the routing gain)</summary>

| KPI | raw baseline | policy | delta % |
|---|---|---|---|
| mean delay per trip | 881.5 | 688.6 | -21.9 |
| AM peak (06-09) mean delay | 328.5 | 320.9 | -2.3 |
| vehicle-km (VKT) | 5,094,966 | 5,113,042 | +0.3 |
| vehicle-hours (VHT) | 203,551 | 176,460 | -13.3 |
| CO2 | 1,960.9 | 1,719.2 | -12.3 |

</details>

## What the policy changed
- `network_change`: variant_network data/hail/hail.v2.wadi_adiri_flowing-9da41288.net.xml.gz, edges_closed 34, edges_changed 0, edges_new 0, edges_removed_in_variant 34, endpoints_moved 561, vehicles_rerouted_closure 5,686, closed_edge_names ['شارع الأمير مقرن بن عبدالعزيز', 'شارع جرير بن عبدالله', 'طريق الملك فيصل بن عبدالعزيز']

Routing: 124,976 vehicle trips; 119,290 kept their baseline
route, 5,011 were routed anew, 675 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 782.2 | 688.6 | -93.6 | -12.0 | better |
| AM peak (06-09) mean delay (s) | 291.4 | 320.9 | 29.5 | +10.1 | worse |
| mean speed (km/h) | 26.9 | 29.0 | 2.1 | +7.9 | better |
| vehicle-km (VKT) (km) | 5,105,525 | 5,113,042 | 7,517 | +0.1 | worse |
| vehicle-hours (VHT) (h) | 190,139 | 176,460 | -13,679 | -7.2 | better |
| vehicle-hours of delay (h) | 108,555 | 95,087 | -13,468 | -12.4 | better |
| vehicle trips completed | 499,584 | 497,096 | -2,488 | -0.5 |  |
| peak-hour departures (veh/h) | 53,936 | 53,676 | -260 | -0.5 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.108 | 0.108 | 0 | +0.0 |  |
| CO2 (t) | 1,839.9 | 1,719.2 | -120.7 | -6.6 | better |
| CO2 in the peak hour (t) | 122.0 | 128.9 | 6.9 | +5.7 | worse |
| NOx (kg) | 985.9 | 930.9 | -55.0 | -5.6 | better |
| mean trip length (km) | 10.2 | 10.3 | 0.07 | +0.7 |  |
| teleports (quality flag) | 20,554 | 16,950 | -3,604 | -17.5 | better |
| teleports per loaded vehicle | 0.1645 | 0.1364 | -0.0281 | -17.1 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,732 | 92,328 | 18.6% | 18.6% | 291.4 | 320.9 |
| PM peak 16-19 | 81,216 | 80,836 | 16.3% | 16.3% | 1,271.0 | 911.0 |
| baseline peak hour 06:00 | 53,936 | 53,676 | 10.8% | 10.8% | 268.4 | 318.3 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,388 | 48.0 | 45.9 |
| 01 | 4,448 | 4,408 | 44.0 | 44.3 |
| 02 | 2,368 | 2,348 | 41.0 | 41.0 |
| 03 | 1,840 | 1,788 | 52.0 | 49.2 |
| 04 | 2,056 | 1,984 | 60.0 | 59.7 |
| 05 | 30,924 | 30,776 | 102.7 | 168.1 |
| 06 | 53,936 | 53,676 | 268.4 | 318.3 |
| 07 | 22,656 | 22,572 | 448.9 | 444.8 |
| 08 | 16,140 | 16,080 | 147.3 | 155.7 |
| 09 | 9,512 | 9,444 | 98.8 | 96.9 |
| 10 | 7,192 | 7,112 | 42.1 | 41.5 |
| 11 | 18,448 | 18,364 | 48.5 | 50.2 |
| 12 | 44,212 | 43,964 | 211.2 | 180.0 |
| 13 | 22,124 | 22,032 | 717.6 | 627.6 |
| 14 | 17,264 | 17,176 | 955.0 | 808.6 |
| 15 | 23,964 | 23,844 | 753.7 | 667.7 |
| 16 | 20,480 | 20,368 | 1,008.9 | 753.3 |
| 17 | 29,856 | 29,712 | 1,172.1 | 733.2 |
| 18 | 30,880 | 30,756 | 1,540.5 | 1,187.1 |
| 19 | 36,600 | 36,440 | 1,513.9 | 1,424.1 |
| 20 | 30,716 | 30,568 | 1,893.9 | 1,697.1 |
| 21 | 26,908 | 26,776 | 1,524.2 | 1,396.6 |
| 22 | 22,000 | 21,900 | 1,167.1 | 1,085.6 |
| 23 | 15,600 | 15,620 | 912.9 | 916.5 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
55 of 61 districts with at least 1,000 trips are better
off, 6 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Industrial Area | 5564.0 | 5564.0 | 1660.2 | 1158.2 | -502.1 |
| Sinaiyah An Nahdah | 3664.0 | 3656.0 | 1642.1 | 1254.6 | -387.5 |
| Al Khamashiyah | 1572.0 | 1572.0 | 1669.6 | 1303.1 | -366.5 |
| Al Talal | 4856.0 | 4848.0 | 1367.8 | 1036.1 | -331.7 |
| Al Jabal | 2624.0 | 2620.0 | 1265.7 | 941.0 | -324.7 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Buhayrah | 4596.0 | 4744.0 | 982.6 | 1198.3 | 215.7 |
| An Narjis | 1168.0 | 1168.0 | 842.6 | 900.4 | 57.8 |
| Qurtubah | 1404.0 | 1404.0 | 94.9 | 137.9 | 42.9 |
| An Nafl | 3296.0 | 3288.0 | 419.3 | 455.6 | 36.3 |
| Mashar | 1724.0 | 1724.0 | 418.2 | 445.7 | 27.5 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 47406.1 | 40526.3 | 259 | -6879.8 |
| طريق الملك سعود بن عبدالعزيز | 13369.2 | 10226.1 | 114 | -3143.1 |
| شارع طلحة بن عبيدالله | 893.5 | 555.2 | 13 | -338.3 |
| طريق الملك فهد بن عبد العزيز | 1231.2 | 953.9 | 86 | -277.3 |
| 553625016#11 | 294.1 | 54.5 | 1 | -239.6 |
| شارع جدة | 715.9 | 530.8 | 28 | -185.1 |
| طريق مشار | 1914.0 | 1780.0 | 53 | -134.0 |
| شارع هارون الرشيد | 135.1 | 20.1 | 21 | -115.1 |
| شارع أمير المؤمنين عمر بن الخطاب | 527.2 | 426.7 | 86 | -100.5 |
| 350093266#3 | 251.6 | 158.6 | 1 | -93.1 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| شارع الفرج | 5150.6 | 5284.9 | 24 | 134.3 |
| شارع النعمان بن عمرو | 625.4 | 690.7 | 43 | 65.3 |
| 324857034#1 | 194.6 | 224.0 | 1 | 29.3 |
| شارع عتبة بن سهيل | 7.1 | 25.8 | 60 | 18.7 |
| -111184603#1 | 14.6 | 31.9 | 1 | 17.2 |
| 325736853#0 | 102.2 | 117.0 | 1 | 14.8 |
| 350093267#27 | 12.0 | 26.0 | 1 | 14.0 |
| 131722997#6 | 229.7 | 243.6 | 1 | 13.9 |
| شارع قرطبة | 1259.0 | 1272.7 | 18 | 13.7 |
| 131722997#5 | 25.0 | 38.1 | 1 | 13.2 |

## Assumptions used
- Policy: A-pol-150
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 7727326c6bbbdc73 | e5816193812c5619 | 765732190ffb2223 | data/hail/hail.v2.wadi_adiri_flowing-9da41288.net.xml.gz | 594810cf106bb39d | fc1d2383bd099e80 | 24adeb5221524c49 | 0 | Eclipse SUMO sumo 1.28.0 |

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

