---
name: assumptions-register
description: How to record every behavioural or data assumption (start times, trips per person, mode shares, rain factors, induced trips, building heights, flood sites) in YAML and in docs/assumptions.md with source, range and status. Use whenever introducing a parameter that describes real-world behaviour.
---
# Assumptions register

Every parameter that describes how Jeddah behaves (not how the code behaves) must appear twice: in the YAML where it is used, and as a row in `docs/assumptions.md`.

Row format:
```
| id | parameter | value | unit | range | source or assumption | status | used in |
```
- `id`: `A-<area>-<nnn>` (e.g. `A-demand-004`).
- `status`: `assumed` | `sourced` | `calibrated`. Only calibration (M8) sets `calibrated`.
- `source`: URL or citation with year; for `assumed`, one sentence on the reasoning and the plausible range.
- `used in`: file paths.

Rules
- Never bury a behavioural constant in code. Load it from YAML.
- When replacing an assumption with a sourced value, keep the row and update it; the history lives in git.
- The policy report template prints the ids of all assumptions a run depended on and the "synthetic demand, uncalibrated" label.
