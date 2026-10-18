# Evacuation (M7)

**Synthetic demand, uncalibrated.** Window background demand is the cut Tier A route set (see
docs/events.md). Every evacuation scenario here is **fictional** (PROJECT.md section 11): the
zones are generic boxes, crowd sizes, timings and orders are invented, and real-site evacuation
plans stay private. Simulation and decision support only: nothing is ever actuated.

PROJECT.md 9.7 (evacuation event), 9.8 (clearance metrics), 9.9 (evacuation strategies) and 9.10
(decision log). Tier B (microscopic) windows only.

## Commands

```bash
# demo command: reference (scenario without the evacuation) + the evacuation as written, in parallel;
# writes runs/<id>-<window>-s<seed>-<hash>/evacuation_report.{json,md} (+ M5 FCD Parquet), copied to runs/<id>/
uv run python -m sim.events.evacuation run --scenario evac_obhur --seed 1          # Obhur Creek mouth (obhur window)
uv run python -m sim.events.evacuation run --scenario evac_flood_balad --seed 1      # Al Balad flood day
uv run python -m sim.events.evacuation run --scenario evac_demo --seed 1 --no-fcd    # demo window, ~15 s
# evacuation strategies: candidates, parallel what-ifs, ranking, explanations, decision log
uv run python -m strategist.evacuation run --scenario evac_obhur --seed 1 [--workers 11] [--only a,b]
uv run python -m strategist.evacuation approve <recommendation_id> [--option 1] [--actor name] [--reject]
uv run python -m strategist.log verify            # same hash-chained log as M6
# helpers
uv run python -m sim.events.evacuation validate sim/scenarios/evac_*.yaml   # (skip evac_settings.yaml)
uv run python -m sim.events.evacuation net --scenario evac_flood_balad      # build/show the contraflow net
uv run python -m sim.events.evacuation register [--check]                   # assumption block below
```

## Scenario file

```yaml
events:
  - type: evacuation
    id: corniche_crowd
    start: 900                 # the evacuation order (s since window time 0)
    zone: [[lon, lat], ...]    # polygon; origins = passenger edges whose midpoint is inside
    vehicles: 2000             # evacuee vehicles (persons = vehicles x A-evac-001, reported only)
    exits: auto                # or a list of window-fringe edge ids
    # exit_count / release_s override A-evac-007 / A-evac-002 (need `source:` or `assumption:`)
    # strategy levers, as written = the "no strategy" run:
    phasing: simultaneous      # simultaneous | near_first | far_first
    exit_assignment: nearest   # nearest | balanced (default A-evac-012)
    contraflow: []             # exit edge ids whose corridor is reversed, or [all]
    signal_plan: default       # default | evacuation
```

Other events of the scenario (for example a flood) run as in M5. The M5 schema accepts the
evacuation event loosely and the M5 registry still rejects it (`sim.runner --scenario` cannot run
it): `sim/events/evacuation.py` validates it with its own strict model and registers its event
class in the worker processes it starts (decision B-D-026). Integration: map `evacuation` in
`sim/events/registry.py` to `sim.events.evacuation` and route `sim.runner --scenario <evac_*>` to
`sim.events.evacuation.run`.

## Model

**Origins.** Passenger edges whose midpoint lies in the zone polygon, weighted by lane length
(A-evac-005: service roads stand in for car-park aisles). Evacuees are private cars: each draws
its vType from the passenger-class members of the scenario mix (A-evac-034). The evacuees' origin edges are sampled
once per (seed, event id) and are identical in every run of the scenario (common random numbers),
so strategies differ only by the strategy.

**Exits.** `auto`: window fringe edges (no passenger successor, i.e. leaving the window) with
capacity lanes x speed >= 40 (A-evac-008), at least 800 m from the zone (A-evac-009) and 400 m
from each other (A-evac-010), the 6 highest-capacity ones (A-evac-007). Leaving the window through
an exit counts as out; what happens beyond the window is Tier A's business.

**Routes.** One reverse free-flow Dijkstra per exit over the passenger graph gives every origin's
free-flow time to every exit and the path. `nearest`: the exit with the least free-flow time
(no guidance, A-evac-012). `balanced`: evacuees in sampled order pick the exit minimising
free-flow time + vehicles already assigned / (1,800 veh/h/lane x exit lanes) (A-evac-011), among
exits within 1.5x their nearest free-flow time (A-evac-013). At departure and every 2 min the
evacuee re-plans its route to its assigned exit with current travel times (A-evac-004).

**Release.** Departures spread evenly with seeded jitter over the mobilisation window (20 min,
A-evac-002, A-evac-003) after the order. `near_first` / `far_first`: evacuees are split into 3
equal bands by free-flow time to their exit (A-evac-014) and each band gets one third of the same
window in turn, so the last departure time is the same as in a simultaneous release. Vehicles that
cannot enter their origin edge wait in SUMO's insertion queue (the "insertion backlog").

**Signal plan** (`evacuation`). At the order, every signal with a movement on a planned evacuation
route gets a new program: green phases serving such a movement x 1.5 (max 90 s), other green
phases x 0.6 (min 6 s), yellow and all-red unchanged (A-evac-022..025). Restored when the last
evacuee is out.

**Contraflow (decision B-D-027).** SUMO cannot reverse a lane during a run. Two documented ways:
(1) a network edit that turns lanes around, (2) the lane-direction trick (reversible lanes built
into the network, switched by permissions at run time). M7 uses both: once per scenario the window
net is edited (`netconvert -s <window>.net.xml -e <patch>.edg.xml -x <patch>.con.xml`) so that
every corridor edge gets the reversed inbound lanes as extra lanes on its median side, with
explicit lane connections from the corridor's predecessor, along the corridor and into its
successor (netconvert keeps the loaded connections, so without them the new lanes are
unreachable). The signal programs are then Webster-retimed on the edited net with the same tool
and settings as the window's own programs (`sim.link.retime_tls`, A-link-009). The result is
`data/windows/<w>/<w>.evac-<hash>.net.xml` (+ `.tls.add.xml`, `.json`); the city net and the
window net are never touched. At run time the extra lanes are closed to every class from the
run's begin in *every* run of the scenario (reference, no strategy, all candidates), so all of
them share one network and the closed lanes only add geometry. Switching a corridor on, 10 min
after the order (setup, A-evac-015), opens its extra lanes and closes the inbound carriageway to
everyone but emergency vehicles (A-evac-020); inbound background traffic reroutes (the M5 closure
manager) and running evacuees re-plan at once. When the last evacuee is out the reversal is undone
after the same setup time.

Corridors never include, and never close, an edge inside the zone (evacuees start there; found
when 159 evacuees could not be inserted on a closed inbound carriageway, decision B-D-034).
Corridors: for the 3 exits most used under nearest and balanced assignment (A-evac-021), the
trailing part of the most common route to the exit that runs on motorway / trunk / primary /
secondary roads (A-evac-019), at most 2 km long (A-evac-016) and at least 300 m (A-evac-017). The
inbound carriageway is found per corridor edge: the reverse edge between the same nodes, else the
nearest anti-parallel edge (heading differs by more than 135 degrees, A-evac-036) of an allowed type within
60 m (A-evac-037) of the edge's start, middle and end, with the same name when both are named; it must run
beside at least half of the corridor's length (A-evac-038). Every corridor edge gets the same number of
reversed lanes, the inbound lane count (length-weighted mode) capped at 3 (A-evac-018).
Limitations: the reversed lanes copy the corridor edge's speed limit and have no crossover
geometry; the inbound match is geometric, so a parallel service road with the same name could be
taken for the inbound carriageway (none observed on the demo corridors, checked by name in the
corridor tables below).

**Metrics.** Clearance: the time after the order until 50 / 90 / 100 % of the evacuee vehicles
have arrived at (left through) their exit; "not reached" if the run ends first. Bottleneck edges:
edges on the planned evacuation routes ranked by halted vehicle-hours (all vehicles; halting
numbers sampled every 5 s from the order until the last evacuee is out), with the share of
evacuees whose planned route uses the edge. Background delay: time loss + insertion delay of
non-evacuee vehicles from tripinfo with unfinished trips included, so the evacuation's side effect
is evacuation run minus reference. Teleports are reported per run: a jammed vehicle is teleported
after 300 s (A-sim-002), which moves it forward and so flatters clearance in gridlocked runs.

## Strategist (`strategist/evacuation.py`)

**Candidates (decision B-D-029).** A screening design over the four levers with the scenario as
written as the no-strategy run: near-first and far-first phased release; balanced exit guidance;
the evacuation signal plan (only where planned routes cross a signal); contraflow on the
corridors towards exits the nearest assignment uses; balanced + all corridors; balanced + signal
plan; balanced + all corridors + signal plan; and the last one with near-first and with far-first
release. Candidates whose resolved plan (vehicles, routes, contraflow, effective signal plan) is
identical to an earlier one are dropped and listed as equivalent.

**Evaluation (decision B-D-028).** Each candidate is a full window run from the scenario's begin,
not a fork of a saved state: flood closures and weather active at the order cannot be re-applied
after `loadState` (M6 B-D-017), and the strategy acts on vehicles that do not exist yet at the
order. Light outputs (tripinfo with unfinished trips, statistics, log; no FCD), one spawned
process and SUMO per candidate, up to 11 in parallel. The no-strategy what-if and the demo
command run the same simulation (same arguments and dispatch order; a test checks identical
clearance on the demo window).

**Score** (lower is better): 0.5 x T90 + 0.5 x T100 (seconds after the order; a level not reached
counts 1.5 x the time to the run end, A-evac-026) + 10 s per background vehicle-hour added versus
no strategy (a penalty only: reductions are not rewarded, A-evac-029) + 30 s per reversed lane-km + 2 s per retimed signal + 60 s per extra staged order
(A-evac-027..032).

**Noise band (decision B-D-035).** One extra run repeats the no-strategy plan (same evacuees and
departure times) with another SUMO seed (seed + 1000, A-evac-035). The absolute T90, T100 and
background-delay differences between the two are the noise band: background delay is penalised,
and counted against the auto-eligibility limit, only beyond it, and options whose T90 is within it
of no strategy are marked (~). Measured before this was added: options with essentially the same
effect differed by up to 75 veh-h of background delay (out of ~600 veh-h in a congested window),
which ranked options by noise. One replicate is a crude estimate.

**Classification.** Contraflow and staged evacuation orders always need approval (A-strat-020).
Balanced exit guidance and the evacuation signal plan are reversible and auto-eligible while the
option adds at most 5 background vehicle-hours (A-evac-033). The evacuation order itself is the
situation (issued by the authority), not a strategist action.

**Explanations.** Measured facts only (M6 B-D-022): clearance times against no strategy; a lever is
named as a cause only when the same option without that lever was simulated, quoting its measured
effect on T90 (or saying it did not help); background delay, contraflow lanes, retimed signals
and the worst bottleneck.

**Decision log.** One `recommendation` record per run in `runs/strategist/decisions.sqlite` (the M6
hash-chained, append-only log), `kind: evacuation`; `approve` verifies the chain and the
`recommendation.json` hash, then appends a `decision` record (approved or rejected) with the
option's strategy and predicted clearance. Nothing is applied: an approved evacuation option is a
plan for the operator.

## Results

All numbers below are from runs in this session (seed 1, SUMO 1.28.0, M3 Pro shared with two
other tracks at load average 30-50). Times are seconds after the evacuation order. **Synthetic
demand, uncalibrated; fictional scenarios.** Clearance counts vehicles leaving the window; jam
teleports (300 s, A-sim-002) move stuck vehicles forward and so flatter clearance in congested
runs, which is why they are listed.

### Obhur Creek mouth (obhur window)

The public evacuation demo is at the mouth of Obhur Creek (Sharm Obhur), on the south bank across
the water from the Jeddah Tower site (decision TI-002: the earlier Al Hamra demo was withdrawn from
the public set). Window `obhur` (`sim/network/windows/obhur.yaml`): 2,339 edges, 1,014 junctions,
no signals, cut from the city net with the same Tier A route set as the other windows (2,757
vehicles; flow check PASS, GEH < 5 on 100 % of 91 edges, total ratio 1.000).

`evac_obhur`: order at 900 s, 1,500 vehicles (~3,750 persons) from 285 zone edges (1.42 km2), release 1200 s, run end 7200 s (horizon 6300 s after the order). Exits: `31134844#4` طريق الملك عبد العزيز (King Abdulaziz Road, south) 4 lanes; `43055955#5` طريق الملك عبد العزيز 3 lanes; `43065390#15.s3` طريق الكورنيش الشمالي (North Corniche) 3 lanes; `444402913#6` (unnamed ramp towards Madinah Road) 3 lanes; `240251260#0` طريق الكورنيش الشمالي 3 lanes; `43097485#13` طريق المدينة المنورة (Madinah Road) 2 lanes.
Contraflow corridors: cf1 towards `31134844#4` (طريق الملك عبد العزيز, 1497 m, 4.49 lane-km); cf2 towards `240251260#0` (طريق الكورنيش الشمالي, 650 m, 0.65 lane-km); cf3 towards `444402913#6` (444402913#0, 1183 m, 3.55 lane-km). Edited net `data/windows/obhur/obhur.evac-c9c151686f.net.xml`.

**Demo command** (`python -m sim.events.evacuation run --scenario evac_obhur --seed 1`, run `evac_obhur-obhur-s1-ecff823b`, wall 118.31 s):

| run | T50 | T90 | T100 | out | teleports (evacuees) | background delay veh-h |
|---|---|---|---|---|---|---|
| reference (no evacuation) | - | - | - | - | 0 | 13.464 |
| evacuation as written | 933 (15.6 min) | 1,702 (28.4 min) | 2,115 (35 min 15 s) | 1500/1500 | 11 (11) | 16.548 (+3.08) |

Bottleneck edges (evacuation as written):

| edge | name | type | lanes | halted veh-h | max halted | planned evacuee share |
|---|---|---|---|---|---|---|
| `140335803#7` | طريق الملك عبد العزيز | highway.secondary | 1 | 7.06 | 35 | 0.401 |
| `140335803#10` | طريق الملك عبد العزيز | highway.secondary | 1 | 6.73 | 27 | 0.401 |
| `140335806` | (unnamed) | highway.secondary_link | 1 | 5.87 | 18 | 0.401 |
| `-157288780#0` | (unnamed) | highway.residential | 1 | 4.05 | 15 | 0.093 |
| `157288736#1` | (unnamed) | highway.residential | 1 | 4.04 | 13 | 0.093 |

**Strategies** (`python -m strategist.evacuation run --scenario evac_obhur --seed 1 --workers 6`, recommendation `rec-20261017T000240Z-9a7e8298`, 8 what-ifs + 1 noise replicate in 216 s on 6 workers, fingerprint `353c178d00b0ed14`; the window has no signals, so the signal-plan candidates resolve to equivalent plans and are dropped). Noise band (replicate, SUMO seed 1001): T90 +/- 17 s, T100 +/- 8 s, background delay +/- 0.9 veh-h.

| rank | option | T50 | T90 | T100 | out | bg delay vs no strategy (veh-h) | lane-km reversed | score | class |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `balanced`: balanced exit guidance | 830 | 1,402 (23.4 min) | 1,789 | 1500/1500 | -1.61 | 0.00 | 1,596 | auto_eligible |
| 2 | `balanced_cf`: balanced exit guidance, contraflow cf1 + cf2 + cf3 | 824 | 1,403 | 1,814 | 1500/1500 | -0.98 | 8.69 | 1,869 | approval_required |
| - | `no_strategy`: no strategy (scenario as written) | 933 | 1,702 | 2,115 | 1500/1500 | +0.00 | 0.00 | 1,908 | none |
| 3 | `far_first_full`: far-first phased release, balanced exit guidance, contraflow cf1 + cf2 + cf3 | 815 | 1,349 (22.5 min) | 1,746 | 1500/1500 | -0.54 | 8.69 | 1,928 | approval_required |
| 4 | `near_first_full`: near-first phased release, balanced exit guidance, contraflow cf1 + cf2 + cf3 | 842 | 1,418 | 1,787 | 1500/1500 | -0.14 | 8.69 | 1,983 | approval_required |
| 5 | `far_first`: far-first phased release | 1,004 | 1,670 | 2,077 | 1500/1500 | -0.38 | 0.00 | 1,994 | approval_required |
| 6 | `near_first`: near-first phased release | 923 | 1,784 | 2,226 | 1500/1500 | -0.21 | 0.00 | 2,125 | approval_required |
| 7 | `contraflow`: contraflow cf1 + cf2 + cf3 | 935 | 1,705 (~) | 2,146 | 1500/1500 | +0.81 | 8.69 | 2,186 | approval_required |

Recommended: `balanced`; fastest clearance: `far_first_full`.

**Film run** (`uv run python -m sim.events.evacuation run --scenario movies/specs/scenarios/evac_obhur_film.yaml --seed 1`: the `far_first_full` option written into a copy of the scenario, same crowd, zone, timing and seed; run `evac_obhur_film-obhur-s1-83e89905`, wall 66.8 s): T50 815 s, T90 1,349 s, T100 1,746 s, 1500/1500 out, contraflow on cf1-cf3 at 1,500 s, background +2.55 veh-h; identical clearance to the strategist's what-if of the same option.

### Al Balad flood day (al_balad window)

`evac_flood_balad`: order at 1500 s, 2,000 vehicles (~5,000 persons) from 296 zone edges (0.917 km2), release 1200 s, run end 7200 s (horizon 5700 s after the order). Exits: `41399858#1-AddedOnRampEdge` طريق الفلاح 3 lanes; `194728659#3` طريق المدينة المنورة 3 lanes; `1073797850#0` (unnamed) 2 lanes; `133055588#12` شارع حائل 2 lanes; `240251224#0.s1` شارع الملك خالد 2 lanes; `26646046#0.s1` طريق الكورنيش 2 lanes.
Contraflow corridors: cf1 towards `194728659#3` (46963269#2, 1439 m, 21 edges, 4.316 lane-km); cf2 towards `133055588#12` (شارع حائل, 1209 m, 9 edges, 2.417 lane-km); cf3 towards `240251224#0.s1` (شارع الملك خالد, 1927 m, 8 edges, 3.854 lane-km). Edited net `data/windows/al_balad/al_balad.evac-f7a77b9743.net.xml`.
Other event: flood `storm_flood`, preset storm, closures of FS-002 (King Abdullah Road / King Fahd Road underpass, 2 edges) from 900.0 s.

**Demo command** (`python -m sim.events.evacuation run --scenario evac_flood_balad --seed 1`, run `evac_flood_balad-al_balad-s1-38064fa6`, wall 197.28 s):

| run | T50 | T90 | T100 | out | teleports (evacuees) | background delay veh-h |
|---|---|---|---|---|---|---|
| reference (no evacuation) | - | - | - | - | 81 | 557.1 |
| evacuation as written | 2,768 | not reached | not reached | 1755/2000 | 602 (503) | 848.9 (+291.8) |

Bottleneck edges (evacuation as written):

| edge | name | type | lanes | halted veh-h | max halted | planned evacuee share |
|---|---|---|---|---|---|---|
| `26282692#0` | طريق المدينة المنورة | highway.primary | 6 | 86.71 | 112 | 0.406 |
| `41409164#5` | شارع حائل | highway.primary | 2 | 82.68 | 160 | 0.126 |
| `41407646#4` | طريق الملك عبدالعزيز | highway.primary | 2 | 40.13 | 58 | 0.104 |
| `45204223#7` |  | highway.residential | 1 | 33.72 | 33 | 0.051 |
| `26282692#0.s1` | طريق المدينة المنورة | highway.primary | 6 | 28.58 | 37 | 0.406 |

**Strategies** (`python -m strategist.evacuation run --scenario evac_flood_balad --seed 1`, recommendation `rec-20261016T053643Z-624adbd0`, 11 what-ifs + 1 noise replicate in 353 s on 11 workers, fingerprint `ff134cd308b9f3e9`). Noise band (replicate, SUMO seed 1001): T90 n/a (neither run reaches it), T100 n/a (neither run reaches it), background delay +/- 13.3 veh-h.

| rank | option | T50 | T90 | T100 | out | bg delay vs no strategy (veh-h) | lane-km reversed | signals | score | class |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `balanced_signals`: balanced exit guidance, evacuation signal plan | 1,796 | 4,493 | 5,212 | 2000/2000 | -169.4 | 0.00 | 4 | 4,860 | auto_eligible |
| 2 | `balanced`: balanced exit guidance | 2,076 | 4,650 | 5,416 | 2000/2000 | -201.7 | 0.00 | 0 | 5,033 | auto_eligible |
| 3 | `signals`: evacuation signal plan | 2,429 | 4,860 | not reached | 1941/2000 | -33.4 | 0.00 | 3 | 6,711 | auto_eligible |
| - | `no_strategy`: no strategy (scenario as written) | 2,768 | not reached | not reached | 1755/2000 | +0.0 | 0.00 | 0 | 8,550 | none |
| 4 | `far_first`: far-first phased release | 3,087 | not reached | not reached | 1673/2000 | -56.1 | 0.00 | 0 | 8,670 | approval_required |
| 5 | `near_first`: near-first phased release | 2,718 | not reached | not reached | 1770/2000 | -32.9 | 0.00 | 0 | 8,670 | approval_required |
| 6 | `contraflow`: contraflow cf1 (46963269#2) | 2,196 | not reached | not reached | 1762/2000 | -103.9 | 4.32 | 0 | 8,679 | approval_required |
| 7 | `balanced_cf`: balanced exit guidance, contraflow cf1 (46963269#2) + cf2 (شارع حائل) + cf3 (شارع الملك خالد) | 2,005 | not reached | not reached | 1743/2000 | -180.4 | 10.59 | 0 | 8,868 | approval_required |
| 8 | `balanced_cf_signals`: balanced exit guidance, evacuation signal plan, contraflow cf1 (46963269#2) + cf2 (شارع حائل) + cf3 (شارع الملك خالد) | 1,925 | not reached | not reached | 1744/2000 | -211.0 | 10.59 | 4 | 8,876 | approval_required |
| 9 | `far_first_full`: far-first phased release, balanced exit guidance, evacuation signal plan, contraflow cf1 (46963269#2) + cf2 (شارع حائل) + cf3 (شارع الملك خالد) | 2,025 | not reached | not reached | 1717/2000 | -208.2 | 10.59 | 4 | 8,996 | approval_required |
| 10 | `near_first_full`: near-first phased release, balanced exit guidance, evacuation signal plan, contraflow cf1 (46963269#2) + cf2 (شارع حائل) + cf3 (شارع الملك خالد) | 1,930 | not reached | not reached | 1722/2000 | -203.4 | 10.59 | 4 | 8,996 | approval_required |

Recommended: `balanced_signals`; fastest clearance: `balanced_signals`.

### Reading the results

- **Obhur.** No strategy clears everyone in about 35 min (T100 2,115 s); 40 % of the planned evacuee
  routes run south over the single-lane stretch of King Abdulaziz Road (`140335803#*`) and its
  link (`140335806`), the bottleneck. **Balanced exit guidance** sends part of the crowd to the
  North Corniche and the ramp towards Madinah Road instead and clears 90 % 5.0 min sooner (T90
  1,402 s, well outside the noise band of +/- 17 s); it is reversible, auto-eligible and the
  recommendation. Contraflow on top of it does not help (T90 1,403 s) and costs 8.69 reversed
  lane-km; contraflow alone is within noise of no strategy (~). A far-first phased release added
  to balanced guidance and contraflow is the fastest plan (T90 1,349 s, T100 1,746 s) but its
  staged orders and contraflow cost more score (381 s) than the 353 s of T90 it saves, so it ranks
  third and needs approval. The `evacuation` film shows that fastest plan (phasing and contraflow
  are visible) and says on screen that the recommendation is balanced guidance alone.
- **Al Balad, flood day.** With the storm (speed x 0.85, longer headways) and the FS-002 underpass
  closed, no strategy gets only 1,755 of 2,000 out by the run end (95 min after the order; T90
  not reached, 503 evacuee jam teleports). **Balanced exit guidance + the evacuation signal plan
  clears everyone** (T90 4,493 s, T100 5,212 s), both actions auto-eligible; balanced guidance
  alone clears everyone 3-4 min later; each of the two measures is credited with its measured
  share (guidance 367 s, signals 157 s of T90). The approved decision is in the log
  (`dec-20261016T054527Z-939a23de`, actor `m7-demo-operator`, simulation only).
  Contraflow options do not reach 90 % (1,717-1,762 out). Measured: in every contraflow option
  the worst bottleneck becomes Dhahab Street (`45266820#4`, ~80 halted veh-h), which is neither a
  corridor nor an inbound edge and is not among the top bottlenecks without contraflow; the
  mechanism (diverted inbound traffic or evacuees re-planning onto it) was not analysed further.
- The demo command and the strategist's no-strategy what-if are the same simulation: identical
  clearance on both windows (and checked by a test on the demo window). Two strategist runs of
  each scenario (three for each after later reporting-only changes) gave the same fingerprint (Obhur `353c178d00b0ed14`, two runs, Al Balad
  `ff134cd308b9f3e9`).

## Assumptions (M7)

Generated from `sim/scenarios/evac_settings.yaml`; integration merges these rows into the Track B
register (decision B-D-031).

<!-- BEGIN M7 assumptions: generated by `python -m sim.events.evacuation register`, do not edit -->
| id | parameter | value | unit | range | source or assumption | status | used in |
|---|---|---|---|---|---|---|---|
| A-evac-001 | event.occupancy | 2.5 | persons per vehicle | 1.5-4.0 | Event crowds arrive in family and friend groups; used only to report persons, never in the simulation. No Jeddah event-parking survey found | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-002 | event.release_s | 1200 | s | 300-3600 | Mobilisation window: evacuees walk to their cars and start over 20 min after the order (evacuation literature uses S-shaped loading curves of 30 min to hours for residential areas; an event crowd that is already awake and gathered is assumed faster). Not calibrated | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-003 | event.release_curve | uniform | shape | uniform | Departures are spread evenly over each phase's release window (seeded jitter); no S-curve, so the first and last minutes are not thinner than the middle | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-004 | event.reroute_period_s | 120 | s | 30-600 | Evacuees re-plan the route to their assigned exit with current travel times at departure and every 2 min (navigation apps, perfect information); the exit itself does not change | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-005 | event.origin_weight | lane_length | weight | lane_length | Evacuee vehicles start on passenger edges inside the zone in proportion to lane length (service roads = car-park aisles); no parking inventory for the site | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-006 | event.background | unchanged | mode | unchanged | Background demand is unchanged during the evacuation (no extra or cancelled background trips, no closure of the zone to inbound traffic; only a strategy's contraflow closes inbound carriageways, A-evac-020); side effects on it are measured, not modelled away | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-007 | exits.count | 6 | exits | 2-12 | With `exits: auto`, the six highest-capacity window fringe edges that pass the filters below; an operator would name the exits in a real plan | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-008 | exits.min_capacity | 40 | lanes x m/s | 20-80 | An exit must carry at least 2 lanes at 72 km/h (or 3 lanes at 48 km/h, ...); excludes residential and service stubs | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-009 | exits.min_distance_m | 800 | m | 300-2000 | An exit must be at least 800 m from the zone, so leaving through it means leaving the crowd area | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-010 | exits.min_spacing_m | 400 | m | 100-1000 | Exits closer than 400 m to an already chosen exit are treated as the same exit (parallel ramps of one road) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-011 | exits.sat_flow_vps_lane | 0.5 | veh/s per lane | 0.4-0.6 | HCM base saturation flow about 1,900 pc/h/lane (unverified, quoted from memory); 1,800 veh/h/lane used; Used only by the balanced exit assignment to estimate how long an exit needs to discharge its assigned vehicles | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-012 | assignment.default | nearest | mode | nearest/balanced | Without guidance every evacuee heads for the exit with the shortest free-flow time from where it starts | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-013 | assignment.balanced_max_detour | 1.5 | x nearest free-flow time | 1.2-3.0 | Balanced guidance only sends a vehicle to an exit whose free-flow time is at most 1.5x its nearest exit | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-014 | phasing.sectors | 3 | bands | 2-5 | Phased release splits evacuees into 3 equal bands by free-flow time to their exit (near, middle, far); each band gets an equal share of the release window in turn, so the last departure time is the same as in a simultaneous release | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-015 | contraflow.setup_s | 600 | s | 300-1800 | Police and barriers need 10 min after the order before the inbound carriageway can be reversed; no Jeddah contraflow plan found | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-016 | contraflow.max_length_m | 2000 | m | 500-5000 | A contraflow corridor covers at most the last 2 km of the route to an exit inside the window (staffing limit) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-017 | contraflow.min_length_m | 300 | m | 100-800 | Shorter reversible segments are not worth the crossover staffing | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-018 | contraflow.max_added_lanes | 3 | lanes | 1-4 | At most 3 inbound lanes per edge are reversed | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-019 | contraflow.road_types | highway.motorway/highway.trunk/highway.primary/highway.secondary | OSM road types |  | Only divided or multi-lane arterials are reversed; tertiary and local streets are not | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-020 | contraflow.inbound_allowed | emergency | vClass | emergency/none | While reversed, the inbound carriageway is closed to everyone except emergency vehicles; inbound background traffic reroutes | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-021 | contraflow.max_corridors | 3 | corridors | 1-6 | Candidate corridors are built for the 3 exits used most under nearest and balanced assignment together; more reversals than that exceed one police shift | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-022 | signals.green_factor | 1.5 | x green | 1.2-2.0 | Evacuation signal plan: phases that give green to an evacuation movement are lengthened by 50 % | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-023 | signals.other_factor | 0.6 | x green | 0.4-0.9 | ... and the other green phases are shortened to 60 % | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-024 | signals.min_green_s | 6 | s | 5-10 | No shortened green below 6 s (pedestrian and safety minimum; same order as the window programs' minimum green, A-link-009) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-025 | signals.max_green_s | 90 | s | 60-120 | No lengthened green above 90 s | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-026 | clearance.not_cleared_factor | 1.5 | x time to run end | 1.0-3.0 | A clearance level not reached before the run ends is scored as 1.5x the time from the order to the run end | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-027 | strategy.w_t90 | 0.5 | score per s | 0-1 | Objective = clearance time: half the weight on the time to 90 % out (the bulk of the crowd) ... | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-028 | strategy.w_t100 | 0.5 | score per s | 0-1 | ... and half on the time to 100 % out (the last vehicle), which is noisier because of stragglers | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-029 | strategy.w_delay | 10.0 | s per background veh-h | 2-60 | One vehicle-hour of background delay added versus the no-strategy evacuation costs 10 s of clearance (life safety first; same scale as the M6 weight A-strat-022). A penalty only: a reduction is not rewarded, because the objective is clearance, not relieving background traffic; and only beyond the noise band (A-evac-035) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-030 | strategy.w_contraflow | 30.0 | s per reversed lane-km | 0-120 | Fixed cost per reversed lane-km (police staffing, crossover risk) on top of the measured delay | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-031 | strategy.w_signal | 2.0 | s per retimed signal | 0-10 | Small fixed cost per signal switched to the evacuation plan | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-032 | strategy.w_order | 60.0 | s per extra staged order | 0-300 | Each extra staged evacuation order (phased release) costs 1 min of clearance equivalent (communication, compliance risk) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-033 | strategy.auto_max_added_veh_h | 5.0 | veh-h beyond noise | 1-20 | A signal plan or exit guidance is auto-eligible only while the option adds at most 5 background vehicle-hours versus no strategy; contraflow and staged evacuation orders always need approval (A-strat-020) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-034 | event.evacuee_types | passenger_share_of_mix | vType shares |  | Evacuees are private cars: each draws its vType (seeded) from the passenger-class members of the scenario's driver mix, renormalised (normal / slow / aggressive); trucks and buses are background only | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-035 | strategy.noise_replicates | 1 | replicate runs | 1-5 | Run-to-run noise is estimated from one replicate of the no-strategy run with another SUMO seed (same evacuees and departure times): the absolute T90 / T100 / background-delay differences form the noise band. Background delay counts as a penalty, and towards the auto-eligibility limit, only beyond that band; T90 differences inside it are flagged. One replicate is a crude estimate (measured band: Obhur +/-0.9 veh-h, Al Balad +/-13.3 veh-h); where neither run reaches 90 % the T90 band is not measurable (n/a) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-036 | contraflow.antiparallel_deg | 135 | deg | 120-170 | An edge is the inbound carriageway of a corridor edge only if their headings differ by more than 135 deg (same threshold as the M5 rubbernecking search, sim/events/netindex.py); excludes cross streets | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-037 | contraflow.partner_search_m | 60 | m | 30-100 | The inbound carriageway is searched within 60 m of the corridor edge's start, middle and end; covers Jeddah divided arterials with wide medians (not measured) | assumed | sim/scenarios/evac_settings.yaml |
| A-evac-038 | contraflow.partner_coverage | 0.5 | share of corridor length | 0.3-0.9 | A corridor is reversible only if an inbound carriageway was found beside at least half of its length (short gaps: split edges, junction areas) | assumed | sim/scenarios/evac_settings.yaml |
<!-- END M7 assumptions -->
