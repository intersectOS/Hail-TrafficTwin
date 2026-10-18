# Run the weekday baseline at 25 % and 100 % and document the cost

Labels: `performance`, `population`

## Context
All city results use a 10 % population sample with capacity scaling (M2 sampling decision). The
brief asks to measure whether a full 24 h meso run fits in 1-2 hours on a laptop; it was never
tried. Without it nobody knows how much the 10 % sample biases the policy deltas.

## Acceptance
- 25 % baseline measured first: wall time (assignment and final run), peak RSS, disk, teleports,
  KPIs against the 10 % run, recorded in `docs/population.md`.
- 100 % run only if the 25 % numbers predict it fits in 18 GB RAM; otherwise the estimate and the
  reason are written down.
- `remote_work_30` delta at 25 % next to the 10 % delta.

## Pointers
`sim.runner --baseline --sample 0.25 --gzip` (`sim/population/baseline.py`,
`sim/population/sampling.py`), route cache keys (TA-013/TA-015), `make city SAMPLE=...`.
Long runs in the background with logs under `logs/`.
