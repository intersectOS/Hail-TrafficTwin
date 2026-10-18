# Assumptions register: Track F (network v2)

Same row format as `docs/assumptions.md`; merged into it at integration. The values live in
`sim/network/config/city-v2.yaml` and the evidence file `sim/network/types/jeddah-lanes.json`
(written by `python -m sim.network.lane_defaults stats`). All results stay **synthetic demand,
uncalibrated**. A-net-301/302 supersede A-network-003 (SUMO typemap defaults, profile v1) and
A-net-201 (judgement overlay, profile m2) for the v2 network; v1 and m2 still build with their own
settings.

| id | parameter | value | unit | range | source or assumption | status | used in |
|---|---|---|---|---|---|---|---|
| A-net-301 | lanes per direction for OSM ways of the major classes without a `lanes` tag (class x oneway) | oneway: motorway 4, trunk 3, primary 3, secondary 3, tertiary 2, motorway_link 2, primary_link 1; two-way ways and classes with < 5 km tagged keep the SUMO typemap | lanes | p25-p75 of tagged km: motorway 3-4, trunk 3-3, primary 2-4, secondary 3-3, tertiary 2-3, motorway_link 2-2, primary_link 1-2 | Source: km-weighted median of the tagged ways of the same class x oneway on the same clip (motorway 173 km tagged, trunk 55, primary 252, secondary 235, tertiary 123, motorway_link 27, primary_link 14), `sim/network/types/jeddah-lanes.json`. Held-out check (130 lane-audit ways, `jeddah-lanes-crosscheck.json`): default equals the way's own tag for motorway 62 %, trunk 89 %, primary 39 %, secondary 60 % (SUMO typemap: 0 / 5 / 17 / 4 %), within one lane 74-98 %. Caveat: mappers tag bigger roads more often, so the median may overstate untagged ways; two-way untagged roads are not widened (undivided) | sourced | sim/network/config/city-v2.yaml, sim/network/lane_defaults.py |
| A-net-302 | `maxspeed` for OSM ways of the major classes without the tag (class x oneway; two-way ways use the class's oneway median) | motorway 100, trunk 90, primary 80, secondary 80, tertiary 80, motorway_link 60 km/h; other links keep the SUMO typemap | km/h | p25-p75: motorway 100-120, trunk 90-90, primary 80-90, secondary 60-90, tertiary 80-80 | Source: km-weighted median of tagged `maxspeed` on the same clip (motorway 405 km tagged, trunk 73, primary 308, secondary 152, tertiary 75, motorway_link 6.5). Posted limits, not travel speeds; meso congestion sets the travel speed | sourced | sim/network/config/city-v2.yaml, sim/network/lane_defaults.py |
