"""Settings read at call time from the environment (so tests and containers can override them).

All defaults are relative to `sim.common.REPO_ROOT`; no absolute host paths.
"""

from __future__ import annotations

import os
from pathlib import Path

from sim.common import REPO_ROOT, SYNTHETIC_LABEL

LABEL = SYNTHETIC_LABEL
CORS_ORIGINS_DEFAULT = "http://localhost:5173"


def _path(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def runs_dir() -> Path:
    """TT_RUNS_DIR, default <repo>/runs."""
    return _path("TT_RUNS_DIR", REPO_ROOT / "runs")


def cache_dir() -> Path:
    """TT_CACHE_DIR, default <runs dir>/_viewer-cache (runs/ is the writable mount)."""
    return _path("TT_CACHE_DIR", runs_dir() / "_viewer-cache")


def logs_dir() -> Path:
    """TT_LOGS_DIR, default <repo>/logs (job logs go to <logs>/api-jobs/)."""
    return _path("TT_LOGS_DIR", REPO_ROOT / "logs")


def districts_path() -> Path:
    return _path("TT_DISTRICTS", REPO_ROOT / "data" / "jeddah" / "districts.geojson")


def buildings_path() -> Path:
    return _path("TT_BUILDINGS", REPO_ROOT / "data" / "jeddah" / "buildings.geojson")


def cors_origins() -> list[str]:
    raw = os.environ.get("TT_CORS_ORIGINS", CORS_ORIGINS_DEFAULT)
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_jobs() -> int:
    """TT_MAX_JOBS: concurrent simulation jobs (a city run needs most of the 18 GB machine)."""
    return int(os.environ.get("TT_MAX_JOBS", "1"))


def strategist_db() -> Path:
    """TT_STRATEGIST_DB, default <runs dir>/strategist/decisions.sqlite (the strategist's log)."""
    return _path("TT_STRATEGIST_DB", runs_dir() / "strategist" / "decisions.sqlite")


def runs_readonly() -> bool:
    """TT_RUNS_READONLY=1: never write into run directories; converted Parquet goes to the cache.

    (Decisions are still appended: approving is the one write the API exists to do.)"""
    return os.environ.get("TT_RUNS_READONLY", "").lower() in ("1", "true", "yes")


def resolve_repo_path(path: str) -> Path:
    """A path stored in meta.json (repo-relative) as an absolute path."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p
