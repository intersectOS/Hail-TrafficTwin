# Track H status: Loop mode choice (branch trackH)

All results: synthetic demand, uncalibrated.

## MODECHOICE: replace the assumed Loop shift share with a mode-choice model (2026-10-17)

Built:
- `sim/loop/mode_choice.py`: binary car-vs-Loop logit on door-to-door generalised time per tour
  leg (tour chooses on the summed legs), pair-hour and tunnel-segment-hour capacity cap
  (first-come; riders above capacity do not shift) with a deterministic queue fed back by
  successive averages; offline `sweep` (no SUMO) and `check` CLIs.
- `sim/loop/config/mode_choice.yaml` (coefficients, car side, queue, services, sweep), every block
  sourced or assumed; register `docs/assumptions-trackH.md` (A-loop-021..030); sources
  `docs/data-sources-trackH.md` (data-scout, checked 17 Oct 2026).
- Integration (additive): `LoopShuttle.mode_choice` field (schema), `resolve_params` passes it,
  `loop_shuttle` calls `shuttle_choice` instead of `u < alpha` when it is set (the alpha path is
  unchanged), `loop_report.json` gets a `mode_choice` block, `evaluate --mode-choice <yaml>
  [--service measured|vendor] [--sim-seed 2] [--demo]` (results in
  `sim/loop/results/evaluation_mode_choice.json`; Track D's `evaluation.json` untouched).
- `tests/test_loop_mode_choice.py` (10 tests: alpha-path policy hash unchanged, register, monotonicity, tour sum, capacity cap and
  queue, two-leg tours, determinism + alpha equivalence, missing car time, params, demo end to end
  run twice).
- `docs/loop-mode-choice.md`; `docs/loop.md` caveat bullet points to it (rest untouched).

Measured (this session; 10 % weekday baseline `...-f124c5`, read from `.worktrees/trackD`):
- Offline legs reproduce Track D: C1 4,772 eligible tours; time-competitive rule 7,240 / 11,760
  riders/day (Track D runs: same).
- Sweep wall time 9-27 s per candidate (4 candidates x 2 services x 108 grid sets + one-at-a-time).
- Central riders/day, measured / vendor: C1 19,530 / 31,450 (grid 10,910-31,910 / 18,750-48,540);
  C2 9,000 / 13,560; C4 6,610 / 10,910; C6 4,180 / 6,520. Fixed alpha: C1 28,820 (0.3) and 47,870
  (0.5). C1 measured is segment-capacity bound in the evening (1,480 riders capped, queue up to
  8.9 min, Track D segment-exceedance check 9.2 %); nothing capped under vendor service.
- Demo window (`evaluate --mode-choice ... --demo`): 24 (measured) / 58 (vendor) of 286 eligible
  riders shift; ~95 s first run (builds the demo baseline), seconds afterwards.
- No city SUMO run was started (only the demo window ran SUMO).

Decisions:
- TH-001 Tour-level choice (sum of leg utilities), because Track D shifts whole tours; the
  alpha path's hashed draw is reused, so P = alpha reproduces the alpha path exactly (tested).
- TH-002 Capacity on both the station pair (as briefed) and each tunnel segment direction: with
  the pair cap alone nothing ever bound (peak pair 160-310 riders/h vs 1,355), while Track D's
  binding constraint was the segment. Segment capacity = 3600 / headway x 0.95 riders per shuttle
  movement, the ratio Track D's C1 runs achieved (A-loop-030).
- TH-003 Ride-hail fares and fuel updated to the data-scout's cited values (Uber KSA 2023, Aramco
  Oct 2026); fare central SAR 5 kept (sweep 0/5/10/20 as briefed). beta and walk weight added as
  one-at-a-time sensitivities (walk weight is the largest lever).
- TH-004 Offline evaluation uses Track D's starting baseline in `.worktrees/trackD/runs/` via
  `--source-root` (read only); the main checkout's baseline `...-65b0f3` has another config hash.
- TH-005 `tests/test_integration.py::test_merged_register_holds_every_track_row` fails on this
  branch by design: it checks that every `docs/assumptions-<track>.md` row is in
  `docs/assumptions.md`, which integration owns and merges. A-loop-021..030 are ready in
  `docs/assumptions-trackH.md`; this branch does not edit `docs/assumptions.md`. README not owned:
  the commands live in `docs/loop-mode-choice.md`; integration may add one line to the README Loop
  section.
- TH-007 Verifier FAIL (check 6) fixed: the new optional field was serialised as
  `mode_choice: None`, changing the policy_hash / config_hash that Track A's runner writes for
  alpha-path Loop policies. `LoopShuttle` now drops it when unset; loop_demo / loop_recommended
  hash as at 007d366 (`c11f0bfaf610771b` = Track D's recorded loop_recommended policy_hash, pinned
  in a test). Result CSVs now carry a label column.
- TH-006 A bug found by the tests: pandas group sums skip NaN, so tours with a leg lacking a car
  time got P = 0.5; such tours are now never shifted.

City re-evaluation for the coordinator (not run here; needs `baseline-weekday-f0.1-s1-e5f1906a-
65fac195-f124c5` and `loop_noise_baseline_s2` in the `runs/` used, both in `.worktrees/trackD/runs/`;
estimate ~10.6 min per run from Track D's shuttle runs):
```
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --sim-seed 2
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --service vendor
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --service vendor --sim-seed 2
# then the same with --ids C2,C4,C6 (12 runs, ~2.1 h)
```

Could not verify: any Saudi value of time or Loop/Gulf ASC; Careem and current ride-hail fares;
Jeddah parking search times; fuel consumption of the Jeddah fleet (assumed ~10 km/L).

Next: run the C1 city commands above (4 runs, ~45 min), then refill docs/loop-mode-choice.md's
recommendation section with relief; segment the value of time (Saudi / expatriate).

Verifier (final): all checks PASS after TH-007 (ruff clean; loop tests 30 passed; full suite 322
passed, 3 skipped, 1 expected pre-integration failure TH-005; sweep deterministic and matches the
committed results; demo end to end both services; alpha-path hashes equal to 007d366; no city run).
MODECHOICE: done
