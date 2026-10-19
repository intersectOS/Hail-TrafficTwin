# Strategist recommendation `rec-20261019T113840Z-620125fa`

**synthetic demand, uncalibrated**. Fictional scenario (PROJECT.md section 11).

08:30 ambulance from Al Wasita to King Khalid Hospital; a crash since 08:25 blocks one of four lanes on its route (fictional). Scenario `emergency_center_0830` on window `center`, seed 1, dispatch t = 1800 s. Snapshot `c08cf0c288b8ec34` (state hash `040f8ca242741928`, network hash `ff661b46062e0c11`, demand hash `d8bdcd1e384f41f9`), config hash `8d5dbbfef8bbd6e6`, Eclipse SUMO sumo 1.28.0. Decision-log record hash `f133ca7f7a875a155ecdad0ce63c08be882af126c0c6b779936280bce4f62813`.

No strategy (default route, no interventions): ambulance 208 s, free flow 148.8 s. Horizon 300 s after dispatch; 4 what-if runs.

| rank | option | classification | ambulance TT | vs no strategy | vs free flow | added veh-h | signals | score |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Route A + signal preemption | auto_eligible | 211 s | +3 s | +59 s | -0.04 | 2 | 212.6 |
| 2 | Route A + preemption + rescue lane | auto_eligible | 214 s | +6 s | +62 s | -0.05 | 2 | 215.5 |
| 3 | Route A only | auto_eligible | 217 s | +9 s | +65 s | +0.05 | 0 | 217.5 |

## Reasons

1. Route A + signal preemption gets the ambulance there in 211 s, 3 s slower than no strategy (208 s); it avoids `326232104`, where the no-strategy ambulance spent 14 s and preempting 2 signals saves 6 s against the same route without it. Over the 300 s horizon it saves 0.04 vehicle-hours of background delay versus no strategy; the longest queue on its route was 9 halted vehicles on `1358424025#10`.
2. Route A + preemption + rescue lane gets the ambulance there in 214 s, 6 s slower than no strategy (208 s); it avoids `326232104`, where the no-strategy ambulance spent 14 s; it also preempts 2 signals and reserves a rescue lane on 14 edges. Over the 300 s horizon it saves 0.05 vehicle-hours of background delay versus no strategy; the longest queue on its route was 27 halted vehicles on `1358424025#10`.
3. Route A only gets the ambulance there in 217 s, 9 s slower than no strategy (208 s); it avoids `326232104`, where the no-strategy ambulance spent 14 s. Over the 300 s horizon it adds 0.05 vehicle-hours of background delay versus no strategy; the longest queue on its route was 8 halted vehicles on `1358424025#10`.

## All what-if runs

| candidate | classification | ambulance TT | background veh-h | added veh-h | signals | rescue edges | junctions held | teleports | score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `no_strategy` | auto_eligible | 208 s | 107.366 | +0.000 | 0 | 0 | 0 | 20 | 208.0 |
| `A:reroute` | auto_eligible | 217 s | 107.411 | +0.046 | 0 | 0 | 0 | 22 | 217.5 |
| `A:reroute+preempt` | auto_eligible | 211 s | 107.321 | -0.045 | 2 | 0 | 0 | 19 | 212.6 |
| `A:reroute+preempt+rescue_lane` | auto_eligible | 214 s | 107.313 | -0.052 | 2 | 14 | 0 | 22 | 215.5 |

Routes: 1 of k = 3 found after 40 Yen paths; lanes closed at T: 131718901#12_3.

Wall time: situation 3.65 s, snapshot 19.59 s (built), candidates 4.34 s, evaluation 12.58 s, rank + explain 0.0 s, total 40.16 s.

Weights (strategist/weights.yaml): w_time = 1.0, w_delay = 10.0, w_closure = 5.0, w_preempt = 1.0. Determinism fingerprint `0e95374c78684110`.

Assumptions used (27): A-event-002, A-event-003, A-event-001, A-strat-001, A-strat-002, A-strat-003, A-strat-004, A-strat-005, A-strat-006, A-strat-007, A-strat-008, A-strat-009, A-strat-010, A-strat-011, A-strat-012, A-strat-013, A-strat-014, A-strat-015, A-strat-016, A-strat-017, A-strat-018, A-strat-019, A-strat-020, A-strat-021, A-strat-022, A-strat-023, A-strat-024.
