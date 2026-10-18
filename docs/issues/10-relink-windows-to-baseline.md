# Link focus windows to the behavioural baseline, not the random-trip smoke

Labels: `events`, `realism`

## Context
Tier B windows get their through-traffic from the M1 random-trip route set (`runs/source-smoke-A`),
not from the M2 synthetic-population baseline (B-D-002). Window events therefore see unrealistic
demand timing.

## Acceptance
- `sim.link` cuts window demand from the weekday baseline routes (10 % sample, scaled to 100 % for
  the micro window or with the scaling documented).
- `sim.link check` flow tolerance still met; `accident_tahlia` and the strategist re-run, numbers
  updated in `docs/events.md` and `docs/strategist.md`.

## Pointers
`sim/link.py`, `sim/network/windows/`, `docs/events.md`, decision B-D-002 in `docs/status/trackB.md`.
