Read PROJECT.md fully, then CLAUDE.md. You are building TrafficTwin Jeddah on this Mac (M3 Pro, 18 GB). Work autonomously; nobody will answer questions in this session, so make the reasonable choice, record it in docs/STATUS.md, and continue.

Deliver milestones M0 and M1 from PROJECT.md section 12, then stop.

M0 Skeleton
- Initialise git on `main`; create the repository layout of PROJECT.md section 8 (empty packages with `__init__.py`, placeholder READMEs where a package is not yet implemented).
- `pyproject.toml` managed by `uv` with a pinned Python 3.12 venv; dependencies: eclipse-sumo, sumolib/traci (from the wheel), pyyaml, pydantic, numpy, pandas, pyarrow, duckdb, shapely, pyproj, geopandas, fastapi, uvicorn, typer, ruff, pytest. If the eclipse-sumo wheel does not install on macOS arm64, `brew install sumo` and set SUMO_HOME; record which.
- `brew install osmium-tool` if missing.
- LICENSE (Apache-2.0), NOTICE (OpenStreetMap ODbL, SUMO EPL-2.0, GASTAT open data), `.gitignore` (data/ except data/demo, data/osm/fixes, data/census; runs/; logs/; .env; .venv; node_modules), `docker-compose.yml` (api + web services, stubs acceptable), GitHub Actions CI running ruff and pytest on the demo window only.
- `docs/STATUS.md`, `docs/assumptions.md`, `docs/data-sources.md` created from the templates in the skills.
- Demo window: a small district extract (about 3 km², choose the Tahlia / Al Andalus area around lon 39.15-39.18, lat 21.54-21.57, adjust to what OSM has) committed under `data/demo/` with a tiny random-trips demand, so tests run in seconds without downloading anything.

M1 Jeddah network
- Use the `osm-jeddah-network` skill. Download the Geofabrik extract that contains Saudi Arabia into `data/osm/` in the background, clip to a Jeddah polygon, and build `data/jeddah/jeddah.net.xml` with `python -m sim.network.build_city`.
- Implement the reproducible OSM fix-list mechanism (`data/osm/fixes/*.yaml`, `sim/network/fixes.py`) with at least one real fix found during the build, or a documented no-op if none was needed.
- Produce `data/jeddah/districts.geojson` and `data/jeddah/buildings.geojson` (gitignore buildings if over 50 MB).
- `python -m sim.network.build_window --name demo` must cut a Tier B window from the city network (use it to regenerate the demo window so the demo and the city share one pipeline).
- Meso smoke run through `python -m sim.runner --smoke --tier A --seed 1` using random trips for one hour: report edges, junctions, traffic lights, lane-km, vehicles, runtime, real-time factor and teleport share (must be under 0.5 %; fix the network, not the threshold).
- Minimal viewer stub: a single static page (Vite + MapLibre, no API keys) that renders the city network edges and districts GeoJSON, so the network can be eyeballed. The full deck.gl viewer is M3; do not build it now.
- Tests on the demo window for the builder, fix list, window cutter and runner; README with the exact commands for building the city network and running the smoke test.

Process
- Use the subagents: `sumo-engineer` for network and runs, `data-scout` once to document the sources used, and `verifier` before declaring each milestone done. Follow the `milestone-handoff` skill at the end of M0 and M1.
- Long commands run in the background with logs in `logs/`; poll them.
- Commit after each milestone. Never commit files under data/ other than data/demo, data/osm/fixes and data/census.
- Stop after M1 with the handoff summary: what was built, the measured numbers (network size, runtime, teleports), decisions taken (SUMO install path, Python version, population sampling implications for M2 given 18 GB RAM), what could not be verified, and the first three tasks of M2.
