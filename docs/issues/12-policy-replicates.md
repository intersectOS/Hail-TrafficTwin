# Seed replicates and confidence bands in the policy report

Labels: `policies`, `good first issue`

## Context
Each policy result has one noise replicate at most; run-to-run noise is about ±2 % on delay and
VHT, so small effects (bus line +2.5 %, Corniche closure +1.1 %) cannot be separated from noise.

## Acceptance
- `sim.policies.sweep` (or a new flag) runs N simulation seeds for a policy and its baseline and
  writes mean and min-max (or a t-interval) per KPI into `policy_report.{json,md}`.
- Tested on the demo-window policy with N=3.

## Pointers
`sim/policies/sweep.py`, `sim/policies/report.py`, `docs/policies.md` (noise section).
