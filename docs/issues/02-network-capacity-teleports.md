# Network capacity: bring the 10 % weekday baseline below 10 % teleported vehicles

Labels: `network`, `realism`

## Context
The 24 h weekday baseline teleports 50.5 % of its vehicles (TA-011): untagged roads default to
1-2 lanes at 100 km/h, junction clusters and ramps choke, and only 72 traffic-light programs
exist (2,264 major 3+-approach junctions have none). Network capacity, not demand, is the binding
issue, so absolute delays are not meaningful.

## Acceptance
- A network variant written under a new name (`data/jeddah/jeddah.<suffix>.net.xml`, never
  overwriting `jeddah.net.xml`) built reproducibly by `sim.network.build_city` with a config file.
- Measured on a 1 % sample first (`make city SAMPLE=0.01`), then 10 %: teleport share, runtime and
  mean delay reported in `docs/network-qa.md`; every new typemap default registered in
  `docs/assumptions.md`.

## Pointers
`sim/network/config/city.yaml`, `sim/population/config/untagged.typ.xml`,
`sim/population/config/network-m2.yaml`, `docs/network-qa.md`, decision D-015 in `docs/STATUS.md`
(`--tls.guess` thresholds).
