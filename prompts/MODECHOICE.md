# MODECHOICE - replace the assumed Loop shift share with a mode-choice model (Track H,
# worktree .worktrees/trackH, branch trackH)

Branch `trackH` is cut from `main`. Status file: `docs/status/trackH.md`; finish with
`MODECHOICE: done` (or `MODECHOICE: blocked - reason`). Compute budget: demo window and the
existing 10 % baseline outputs only. NO new SUMO city runs (another agent owns the machine for
city runs); if a city re-evaluation is needed, write the exact commands into the status file for
the coordinator and evaluate on the demo window instead.

Context: docs/loop.md, sim/loop/, docs/assumptions-trackD.md. The Loop result's largest
behavioural caveat is the exogenous shift share alpha (A-loop-0xx) and the rider-time flag
(70 % of shifted riders slower than by car under measured service). Replace alpha with a
transparent mode-choice model and quantify what it does to the recommendation.

1. **Model.** A binary (car vs Loop) logit on door-to-door generalised time per tour leg:
   car time from the baseline run (edge travel times, incl. parking search as an assumption),
   Loop time = walk access + wait + ride + walk egress (+ transfer if any), plus a fare term and an
   alternative-specific constant. Coefficients from the literature (value of time, wait-time
   multiplier 1.5-2.5, walk multiplier, ASC range) with sources; expose them in YAML with
   `source:`/`assumption:` and register them (A-loop-NNN). Produce the shift share as an OUTPUT,
   per station pair and per hour, under the measured service (90 km/h, 12.5 min wait, 5.3 s headway)
   and the vendor service (160 km/h, 2 min wait, 1.5 s headway), with capacity capping and queueing
   when demand exceeds the pair capacity (riders above capacity do not shift).
2. **Sensitivity.** Sweep VOT, wait multiplier, ASC and fare (SAR 0/5/10/20); report the implied
   ridership for C1 and the top-3 candidates as ranges, and compare with the fixed-alpha
   ridership (28,820 and 47,870 pax/day) and the time-competitive runs (7,240 / 11,760).
3. **Integration.** `python -m sim.loop.evaluate --mode-choice <yaml>` emits the shifted tours
   exactly as the alpha path does, so the coordinator can run the city evaluation later with one
   command (write that command in the status). Unit tests on synthetic legs (monotonicity, capacity
   cap, determinism). Demo-window end-to-end run.
4. **Docs.** `docs/loop-mode-choice.md`: method, coefficients and sources, results table, what
   changes in the recommendation under each service case (as far as can be said without the city
   run), and an honest limitations list (no induced demand, no transfers, single-day). Update
   docs/loop.md's caveat paragraph to point to it (keep the rest of loop.md untouched).
Verifier subagent on tests, determinism, sources, and that no city run was started. Then the
status line.
