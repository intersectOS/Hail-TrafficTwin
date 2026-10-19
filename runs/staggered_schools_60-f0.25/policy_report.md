# Policy report: Staggered school hours: schools in half of the districts start 60 min later

> **synthetic demand, uncalibrated.** Tier A (meso), policy `staggered_schools_60` on day type `weekday` compared
> with the baseline `staggered_schools_60-f0.25--control` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy staggered_schools_60 vs weekday baseline [synthetic demand, uncalibrated]: mean delay +2.4 %, AM-peak delay -15.8 %, VKT +0.0 %, VHT +1.3 %, CO2 +1.1 %**


> **Compared with a matched control** (TA-018): `staggered_schools_60-f0.25--control` is the baseline with the same
> 9,796 baseline vehicles re-routed (one-shot, at their baseline
> times, no policy). One-shot routes beat the baseline's 3-step assignment, so comparing with the
> raw baseline would credit the policy with that routing gain.

<details><summary>Against the raw baseline (includes the routing gain)</summary>

| KPI | raw baseline | policy | delta % |
|---|---|---|---|
| mean delay per trip | 881.5 | 732.9 | -16.9 |
| AM peak (06-09) mean delay | 328.5 | 327.9 | -0.2 |
| vehicle-km (VKT) | 5,094,966 | 5,104,097 | +0.2 |
| vehicle-hours (VHT) | 203,551 | 183,320 | -9.9 |
| CO2 | 1,960.9 | 1,778.1 | -9.3 |

</details>

## What the policy changed
- `staggered_hours`: segment school, institutions 75, institutions_shifted 34, mean_shift_min 63.3, tours_retimed 9,182, vehicles_retimed 9,796

Routing: 124,976 vehicle trips; 115,180 kept their baseline
route, 9,796 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 715.5 | 732.9 | 17.4 | +2.4 | worse |
| AM peak (06-09) mean delay (s) | 389.4 | 327.9 | -61.5 | -15.8 | better |
| mean speed (km/h) | 28.2 | 27.8 | -0.35 | -1.2 | worse |
| vehicle-km (VKT) (km) | 5,102,907 | 5,104,097 | 1,190 | +0.0 | worse |
| vehicle-hours (VHT) (h) | 181,038 | 183,320 | 2,282 | +1.3 | worse |
| vehicle-hours of delay (h) | 99,295 | 101,712 | 2,417 | +2.4 | worse |
| vehicle trips completed | 499,620 | 499,640 | 20 | +0.0 |  |
| peak-hour departures (veh/h) | 53,896 | 44,176 | -9,720 | -18.0 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.0884 | -0.0195 | -18.1 | better |
| CO2 (t) | 1,759.0 | 1,778.1 | 19.1 | +1.1 | worse |
| CO2 in the peak hour (t) | 132.7 | 115.4 | -17.3 | -13.0 | better |
| NOx (kg) | 948.7 | 961.4 | 12.7 | +1.3 | worse |
| mean trip length (km) | 10.2 | 10.2 | 0.01 | +0.1 |  |
| teleports (quality flag) | 18,580 | 18,492 | -88 | -0.5 | better |
| teleports per loaded vehicle | 0.1487 | 0.148 | -0.0007 | -0.5 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,728 | 97,888 | 18.6% | 19.6% | 389.4 | 327.9 |
| PM peak 16-19 | 81,236 | 81,248 | 16.3% | 16.3% | 914.6 | 992.1 |
| baseline peak hour 06:00 | 53,896 | 44,176 | 10.8% | 8.8% | 342.7 | 333.5 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,460 | 47.7 | 47.7 |
| 01 | 4,448 | 4,448 | 44.1 | 44.1 |
| 02 | 2,368 | 2,368 | 40.9 | 40.9 |
| 03 | 1,840 | 1,840 | 51.4 | 51.4 |
| 04 | 2,056 | 2,056 | 60.2 | 60.2 |
| 05 | 30,928 | 25,768 | 157.5 | 107.3 |
| 06 | 53,896 | 44,176 | 342.7 | 333.5 |
| 07 | 22,676 | 36,912 | 597.2 | 385.7 |
| 08 | 16,156 | 16,800 | 253.6 | 186.3 |
| 09 | 9,512 | 9,512 | 132.3 | 115.2 |
| 10 | 7,192 | 7,056 | 42.3 | 41.8 |
| 11 | 18,448 | 14,128 | 47.6 | 53.5 |
| 12 | 44,216 | 36,808 | 118.3 | 123.4 |
| 13 | 22,132 | 29,864 | 342.5 | 273.8 |
| 14 | 17,256 | 21,260 | 697.6 | 620.1 |
| 15 | 23,980 | 24,096 | 588.7 | 640.4 |
| 16 | 20,464 | 20,460 | 690.8 | 729.8 |
| 17 | 29,868 | 29,868 | 711.9 | 784.5 |
| 18 | 30,904 | 30,920 | 1,258.6 | 1,366.3 |
| 19 | 36,632 | 36,636 | 1,488.5 | 1,509.7 |
| 20 | 30,692 | 30,704 | 1,899.8 | 1,934.3 |
| 21 | 26,952 | 26,904 | 1,659.0 | 1,720.0 |
| 22 | 22,060 | 22,028 | 1,291.4 | 1,332.0 |
| 23 | 15,484 | 15,568 | 890.0 | 1,023.5 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
25 of 61 districts with at least 1,000 trips are better
off, 36 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Barzan | 1640.0 | 1640.0 | 1073.1 | 970.7 | -102.5 |
| Al Masif | 3136.0 | 3136.0 | 504.4 | 449.2 | -55.1 |
| Al Andalus | 10512.0 | 10512.0 | 737.7 | 688.5 | -49.2 |
| Mashar | 1724.0 | 1724.0 | 451.7 | 404.5 | -47.3 |
| Samah | 3252.0 | 3260.0 | 922.7 | 876.9 | -45.8 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Khamashiyah | 1572.0 | 1572.0 | 1672.1 | 1892.7 | 220.6 |
| Sinaiyah An Nahdah | 3664.0 | 3664.0 | 1496.7 | 1644.2 | 147.5 |
| Al Buhayrah | 4596.0 | 4672.0 | 1153.1 | 1274.8 | 121.7 |
| Industrial Area | 5564.0 | 5564.0 | 1310.4 | 1420.5 | 110.1 |
| Luluah qafar | 2428.0 | 2428.0 | 1051.3 | 1144.8 | 93.4 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق جبة | 1115.8 | 832.5 | 48 | -283.3 |
| طريق مشار | 2622.1 | 2365.3 | 53 | -256.8 |
| شارع الشيخ محمد بن صالح العثيمين | 1698.6 | 1579.6 | 55 | -119.0 |
| 1191274599#0 | 1109.4 | 1041.8 | 1 | -67.6 |
| شارع جدة | 574.8 | 513.6 | 28 | -61.2 |
| شارع قرطبة | 1241.7 | 1181.8 | 18 | -59.9 |
| 131722997#5 | 154.0 | 94.2 | 1 | -59.8 |
| 324857034#1-AddedOnRampEdge | 206.2 | 164.6 | 1 | -41.6 |
| 350093266#3 | 303.4 | 270.2 | 1 | -33.2 |
| 1084932139#11 | 117.7 | 86.3 | 1 | -31.4 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 39184.8 | 41183.9 | 259 | 1999.1 |
| طريق الملك سعود بن عبدالعزيز | 13713.4 | 14060.2 | 114 | 346.9 |
| شارع الفرج | 3214.6 | 3443.1 | 24 | 228.4 |
| شارع طلحة بن عبيدالله | 820.8 | 948.2 | 13 | 127.4 |
| شارع الأمير عبدالعزيز بن سعد بن عبدالعزيز | 328.5 | 393.1 | 107 | 64.6 |
| 553625016#13 | 0.1 | 57.2 | 1 | 57.1 |
| 553625016#14 | 0.9 | 56.9 | 1 | 56.0 |
| طريق الملك فهد بن عبد العزيز | 1560.5 | 1613.3 | 86 | 52.8 |
| شارع الأمير نايف بن عبدالعزيز | 215.7 | 260.9 | 43 | 45.2 |
| 298009838 | 317.5 | 354.2 | 1 | 36.7 |

## Assumptions used
- Policy: A-pol-010
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | 95b8b5e7d01aa814 | cbb0bc61e0d240dc | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | c71c4f0244bb6011 | dd6bc9d7f3c54e24 | 0 | Eclipse SUMO sumo 1.28.0 |

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

