# Network v2: closing the Tier A capacity gap (Track F)

Date: 2026-10-17. Eclipse SUMO 1.28.0, same OSM clip as v1/m2 (`data/osm/jeddah.osm.gz`, hash
b491ff1d; GCC extract of 2026-10-14). All results: **synthetic demand, uncalibrated**. Decisions
TF-nnn are in `docs/status/trackF.md`; assumptions A-net-301/302 in `docs/assumptions-trackF.md`.

## 1. Profiles and hashes

| profile | config | network file | hash | lanes / maxspeed on untagged ways |
|---|---|---|---|---|
| v1 (M1) | `sim/network/config/city.yaml` | `data/jeddah/jeddah.net.xml` | 5b8a19d3a3fd4d59 | SUMO typemap (A-network-003) |
| m2 (Track A) | `sim/population/config/network-m2.yaml` | `data/jeddah/jeddah.m2.net.xml` | e5f1906af7fded33 | judgement overlay (A-net-201) |
| **v2 (default)** | `sim/network/config/city-v2.yaml` | `data/jeddah/jeddah.v2.net.xml` | **ae7645589de321f9** | measured medians (A-net-301/302) |

```
uv run python -m sim.network.build_city                          # v2 (default profile)
uv run python -m sim.network.build_city --network-profile v1     # M1 settings
uv run python -m sim.network.build_city --network-profile m2 --out data/jeddah/jeddah.m2.net.xml --no-side-outputs
```
v1 and m2 rebuilt from their settings into `/tmp` reproduce 5b8a19d3 and e5f1906a byte for byte;
v2 built twice (once with an uncompressed and once with a gzipped pre-pass file) gives ae764558
both times.

| | v1 | m2 | v2 |
|---|---|---|---|
| edges / junctions / TLS | 156,126 / 62,513 / 72 | 155,366 / 61,774 / 74 | 155,663 / 62,136 / 73 |
| lane-km | 20,952.9 | 22,968.2 | 25,410.8 |
| main passenger SCC | 99.10 % | 99.09 % | 99.10 % (154,250 of 155,653; 617 SCCs) |
| 1 h random-trip smoke (seed 1) | 26 teleports = 0.144 % | - | 0 teleports (smoke-A-s1-ae764558-ab76d081; 17,996 inserted) |

## 2. Evidence-based lane and speed defaults

`python -m sim.network.lane_defaults stats` exports every highway way of the measured classes from
the clip (osmium), measures its length, and for each class x oneway computes the km-weighted
distribution of **lanes per direction** (oneway: `lanes`; two-way: `lanes:forward`/`backward`,
else `lanes`/2) and of `maxspeed`, over the ways that carry the tag. Output:
`sim/network/types/jeddah-lanes.json` (committed, with the source hash cafede24).

| class x direction | km | tagged km (share) | lanes p25 / p50 / p75 | maxspeed p25 / p50 / p75 (tagged km) | v2 default |
|---|---|---|---|---|---|
| motorway oneway | 450.7 | 172.6 (38 %) | 3 / 4 / 4 | 100 / 100 / 120 (405) | 4 lanes, 100 km/h |
| trunk oneway | 159.2 | 55.3 (35 %) | 3 / 3 / 3 | 90 / 90 / 90 (73) | 3, 90 |
| primary oneway | 863.1 | 251.5 (29 %) | 2 / 3 / 4 | 80 / 80 / 90 (308) | 3, 80 |
| secondary oneway | 1,389.9 | 235.1 (17 %) | 3 / 3 / 3 | 60 / 80 / 90 (152) | 3, 80 |
| tertiary oneway | 1,143.5 | 122.6 (11 %) | 2 / 2 / 3 | 80 / 80 / 80 (75) | 2, 80 |
| motorway_link oneway | 177.2 | 27.4 (15 %) | 2 / 2 / 2 | 60 / 60 / 90 (6.5) | 2, 60 |
| primary_link oneway | 88.1 | 13.6 (15 %) | 1 / 1 / 2 | - | 1, typemap speed |
| secondary / tertiary / primary two-way | 106 / 78 / 3 | 1.4 / 2.1 / 2.0 | (too little) | class median | typemap lanes, 80 km/h |
| trunk_link, secondary_link, tertiary_link | 39 / 38 / 10 | 1.2 / 3.3 / 0.6 | (too little) | - | typemap |

Rules (TF-001, TF-002): a median is used only with >= 5 km of tagged evidence; lanes round half up;
two-way ways are never widened from the dual-carriageway median (undivided roads); minor classes
(residential, unclassified) keep the typemap.

**Mechanism.** A typemap applies one `numLanes` per class to both oneway and two-way ways, so it
cannot express the table. v2 uses a reproducible pre-pass instead: `python -m
sim.network.lane_defaults tag` streams the clipped OSM XML and adds `lanes` (two-way: 2 x per
direction) and `maxspeed` to ways that lack them, marked `traffictwin:defaults=A-net-301;A-net-302`.
Tagged ways are untouched. On the Jeddah clip it tags 4,110 ways with lanes and 4,275 with
maxspeed (81,602 ways read). `build_city` runs it when the config has a `lane_defaults:` block:
the city build writes `data/osm/jeddah.v2.osm.gz` (gzip with mtime 0, so the file hash is stable),
a build from `--osm` or to `--out` writes `<output>.lanes.osm.gz` beside its own output, and the
file is reused only when its sidecar `.json` records the same input and evidence hashes. The
5 km evidence threshold is a method setting (`stats --min-tagged-km`, recorded in the evidence
file).

**Held-out cross-check** (`python -m sim.network.lane_defaults crosscheck --imagery-dir
<lane-audit data>/data/imagery --sets v2-holdout,holdout,v2-calibration,calibration`; reads the
existing lane-audit results, no imagery calls; `sim/network/types/jeddah-lanes-crosscheck.json`).
The lane-audit ways are tagged ways, so the question is: had this way been untagged, would the
default have matched its tag?

| class | ways | v2 default = tag | within 1 lane | SUMO typemap = tag | m2 overlay = tag | v2 default = imagery read |
|---|---|---|---|---|---|---|
| motorway oneway | 42 | 62 % | 98 % | 0 % | 36 % | 45 % (40 reads) |
| trunk oneway | 38 | 89 % | 95 % | 5 % | 89 % | 65 % (34) |
| primary oneway | 23 | 39 % | 74 % | 17 % | 39 % | 57 % (23) |
| secondary oneway | 25 | 60 % | 96 % | 4 % | 28 % | 68 % (25) |

No class disagrees strongly, so the tagged-OSM median stays (TF-003). The imagery reads failed
their own 80 % gate (docs/lane-audit.md) and are a weak second opinion; where they differ, they
read motorways as 3 lanes. Caveat: the sample overlaps the ways the medians are computed from, and
mappers tag bigger roads more often, so the medians may overstate untagged ways.

## 3. Junctions and ramps: peak probe

The 1-hour random-trip smoke (0.14 % teleports on v1) cannot separate variants. `python -m
sim.network.probe` (TF-004) takes the m2 baseline's own vehicle trips departing 05:00-09:00
(91,392 sampled vehicles, capacity-scaled vTypes), routes them once at free flow on the candidate
network and simulates 05:00-10:00 in meso with the baseline's Tier A options (limited junction
control, 120 s teleport time, tau x10). Teleports are counted per vehicle as in the baseline's
`teleport_share`. Free-flow routes load harder than the 3-step assignment (m2: 57.3 % in the probe,
50.5 % in its 24 h baseline), so the probe is a comparison, not a forecast.

| variant | change vs v2a | hash | teleports | mean speed | time loss | on junction internals / guessed ramps |
|---|---|---|---|---|---|---|
| m2 (control) | Track A overlay | e5f1906a | 57.3 % | 34.3 km/h | 1,608 s | 21 % / 18 % |
| **v2a = v2** | measured lanes + maxspeed, v1 netconvert options | ae764558 | **40.0 %** | 43.3 | 1,204 | 15 % / 19 % |
| v2h | `--junctions.join-dist 30` | 80b9c370 | 40.3 % | 43.7 | 1,188 | 15 % / 19 % |
| v2i | `--no-internal-links` | 08dbc7a4 | 41.5 % | 45.0 | 1,061 | 0 % / 18 % |
| v2b | `--ramps.no-split` | bf84c83a | 48.0 % | 41.8 | 1,226 | 17 % / 0 % |
| v2c | no-split + join-dist 30 | ebc9d3a3 | 48.6 % | 41.9 | 1,248 | 17 % / 0 % |
| v2d | no-split + no internal links | 290ec69b | 51.4 % | 43.5 | 1,082 | 0 % / 0 % |

Decisions: ramp splitting stays (TF-005: the 95-m ramp edges are where teleports are counted, but
they carry the extra lane; without them the diverge has fewer lanes and teleports rise);
`--no-internal-links` is rejected (TF-006: it removes junction-internal teleports by moving them
upstream, and Tier B windows need internal links); a 30-m join distance is neutral and rejected
(TF-007, it would also change more edge ids). `--tls.guess` on the corrected speeds (v2k,
c2c84582: 283 TLS instead of 73) was probed after the city run: 40.2 % vs 40.0 %, so it is rejected
(TF-011; 210 guessed signals with no inventory to check them against, docs/network-qa.md §4); the
OSM signals stay. Roundabout guessing and turn lanes were **not tested**, only kept as in v1:
`--roundabouts.guess` is already on, and meso does not model lanes per movement, so OSM turn lanes
(`--osm.turn-lanes`) would change lane directions, not meso capacity. This is an argument, not a
measurement.

Not completed: the probe of v2j (join-dist 30 + no internal links) was stopped to free the
machine for the city run; both of its parts were neutral or worse on their own. Built but never
probed (superseded once no-split proved worse): v2e (no `--ramps.guess`), v2f (no-split + no
internal links + join-dist 30), v2g (no-split + no internal links + `--ramps.min-highway-speed
25`). Variant configs were generated from `city-v2.yaml` with the changes listed for each (scratch
files, not committed); every probe's options and hash are in `runs/probes/<label>-<hash>-05-09/`.

## 4. City baseline on v2

`uv run python -m sim.policies.baseline_launch weekday --routing-threads 6 --gzip` (10 % sample,
seed 1, meso, 3-step incremental duaIterate, 120 s teleport time, capacity x10; zones rebuilt on the
v2 edges: zones hash d949c812, population 346893f2). Run id
**`baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1`** (in this worktree's `runs/`). Wall time
1 h 44 min under heavy load from other tracks (load average 25-45): assignment 96.7 min (routing
6 threads), final 24 h simulation 6.3 min, peak 3.6 GB
(duarouter) / 3.3 GB (sumo). Assignment steps (from the step logs `iteration_00k.sumo.log`, deleted with the duaIterate
work directory after the run, so not kept as artefacts): step 0 (1/3 of the demand) 868 teleports
= 0.67 % of inserted vehicles, step 1 (2/3) 22,868 = 8.8 %; final run (full demand) 28.3 %.

| KPI (synthetic demand, uncalibrated) | m2 baseline (e5f1906a) | **v2 baseline (ae764558)** | change |
|---|---|---|---|
| vehicles (sampled) | 389,289 | 389,301 | (new zones, same population size) |
| **teleports per vehicle** | 50.5 % (196,721) | **28.3 % (110,027)** | -22.3 points (-44 %) |
| completion share | 99.19 % | 99.60 % | |
| mean speed | 20.5 km/h | 28.7 km/h | +40 % |
| mean delay per trip | 1,876.5 s | 1,172.6 s | -38 % |
| AM peak (06-09) mean delay | 2,098 s | 1,297 s | -38 % |
| PM peak (17-20) mean delay | 2,785 s | 1,775 s | -36 % |
| evening (20-23) mean delay | 3,165 s | 2,205 s | -30 % |
| mean trip duration / length | 2,563 s / 14.57 km | 1,804 s / 14.39 km | |
| VKT (real-scale) | 56.10 M veh-km | 55.72 M veh-km | -0.7 % |
| VHT (real-scale) | 2.74 M veh-h | 1.94 M veh-h | -29 % |
| CO2 | 26,185 t | 19,980 t | -24 % |

Plausibility: 55.7 M veh-km/day is about 15 veh-km per resident (3.71 M residents) and the day mean
speed is 28.7 km/h; neither is checked against Jeddah data (none is open). The delay is not
plausible: time loss is 63 % of trip time, i.e. trips take 2.7 times their free-flow time on
average. The network is still overloaded, mostly in the evening.

**Where the remaining teleports are** (`python -m sim.network.teleports hotspots
runs/baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1/sumo.log --net data/jeddah/jeddah.v2.net.xml`):
4,906 locations; the top 10 hold 3.7 %; 18 % on junction internals, 18 % on guessed ramp edges;
by hour 06-09 19 %, 18-24 67 %. Spatially (2 km cells) the central corridor of King Abdullah Road /
Bani Malik St / Prince Majid Rd / Abdullah Sulaiman St (lon 39.19-39.25, lat 21.49-21.53) holds
29 %.

| # | edge / junction | class | lanes | length m | name | teleports | peak hours | lon, lat |
|---|---|---|---|---|---|---|---|---|
| 1 | 39225640#62 | secondary | 3 | 358 | شارع الأمير نايف (Prince Naif St) | 576 (0.5 %) | 13, 7, 9 | 39.12122, 21.78554 |
| 2 | 507564171#1 | trunk | 6 | 60 | طريق الملك عبدالله (King Abdullah Rd) | 500 (0.5 %) | 19, 20, 6 | 39.23327, 21.51038 |
| 3 | 41410219#7-AddedOffRampEdge | secondary | 6 | 96 | - | 412 (0.4 %) | 13, 6, 20 | 39.23966, 21.50884 |
| 4 | 219626061#12-AddedOffRampEdge | motorway | 6 | 94 | - | 402 (0.4 %) | 7, 8, 21 | 39.12999, 21.78859 |
| 5 | 294798624-AddedOffRampEdge | motorway | 8 | 94 | طريق المدينة المنورة (Madinah Rd) | 380 (0.4 %) | 18, 17, 22 | 39.13914, 21.78268 |
| 6 | 48559212#15-AddedOffRampEdge | primary | 6 | 94 | - | 380 (0.4 %) | 17, 18, 20 | 39.19363, 21.50766 |
| 7 | 346621217#12 | motorway | 6 | 86 | طريق الحرمين (Al Harameen Rd) | 362 (0.3 %) | 23, 20, 22 | 39.23040, 21.57054 |
| 8 | 92028872#5 | residential | 1 | 401 | شارع الملاعب (Al-Mala'ib St) | 360 (0.3 %) | 18, 12, 22 | 39.23972, 21.49836 |
| 9 | 1506112912#1 | tertiary | 3 | 197 | شارع النسيم (Al Naseem St) | 348 (0.3 %) | 20, 19, 21 | 39.22236, 21.52368 |
| 10 | cluster_5336946617_5339560343 | junction (priority) | - | - | - | 346 (0.3 %) | 6, 19, 20 | 39.23891, 21.51776 |

**Iteration on the hotspots (TF-013): no fix-list entry qualifies, so no second city run.** The
diverge hotspots (#3-#6) are 4 mainline + 2 exit lanes, consistent with the tags of the same roads;
the queues come from the exits into the grid. The central cluster's ways are mostly untagged and
carry the class defaults, but their tagged segments of the same road agree with those defaults
(King Abdullah Rd trunk: 6.0 km tagged, median 3 = class default; Bani Malik St 7.8 km, 3; Prince
Majid Rd 42.4 km, 3). With no evidence of a wrong lane count, an entry would be a guess, and the
fix list takes reviewed, sourced entries only. Probe diagnostics on v2 support this:

| probe (AM 05-09) | teleports | mean speed | vehicles still running at 10:00 |
|---|---|---|---|
| v2 | 40.0 % | 43.3 km/h | 3,616 |
| v2 + `--tls.guess` (283 TLS instead of 73; v2k, c2c84582) | 40.2 % | 43.0 | 3,664 |
| v2, teleport time 300 s instead of 120 s (diagnostic, not a setting change) | 40.6 % | 38.5 | 12,500 |

With a longer teleport time the vehicles stay stuck instead of jumping: the teleports are gridlock,
not an artefact of the 120 s threshold.

## 5. What remains, and for whom

Target (< 10 % teleports) **not reached**: 28.3 %. Network v2 removed 44 % of the teleports and
38 % of the delay using only evidence from OSM itself. What is left is not visible as a network
error with the data we trust:

1. **Load in the evening.** 67 % of teleports are 18-24 h; 170-270 k real-scale departures per hour
   continue from 16 to 23 h (hours 16-22). The evening activity profile (Track A day types) and the
   no-retiming of trips under congestion are the first thing to check.
2. **Sampling and meso settings (A-sim-101/102/103).** 10 % sampling makes every vehicle 71 m long;
   55 % of Jeddah's edges are shorter than 75 m, and 66 % of v2 edge teleports are on edges under
   100 m. A 25 % run (open since TA-011) would show how much is a sampling artefact.
3. **Same-road lane evidence (not adopted).** Propagating the median of tagged segments of the same
   named road (instead of the class median) covers 386 untagged km and changes 168 km, in both
   directions (Huda Al Sham and Madinah Rd motorways 4 -> 3, King Abdulaziz Rd 3 -> 4 as FIX-0001,
   Al Makarona Rd 3 -> 2). It is more specific evidence, but it does not touch the hotspots and lowers
   motorway capacity; a candidate for v3, with a leave-one-out check against the tags first.
4. **Real lane counts and signal inventory.** The imagery audit stays blocked; an official Jeddah
   road inventory (MOMRAH / Jeddah Municipality) would replace both medians.

## 6. Reproduce

```
uv run python -m sim.network.lane_defaults stats                 # evidence file (committed)
uv run python -m sim.network.build_city                          # v2 -> data/jeddah/jeddah.v2.net.xml
uv run python -m sim.population.zones                            # zones on v2 (zones.yaml points at v2)
uv run python -m sim.policies.baseline_launch weekday --routing-threads 6 --gzip
uv run python -m sim.network.teleports hotspots runs/<run>/sumo.log --net data/jeddah/jeddah.v2.net.xml
uv run python -m sim.network.probe --net data/jeddah/jeddah.v2.net.xml --trips runs/<baseline>/trips.xml --label v2
```
