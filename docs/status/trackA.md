> **MONITOR NOTE (2026-10-16 07:35, written by the overnight orchestrator, not by Track A):** the 25 % baseline
> was deliberately KILLED by the monitor at 06:27 (not an OOM): the Mac's disk is at 99 % (≈7 GB free) and swap was
> full. Do NOT re-run the 25 % (or 100 %) baseline in this session. Treat the 10 % weekday baseline as the M2 result,
> record the 25 % attempt as "stopped by the monitor for disk/memory pressure; step-0 routing exceeded 45 min under
> contention", finish M2 (metrics, plots, fidelity report, tests, verifier, `M2: done`) and move on to M4. See
> logs/INTERVENTION.md.

# Track A status

## M2 Population and baseline — in progress (2026-10-16)
Decisions so far (details in docs/population.md once written):
- TA-001 Zones = 112 OSM districts; 3,712,917 residents spread by a blend of residential building
  footprint area (0.5), residential-street km (0.35) and landuse=residential area (0.15) because
  OSM footprints cover only part of Jeddah (27,783 buildings). Airport, seaport, naval base and
  industrial area hold no residents. A-pop-001.
- TA-002 OSM has no `route=bus` relations and no GTFS was found: bus availability uses OSM bus-stop
  nodes (49) with the 500 m catchment.
- TA-003 Routing algorithm: A* (benchmark on 20,205 trips, 8 threads, city net: dijkstra 80 s /
  3.1 GB, astar 62 s / 3.4 GB, CH 70 s / 5.0 GB single-threaded). Includes ~15 s net loading.
- TA-004 vTypes travel inside the trips file because duaIterate does not pass `-+` additional
  files to duarouter.
- TA-005 Capacity scaling for samples: vehicle length+minGap x 1/f and meso tau* x 1/f (A-sim-101).
- TA-006 Dependencies added to pyproject (shared file, additive): adhanpy (prayer times),
  matplotlib (plots), psutil (peak memory of runs).

Run estimate before the first city baseline (10 %, weekday, 3 duaIterate steps): about 424k
vehicle trips; routing about 17 min per step (A* benchmark), meso simulation unknown (M1 smoke:
real-time factor ~150 at ~7k running vehicles). Estimate 60-110 min end to end.

Update 02:25: duaIterate step 0 routing took 14.3 min (424,311 trips, A*, 8 threads); the step-0
meso simulation reached 06:45 after 8 min with ~10k teleports concentrated in the 06:00-07:00 hour
(free-flow routes). Revised estimate for the 10 % baseline: 2-2.5 h end to end (3 steps + final run).

### First 10 % attempt stalled (02:00-02:35) and what changed
The first 10 % baseline (M1 network, full meso junction control, sharp school peak) stalled in the
step-0 simulation: from 06:45 to 06:51 of simulated time took 13 min, ~13.8k teleports. It was
stopped. Diagnostics on the step-0 routes, 00:00-09:00, 10-min cap each (`runs/diag/`, logs/diag-*):

| run | capacity scaling | junction control | result |
|---|---|---|---|
| C | none (10 % demand as is) | full | 55 s, 1,969 teleports, 8.4k vehicles stuck at 09:00 |
| E | none | limited | 60 s, 59 teleports |
| F | none | off | 50 s, 13 teleports |
| A / D | length + tau x10 | full / off | killed at 600 s at ~06:48, ~11k teleports (AM gridlock) |
| G | length + tau x10 | limited | killed at 600 s in the 06:00 hour, 10.8k teleports, ~120 before 05:00 |
| H | tau x10 only (storage unscaled) | limited | 66 s, 13.4k teleports, 40.6k running at 09:00 |
| I | tau x10, storage x5.6 (f^0.75) | limited | killed at 600 s at 07:13, 21.5k teleports |

Findings and decisions:
- TA-007 Track A network variant `data/jeddah/jeddah.m2.net.xml` (new name; M1 net untouched):
  M1 build + `sim/population/config/untagged.typ.xml`, argued lanes/speeds for ways WITHOUT
  `lanes`/`maxspeed` tags (motorway 3 lanes 100 km/h, trunk 3/80, primary 3/70, secondary 2/60,
  tertiary 1/50; A-net-201). Built with `python -m sim.network.build_city --config
  sim/population/config/network-m2.yaml --out data/jeddah/jeddah.m2.net.xml --no-side-outputs`
  (100 s): 155,366 edges, 61,774 junctions, 74 TLS, 22,968 lane-km (M1: 20,953). This is the M1
  handoff's "untagged-road overlay" task; integration may move the two files to sim/network/.
- TA-008 Baselines use `--meso-junction-control.limited` (override in
  sim/population/config/baseline.yaml; runner.yaml is shared and unchanged): full junction control
  jams priority junctions at light load (C vs E). Recommend the same for the Tier A smoke.
- TA-009 Demand concentration was the main cause of the AM gridlock: 14.4 % of daily vehicle trips
  left in the 06:00 hour, 74 % of them school drop-offs and empty escort legs. Changes (all
  registered): early-arrival buffer U(0, 25) min (A-act-006); school start as a 50/50 mix of the two
  published Riyadh schedules (A-day-001); government flexible starts 07:30/08:30/09:30 (A-day-004);
  escort occupancy 2 and empty legs only with probability 0.5 (parents continuing to work;
  A-mode-001). Result: top-hour share 9.6 %, 1.05 vehicle trips per resident (3.9 M/day).
- Capacity scaling kept consistent (flow and storage, A-sim-101): storage-light variants (H, I) are
  no better on the old demand, and only consistent scaling keeps queues comparable across samples.

### Second 10 % attempt (03:16-03:58): step 0 too slow, switched to incremental loading
With the de-peaked demand, m2 network and limited junction control, routing step 0 took ~12 min,
but the step-0 meso simulation (free-flow routes, full-equivalent load) reached only 07:30 after 30
min (real-time factor 1.4 in the peak, 23k teleports). Stopped. Tests on its routes, 05:00-08:00:
`--meso-recheck 10` is 8x faster but 5x the teleports; the rerouting device (period 300 s) was far
slower (05:50 after 9 min). TA-010: duaIterate incremental loading (`--inc-base 3`: steps at 1/3,
2/3 and full demand) so routes adapt before the full load.

### Third 10 % attempt (from 03:58, incremental loading) and the 25 % start
Step 0 (1/3 load): ~16 min, 206 teleports. Step 1 (2/3 load): simulation fast (24 h in ~10 min)
but ~21k teleports, on motorway off-ramps (`ramps.guess` one-lane `AddedOffRampEdge`, Al Harameen
Road ramps) in both peaks. Incident: while freeing disk (6.6 GB free machine-wide) I deleted the
running baseline's run directory and population cache by mistake; both were regenerated
deterministically from the same seed/config (population hash 65fac195, 389,289 vehicles, identical
to the routed set) so the run continued.
25 % estimate recorded before starting (04:50): ~970k vehicle trips; routing ~30 min per step x 3,
simulations 15-40 min each, final run and post-processing: 2.5-3.5 h, run in parallel with the
end of the 10 % run. The 10 % result is the smaller-sample result.

### Overload diagnosis (05:00-05:55) and bounded baselines
Step 1 of the incremental 10 % run gridlocked in the PM peak (18:21 -> 19:11 simulated in 27 min).
Tests on its routes, 16:00-19:00, 10-min caps:
- S: true full demand (`--scale 10`, normal vehicles): 168.6k running at 17:25 and rising.
- T: the 10 % sample with capacity scaling: 111k equivalent running at 17:25 and rising, so the
  scaled sample is, if anything, optimistic; capacity scaling is not the cause.
- T2: T without junction control: same growth. 32-41 % of teleports are inside junction clusters,
  the rest on primary/secondary roads and motorway ramps.
- PM 15:00-21:00 at full equivalent load: 300 s teleport time 366 s wall for 2.7 h simulated;
  `--meso-recheck 10` 115 s / 200k teleports; teleport time 120 s 221 s / 90k teleports.
TA-011 Finding: at the expected demand (3.9 M vehicle trips/day; consistent with the 2014 "6 M
trips/day" anchor and the brief's 4.5-5.5 M sizing) the M1/m2 network overloads in both peaks in
meso with 3 assignment steps. Network capacity (untagged lanes, junction clusters, ramps) is the
binding issue: handed to the network/lane-audit work as the top open issue. Decision: city
baselines use a 120 s teleport time (A-sim-103) so a 24 h run is bounded, and every report shows
the teleport share as the quality flag. Results are gridlock-affected and must be read as such.
25 % started again at 05:57 in parallel (estimate 2.5-3.5 h).
- 06:25 the parallel 25 % run died silently during step-0 routing (empty log; machine load average ~99 from Track B multiprocessing; likely killed under memory pressure). 25 % to re-run alone after the 10 % run.

### Result: 10 % weekday baseline completed (05:40-07:49)
Run `runs/baseline-weekday-f0.1-s1-e5f1906a-65fac195-f124c5` from the one command
`uv run python -m sim.runner --baseline --daytype weekday --sample 0.10 --seed 1` (m2 network, meso,
limited junction control, capacity x10, 3 incremental duaIterate steps, 120 s teleport time).
- Runtime: assignment 118 min (routing 24 / 29 / 47 min under heavy machine contention from other
  tracks; sims 2 / 5 / 11 min), final 24 h meso run 9 min (real-time factor 175), post-processing
  1.3 min; 129 min total. Peak RSS 3.7 GB (duarouter), 3.1 GB (sumo).
- Demand: 371,450 persons, 1,006,762 person trips (2.69/person), 389,289 vehicle trips (3.89 M
  city-equivalent, 1.05 per resident), top-hour share 9.6 % (06:00).
- KPIs (city-equivalent): 3.85 M trips completed (99.2 %), VKT 56.1 M, VHT 2.74 M (2.01 M delay),
  mean trip 14.6 km / 42.7 min, mean delay 31.3 min, mean speed 20.5 km/h, CO2 26,185 t, NOx 16,217 kg.
- Quality flag: 196,721 jam teleports (0.51 per loaded vehicle). Where (from sumo.log): motorway
  ramps (`Added*RampEdge`) 33k (17 %), inside junction clusters 42k (21 %), other edges 122k (62 %).
  When: ~125k (64 %) between 18:00 and 24:00, ~34k in 06:00-09:00; evening speeds 13-15 km/h. The baseline is
  gridlock-affected (TA-011: network capacity), labelled synthetic demand, uncalibrated. The top open
  issue for integration is network capacity (untagged lanes, ramps, junction clusters), not demand.
- Outputs: meta.json, metrics.json, report.md (with the fidelity caveats), tripinfo/edgedata/
  emissions/metrics_hourly/metrics_district Parquet, plots/ (departures, trip length, trips per
  person). Raw XML is deleted after conversion (disk).

### 25 % sample: runtime measured as a lower bound, not completed
One attempt, started 05:40 alongside the 10 % run (log `logs/baseline-weekday-f0.25-s1.log`, empty).
It was stopped by the overnight monitor at 06:27 for disk and memory pressure (data volume 99 % full,
swap 8.3/9.2 GB, load ~46; logs/INTERVENTION.md), still in step-0 routing after 45 min (10 %: 24 min
for the same step). Correction: the 06:25 note above ("died silently", "started again at 05:57")
was written before the monitor's account and is superseded by it. Per the monitor it is not re-run
in this session; the machine needs ~15 GB free first.
Estimate for an uncontended 25 % run with 8 routing threads: 3-4 h (routing scales ~linearly with
trips, ~970k); with the deterministic 1-thread default (TA-013) about 4x the routing time, 8-12 h.

### Sampling decision (default `--sample`)
TA-012 Default for Tier A baselines and policy runs: `--sample 0.10` with consistent capacity
scaling (`--scale` equivalent: length+minGap and meso tau x10, A-sim-101). Reason: 10 % is the only
city sample that fits the 18 GB machine alongside other work; 25 % needs ~2x the routing time and
memory. Updated after TA-013: the deterministic default (1 routing thread) makes a fresh 10 % run
~5 h (routing ~4x slower); the 8-thread setting (~2 h) is allowed for exploratory runs and is flagged
`routes_deterministic: false`. Reported results and policy comparisons use 1 thread or a cached
route set. Use 0.25 for final comparisons once disk/memory allow; 1.0 is not planned on this machine.

### Determinism of the assignment (verifier finding, fixed)
TA-013 The verifier found that two from-scratch demo assignments gave different routes: the seed did
not reach duaIterate, and multi-threaded duarouter is not repeatable. Fix: the run seed now goes to
every duarouter and sumo step (`duarouter--seed`, `sumo--seed`), and `routing_threads` defaults to 1.
With the seed alone, 8 threads still differed on the demo; with 1 thread the routes and tripinfo are
identical (new test `test_baseline_assignment_reproducible_from_seed`, empty caches, 2 steps).
Cost measured on the city net (21k trips, A*, free flow): 1 thread 427 s / 3.1 GB, 8 threads 106 s
/ 3.6 GB, so 1 thread routes ~4x slower. The 10 % baseline above was routed with 8 threads before
this fix: its routes (routes_hash in meta.json) are reproducible from the route cache
`data/population/routes/9724fafeab351805` only, not from the seed; the final simulation on them is
seeded and repeatable. It is not re-run now (disk, and ~5 h at 1 thread). A run that sets
`routing_threads: 8` records `routes_deterministic: false` in meta.json.

### M2 handoff (2026-10-16 08:30)
ruff clean; pytest 45 passed (demo window); verifier PASS after one fix round (assignment
determinism, sanity table, status corrections). Carried forward: re-run the 10 % baseline with 1
routing thread when ~15 GB are free (closes TA-013 for the reported run); 25 % run and the 10 % vs
25 % capacity-scaling check (A-sim-101); network capacity (TA-011) is the top issue for the
lane-audit/network work; README M2 command at integration (`uv run python -m sim.runner --baseline
--daytype weekday --sample 0.10 --seed 1`).
M2: done

## M4 Policy lab (2026-10-16)
Run estimate before starting the two new city baselines (recorded 08:35): the Friday and Ramadan-weekday
10 % baselines (`python -m sim.runner --baseline --daytype friday|ramadan_weekday --sample 0.10
--seed 1`) need their own duaIterate assignment (the whole population is re-timed). With the
deterministic 1-thread default (TA-013) routing is ~4x slower than the 8-thread M2 run: estimate
2.5-4 h each, run in parallel (2 routing cores, ~3-4 GB RAM each). The 10 % sample is the smallest
city sample; the weekday 10 % baseline from M2 is the result already available.

Decisions (M4):
- TA-014 Incremental routing for policy runs (A-pol-090): unchanged vehicles keep their baseline
  route; new / re-timed / re-moded / affected vehicles get a one-shot duarouter route on the
  starting baseline's congested travel times (edgedata, 900 s). A fresh 3-step assignment per
  policy would cost 2-5 h each; an incremental run costs 14-17 min end to end, 17-24 min when a
  matched control is included (`total_s` in each run's meta.json; the control runs inside it). A no-change policy reproduces
  the baseline tripinfo bit for bit (test). One-shot routing on fixed weights is repeatable with
  any thread count (test), so policy runs use 8 routing threads.
- Policy models live in `sim/schemas.py` (Track A's file since M2; additive) and
  `python -m sim.validate` is a new module; `sim/runner.py` gets an additive `--policy` option.
  `--daytype` is the comparison baseline; a policy with a `daytype` transform starts from that
  day type's baseline (Friday, Ramadan) and a daytype-only policy reuses its outputs.
- TA-015 The Ramadan baseline died when the disk filled (09:00, 1 GB free) and was restarted with
  8 routing threads (launcher monkeypatches `routing_threads`; baseline.yaml unchanged), so its
  routes, like the M2 weekday routes, are reproducible from the route cache only
  (`routes_deterministic: false`). The Friday baseline continues with 1 thread.
- TA-016 Policy runs write gzipped SUMO outputs (the uncompressed 10 % edgedata is 2.2 GB and
  filled the disk once); `sim/metrics.py` reads `.xml.gz`; sumo/build logs are gzipped.
- TA-017 `staggered_hours` groups institutions by the district of the school / workplace: the
  synthetic population has no school ids (the first attempt grouped by school edge: 35,715
  "schools", effectively per pupil).
- Network variants of `network_change` go to `data/jeddah/jeddah.m2.<policy>-<hash>.net.xml.gz`
  (new names; the base network is untouched); netconvert with the window cutter's structural
  options reproduces the base network body byte for byte on an empty patch.
- TA-018 Routing-gain bias and matched controls. A placebo policy that re-routes 8 % of unchanged
  weekday vehicles one-shot (no trip changed) cut mean delay by 20 %, VHT 13 %: the 3-step
  baseline assignment is far from equilibrium, so re-routed vehicles gain. Policies that re-route
  baseline vehicles (staggered hours, cordon, closure) are therefore compared with a matched
  control run (same vehicles re-routed at their baseline times, no policy); reports show the
  raw-baseline comparison too. Same-class vType changes (car -> ride-hail) now keep their route
  (the first ride-hail run re-routed the converted vehicles and showed -12.3 % delay with +3.9 % VKT,
  recorded from the run console at the time; its log and run were overwritten, so the figure is not reproducible from saved
  outputs).
- Noise: re-simulating the weekday baseline with sim seed 2 changes mean delay +1.8 %, VHT +1.3 %.
- Friday baseline restarted with 8 threads after the Ramadan run (09:50; the 1-thread Friday
  assignment needed ~1.5 h per step under contention). Baseline final runs go through a launcher
  that gzips SUMO outputs (`python -m sim.policies.baseline_launch <daytype> --routing-threads 8 --gzip`, same code as the ad-hoc launcher used for the runs); integration should make
  `sim/population/baseline.py` write `.xml.gz` (metrics already reads it).

### M4 handoff (2026-10-16 13:45)
Built: policy models in `sim/schemas.py` + `python -m sim.validate`; `sim/policies/`: transforms
(remote_work with per-sector shares, staggered_hours, daytype, pt_line via ptlines2flows.py,
road_pricing with elasticity and edge-weight penalty, network_change via netconvert patch,
ridehail_share), incremental re-routing runner with matched controls, policy report (KPIs, peak
spreading, district winners/losers, top-10 relieved/worsened corridors, assumption ids, label),
parallel sweep (CSV + PNG), results summary, baseline launcher; `sim.runner --policy` (additive);
`sim/metrics.py` reads gzipped outputs. 9 demo policies incl. the composed Ramadan + 30 % remote.
Measured (10 % sample, seed 1, all "synthetic demand, uncalibrated"; table in docs/policies.md):
- New city baselines: Ramadan weekday 451,313 vehicle trips (4.51 M city-equivalent), mean delay
  1,805 s, 0.48 teleports/vehicle; Friday 385,392 (3.85 M), mean delay 1,596 s, peak hour 11:00,
  0.60 teleports/vehicle; Friday assignment 71 min (8 threads), final runs 10 min (Friday) and 20 min (Ramadan).
- Policies vs matching baseline (mean delay / AM-peak delay / VKT / CO2): remote_work_30 -9.3 /
  -9.4 / -1.6 / -6.9 %; staggered_schools_60 (vs control) -1.1 / -9.1 / +0.2 / -0.6 %, top-hour
  share -19 %; friday -14.9 / -98.0 / -3.3 / -13.0 %; ramadan_weekday -3.8 / -33.1 / +13.8 /
  +12.4 %; bus_line_tahlia +2.5 / +0.7 / -0.2 / +1.7 %; cordon_center (vs control) +20.1 / +8.6 /
  -0.4 / +10.4 %; close_corniche_road (vs control) +1.1 / +0.7 / -0.1 / +0.6 %; ramadan_remote_30
  (vs Ramadan) -9.8 / -13.9 / -1.2 / -7.2 %; ridehail_plus_10 +1.5 / -0.5 / +2.7 / +4.7 %.
- Noise replicate (sim seed 2): mean delay +1.8 %, VHT +1.3 % (one replicate). Placebo (8 %
  re-routed, no trip changed): mean delay -20.1 %, VHT -13.3 % (TA-018).
- Sweep remote_work share 0.1-0.5: 5 points, 2 processes, 33 min wall; linear, mean delay -3.1 %
  to -15.4 %, AM-peak -3.5 % to -15.6 %: no tested share halves the morning peak. The 0.3 point
  reproduces remote_work_30 bit for bit (tripinfo hash 81cd70d69a1a0790).
- Run cost: 14-17 min per incremental policy run, 17-24 min with its matched control.
- Tests: ruff clean; pytest 72 passed (demo window, ~1.5 min).
Commands (README at integration): `uv run python -m sim.runner --policy remote_work_30 --daytype
weekday --sample 0.10 --seed 1`; `uv run python -m sim.policies.sweep --policy remote_work --param
share=0.1:0.5:0.1 --sample 0.10`; `uv run python -m sim.validate sim/policies/*.yaml`.
Could not verify: real-world magnitudes (no counts; uncalibrated); whether the bus-line effect
exceeds noise (one replicate only); a deterministic 1-thread assignment of any city baseline (all
three use 8 threads and are reproducible from the route cache only).
Integration notes: `sim/schemas.py` also changed two existing lines (docstring, typing import);
`sim/validate.py` and `docs/img/m4-remote-work-sweep.png` are new; fold the `--gzip` option of
`sim/policies/baseline_launch.py` into baseline.py; the network variant
`data/jeddah/jeddah.m2.close_corniche_road-8376e92d.net.xml.gz` lives in the shared data dir; run
provenance stores absolute network paths (runs/ is untracked; make relative before publishing).
Next: more assignment steps and replicates to shrink the routing-gain and noise bands; README
commands at integration; network capacity (TA-011) remains the top issue.

Verifier: PASS on all 11 criteria after two fix rounds (per-sector share test, status accuracy).
M4: done

## M8 Calibration scaffolding (dormant) — 2026-10-16
Scope: PROJECT.md 9.12 and M8 without real data. No Jeddah counts exist; the path is built, proven
on synthetic counts and left dormant. All results stay "synthetic demand, uncalibrated".

Built:
- `sim/adapters/counts.py`: count CSV (`detector_id, edge_id, hour, count`) reader with validation,
  duplicate handling (A-cal-003), edge-id check against a network, edgeData writer for
  routeSampler (scaled to the population sample); CLI `python -m sim.adapters.counts check|to-edgedata`.
- `sim/adapters/traveltimes.py`: travel-time CSV (`segment_id, edge_ids, hour, travel_time_s,
  samples`) reader and comparison with simulated edge travel times (A-cal-002); CLI `check`.
- `sim/adapters/commercial.py`: `CountSource` / `TravelTimeSource` protocols and interface-only
  stubs for Google Routes, TomTom, HERE (raise NotImplementedError; key from env; data never
  committed).
- `sim/calibrate.py`: `python -m sim.calibrate --counts <csv> --daytype weekday` -> edgeData targets
  -> SUMO `routeSampler.py` over the day type's newest baseline routes (or `--net/--routes`) ->
  meso re-simulation with the baseline capacity scaling -> GEH per (edge, hour), per-hour table,
  optional travel-time check and `--before` reference; writes report.md, meta.json (seed, config,
  counts, network, routes hashes, SUMO version), geh.csv, mismatch.xml; exit code 2 on a miss.
- `sim/adapters/synthetic.py`: synthetic truth counts + unrelated candidate routes for the round trip.
- `sim/adapters/baseline_counts.py`: counts derived from a baseline run's edgeData for the
  city-scale mechanics check (not data).
- Config `sim/adapters/config/calibrate.yaml` (with an `assumptions:` block: `source:` /
  `assumption:` per id, values checked against the settings by a test); assumptions A-cal-001..006 in
  docs/assumptions-trackA.md; docs/calibration.md (pipeline, results, limits, partner data request).

Measured (all synthetic):
- Demo round trip (meso, seed 1; 40 detectors x 2 h = 80 counts; 14,400 candidate vehicles from
  another seed): GEH < 5 on 100 % (mean 0.32, max 0.74); candidates unchanged 0 % (mean 18.8);
  2,802 vehicles sampled; travel times 20/20 rows (10 segments x 2 h) within 15 % (mean abs error
  1.8 %). Also 100 % with
  `--sample 0.5` and with `--mode micro`. About 3 s per calibration. Same seed twice: identical
  calibrated routes hash, run id and GEH report.
- City check (weekday 10 % baseline as candidates, 389,289 vehicles; counts derived from the
  baseline's own edgeData with `sim.adapters.baseline_counts`, 50 edges, A-cal-006): hours 10-11
  only 80.0 % (FAIL: the first hour has no warm-up traffic, 64 %, volume 0.81; second hour 96 %),
  78-114 s over two identical-result runs (run calibrate-weekday-s1-3589cd5a-334e0110); full day 0-23, 1,200 counts: 87.7 % PASS
  (hourly 62-96 %, mean GEH 2.48), 101,578 vehicles sampled, 508 s with routeSampler 399 s, peak
  RSS routeSampler 4.2 GB, SUMO 2.6 GB (run calibrate-weekday-s1-f40885bc-334e0110; identical GEH
  in an earlier run before the run-id fix).
- Tests: ruff clean; pytest 87 passed (15 in tests/test_calibrate.py), about 1.8 min.

Decisions:
- TA-030 Counts are measured in a re-simulation of the sampled routes (edge `entered` per hour), not
  taken from routeSampler's own estimate, so the GEH includes congestion and hour-boundary effects.
- TA-031 routeSampler runs greedy (no `--optimize`): the LP optimiser needs scipy, not a project
  dependency. Add it if real counts leave large mismatch.
- TA-032 No `--keep-attributes`: it restores each candidate's original depart time and breaks the
  hourly placement. Sampled vehicles take one vType (`car`, copied from the candidates); the
  baseline mode mix is not preserved in a fit.
- TA-033 Partner counts must cover the whole day: a fit window that starts mid-day misses in its
  first hour (city check above). The data request asks for 24 hours.
- TA-034 The label never changes automatically: calibration runs record `calibration_status:
  fitted, not reviewed` and keep "synthetic demand, uncalibrated" until a human reviews a fit
  against real counts.
- TA-035 Duplicate detectors on one edge and hour are averaged (A-cal-003).
- TA-036 Run ids hash the candidate routes by content (SUMO headers ignored), so regenerated but
  identical candidates give the same run id; count CSVs are written with LF line endings.
- Verifier round 1: FAIL on the YAML assumption format (comments instead of `source:` /
  `assumption:`), plus doc fixes (travel-time row count, unreproducible "7,535 edges" without a
  committed generator, unrecorded peak RSS, run-id determinism). All fixed above.

Commands: `uv run python -m sim.adapters.synthetic --out runs/synthetic-demo` then
`uv run python -m sim.calibrate --counts runs/synthetic-demo/counts.csv --net data/demo/demo.net.xml
--routes runs/synthetic-demo/candidates.rou.xml --sample 1.0 --travel-times
runs/synthetic-demo/traveltimes.csv --counts-source synthetic --before` (README at integration).
Could not verify: any real-world fit (no counts); behaviour with real detector noise, missing hours
or detectors that do not map one-to-one to SUMO edges; whether the GEH target holds when the
baseline network capacity issue (TA-011) is fixed.
Integration notes: new files only (no shared file touched); README demo commands to add at
integration; `docs/calibration.md` is the page to link from the README.
- Verifier round 2: PASS on all criteria (ruff clean, 87 passed, determinism re-checked from scratch,
  city numbers matched). Its two minor notes were fixed after: travel-time output now says
  "segment-hours" (10 segments x 2 h) instead of "segments"; the hours 10-11 city run was
  regenerated from the committed generator (run id 3589cd5a, identical GEH).

Verifier: PASS (round 2, 2026-10-16).
M8: done
