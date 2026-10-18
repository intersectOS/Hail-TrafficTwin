# OBHUR_BRIDGE - what if one or two bridges linked South and North Obhur across Sharm Obhur
# (Obhur Creek)? (Track J, worktree .worktrees/trackJ, branch trackJ)

Branch `trackJ` is cut from `main`. Status file: `docs/status/trackJ.md`; finish with
`OBHUR_BRIDGE: done` (or `OBHUR_BRIDGE: blocked - reason`). Owner's ask: "add a sim for linking
south Obhur and north Obhur with a bridge or two over Sharm Jeddah; it was planned but not built."

Compute rules: NO SUMO city (Tier A) runs in this track (another agent owns the machine for
those; the coordinator will run the city evaluations later from the commands you leave in the
status file). Window-scale (Tier B) runs and one render at a time are allowed. Check
`df -h /System/Volumes/Data`; stop under 5 GB free.

## 1. Candidate crossings (siting from the network and public plans)
- Today the creek is crossed only at its head (east end, Madinah Road side); north-south trips
  between the Obhur banks detour around it. Quantify that from the baseline: desire lines between
  districts north and south of the creek (sim/loop has desire-line code to reuse), the detour
  length and delay per trip today, and the daily trips affected.
- Candidate alignments, each with a short public source note where one exists (the owner says a
  crossing was planned; search the web for Obhur Creek / Sharm Obhur bridge plans, Jeddah Tower /
  Jeddah Economic City access, and cite what you find; if nothing reliable, say so and treat the
  alignments as analysis assumptions):
  B1 creek mouth (west end, near the Corniche / Jeddah Tower site), B2 mid-creek, B3 both.
  For each: endpoint junctions on existing roads on both banks, length, lanes (2+2 and 3+3
  variants), speed 60-80 km/h, ramps/approach links so it connects to real arterials, and a
  navigable-span note (the creek carries boats; a fixed high bridge vs a bascule is out of scope,
  just flag it).
- Implement them as `network_change` policies (`sim/policies/obhur_bridge_b1.yaml` etc.) using
  the existing new-link mechanism (netconvert additional edges/nodes with correct geometry in the
  network's projection); verify the new edges are in the main SCC, have through-routes, and that
  `python -m sim.policies.run <policy> --validate` passes. Register assumptions (A-obh-NNN).

## 2. Evaluation
- Window scale now: use the Obhur focus window if `.worktrees/trackI/sim/network/windows/obhur.yaml`
  exists (read-only; copy the polygon, do not edit that worktree), otherwise define
  `sim/network/windows/obhur.yaml` yourself around the creek (21.70-21.76 N, 39.08-39.14 E) with
  the standard tooling. Run the window baseline and each bridge variant in Tier B with a matched
  control (same routing-gain treatment as the policy lab, TA-018), weekday AM and PM peaks: bridge
  volumes, delay and mean speed on the approach roads, detour distance saved, and the local
  winners/losers (edges relieved vs worsened). Report the noise band from a second seed.
- City scale later: write the exact commands for the coordinator (`python -m sim.policies.run
  obhur_bridge_b1 --daytype weekday --control matched`, etc.) and the expected runtime; the
  coordinator runs them on the v2 network after the network track lands. Prepare
  `docs/obhur-bridge.md` with placeholders clearly marked "pending city run" for VHT, VKT and
  AM-peak delay changes, induced demand caveat, and a per-district effect table to be filled.
- Cost framing (sourced ranges only): typical bridge cost per lane-km for a 0.4-1.2 km span, so
  the doc can state relief per USD M in the same style as docs/loop.md once the city numbers exist.

## 3. Viewer and film
- The new links show in the viewer's network layer and difference mode (nothing more than making
  sure the ingest handles added edges). Write a film spec `movies/specs/obhur-bridge.yaml`
  (camera over the creek, before/after wipe, bridge callout labels, KPI counters) rendered on the
  window run now; the coordinator re-renders it after the city run. Narration lines if the
  narration mechanism from trackI exists in main by then (check `scripts/movies/narrate.py`);
  otherwise leave a `narration` block in the spec for later.
- Tests on synthetic geometry (link insertion, SCC membership, policy validation). Verifier
  subagent: policy validates, window results reproducible, docs honest about what is pending.
Then the status line.
