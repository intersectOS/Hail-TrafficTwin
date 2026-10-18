# Induced demand: make capacity and remote-work policies add trips back

Labels: `policies`, `modelling`

## Context
Remote work has one induced-trip parameter (`induced_trip_probability`, A-pol-001/002). Network
changes (Loop, lane additions, closures) have no induced or suppressed demand at all, so relief
is an upper bound.

## Acceptance
- An elasticity-based transform (travel-time change to trip-rate change by purpose) applied after
  a first assignment, with the elasticity in YAML and a register row with a literature source.
- Demonstrated on `loop_recommended` and one network-change policy: relief with and without
  induced demand in the policy report.
- Unit test on the demo population.

## Pointers
`sim/policies/transforms.py`, `sim/policies/run.py`, `sim/loop/`, `docs/policies.md`, `docs/loop.md`.
