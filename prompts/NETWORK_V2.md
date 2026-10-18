# NETWORK_V2 - fix the Tier A capacity gap (Track F, worktree .worktrees/trackF, branch trackF)

Branch `trackF` is cut from `main` (everything merged: M0-M9, Loop, movies). Status file:
`docs/status/trackF.md`; finish with `NETWORK_V2: done` (or `NETWORK_V2: blocked - reason`).

## The problem (read first: docs/network-qa.md, docs/lane-audit.md, docs/status/trackA.md TA-011)
The 10 % weekday baseline teleports 50.5 % of vehicles. `docs/network-qa.md` already found the
cause: major OSM ways inside Jeddah with no `lanes` tag fall back to the SUMO typemap defaults
(secondary = 1 lane, primary/trunk/motorway = 2), far below reality; plus junction clusters and
ramps that netconvert guesses badly. The imagery lane audit is BLOCKED (60 % precision < 80 %
gate): do NOT reopen it. Fix the capacity gap with data we trust.

## What to do
1. **Evidence-based lane defaults (A-net-xxx, registered).** For every OSM highway class inside the
   clip, take the ways that DO carry a `lanes` tag (and `oneway`) and compute the distribution of
   lanes per direction, by class x oneway, from the Jeddah PBF itself. Use the median (report
   p25/p50/p75 and km) as the default for untagged ways of that class x oneway, and the matching
   `maxspeed` median. Cross-check the defaults against the lane-audit held-out set
   (`data/osm/fixes/imagery-eval.json`): report per-class agreement; if a class disagrees strongly,
   say so and prefer the tagged-OSM median. Write a Jeddah typemap (`sim/network/types/jeddah.typ.xml`)
   or an equivalent reproducible pre-pass that tags untagged ways, keep the mechanism in `sim/network/`
   with tests on the demo window, and document it in `docs/network-v2.md`.
2. **Junctions and ramps.** Revisit `--junctions.join` distance, `--ramps.guess` parameters,
   `--tls.guess-signals` / `--tls.join`, roundabouts, and turn-lane handling for the main
   arterials; keep what reduces jam teleports in the smoke run without creating unrealistic
   capacity. Record each decision (TF-nnn) with the before/after numbers.
3. **Rebuild and measure.** `python -m sim.network.build_city` with the new settings → new
   network hash. Run the smoke (teleports, SCC) then the 10 % weekday baseline with the existing
   launcher (`python -m sim.policies.baseline_launch weekday --routing-threads 8 --gzip`; about 2 h;
   ONE city run at a time; two other agents run light work in parallel, so keep routing threads
   at 6 and never start a second SUMO city run). Target: teleports under 10 % of vehicles
   (stretch: under 5 %) with mean speed and VHT in a plausible range for a city of this size; report
   AM/PM peak delay, mean speed, VKT, VHT, teleports, and the top 10 remaining teleport hotspots.
   If the first attempt is still above 10 %, iterate once on the hotspots (fix list entries in
   `data/osm/fixes/`, reviewed and sourced), rebuild, rerun. At most 3 city runs in total.
4. **Keep v1 reproducible.** The old network must still build from the old settings
   (`--network-profile v1` or similar); the new one is the default. Note which run ids belong to
   which network hash. Do not delete v1 runs.
5. **Re-link what depends on the baseline.** Update `docs/contracts/run-outputs.md` if anything
   changes; note in the status file which downstream results (policies, Loop, films) need a rerun
   on the v2 network. Do NOT rerun them yourself (the coordinator will); except: rerun the
   demo-window pipeline (`make demo` steps that are quick) so tests and the demo still pass.
6. Register every assumption (A-net-NNN), keep `make test` green, run the verifier subagent on:
   teleport share, reproducibility (same seed ⇒ same network hash and KPIs), v1 still builds,
   tests, docs. Then write the status line.

Hard rules: no imagery calls, no external tiles, never say "calibrated" (still synthetic demand),
disk: stop any run if free space < 5 GB (`df -h /System/Volumes/Data`), gzip SUMO outputs.
