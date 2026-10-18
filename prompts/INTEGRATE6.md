# Integration pass 6 — merge trackI (movies v2) and trackF (network v2), then re-evaluate on v2

You are in the main checkout on `main` (HEAD d2bbaab, trackJ already merged). Two branches remain:
- `trackI` — MOVIES_V2 (status `.worktrees/trackI/docs/status/trackI.md`, ends `MOVIES_V2: done`): Obhur evacuation window + scenario replacing Al Hamra, street-name/landmark labels, compass/scale/legend HUD, Kokoro-82M narration + subtitles, all films re-rendered. Rendered movies live under `.worktrees/trackI/movies/` and are git-ignored: copy NOTHING from `movies/` renders into git; leave the rendered files where they are (they may be symlinked into `movies/` of main, not committed).
- `trackF` — NETWORK_V2 (status `.worktrees/trackF/docs/status/trackF.md`, ends `NETWORK_V2: blocked`): the v2 Tier A network is built (`data/jeddah/jeddah.v2.net.xml`, shared with main through the `data/jeddah` symlink), is the DEFAULT profile, has its own zones/population (edge ids changed), and the 10 % weekday baseline on v2 is `.worktrees/trackF/runs/baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1` (teleports 28.3 % vs 50.5 % on v1/m2; target < 10 % NOT reached, documented in `docs/network-v2.md` with TF-001..TF-013). "blocked" here means the target was missed, not that the code is broken: merge it anyway and keep both the v1 and v2 numbers everywhere.

## Part 1 — merge (no SUMO runs yet)
1. Merge `trackI` first, then `trackF` (`git merge --no-ff`). Resolve conflicts preserving both sides' content; run the test suite and `npm run build` after each merge; commit fixes separately. Update `docs/status/integration.md` and `docs/STATUS.md` (pass 6 section). The public evacuation demo is Obhur, never Al Hamra; the Al Hamra window may remain as a non-default example only if trackI kept it that way.
2. Make the trackF v2 baseline run visible from main without copying 1.4 GB: symlink `runs/<id> -> ../.worktrees/trackF/runs/<id>` for the v2 baseline (and any v2 probe/smoke run the docs cite). Check `python -m sim.policies.baseline_launch --help` style commands still resolve the v2 network, zones and population from main.
3. Commit. Never `git push`, never create a remote, never delete worktrees.

## Part 2 — re-evaluate on v2 (city runs allowed in THIS pass only; one at a time; `--routing-threads 8`)
Clock rule: do NOT start a new city run after 10:30 local (`date`); a run already going may finish. Check the time before each launch. Each 10 % weekday policy run on v2 takes roughly 1-2 h; log each launch in `logs/orch/pass6-runs.log` with start/end times and the run id.
Run in this priority order, each with its matched control = the v2 baseline above (same seed, same demand), using the same commands the policy lab used on v1 (see `docs/policies.md`, `docs/obhur-bridge.md` "pending city run" section, `docs/loop.md`, `docs/loop-mode-choice.md`):
1. Obhur bridge B3 (both bridges) — the bridge `network_change` must be rebuilt on the v2 base network (the m2 bridge nets under `data/jeddah/jeddah.m2.bridge-*.net.xml.gz` are v1-based; do not reuse them).
2. Staggered schools.
3. Loop recommended configuration (C1 Al-Salamah → KAU) with `--mode-choice` (and the assumed-share variant if it is cheap, i.e. no extra city run).
4. Remote work 30 %.
5. Central cordon.
6. Obhur bridge B1.
For each finished run: fill the v2 column NEXT TO the v1 numbers in `docs/policies.md`, `docs/obhur-bridge.md` (replace the "pending city run" placeholders only for runs that finished; leave the others marked pending), `docs/loop.md`/`docs/loop-mode-choice.md`, and `docs/STATUS.md`. Never delete v1 numbers; always state the teleport share of each run next to its VHT/delay numbers, because 28 % teleports is a quality flag. Note the seed-noise band (±34k VHT/day on v1; recompute on v2 only if a second-seed baseline already exists — do NOT spend a city run on it).
Stop condition: all six done, or the 10:30 cutoff reached and the last run finished. Do not re-render films (the coordinator decides that separately). If disk free (`df -h /System/Volumes/Data`) drops below 8 GB, gzip or delete the largest intermediate outputs of finished runs (keep summaries/KPIs) and note it.

## Part 3 — close
Commit everything (docs, assumptions register merges, status). Append to `docs/status/integration.md` a pass-6 table: what merged, which v2 runs finished with v1 vs v2 numbers and teleport shares, which are still pending, and the exact commands to finish the pending ones. End your final message with the line `INTEGRATE6: done` (or `INTEGRATE6: blocked — <reason>`).
