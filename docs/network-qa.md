# Network QA: Tier A Jeddah network (M1)

> **Read first.** Sections 1-5 below analyse the intermediate network `40677b9f9e0c8be4` (polygon
> south edge at lat 21.30). Acting on recommendation 2, the polygon was then extended to lat 21.26;
> the **current** network is `5b8a19d3a3fd4d59` and its figures are in the Addendum at the end
> (smoke `smoke-A-s1-5b8a19d3-ab76d081`: 0.144 % teleports; main SCC 99.10 %). The SCC figures are
> reproducible with `uv run python -m sim.network.netinfo scc data/jeddah/jeddah.net.xml`.

Date: 2026-10-15. Network `data/jeddah/jeddah.net.xml` (post-fix, FIX-0001..0003), network hash
`40677b9f9e0c8be4`, Eclipse SUMO 1.28.0. All results: **synthetic demand, uncalibrated**.

## 1. Official smoke run (Tier A, meso)

Command: `uv run python -m sim.runner --smoke --tier A --seed 1` (log `logs/smoke-A-city-2.log`).
Run id: `smoke-A-s1-40677b9f-ab76d081` (config hash `ab76d0816327cacf`, population hash
`1242678a4e2da7ec`).

| Measure | Value |
|---|---|
| Edges / junctions / TLS programs | 151,000 / 60,600 / 72 |
| Lanes / lane-km / edge-km | 165,987 / 20,062.58 / 17,322.59 |
| Vehicles loaded / inserted / completed | 18,001 / 17,995 / 11,077 |
| Running / waiting at t = 3600 s | 6,918 / 1 |
| Teleports | 41 (all jam) = **0.228 %** of loaded (limit 0.5 %): **PASS** |
| SUMO wall time (runner) | 21.26 s for 3,600 s, RTF 169.3 (SUMO's own clock: 10.19 s, RTF 353.5) |
| Demand generation (randomTrips + duarouter) | 476.7 s |
| Peak memory, SUMO meso, same routes | 2.87 GB max RSS (3.00 GB peak footprint; `/usr/bin/time -l`) |
| Mean trip: duration / length / speed | 1,061.8 s / 24.3 km / 22.7 m/s |

Determinism: a separate SUMO invocation on the same routes (for the memory measurement) reproduced
17,995 inserted and 41 jam teleports.

Demand generation time: randomTrips in SUMO 1.28 validates trips by default (`--validate`), so even
with a single `-r` call it runs duarouter twice (a routing pass and a `--write-trips` validation pass).
Passing `--no-validate` would roughly halve the time but keep unroutable trips. The 8 min only affects
smoke runs; M2 demand will be routed differently.

### Teleport hotspot

All 41 teleports happen between t = 2,278 s and 3,568 s, at 16 junctions inside one ~3 km cluster in
north Jeddah (lon 39.202-39.210, lat 21.749-21.782). None are on or next to the King Abdulaziz Road
fix edges, and none end there.

Cause: a chain of **oneway secondaries with no `lanes` and no `maxspeed` tag** (OSM ways 679042576,
293223257, 208083192 "M-UN", 679042577, 1008050444). The typemap turns them into **1 lane at 100 km/h**.
The high default speed draws shortest-time routes onto them: about 1,100 of the 18,000 random routes
use the same single-lane edges in one hour, and queues form at priority junctions with residential
side roads.

This is systemic, not local. Among major OSM ways inside the clip that have no `lanes` tag:

| OSM class (as clipped) | km | km without `lanes` | km without `maxspeed` |
|---|---|---|---|
| motorway (oneway) | 412.6 | 239.7 (58 %) | 6.8 (2 %) |
| trunk oneway | 159.4 | 104.0 (65 %) | 86.5 (54 %) |
| primary oneway | 781.3 | 571.2 (73 %) | 472.4 (60 %) |
| secondary oneway | 1,369.1 | 1,134.1 (83 %) | 1,217.0 (89 %) |
| tertiary oneway | 1,099.7 | 976.9 (89 %) | 1,024.2 (93 %) |

Typemap defaults (`osmNetconvert.typ.xml`): motorway/trunk/primary 2 lanes, secondary 1 lane at
100 km/h, tertiary 1 lane at 80 km/h. Jeddah arterials are mostly dual carriageways (each side mapped
as a oneway). As a result, most of the major network gets the minimum lane count and a rural speed.
Another example from the route loads: Al Harameen Road (way 346621217, tagged maxspeed 100 but no
`lanes`) is 2 lanes between 4-5-lane ramp edges and carries 2,916 routes in the smoke.

## 2. Fix list check

`uv run python -m sim.network.fixes check --net data/jeddah/jeddah.net.xml`: all three fixes resolve
(FIX-0001 → 55 edges, FIX-0002 → 10, FIX-0003 → 3). Lane counts in the final network (streamed
parse):

| Fix | OSM way | Edges | Lanes | In main SCC |
|---|---|---|---|---|
| FIX-0001 | 85191646 | 55 | 54 × 4, 1 × 6 (a guessed ramp edge, kept by `lanes_min`) | 55/55 |
| FIX-0002 | 43061113 | 10 | 10 × 4 | 10/10 |
| FIX-0003 | 1071541010 | 3 | 3 × 4 | 3/3 |

No teleports start or end on these edges. Before the fix: 39 teleports (0.217 %); after: 41 (0.228 %).
The difference sits entirely in the northern hotspot above.

## 3. Connectivity (passenger)

- Weak connectivity: `netcheck.py -l passenger` → **1 component, 150,989 edges** (100 % of
  passenger edges; 11 edges in the net do not allow passenger cars).
- Strong connectivity (Tarjan on the edge graph via lane-level connections whose lanes both allow
  passenger cars): **651 SCCs; the main SCC has 148,893 edges = 98.61 % of passenger edges and
  19,203 of 20,060 lane-km (95.7 %)**. Stragglers: 2,096 edges, 608 edge-km.
- Straggler classes relative to the main SCC: 1,550 edges can reach it but cannot be reached from
  it (sources), 516 can be reached but cannot get back (sinks), 30 neither. 594 of the 650 small
  SCCs are single edges. 361 straggler edges are within 300 m of the polygon.
- Types: 1,655 residential, 134 secondary, 94 unclassified, 82 tertiary, 56 motorway, 35
  motorway_link, 17 primary, 6 trunk.

What the stragglers are:
1. **Southern border cut (≈1,075 edges, ≈170 km):** the largest straggler SCC (990 edges, 161 km;
   residential + secondary, lon 39.27 lat 21.32) and two smaller ones (63 and 22 edges) at the southern
   polygon edge (lat 21.30). Traffic can leave via the northbound Al Lith Road (way 1092887137), but the
   only way in from the southbound carriageway (way 1092887136) is a crossing south of lat 21.30,
   which the clip removes. The southbound carriageway itself ends at the polygon (dead end).
2. **Cordon carriageways (expected):** inbound and outbound carriageways of the motorways leaving the
   polygon (Jeddah-Makkah Expressway near 39.30/21.43, Huda Al Sham Road near 39.27-39.30/21.62,
   Al Lith Road). Inbound ones are sources and outbound ones are sinks by construction. They are the
   natural external gateways for M2, not errors.
3. **Northern enclave (117 edges, 14 km, lon 39.128 lat 21.772):** mostly two-way residential
   streets with a single access junction, `cluster_2196926572_7834981531`. Main-SCC edges connect in,
   but there is no connection out (`660165242#6` connects only to edges inside the enclave). This is
   either an OSM turn restriction or a junction-join artefact. Check against imagery before adding a
   fix.
4. **Single-edge stragglers (594):** oneway stubs and dead-end oneways, mostly residential.

## 4. Traffic lights

- OSM has 338 `highway=traffic_signals` nodes. After `--tls.guess-signals`, `--tls.join`,
  `--tls.discard-simple` and junction joining, these become 72 TLS programs controlling 77 junctions.
- Gap: junctions with at least 3 distinct neighbour junctions over trunk/primary/secondary edges:
  **2,264 priority-controlled vs 62 signalised**. With 4+ approaches: 436 priority vs 53 signalised.
  Including tertiary: 4,105 priority vs 74 signalised (908 vs 64 with 4+ approaches). The real number
  of signals in Jeddah is not known from open data (to verify: Jeddah Municipality / MOMRAH). Many
  major Jeddah crossings are grade-separated or roundabouts, so not all 2,264 should be signals.
- Scratch builds (city.yaml options plus the flag, without the fix list; output under `/tmp`, deleted afterwards):
  - `--tls.guess` (default threshold 69.44 m/s, the sum of incoming lane speeds) → **222** TLS programs.
  - `--tls.guess --tls.guess.threshold 40` → **30,275** programs (nonsense: almost every junction
    with a 100 km/h default speed qualifies).
  `--tls.guess` keys on incoming speed, and 89 % of secondary km carry the 100 km/h default. Guessing
  therefore depends on the untagged-speed problem in section 1 and is not reliable until that is
  fixed.

## 5. Recommendations

For M1: no build change needed. The smoke passes at 0.228 %, and connectivity is 100 % weak and
98.6 % strong.

For M2:
1. **Restrict demand to the main SCC.** Internal zones snap origins and destinations only to edges
   in the main passenger SCC. External gateways use cordon source edges for inbound trips and sink
   edges for outbound trips. Write the SCC membership once per network hash (for example
   `data/jeddah/main_scc.txt`) and use it in the demand builder. This removes the ~1.4 % of
   unroutable random trips seen in M1 (244 of 18,000 failed validation).
2. **Southern border:** extend `data/osm/jeddah.poly` south (to about lat 21.27) so the Al Lith Road
   crossing that serves the 990-edge district is inside. Then re-check the SCC; if a new cut appears,
   add a fix instead. This is a polygon (D-004) decision.
3. **Untagged major roads (largest realism issue):** add a Tier A type overlay for untagged oneway
   carriageways, with lanes and speed per class registered as assumptions in `docs/assumptions.md`.
   Candidate values: secondary 2 lanes at 60-70 km/h, tertiary 1-2 lanes at 50 km/h, primary 3 lanes,
   motorway 3-4 lanes. Note that typemap `numLanes` also applies per direction to two-way ways (only
   ~100 km of two-way secondary). Keep per-way fixes such as FIX-0001 for named arterials where tagged
   neighbours give the evidence. Add Al Harameen Road (way 346621217) as the next fix candidate.
4. **Traffic lights:** keep OSM-only signals plus `--tls.guess-signals` until item 3 is in.
   Then test `--tls.guess` (default threshold) on the corrected speeds and compare the count against
   any official signal inventory. Prefer a reviewed list of signalised junctions in the fix list over
   threshold tuning. The meso TLS penalty (A-sim-001) makes the TLS count matter less on Tier A than
   on Tier B windows.
5. **Northern enclave:** inspect `cluster_2196926572_7834981531` on imagery and add a connection or
   restriction fix if the exit is real.

## Commands used

```
nohup uv run python -m sim.runner --smoke --tier A --seed 1 > logs/smoke-A-city-2.log 2>&1 &
uv run python -m sim.network.fixes check --net data/jeddah/jeddah.net.xml
uv run python $SUMO_HOME/tools/net/netcheck.py data/jeddah/jeddah.net.xml -l passenger
/usr/bin/time -l sumo -n data/jeddah/jeddah.net.xml -r runs/smoke-A-s1-40677b9f-ab76d081/routes.rou.xml \
  --mesosim --meso-junction-control --meso-tls-penalty 0.5 --begin 0 --end 3600 --step-length 1 --seed 1 \
  --time-to-teleport 300 --ignore-route-errors
```
The SCC, tag-coverage, TLS-gap and teleport-hotspot analyses used throwaway streaming scripts (not in
the repo). netconvert scratch builds for `--tls.guess` used the city.yaml options plus the flag, with
output in `/tmp`.

Not verified: real signal count in Jeddah; actual lane counts on the untagged ways (imagery not checked);
whether the northern enclave exit is legally restricted.

## Addendum (2026-10-15, after the QA above): polygon extended south

Acting on the recommendation above, `data/osm/jeddah.poly` was extended south from lat 21.30 to
21.26, which brings the Al Lith Road crossing inside the clip and reconnects the southern district.
Rebuild and re-run, same seed and settings:

| | before (21.30) | after (21.26) |
|---|---|---|
| edges / junctions / TLS | 151,000 / 60,600 / 72 | 156,126 / 62,513 / 72 |
| lane-km | 20,062.58 | 20,952.88 |
| districts (admin_level 10 polygons) | 107 | 112 |
| main SCC, share of passenger edges | 98.61 % | 99.10 % (154,712 of 156,115; 622 SCCs, 2nd largest 443 edges) |
| smoke run id | smoke-A-s1-40677b9f-ab76d081 | smoke-A-s1-5b8a19d3-ab76d081 |
| loaded / inserted / completed | 18,001 / 17,995 / 11,077 | 18,001 / 17,994 / 10,825 |
| SUMO wall time (RTF) | 21.3 s (169) | 24.1 s (149) |
| teleports | 41 = 0.228 % | 26 = 0.144 % |

The remaining stragglers (single-edge oneway stubs, boundary carriageways, the northern enclave)
are handled in M2 by snapping zones to the main SCC (recommendation 1).
