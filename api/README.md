# api

Thin, file-backed FastAPI viewer API for TrafficTwin Jeddah. Spec: `docs/contracts/run-outputs.md`.
Everything it serves is **synthetic demand, uncalibrated**. Read-only except for two writes:
starting a smoke run (`POST /api/jobs`) and logging a strategy decision (append-only, hash-chained
`decisions.jsonl`, or for strategist recommendations the strategist's SQLite log
`runs/strategist/decisions.sqlite`; logging never actuates anything). `TT_RUNS_READONLY=1` keeps
even XML-to-Parquet conversions out of run directories (they go to the cache).

## Run

```bash
uv run uvicorn api.main:app --reload            # http://localhost:8000, docs at /docs
uv run uvicorn api.main:app --port 8000         # what the viewer (web/, port 5173) expects
```

## Ingest (optional; the API also builds lazily on first request)

```bash
uv run python -m api.ingest runs/<run_id>       # one run
uv run python -m api.ingest --all               # every run under TT_RUNS_DIR
uv run python -m api.ingest --all --force       # rebuild even if fresh
```

It streams `edgedata.xml` -> `edgedata.parquet` and `fcd.xml` -> `fcd.parquet` (iterparse, Parquet row
groups, DuckDB external sort for FCD) and builds the cache: the edge index (`edges.bin`, `edges.json`)
per network hash and sparse float32 bin arrays per run (contract §10, layout `sparse-v1`). Deleting the cache is always safe.

## Example reports (fictional, for demonstrating the viewer)

```bash
uv run python -m api.examples smoke-B-s1-25c06763-9cfa755f [--baseline <run_id>] [--seed 0]
```

It writes `policy_report.json`, `scenario_report.json` and `recommendations.json` into a Tier B run, all
marked `"example": true, "fictional": true` with a `note`. The values are illustrative only.

## Environment

| variable | default | meaning |
|---|---|---|
| `TT_RUNS_DIR` | `<repo>/runs` | run directories |
| `TT_CACHE_DIR` | `<TT_RUNS_DIR>/_viewer-cache` | derived cache (under runs/, the writable mount in docker) |
| `TT_LOGS_DIR` | `<repo>/logs` | job logs and state in `api-jobs/<job_id>.log` and `.json` |
| `TT_DISTRICTS` | `<repo>/data/jeddah/districts.geojson` | district polygons (`osm_id`) |
| `TT_BUILDINGS` | `<repo>/data/jeddah/buildings.geojson` | building footprints with `height_m` |
| `TT_CORS_ORIGINS` | `http://localhost:5173` | comma-separated allowed origins |
| `TT_MAX_JOBS` | `1` | concurrent simulation jobs (409 beyond it) |

Relative values resolve against the repo root, so the same code runs unchanged from `/app` in the container.

## Layout

`main.py` (app factory `create_app()`), `routers/` (runs, networks, geo, jobs), `ingest.py`,
`edges.py` (edge index), `bins.py` (sparse bins), `normalize.py` + `schema.py` (producer shapes -> contract, §12), `strategist_link.py` (strategist recommendations and SQLite decision log), `districts.py`, `trajectories.py`, `geo.py`
(buildings), `decisions.py` (hash chain; `verify_chain()`), `jobs.py`, `examples.py`, `settings.py`.
Tests: `uv run pytest -q tests/test_api.py` (demo window, offline, about 6 s).
