# Contributing to TrafficTwin Jeddah

Thanks for helping. This is a simulation and decision-support project: it never actuates real
infrastructure, and every result is **synthetic demand, uncalibrated** until calibrated against
real counts (M8). Please keep it that way in code, docs and screenshots.

## Getting started

```bash
git clone https://github.com/alturkestani/TrafficTwin.git && cd TrafficTwin
make demo CITY=0      # setup, demo-window runs (about 30 s), API on :8000, viewer on :5173
make test             # ruff, ruff format --check, pytest (demo window, about 3 min), web typecheck
```
`make demo` without `CITY=0` also downloads the 243 MB Geofabrik extract and builds the Jeddah
network (a few minutes). Read `PROJECT.md` (the brief), `docs/architecture.md` and `docs/STATUS.md`
before a larger change.

## Ground rules

- **Python 3.12**, type hints, `ruff` (lint and format, line length 100), `pytest`. TypeScript is
  strict in `web/` (`npm run typecheck` must pass).
- **Every module has a CLI** (`python -m sim.<module> ...`) and a **test on the demo window**
  (`data/demo/`). City-scale runs are never part of pytest or CI.
- **Determinism:** every run takes `--seed` and records seed, config hash, population hash, network
  hash and SUMO version in `meta.json`. A change that alters results for the same seed must say so
  in the PR.
- **No magic numbers.** Every behavioural parameter (start times, trip rates, mode shares, rain
  factors, induced trips, ...) lives in YAML with a `source:` or `assumption:` and a row in
  `docs/assumptions.md` (id, value, unit, range, source or assumption, status, used in). See
  `.claude/skills/assumptions-register/`.
- **Layers stay separate:** `sim/` simulates, `strategist/` decides, `api/` + `web/` present.
  Policies transform the population or network *before* a run; events act through TraCI *during*
  a run. Micro-only SUMO features stay in Tier B (asserted at config load).
- **Prefer SUMO built-ins** (`cutRoutes.py`, `duaIterate.py`, `routeSampler.py`,
  `ptlines2flows.py`, bluelight device, `saveState`) over reimplementations.
- **Data:** `data/` is gitignored except `data/demo/`, `data/osm/fixes/`, `data/osm/jeddah.poly`,
  public tables in `data/census/` and the reviewed public flood-site list. Never commit private,
  partner or commercial data (counts, OD tables, imagery crops), secrets or `.env` files.
- **Publication policy (PROJECT.md section 11):** real-city emergency, evacuation and motorcade
  plans stay private. Public scenario files are fictional or use the demo window.

## OSM fixes

Network corrections go in `data/osm/fixes/*.yaml` (one reviewed fix per entry, with the OSM way ids
and evidence), are applied by `sim.network.build_city` and checked with
`uv run python -m sim.network.fixes check --net data/jeddah/jeddah.net.xml`. When you are confident
a fix is real, please also fix OpenStreetMap upstream.

## Commits and pull requests

- Small commits with conventional messages: `feat(policies): ...`, `fix(api): ...`,
  `docs(status): ...`, `test(...)`, `build: ...`.
- A PR states what changed, how it was tested (commands and numbers), any new assumption ids, and
  whether outputs for an existing seed change.
- CI (`.github/workflows/ci.yml`) runs ruff, pytest and the web typecheck; it must be green.
- Update `docs/STATUS.md` when you change what is built or measured, and `CHANGELOG.md` for
  user-visible changes.

## Licence

By contributing you agree that your contribution is licensed under Apache-2.0 (`LICENSE`). Data
derived from OpenStreetMap stays under ODbL; see `NOTICE`.
