# Track F: NETWORK_V2 (fix the Tier A capacity gap)

Branch `trackF`, worktree `.worktrees/trackF`, cut from `main` at 007d366. Everything below is
**synthetic demand, uncalibrated**. Details and tables: `docs/network-v2.md`.

## NETWORK_V2 — blocked: target not reached (2026-10-17)

### Diagnosis of the m2 baseline (before any change)
`python -m sim.network.teleports hotspots runs/baseline-weekday-f0.1-s1-e5f1906a-65fac195-65b0f3/sumo.log
--net data/jeddah/jeddah.m2.net.xml` (195,277 teleport lines parsed of 196,721 counted by SUMO):
teleports are diffuse (7,517 locations; top 15 = 3.6 %), 21 % on junction internal edges, 17 % on
the 95-m edges netconvert adds when it guesses ramps, 67 % of edge teleports on edges < 100 m,
and they pile up in the evening (hours 18-23 hold 64 %). Sampled vehicles are 71 m long (46 m +
25 m gap: 10 % capacity scaling, A-sim-101), and 55 % of the city's edges are shorter than 75 m,
so short-edge storage is part of the mechanism; lane counts are the other part.

### Decisions
- **TF-001 Evidence-based lane/speed defaults as an OSM pre-pass, not a typemap.** A typemap cannot
  tell a oneway carriageway from a two-way road of the same class; the pre-pass
  (`sim/network/lane_defaults.py tag`) adds `lanes`/`maxspeed` per class x oneway to untagged ways
  only, marked `traffictwin:defaults=A-net-301;A-net-302`. Defaults = km-weighted median of the
  tagged ways of the same class x oneway on the same clip (evidence file
  `sim/network/types/jeddah-lanes.json`), used when >= 5 km are tagged.
- **TF-002 Two-way roads are not widened.** Two-way secondary/tertiary/primary have 1.4 / 2.1 /
  2.0 km tagged; borrowing the dual-carriageway median (3 lanes per direction) would turn
  undivided roads into 6-lane roads. Their lanes stay on the SUMO typemap; maxspeed falls back to
  the class median.
- **TF-003 Held-out cross-check: no class disagrees strongly; the tagged median is kept.**
  130 lane-audit ways (both holdouts + calibration sets, read from Track C's results, no imagery
  calls): the default equals the way's own tag for motorway 62 %, trunk 89 %, primary 39 %,
  secondary 60 % (SUMO typemap 0 / 5 / 17 / 4 %, m2 overlay 36 / 89 / 39 / 28 %); within one lane
  74-98 %. Imagery reads agree 45-68 % (the imagery itself failed its 80 % gate). Motorway is the
  weakest (imagery tends to read 3 where the median says 4); the brief says to prefer the tagged
  median, so 4 stays.
- **TF-004 A peak probe instead of the 1-hour random-trip smoke for comparing variants.** The
  official smoke teleports 0.14 % on v1 and cannot tell variants apart. `python -m
  sim.network.probe` takes the m2 baseline's own vehicle trips 05:00-09:00 (91,392 sampled
  vehicles, capacity-scaled vTypes), routes them once at free flow and runs meso with the baseline
  Tier A options; ~6 min per variant. Free-flow routes load harder than the 3-step assignment, so
  the probe is relative (m2: probe 57.3 % vs baseline 50.5 %).
- **TF-005 Ramp splitting kept (`--ramps.guess` as in v1).** `--ramps.no-split` removes the short
  ramp edges but also the extra lane they carry: probe 48.0 % vs 40.0 % with splitting.
- **TF-006 `--no-internal-links` rejected.** Removes the junction-internal teleports but moves them
  upstream: 51.4 % (with no-split) vs 48.0 % without.
- **TF-007 `--junctions.join-dist 30` rejected** (with no-split): 48.6 % vs 48.0 % at 20 m.
- **TF-008 v2 is the default for Tier A baselines.** `sim/population/config/baseline.yaml` and
  `zones.yaml` point at `data/jeddah/jeddah.v2.net.xml`; `build_city` defaults to profile v2;
  `--network-profile v1|m2` rebuild the old networks (both reproduce their hashes, 5b8a19d3 and
  e5f1906a, written to /tmp).
- **TF-009 Incident: shared clip mtimes touched.** The first v2 build re-ran `osmium extract/cat`
  onto `data/osm/jeddah.osm.pbf` and `jeddah.osm.gz` (symlinks into main) because the worktree's
  `jeddah.poly` was newer than the clip. Content is byte-identical (hashes cafede24 / b491ff1d
  before and after); only mtimes changed. It also appended to the shared
  `data/jeddah/build_city-jeddah.log`; `build_city` now names custom-output logs after the full
  output stem so variants never share a log.

- **TF-010 Zones and population rebuilt on v2.** Zone edges are network edge ids, so v2 has its own
  zones (hash d949c812) and population (346893f2); v1/m2 zones are untouched in the main checkout.
- **TF-011 `--tls.guess` rejected** (probe 40.2 % vs 40.0 %, 283 TLS vs 73): no gain, and 210
  guessed signals cannot be checked against an inventory.
- **TF-012 v2 = v2a settings.** None of the junction/ramp/TLS variants beat measured lanes + speeds
  with the v1 netconvert options; `city-v2.yaml` keeps those options.
- **TF-013 No second city run.** First run 28.3 % > 10 %, so the hotspots were checked for fix-list
  entries: the diverges are consistent with the tags of the same roads, and the central cluster's
  same-road tagged segments agree with the defaults (King Abdullah Rd trunk 6.0 km tagged, median 3;
  Bani Malik St 7.8 km, 3; Prince Majid Rd 42.4 km, 3). No entry is sourced, the top 10 hold 3.7 %,
  and a teleport-time-300 probe shows real gridlock (40.6 %, 12,500 vehicles stuck vs 3,616), so a
  rerun would cost 2 h for at most a few points. Unsourced fixes are not added.
- **TF-014 Same-road lane propagation not adopted** (documented as a v3 candidate,
  docs/network-v2.md §5): 386 untagged km covered, 168 km changed in both directions, not at the
  hotspots, and it lowers two motorways from 4 to 3 lanes.
- **TF-015 Demo window and Tier B windows stay cut from v1.** Tier B is microscopic and its windows
  were cut and linked on v1/M1 routes (B-D-002); re-cutting from v2 is listed for the coordinator.
  The quick demo steps were rerun: same run ids and KPIs as M9 (tier-b smoke-B-s1-25c06763-9cfa755f
  0 teleports; events demo_events-demo-s1-342c09a8; strategist; evac_demo-demo-s1-ed042153; policy
  VKT -1.6 %, VHT -1.4 %); only the demo-policy baseline's config hash moved (1ea5e5 -> 0541a8)
  because `baseline.yaml`'s `net:` path is part of the hashed config.

- **TF-016 Pre-pass isolation (verifier finding, fixed).** The first version wrote the pre-pass of
  every build, including `--osm` test builds, to the city's `data/osm/jeddah.v2.osm.gz` and trusted
  it by mtime, so the demo build tests silently built the whole city, and in a fresh checkout a
  test could have planted demo-tagged OSM for the next city build. Now only the city build uses
  that path, custom builds write `<output>.lanes.osm.gz` beside their output, and reuse requires a
  sidecar with the same input and evidence hashes; the tests assert the file is under the test
  directory and the network is demo-sized. The city file was never overwritten (hash fb6a48f1
  before and after; v2 rebuilt after the fix: ae764558).

### Probe results (AM 05-09, same 91,392 vehicles; teleports per vehicle)
| network | settings | hash | teleports | mean speed | time loss |
|---|---|---|---|---|---|
| m2 (control) | Track A overlay A-net-201 | e5f1906a | 57.3 % | 34.3 km/h | 1,608 s |
| v2a | measured lanes + maxspeed (pre-pass) | ae764558 | 40.0 % | 43.3 km/h | 1,204 s |
| v2b | v2a + `--ramps.no-split` | bf84c83a | 48.0 % | 41.8 km/h | 1,226 s |
| v2c | v2b + `--junctions.join-dist 30` | ebc9d3a3 | 48.6 % | 41.9 km/h | 1,248 s |
| v2d | v2b + `--no-internal-links` | 290ec69b | 51.4 % | 43.5 km/h | 1,082 s |
| v2h | v2a + `--junctions.join-dist 30` | 80b9c370 | 40.3 % | 43.7 km/h | 1,188 s |
| v2i | v2a + `--no-internal-links` | 08dbc7a4 | 41.5 % | 45.0 km/h | 1,061 s |
| v2k | v2a + `--tls.guess` | c2c84582 | 40.2 % | 43.0 km/h | 1,210 s |
| v2 diag. | v2a, `--time-to-teleport 300` | ae764558 | 40.6 % | 38.5 km/h | 1,716 s |
(v2j, join 30 + no internal links, was stopped unfinished to free the machine for the city run.)

### City run estimate (recorded before starting)
10 % weekday baseline on v2 with `python -m sim.policies.baseline_launch weekday --routing-threads 6
--gzip`: new zones (v2 edges) mean a fresh population, trips and a 3-step assignment. Track A's 8-
thread run took 118 min of assignment under contention; with 6 threads and today's load (~25-30
from other tracks) estimate **2.5-3 h**. The smaller-sample result available beforehand is the
peak probe above (10 % sample, AM window).

### City runs (2 of the 3 allowed; one at a time)
| run id | network | what | result |
|---|---|---|---|
| baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1 | v2 ae764558 | 10 % weekday baseline, `baseline_launch weekday --routing-threads 6 --gzip`, 03:21-05:05 (1 h 44 min, load 25-45 from other tracks) | **teleports 28.3 %** (110,027); mean speed 28.7 km/h; mean delay 1,172.6 s; AM (06-09) 1,297 s; PM (17-20) 1,775 s; VKT 55.72 M; VHT 1.94 M; CO2 19,980 t |
| runs/repro/baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1 | v2 | same seed, re-simulated from the route cache (sim only, 5.4 min) | metrics.json summary identical; same network/population/routes/config hashes |
| smoke-A-s1-ae764558-ab76d081 | v2 | official 1 h random-trip smoke | 0 teleports (v1: 26 = 0.144 %) |
| probes (runs/probes/*) | m2, v2a-v2k | AM 05-09 peak probes, ~6 min each | table above |

Reproducibility: v2 built twice gives ae764558; v1 and m2 rebuilt to /tmp reproduce 5b8a19d3 and
e5f1906a. The baseline routes used 6 routing threads, so they are reproducible from the cache
only (routes_deterministic false in meta.json, TA-015); the simulation from those routes is
bit-repeatable (above). Runs on v1/m2 are untouched in the main checkout's `runs/`.

### Which run belongs to which network
- v1 5b8a19d3 (`jeddah.net.xml`): Tier A smokes `smoke-A-*-5b8a19d3-*`, the M9 demo Tier A smoke on
  a fresh clone (79f35c9a, newer OSM), Tier B windows and the demo window (cut from v1).
- m2 e5f1906a (`jeddah.m2.net.xml`): every city run before this track: baseline
  `baseline-weekday-f0.1-s1-e5f1906a-65fac195-65b0f3` (and Track A's f124c5), Friday and Ramadan
  baselines, policies (remote_work_30, staggered_schools_60(+control), cordon_center(+control),
  sweeps), M8 synthetic calibration round trip, Loop (loop-10bd36fcec network derived from m2,
  loop_recommended, loop-demo), Track H mode-choice work on the baseline outputs.
- v2 ae764558 (`jeddah.v2.net.xml`): the runs in the table above.

### Downstream results that need a rerun on v2 (for the coordinator; not rerun here)
1. Friday and Ramadan-weekday 10 % baselines (Track A M4).
2. All Tier A policy runs and sweeps against the v2 weekday baseline (remote_work_30,
   staggered_schools_60 + control, cordon_center + control, policy sweeps).
3. Loop: rebuild the loop network from v2 (`sim.loop.network data/jeddah/jeddah.v2.net.xml ...`),
   rerun loop_recommended and the corridor screening; Track H mode choice reads the baseline
   outputs, so its numbers move too.
4. Films that reference the m2 baseline or the runs above: `city-24h`, `policy-lab`, `loop`
   (movies/specs pin `baseline-weekday-f0.1-s1-e5f1906a-...`), then the showreel.
5. M8 synthetic calibration round trip (network-dependent edge ids).
6. Optional: re-cut Tier B windows and the demo window from v2 and re-link them to the v2 baseline
   routes (B-D-002); Tier B events, strategist and evacuation results are on windows and do not
   change otherwise.
7. The 25 % sample check (TA-011, A-sim-101) is now more useful than ever: it separates the
   sampling artefact from real overload.
Not affected: Tier B window runs, strategist, evacuation, the demo steps (rerun here: same run ids
and KPIs as M9).

### Departures from the brief (for the coordinator)
- Target < 10 % teleports **not reached**: 28.3 % on v2 (50.5 % on m2).
- The brief's "iterate once on the hotspots and rerun" was carried out as analysis only: no
  hotspot has a sourced fix (TF-013), so no second city run was made (2 of 3 allowed used: the
  baseline and its re-simulation; the smoke is the official 1 h smoke).
- Roundabouts and turn lanes were kept as in v1 by argument, not measured (docs/network-v2.md §3).
- The held-out cross-check reads Track C's untracked lane-audit results
  (`.worktrees/trackC/data/imagery/*/ways.json`, `results/`): `imagery-eval.json` holds aggregates
  only. The per-class summary is committed (`sim/network/types/jeddah-lanes-crosscheck.json`); the
  lane-audit ways are tagged ways that also enter the medians (stated in the doc).

### Verifier
Run 1 (2026-10-17 06:27): KPIs, hotspots, all three network hashes (rebuilt independently to
/tmp: v2 ae764558, v1 5b8a19d3, m2 e5f1906a), same-seed KPIs from the route cache, register,
labels and git hygiene PASS; pytest 324 passed / 3 skipped. FAILs: target missed (stands; this is
the blocked reason), F1 pre-pass isolation (fixed, TF-016), status not committed (committed),
`--tls.guess` contradiction and unprobed variants v2e/f/g undocumented (fixed in
docs/network-v2.md §3), `MIN_TAGGED_KM` / reference lane values in code (now a recorded CLI option
and read from the v1/m2 type files), two number nits (fixed).

NETWORK_V2: blocked - teleports 28.3 % on v2 vs the < 10 % target (m2 50.5 %); v2 is built, measured and the default, but no sourced network fix remains (TF-013); next: 25 % sample run and evening demand check (docs/network-v2.md §5)
