# Policy report: New bus line H1 on King Abdulaziz Rd, every 10 min, 06:00-23:00, 10 % car shift in the catchment

> **synthetic demand, uncalibrated.** Tier A (meso), policy `bus_line_king_abdulaziz` on day type `weekday` compared
> with the baseline `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875` (same seed 1, population sample
> 25 % with capacity scaling; totals scaled to the full city).
> Started from `baseline-weekday-f0.25-s1-addfcb64-76573219-d30875`.

**Policy bus_line_king_abdulaziz vs weekday baseline [synthetic demand, uncalibrated]: mean delay -2.5 %, AM-peak delay +0.3 %, VKT +0.3 %, VHT -1.3 %, CO2 -0.6 %**


## What the policy changed
- `pt_line`: line H1, stops 28, directions 2, bus_departures 204, tours_in_catchment 213, tours_shifted 25, shift_tours_changed 25, shift_vehicles_before 53, shift_vehicles_after 0

Routing: 124,923 vehicle trips; 124,923 kept their baseline
route, 0 were routed anew, 0 could not be routed.

## City KPIs (policy vs baseline)
| KPI | baseline | policy | delta | delta % |  |
|---|---|---|---|---|---|
| mean delay per trip (s) | 881.5 | 859.3 | -22.2 | -2.5 | better |
| AM peak (06-09) mean delay (s) | 328.5 | 329.4 | 0.9 | +0.3 | worse |
| mean speed (km/h) | 25.0 | 25.4 | 0.42 | +1.7 | better |
| vehicle-km (VKT) (km) | 5,094,966 | 5,111,943 | 16,977 | +0.3 | worse |
| vehicle-hours (VHT) (h) | 203,551 | 200,881 | -2,670 | -1.3 | better |
| vehicle-hours of delay (h) | 122,304 | 119,405 | -2,899 | -2.4 | better |
| vehicle trips completed | 499,456 | 500,212 | 756 | +0.1 |  |
| peak-hour departures (veh/h) | 53,908 | 53,952 | 44 | +0.1 |  |
| peak hour (start) (h) | 6 | 6 | 0 |  |  |
| top-hour share of trips | 0.1079 | 0.1079 | 0 | +0.0 |  |
| CO2 (t) | 1,960.9 | 1,949.8 | -11.1 | -0.6 | better |
| CO2 in the peak hour (t) | 127.0 | 127.8 | 0.8 | +0.6 | worse |
| NOx (kg) | 1,045.9 | 1,056.3 | 10.4 | +1.0 | worse |
| mean trip length (km) | 10.2 | 10.2 | 0.02 | +0.2 |  |
| teleports (quality flag) | 22,814 | 22,190 | -624 | -2.7 | better |
| teleports per loaded vehicle | 0.1825 | 0.1773 | -0.0052 | -2.9 | better |

## Peak spreading
| window | departures base | departures policy | share base | share policy | mean delay base (s) | mean delay policy (s) |
|---|---|---|---|---|---|---|
| AM peak 06-09 | 92,736 | 92,836 | 18.6% | 18.6% | 328.5 | 329.4 |
| PM peak 16-19 | 81,180 | 81,304 | 16.2% | 16.2% | 1,428.2 | 1,410.6 |
| baseline peak hour 06:00 | 53,908 | 53,952 | 10.8% | 10.8% | 307.0 | 306.9 |

<details><summary>Hourly departures and mean delay</summary>

| hour | departures base | departures policy | delay base (s) | delay policy (s) |
|---|---|---|---|---|
| 00 | 9,460 | 9,456 | 47.7 | 46.9 |
| 01 | 4,448 | 4,448 | 44.1 | 43.5 |
| 02 | 2,368 | 2,368 | 40.9 | 41.0 |
| 03 | 1,840 | 1,836 | 51.4 | 50.4 |
| 04 | 2,056 | 2,056 | 60.2 | 61.5 |
| 05 | 30,920 | 30,924 | 116.0 | 108.0 |
| 06 | 53,908 | 53,952 | 307.0 | 306.9 |
| 07 | 22,672 | 22,676 | 488.0 | 487.0 |
| 08 | 16,156 | 16,208 | 176.1 | 183.4 |
| 09 | 9,512 | 9,560 | 122.3 | 130.3 |
| 10 | 7,192 | 7,240 | 42.1 | 52.6 |
| 11 | 18,448 | 18,492 | 48.7 | 56.8 |
| 12 | 44,212 | 44,264 | 215.7 | 178.1 |
| 13 | 22,116 | 22,172 | 713.8 | 630.7 |
| 14 | 17,272 | 17,284 | 968.2 | 875.1 |
| 15 | 23,976 | 24,016 | 786.6 | 717.3 |
| 16 | 20,472 | 20,492 | 1,105.9 | 982.7 |
| 17 | 29,848 | 29,892 | 1,348.4 | 1,373.6 |
| 18 | 30,860 | 30,920 | 1,719.3 | 1,730.0 |
| 19 | 36,596 | 36,616 | 1,651.6 | 1,644.7 |
| 20 | 30,680 | 30,764 | 2,170.4 | 2,146.7 |
| 21 | 26,924 | 26,936 | 1,853.5 | 1,827.0 |
| 22 | 22,056 | 22,052 | 1,460.6 | 1,430.2 |
| 23 | 15,464 | 15,588 | 1,094.3 | 1,051.2 |

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
43 of 61 districts with at least 1,000 trips are better
off, 18 worse.

Winners
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Barzan | 1640.0 | 1640.0 | 1291.9 | 1091.5 | -200.5 |
| Al Anwar | 2584.0 | 2580.0 | 1254.9 | 1116.0 | -138.9 |
| Al Buhayrah | 4612.0 | 4588.0 | 1390.5 | 1261.8 | -128.7 |
| Luluah qafar | 2428.0 | 2428.0 | 1331.5 | 1205.1 | -126.4 |
| Al Wadi | 6004.0 | 6004.0 | 1360.7 | 1259.4 | -101.3 |

Losers
| name_en | trips_base | trips_policy | mean_delay_s_base | mean_delay_s_policy | delta_delay_s |
|---|---|---|---|---|---|
| Al Muzaabar | 1252.0 | 1240.0 | 607.7 | 695.4 | 87.8 |
| An Nasiyah | 2684.0 | 2684.0 | 870.5 | 947.6 | 77.1 |
| zone 20 | 2964.0 | 2964.0 | 794.6 | 853.1 | 58.5 |
| An Narjis | 1168.0 | 1168.0 | 961.8 | 1017.7 | 55.9 |
| Qfaar | 7752.0 | 7752.0 | 1006.0 | 1047.4 | 41.4 |

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| طريق الملك عبدالعزيز | 51790.9 | 51296.4 | 259 | -494.4 |
| طريق الملك سعود بن عبدالعزيز | 16709.5 | 16311.0 | 114 | -398.5 |
| طريق مشار | 2344.3 | 1966.8 | 53 | -377.5 |
| 553625016#11 | 279.6 | 56.3 | 1 | -223.3 |
| 1191274601#2 | 119.4 | 18.2 | 1 | -101.2 |
| شارع هارون الرشيد | 99.6 | 30.3 | 21 | -69.3 |
| شارع الشيخ محمد بن صالح العثيمين | 1930.0 | 1861.6 | 55 | -68.5 |
| 1191274601#2-AddedOnRampEdge | 67.9 | 0.1 | 1 | -67.9 |
| 350093266#3 | 387.7 | 321.8 | 1 | -65.9 |
| 553625016#13 | 64.2 | 0.2 | 1 | -64.0 |

Ten most worsened
| corridor | time_loss_base_veh_h | time_loss_policy_veh_h | edges | delta_veh_h |
|---|---|---|---|---|
| شارع قرطبة | 1222.7 | 1282.1 | 18 | 59.4 |
| 298009829#21 | 53.3 | 109.5 | 1 | 56.1 |
| طريق الملك فهد بن عبد العزيز | 1935.1 | 1986.6 | 86 | 51.5 |
| 298009829#21-AddedOnRampEdge | 12.8 | 53.7 | 1 | 40.9 |
| شارع الفرج | 5511.7 | 5543.6 | 24 | 31.9 |
| شارع خليفة بن عبدالله بن الحارث | 52.8 | 77.8 | 20 | 25.0 |
| 107434755 | 36.8 | 61.6 | 1 | 24.7 |
| 1084726666 | 275.7 | 290.8 | 1 | 15.1 |
| شارع الأمير عبدالعزيز بن سعد بن عبدالعزيز | 342.5 | 353.5 | 107 | 11.0 |
| 844332859#6 | 45.0 | 55.0 | 1 | 10.0 |

## Assumptions used
- Policy: A-pol-030, A-pol-031, A-pol-091
- Day type: A-day-001, A-day-002, A-day-003, A-day-004, A-day-005, A-day-006, A-day-007, A-day-008, A-day-009, A-day-010, A-day-011, A-day-012, A-day-013, A-day-014, A-day-015, A-day-016, A-day-017
- Baseline model: A-act-001, A-act-002, A-act-003, A-act-004, A-act-005, A-act-006, A-exp-001, A-mode-001, A-mode-002, A-mode-003, A-net-301, A-pop-001, A-pop-002, A-pop-010, A-pop-011, A-pop-012, A-pop-013, A-pop-014, A-pop-015, A-pop-016, A-pop-017, A-pop-018, A-sim-101, A-sim-103

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
| seed | sample | config_hash | policy_hash | population_hash | network | network_hash | vehicles_hash | routes_hash | routes_deterministic | sumo_version |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.25 | e5e21a9522d28a6c | 4266eb209a77683f | 765732190ffb2223 | data/hail/hail.v2.net.xml | addfcb64bedc9fa3 | 71f6659f98c506fa | e6987cb114c4b3c3 | 0 | Eclipse SUMO sumo 1.28.0 |

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

