# Replace fixed mode shares with a logit mode choice

Labels: `population`, `modelling`

## Context
v1 assigns modes from fixed shares per segment (`sim/population/config/modes.yaml`). Policies
that should shift modes (bus line, cordon, Loop) therefore use a fixed shift share, and the Loop
result rests on an unsourced shift share alpha (`docs/loop.md`, "Vendor claims versus measured
figures").

## Acceptance
- A multinomial logit over car, ride-hail, bus and walk with time and cost terms, parameters in
  YAML with `source:` or `assumption:` and register rows.
- Deterministic for a seed; unit tests on the demo population; baseline mode shares within the
  current documented ranges.
- `bus_line_tahlia` re-run with the logit, compared with the fixed-share result in
  `docs/policies.md`.

## Pointers
`sim/population/modes.py`, `sim/policies/transforms.py`, `sim/policies/ptline.py`, `docs/population.md`.
