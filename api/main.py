"""TrafficTwin Jeddah viewer API (contract: docs/contracts/run-outputs.md).

Thin and file-backed: reads runs/ and a derived cache; the only writes are starting a smoke run
(POST /api/jobs) and logging a strategy decision. Settings are read from the environment at
request time (TT_RUNS_DIR, TT_CACHE_DIR, TT_LOGS_DIR, TT_CORS_ORIGINS, TT_MAX_JOBS).

    uv run uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api import settings
from api.routers import geo, jobs, networks, runs

GZIP_MIN_BYTES = 1024


def create_app() -> FastAPI:
    app = FastAPI(title="TrafficTwin Jeddah API", version="1.0.0")
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=[
            "X-Metric",
            "X-Bin-Begin-S",
            "X-Bin-End-S",
            "X-N-Edges",
            "X-Network-Hash",
            "X-Label",
            "X-Feature-Count",
        ],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "label": settings.LABEL}

    for module in (runs, networks, geo, jobs):
        app.include_router(module.router)
    return app


app = create_app()
