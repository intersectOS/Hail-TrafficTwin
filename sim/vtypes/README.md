# sim/vtypes

Driver and vehicle types for focus windows (M5).

- `types.yaml`: vType library (normal, slow, aggressive, truck, bus, emergency, convoy). Every
  parameter has a register id, range and `source:` or `assumption:` (docs/assumptions-trackB.md).
  `emergency` carries the bluelight device and is `tier_b_only`; `convoy` uses vClass `vip`.
- `mix_default.yaml`: default mix (shares sum to 1). Scenarios override with `vtype_mix:`.
- `loader.py`: `write_vtypes_additional()` writes all vTypes plus a `vTypeDistribution`
  (`mix`); Tier A refuses tier-B-only types. `apply_mix()` streams a trips/routes file and gives
  vehicles without a type the distribution id (SUMO samples members with its seeded RNG).

    python -m sim.vtypes check
    python -m sim.vtypes write --out /tmp/vtypes.add.xml --tier B
