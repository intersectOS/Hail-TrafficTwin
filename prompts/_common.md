## Common rules for this session (read first)
- Read `PROJECT.md`, `CLAUDE.md` and `docs/STATUS.md`, then `docs/status/<your track>.md` if it exists. Nobody will answer questions: decide, record the decision in your track status file, continue.
- You are on a git branch in a worktree. Commit on this branch only, small and often. Never run `git checkout`, `git merge`, `git rebase`, `git worktree` or touch other branches.
- File ownership is listed in your prompt. Files you do not own are read-only, with one exception: `sim/runner.py` may get ADDITIVE changes only (a new function or CLI option; never reorder or rewrite existing code), so the integration merge stays trivial.
- Shared data: `data/jeddah/` and the large files in `data/osm/` are symlinks to the main checkout. NEVER overwrite `data/jeddah/jeddah.net.xml` or the files beside it; if you need a changed city network, write it under a new name (`data/jeddah/jeddah.<suffix>.net.xml`) and record it.
- Assumptions go in `docs/assumptions-<track>.md` (same row format as `docs/assumptions.md`); integration merges them. Status goes in `docs/status/<track>.md` with one block per milestone, ending in a line `M<n>: done` or `M<n>: blocked - <reason>`. The orchestrator greps for that line.
- Use subagents in parallel where tasks are independent (e.g. `verifier` while you write docs; `data-scout` while code runs). Long runs in background with logs under `logs/`; poll, never block more than two minutes.
- End every milestone with the `milestone-handoff` skill: ruff, pytest, README command, `verifier` subagent, status block, commit. A milestone with an open verifier FAIL is not done.
- Budget discipline: city-scale runs are measured on a 10 % sample first. Do not start a run you expect to take more than 90 minutes without first recording the estimate in the status file and making the smaller-sample result available.
- Everything stays labelled "synthetic demand, uncalibrated".
