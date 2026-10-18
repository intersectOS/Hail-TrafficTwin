# Emergency strategist (M6)

**Synthetic demand, uncalibrated.** Window demand is the M1 Tier A smoke route set cut into the
window (see docs/events.md). The demo situation `emergency_tahlia_0830` is **fictional**
(PROJECT.md section 11): crash, times and ambulance trip are invented.

PROJECT.md 9.9 (strategist) and 9.10 (decision log), Tier B windows only.

## Commands

```bash
# ranked top 3 for the situation; writes runs/strategist/<recommendation id>/recommendation.{json,md}
uv run python -m strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1
uv run python -m strategist.run --scenario emergency_demo --seed 1 --weights my_weights.yaml
#   --fresh  rebuild the snapshot   --db <sqlite>  decision log   --runs-dir <dir>   --serial
# apply (or reject) an option; logs the human decision
uv run python -m strategist.approve <recommendation_id> [--option 1] [--actor name] [--reject] [--to-end]
# decision log
uv run python -m strategist.log verify      # exit 1 on any break, edited record or missing trigger
uv run python -m strategist.log show
# assumption rows of strategist/*.yaml -> the block at the end of this file
uv run python -m strategist.register [--check]
```

Scenario ids resolve from `strategist/scenarios/` first, then `sim/scenarios/` (same `Scenario`
schema). A situation is a scenario with exactly one `emergency_trip` flagged `strategist: true`;
its `start` is the dispatch time T. Clock convention (decision): window t = 0 is 08:00 of the
weekday demo hour, so 08:30 = 1800 s.

## Pipeline

1. **Snapshot** (`strategist/snapshot.py`). The window runs from its begin to T with the
   scenario's background events (the crash) but not the strategist trip, without FCD and
   without per-edge subscriptions, then `simulation.saveState` with `--save-state.rng` and
   `--save-state.precision 6`. Cached in `runs/strategist/snapshots/<key>/`, key = hash of
   (background event plans, window, seed, T, vTypes and mix, SUMO options, net / demand /
   additional content hashes); `--fresh` rebuilds. Measured at T and stored: per-edge mean
   travel time over [T - 300 s, T) (SUMO `edgeData`, A-strat-001), halted vehicles per edge,
   instantaneous edge travel time, running and waiting vehicles, signal program and phase.
2. **Candidates** (`strategist/candidates.py`, `strategist/graph.py`). Edge graph for vClass
   emergency with the lanes closed at T removed (a fully closed edge drops out; a partly closed
   edge keeps only its open lanes' connections). Edge cost = the ambulance's free-flow time x
   the congestion ratio measured before T (mean travel time / free-flow time at the limit,
   capped at 20x, A-strat-002). Yen's loopless k-shortest paths, kept only if at most 60 % of
   their length is shared with every route already chosen (A-strat-005) and they cost at most
   3x the best (A-strat-006), until k = 3 routes (A-strat-003) or 40 paths (A-strat-004).
   "Time-dependent" here means the travel times measured at T; nothing forecasts how queues
   evolve during the 1-3 min trip. Per route: (a) route only, (b) + signal preemption, (c) +
   preemption + rescue lane (route-only is skipped for the default route: it is the
   no-strategy run). Plus one approval-required option: preemption + side-entry hold upstream
   of the most-halted edge on the candidate route with most halted vehicles at T. Plus the
   **no-strategy run**: the default fastest route of `sim.events.emergency.resolve` with no
   interventions.
3. **Evaluate** (`strategist/evaluate.py`). Each candidate in its own spawned process and SUMO,
   same net, demand, additionals, options and seed, plus `--load-state`; events active at T are
   re-applied (below), the ambulance is inserted at T on the candidate route, actions are
   stepped each second until T + 300 s (A-strat-016). Measured: ambulance travel time (tripinfo
   definition, arrival - actual departure; checked equal to tripinfo in `approve`), time per
   route edge, background vehicle-hours (running + waiting to be inserted, ambulance excluded)
   over the horizon, background arrivals, teleports, the most-halted edges on the route,
   signals preempted and for how long, rescue-lane edges, junctions held. No FCD; only the
   ambulance and the route edges are subscribed.
4. **Rank** (`strategist/rank.py`): score = w_time x TT + w_delay x added background veh-h vs
   the no-strategy run + w_closure x junctions held + w_preempt x signals preempted (lower is
   better; not arrived by the horizon = 2x horizon, A-strat-017). Defaults in
   `strategist/weights.yaml` (A-strat-021..024: 1 per ambulance second, 10 s per veh-h, 5 s
   per held junction, 1 s per signal); `--weights file.yaml` overrides any of them (plain
   numbers allowed; recorded as overrides). Top 3: the best option of each distinct route
   first, in score order, then filled with the next best (decision); rank 1 is always the
   overall best score.
5. **Explain** (`strategist/explain.py`): two sentences per option, every number a registered
   fact `{value, text, source}` taken from the what-if results, the snapshot or the horizon
   setting (tests check that every number in the text is such a fact and equals its source).
   The reason names the edge where the no-strategy ambulance lost most time against free flow:
   "avoids `e`, where the no-strategy ambulance spent N s" (other route) or "spends M s on `e`
   instead of N s" (same edge), then preemption / rescue lane counts, then the added or saved
   background vehicle-hours and the longest queue on the route. "because" is written only when
   the option is measured faster than no strategy.
6. **Classify** (`strategist/classify.py`): rerouting the ambulance is advisory and always
   `auto_eligible`; preemption and the rescue-lane proxy are `auto_eligible` while the option's
   added background delay is at most 2 veh-h (A-strat-018) and at most 6 signals are preempted
   (A-strat-019); closures (later contraflow, evacuation orders) are always
   `approval_required` (A-strat-020). An option is approval-required if any action is.
7. **Log** (`strategist/decision_log.py`): a `recommendation` record per run, a `decision`
   record per approve/reject.

`strategist.run` never applies anything: the what-ifs are forks. `strategist.approve` is the
only path that applies an option; it re-runs it from the same state and seed (to the horizon,
or the scenario end with `--to-end`), writes tripinfo, statistics and the SUMO log to
`runs/strategist/<recommendation id>/applied-option<k>/`, checks the measured ambulance time
against the prediction (exit code 3 if they differ), refuses a second decision for the same
recommendation and refuses to run if the log fails verification or the saved state changed.

## What survives saveState / loadState (SUMO 1.28, measured)

| item | survives | handling |
|---|---|---|
| vehicles, their routes incl. TraCI reroutes, TraCI-added routes and vehicles | yes | - |
| RNG state (`--save-state.rng`) | yes | forks of the same state are bit-identical |
| signal program and phase | yes | checked against the snapshot in a test |
| lane permissions (`lane.setAllowed`: accident closures) | **no** | re-applied (below) and asserted |
| lane speed limits (`lane.setMaxSpeed`: rubbernecking) | **no** | re-applied by accident `on_start` |
| vType parameter changes (`vehicletype.set*`) | **no** (additional-file values return) | weather events active at T refused |

After `--load-state` every background event active at T is dispatched again with ctx.t = T
(accident `on_start` closes the lanes and slows the opposite carriageway), and the fork asserts
that each closed lane is disallowed (`strategist/fork.py`). Events that ended before T are
marked done; events starting after T run normally. Active rain, flood, motorcade or other
emergency trips are refused with a clear error: weather multipliers and per-vehicle speed
factors would compound, and convoy / emergency vehicles already exist in the state (open item).

## Actions

- **Signal preemption** (`Preemption`): when the ambulance is within 250 m of the stop line
  (A-strat-007) movements losing green get 3 s yellow (A-strat-008), then the ambulance's links
  are green and every other link red (A-strat-009, conservative: no conflict matrix); after the
  ambulance has left the junction the saved program and phase are restored (`setProgram` +
  `setPhase`; the restored phase restarts its full duration). Joined clusters crossed on
  consecutive route edges are one preemption.
- **Rescue lane, proxy.** SUMO's bluelight rescue corridor needs the sublane model
  (`--lateral-resolution`), which the window runs and the saved state do not use; switching
  model in the fork would change every vehicle's dynamics and break the comparison with the
  no-strategy fork. The ambulance keeps its vType (bluelight device present, as in M5) in every
  candidate. Proxy (A-strat-010..012): on each multi-lane route edge starting within 300 m
  ahead, the leftmost open lane that continues the route is restricted to vClass emergency
  through the owner-based `ClosureManager` (vehicles on it change out, as with accident
  closures), the ambulance is asked to use it (`vehicle.changeLane`), and the lane is released
  when the ambulance leaves the edge. A lane is reserved only if every movement into and out
  of the edge keeps another open lane: on the demo window, reserving the only target lane of an
  upstream edge blocked the queue ahead and the ambulance did not arrive within 300 s
  (measured, then excluded). Limits: drivers vacate the lane by SUMO lane-change logic, not by
  pulling over; vehicles stuck in a jam cannot leave it; it is not a sublane corridor.
- **Side-entry hold** (approval required, `SideEntryHold`): the internal lanes of every movement
  entering the route (from other edges) at route junctions within 400 m upstream of the
  most-halted edge (A-strat-013) are closed to all but vClass emergency from dispatch until 10 s
  after the ambulance passed (A-strat-015), at most 5 min (A-strat-014).

## Decision log (PROJECT.md 9.10)

SQLite table `records` (`runs/strategist/decisions.sqlite` by default, `--db`): seq, record_id,
kind (`recommendation` | `decision`), snapshot_id, candidates, scores, recommendation, decision,
actor, timestamp (UTC ISO 8601), prev_hash, hash = sha256 of the canonical JSON (sorted keys,
no whitespace) of all fields incl. prev_hash; JSON fields are stored as canonical text and
hashed as stored. First prev_hash = 64 zeros. Triggers `records_no_update` and
`records_no_delete` RAISE on UPDATE / DELETE. `strategist.log verify` walks the chain and
reports missing triggers, edited records (hash mismatch) and removed or reordered records
(prev_hash mismatch); tests drop a trigger, edit a row and delete a row and check each is
detected. Limit: removing the newest records (after dropping the triggers) leaves a valid
shorter chain; each `recommendation.json` keeps its record hash (`log_hash`), and `approve`
checks it, so an external copy of the head hash is needed to detect truncation.

## Acceptance run: `emergency_tahlia_0830` on tahlia, seed 1 (2026-10-16)

Situation (fictional): crash closes 1 of 2 lanes of `44795819#33` from 08:25 (1500 s) for
20 min; ambulance `44795819#21` -> `44796463#1` dispatched at 08:30 (1800 s). One lane, not
both (decision): the default route stays open but slowed, so rerouting, preemption and rescue
lanes all compete; the measured no-strategy trip (173 s, 3.7x free flow) leaves ample room.
At T: 321 vehicles running, 0 waiting, 87 halted, lane `44795819#33_1` closed.

Hardware: Apple M3 Pro, 11 cores, 18 GB; SUMO 1.28.0 (eclipse-sumo wheel), Python 3.12. During
the acceptance runs another track's two `duarouter` jobs kept the load average at about 50, so
the wall times below are pessimistic; development runs of the same 9 candidates on a quieter
machine took 9.3 s cold and 5.0 s from the saved state (snapshot warm-up 2.7 s, evaluation
3.1-3.7 s).

| measured (load average about 50) | run 1 (cold) | run 2 | run 3 |
|---|---:|---:|---:|
| snapshot | built: warm-up 13.3 s, save + measure 2.5 s (16.2 s with setup) | reused (0.1 s) | reused (0.1 s) |
| candidates (Yen: 17 paths for 3 routes) | 0.6 s | 0.6 s | 0.4 s |
| evaluation, 9 what-if runs in parallel | 8.7 s | 8.9 s | 8.6 s |
| total wall (`time`) | 29.9 s | 13.2 s | 13.5 s |
| determinism fingerprint (all measured fields) | `c345c0094c51cc15` | same | same |

Acceptance: 3 ranked options in 13.2-13.5 s from the saved state (cold 29.9 s), within 60 s;
the best option beats the no-strategy baseline from the same snapshot (68 s vs 173 s).

No strategy (default route B, 1,710 m): **173 s**, free flow 47.4 s; the ambulance spent 77 s
on `444771953#1`, the approach to the signalled single-lane right turn into Madinah Road
(cluster `GS_cluster_13626783524_...`). For comparison M5's `emergency_tahlia` (crash at 600 s,
dispatch 900 s): 94 s.

| rank | option | class | ambulance TT | vs no strategy | free flow (vs ff) | added veh-h | score |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Route A + rescue lane (7 edges) | auto_eligible | 68 s | -105 s | 62.2 s (+6 s) | -0.03 | 67.8 |
| 2 | Route B + preemption (1 signal) + rescue lane (27 edges) | auto_eligible | 89 s | -84 s | 47.4 s (+42 s) | -0.05 | 89.5 |
| 3 | Route C only | auto_eligible | 95 s | -78 s | 66.8 s (+28 s) | -0.10 | 94.0 |

Reasons as printed (final run after the attribution fix: an action is named as a cause only when
the same route without it was measured slower, with its own measured saving; otherwise it is stated
as a fact):
1. Route A + rescue lane gets the ambulance there in 68 s, 105 s faster than no strategy (173 s)
   because it avoids `444771953#1`, where the no-strategy ambulance spent 77 s and the rescue lane
   on 7 edges saves 2 s against the same route without it. Over the 300 s horizon it saves 0.03
   vehicle-hours of background delay versus no strategy.
2. Route B + preemption + rescue lane gets the ambulance there in 89 s, 84 s faster than no
   strategy (173 s) because it spends 8 s on `444771953#1` instead of 77 s and the rescue lane on
   27 edges saves 8 s against the same route without it; it also preempts 1 signal. Over the
   300 s horizon it saves 0.05 vehicle-hours of background delay versus no strategy; the longest
   queue on its route was 11 halted vehicles on `44795819#35-AddedOffRampEdge`.
3. Route C only gets the ambulance there in 95 s, 78 s faster than no strategy (173 s) because
   it also uses `444771953#1` but spends 4 s there instead of 77 s. Over the 300 s horizon it
   saves 0.10 vehicle-hours of background delay versus no strategy; the longest queue on its
   route was 9 halted vehicles on `44795819#35-AddedOffRampEdge`.

Final acceptance run (2026-10-16 03:04 UTC, load average ~55 from other tracks): evaluation
6.6 s, total 10.1 s from the saved state (11.1 s process wall); approve reproduced 68.0 s;
`strategist.log verify` OK.

All 9 what-ifs (background veh-h over 1800-2100 s; no-strategy 27.679 veh-h):

| candidate | class | TT | added veh-h | signals | rescue edges | held | score |
|---|---|---:|---:|---:|---:|---:|---:|
| no_strategy | - | 173 s | 0 | 0 | 0 | 0 | 173.0 |
| A:reroute | auto | 70 s | -0.060 | 0 | 0 | 0 | 69.4 |
| A:reroute+rescue_lane | auto | 68 s | -0.025 | 0 | 7 | 0 | 67.8 |
| B:preempt | auto | 97 s | -0.220 | 1 | 0 | 0 | 95.8 |
| B:preempt+rescue_lane | auto | 89 s | -0.049 | 1 | 27 | 0 | 89.5 |
| C:reroute | auto | 95 s | -0.104 | 0 | 0 | 0 | 94.0 |
| C:reroute+preempt | auto | 94 s | -0.005 | 1 | 0 | 0 | 95.0 |
| C:reroute+preempt+rescue_lane | auto | 104 s | +0.035 | 1 | 15 | 0 | 105.3 |
| B:preempt+closure | approval_required | 97 s | -0.220 | 1 | 0 | 5 | 120.8 |

Determinism and apply: three runs (one cold, two from the cached snapshot) gave identical
measured results (fingerprint above), so a rebuilt snapshot reproduces the cached one.
`strategist.approve rec-20261016T024540Z-9ab34977` (option 1) re-ran it from the state:
68 s measured = 68 s predicted = 68 s tripinfo; `strategist.log verify`: OK, 3 records, chain
intact, triggers present.

Reading the numbers
- Background delay differences between candidates are at most 0.22 veh-h of about 27.7 veh-h
  (< 1 %), the size of the run-to-run perturbation from one vehicle taking another path (M5:
  one ambulance moved window mean delay by 2.7 %). Here they do not decide the ranking; they
  would with weights much above 10 s per veh-h. Preempting the signal on route B *reduces*
  background delay (-0.22 veh-h): the no-strategy ambulance itself blocks the single-lane
  approach for 77 s.
- The 77 s on `444771953#1` is largely signal timing: route C reaches the same approach at
  another moment and passes in 4 s. Each what-if is one replication from one state, so options
  that differ only in arrival timing at a signal are not robustly ranked (open: replications
  with perturbed RNG states).
- The side-entry hold changed nothing measurable: background veh-h identical to 4 decimals with
  and without the 5 holds (40-54 s each), so no vehicle used the held entries in that time; with
  its fixed cost it ranks last. Holding entries is not a lever at this bottleneck.
- Route A (2,027 m, avoids the corridor) is the robust winner: 68-70 s with or without the rescue
  lane, 6-8 s above its free flow.

Not verified / limits
- Preemption realism: all non-route links red, 3 s yellow, fixed 250 m detection; no Jeddah EVP
  specification found. Rescue lane is a lane-reservation proxy, not SUMO's bluelight corridor.
- What the bluelight device does without the sublane model (e.g. passing red) was not examined
  separately; it is the same in every candidate.
- Single replication per candidate; no forecast of travel times along the trip.
- Edge costs use `edgeData` travel times of background traffic scaled to the ambulance's speed
  factor; internal junction lanes carry no cost.

Tests: `tests/test_strategist.py` (13, no SUMO runs) and `tests/test_strategist_run.py` (11, demo
window forks), about 10-20 s together.

## Assumptions register (M6)

`docs/assumptions-trackB.md` is generated verbatim by `python -m sim.scenarios register` from a
fixed list of sources and a test compares it byte for byte, so the strategist rows are generated
here by `python -m strategist.register` (checked by a test, ids disjoint from the Track B
register); integration can add `strategist/strategist.yaml` and `strategist/weights.yaml` to
`sim.scenarios.register.SOURCES` to merge them.

<!-- BEGIN M6 assumptions: generated by `python -m strategist.register`, do not edit -->
| id | parameter | value | unit | range | source or assumption | status | used in |
|---|---|---|---|---|---|---|---|
| A-strat-001 | snapshot.edge_tt_window_s | 300 | s | 60-900 | Routing cost of an edge = SUMO edgeData mean travel time over the 5 min before dispatch (what a live probe feed would show at T); no forecast of how the queue evolves during the trip | assumed | strategist/strategist.yaml |
| A-strat-002 | snapshot.congestion_ratio_max | 20.0 | x free flow | 5-50 | Cap on measured / free-flow travel time per edge, so an edge with one stopped car (mean speed near 0) does not get an unbounded cost | assumed | strategist/strategist.yaml |
| A-strat-003 | candidates.k_routes | 3 | routes | 1-5 | Three diverse routes give the operator real alternatives; with up to 3 variants each (the default route has no separate route-only run) plus the no-strategy run and the closure option this is at most 11 what-if runs (9 on tahlia), fitting the 11 cores of the M3 Pro in one parallel wave | assumed | strategist/strategist.yaml |
| A-strat-004 | candidates.yen_max_paths | 40 | paths | 10-100 | Yen's loopless k-shortest paths examined before the diversity filter; window nets have many near-duplicate paths (0 m split parts, ramps), so more paths than routes are needed | assumed | strategist/strategist.yaml |
| A-strat-005 | candidates.max_overlap | 0.6 | share of route length | 0.4-0.9 | A path is a distinct alternative only if at most 60 % of its length is shared with each route already chosen | assumed | strategist/strategist.yaml |
| A-strat-006 | candidates.max_cost_ratio | 3.0 | x best route cost | 1.5-5 | Alternatives whose measured cost exceeds 3x the best route are not worth simulating for an ambulance | assumed | strategist/strategist.yaml |
| A-strat-007 | preemption.lookahead_m | 250 | m | 100-500 | Signal is preempted when the ambulance is within 250 m of the stop line on its route; long enough to flush a queue at 50-60 km/h approach speeds; no Jeddah EVP specification found | assumed | strategist/strategist.yaml |
| A-strat-008 | preemption.yellow_s | 3 | s | 3-5 | Yellow shown to movements losing green before the ambulance movement turns green; equals the 3 s lower bound of typical urban yellow (the window programs use 4 s, A-link-009) | assumed | strategist/strategist.yaml |
| A-strat-009 | preemption.others_state | r | signal state | r | Every movement except the ambulance's own is held red while preempted (conservative: no conflict matrix is used, so non-conflicting movements are stopped too) | assumed | strategist/strategist.yaml |
| A-strat-010 | rescue_lane.lookahead_m | 300 | m | 150-600 | Proxy for a blue-light rescue corridor: one lane of each multi-lane route edge starting within 300 m ahead of the ambulance is reserved for vClass emergency; drivers react roughly at siren range; no Jeddah data | assumed | strategist/strategist.yaml |
| A-strat-011 | rescue_lane.min_open_lanes | 2 | lanes | 2-3 | A lane is reserved only where at least 2 lanes are open, so background traffic keeps one lane | assumed | strategist/strategist.yaml |
| A-strat-012 | rescue_lane.nudge_s | 5 | s | 1-10 | The ambulance is asked (vehicle.changeLane) to use the reserved lane for this long, renewed every step while on a reserved edge | assumed | strategist/strategist.yaml |
| A-strat-013 | closure.upstream_m | 400 | m | 200-800 | Side entries are held at route junctions within 400 m upstream of the most-halted edge on the route (the bottleneck), to drain the queue ahead of the ambulance | assumed | strategist/strategist.yaml |
| A-strat-014 | closure.max_s | 300 | s | 120-600 | A side-entry hold lasts at most 5 min (a short police-held closure) | assumed | strategist/strategist.yaml |
| A-strat-015 | closure.clear_s | 10 | s | 5-30 | A held junction is released this long after the ambulance has passed it | assumed | strategist/strategist.yaml |
| A-strat-016 | evaluation.horizon_s | 300 | s | 180-900 | What-if horizon after dispatch: the demo ambulance needs 70-150 s, so 300 s also covers the queue recovery after preemption and holds; side effects beyond 5 min are not counted | assumed | strategist/strategist.yaml |
| A-strat-017 | evaluation.not_arrived_factor | 2.0 | x horizon | 1.5-5 | An ambulance that has not arrived by the horizon is scored as if its travel time were 2x the horizon | assumed | strategist/strategist.yaml |
| A-strat-018 | classification.auto_max_added_veh_h | 2.0 | veh-h | 0.5-5 | Reversible actions (reroute, preemption, rescue-lane proxy) are auto-eligible only while the option adds at most 2 vehicle-hours of background delay over the horizon versus no strategy | assumed | strategist/strategist.yaml |
| A-strat-019 | classification.auto_max_signals | 6 | signals | 3-12 | Preempting more than 6 signals in one trip needs an operator's approval | assumed | strategist/strategist.yaml |
| A-strat-020 | classification.approval_actions | closure | action types | closure/contraflow/evacuation_order | Closures (and in M7 contraflow and evacuation orders) always need human approval (PROJECT.md 9.9 step 5) | assumed | strategist/strategist.yaml |
| A-strat-021 | w_time | 1.0 | score per ambulance second | 1-1 | Objective = emergency travel time; the other weights are expressed relative to it | assumed | strategist/weights.yaml |
| A-strat-022 | w_delay | 10.0 | ambulance s per background veh-h | 2-60 | One background vehicle-hour of added delay is worth 10 s of ambulance time (so a 30 s faster ambulance justifies up to 3 veh-h of extra delay); a policy judgement, no Saudi EMS valuation found | assumed | strategist/weights.yaml |
| A-strat-023 | w_closure | 5.0 | ambulance s per held junction | 0-30 | Each held side entry carries a fixed cost (police staffing, driver confusion) on top of the delay it causes, which is already measured | assumed | strategist/weights.yaml |
| A-strat-024 | w_preempt | 1.0 | ambulance s per preempted signal | 0-10 | Small fixed cost per preempted signal (program disruption, safety at the switch); its measured delay is already in w_delay | assumed | strategist/weights.yaml |
<!-- END M6 assumptions -->
