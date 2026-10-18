# CLAUDE.md — TrafficTwin Jeddah

Read `PROJECT.md` first. It is the brief: scope, two-tier architecture (Tier A = all-Jeddah mesoscopic, Tier B = microscopic focus windows), policy lab, milestones and acceptance criteria. This file holds the working rules.

## Machine
Apple M3 Pro, 18 GB RAM, macOS. Tools present: claude, uv 0.11, python3 (3.14 system), node 25, npm, docker, brew, git. Missing: sumo, osmium (install them).
- Use `uv` with a pinned **Python 3.12** venv (`uv python install 3.12 && uv venv --python 3.12`); SUMO wheels may not exist for 3.14.
- Install SUMO with `uv pip install eclipse-sumo` (set `SUMO_HOME` from `sumolib`'s location if tools need it). If the wheel fails on macOS arm64, fall back to `brew install sumo` and record which path was used in `docs/STATUS.md`.
- `brew install osmium-tool` for clipping PBF extracts.
- 18 GB RAM is the constraint for city-scale runs: stream outputs, never load full FCD into pandas; measure before choosing the population sample.

## Engineering rules
- Python 3.12, type-hinted, `ruff` (lint + format), `pytest`; TypeScript strict in `web/`.
- Every module has a CLI (`python -m sim.network.build_city ...`) and a test on the small demo window in `data/demo/`. City-scale runs are never part of CI or pytest.
- Determinism: every run takes `--seed`; outputs record seed, config hash, population hash, network hash, SUMO version.
- Every behavioural assumption lives in YAML with `source:` or `assumption:` and is registered in `docs/assumptions.md` (see skill `assumptions-register`). No magic numbers in code.
- Keep `sim/` (simulation), `strategist/` (decisions) and `api/` + `web/` (presentation) separate. Policies transform population and network *before* a run; events act through TraCI *during* a run.
- Prefer SUMO built-ins (`cutRoutes.py`, `duaIterate.py`, `routeSampler.py`, `ptlines2flows.py`, bluelight device, `saveState`) over reimplementation.
- Micro-only features (sublane, opposite-direction driving, lane-area detectors, lane-level outputs, bluelight) are confined to Tier B and asserted at config load.
- Label every result "synthetic demand, uncalibrated" until calibration (M8) says otherwise.
- No secrets in the repo or URLs. `.env` gitignored. `data/` gitignored except `data/demo/`, `data/osm/fixes/`, public licensed tables in `data/census/`, and the reviewed public flood-site list `data/jeddah_flood_sites.yaml`. Imagery crops are never committed.
- Licence Apache-2.0; `NOTICE` attributes OpenStreetMap (ODbL), SUMO (EPL-2.0), GASTAT open data.

## Workflow
- Parallel tracks: milestones may run in git worktrees under `.worktrees/` on branches `trackA` (demand, policies, calibration), `trackB` (windows, events, strategist, evacuation) and `trackC` (lane audit, viewer, API); `prompts/_common.md` has the ownership and merge rules. Status per track in `docs/status/`.
- Work milestone by milestone as ordered in PROJECT.md section 12. Do not start the next milestone until the current one passes its acceptance criteria.
- Commit small and often on `main` with conventional messages (`feat(network): ...`). Initialise git in M0.
- Keep `docs/STATUS.md` current: what is built, measured numbers (runtime, edges, teleports), decisions taken, what is next. Update it at the end of every milestone (skill `milestone-handoff`).
- Long commands (downloads, city builds, 24 h runs) go in the background with logs under `logs/`; poll the log, do not block.
- Network access is available (Geofabrik, PyPI, npm, brew). Downloads larger than 50 MB go to `data/osm/` and are gitignored.
- When something cannot be verified (a data source, a SUMO option), say so in STATUS.md instead of guessing.

## Subagents (in `.claude/agents/`)
- `sumo-engineer`: network build, netconvert, SUMO runs, TraCI, meso/micro constraints.
- `demand-modeler`: synthetic population, activity chains, day types, policy transforms.
- `viewer-engineer`: React + deck.gl + MapLibre viewer and FastAPI streaming.
- `strategist-engineer`: candidates, parallel what-ifs, ranking, explanations, decision log.
- `data-scout`: finds and documents public Jeddah data and licences; writes `docs/data-sources.md`.
- `imagery-analyst`: counts lanes on aerial imagery crops (lane audit only).
- `verifier`: checks a milestone against its acceptance criteria; runs tests; reviews determinism and the assumptions register. Run it before declaring any milestone done.

## Skills (in `.claude/skills/`)
`sumo-run`, `osm-jeddah-network`, `policy-yaml`, `milestone-handoff`, `assumptions-register`, `lane-audit-imagery`. Use them when their description matches the task.
