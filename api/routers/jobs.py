"""Start a smoke run (the only write besides decisions) and follow it with Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api import settings
from api.jobs import TERMINAL, JobRequest, get_job, log_path, running_count, start_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
POLL_S = 0.2  # log tail poll interval


@router.post("")
def create_job(req: JobRequest) -> dict[str, Any]:
    if running_count() >= settings.max_jobs():
        raise HTTPException(status_code=409, detail="a job is already running (TT_MAX_JOBS)")
    job = start_job(req)
    return {"job_id": job.job_id, "status": job.status, "label": settings.LABEL}


def _job_or_404(job_id: str) -> Any:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    return _job_or_404(job_id).public()


def _sse(event: str, data: str) -> str:
    lines = "".join(f"data: {part}\n" for part in data.split("\n"))
    return f"event: {event}\n{lines}\n"


async def _follow(job_id: str) -> AsyncIterator[str]:
    path = log_path(job_id)
    last_status: str | None = None
    pos = 0
    pending = ""
    while True:
        job = get_job(job_id)
        status = job.status if job else "failed"
        if path.is_file():
            with path.open("rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos += len(chunk)
            pending += chunk.decode(errors="replace")
            *lines, pending = pending.split("\n")
            for line in lines:
                yield _sse("log", line.rstrip("\r"))
        if status != last_status:
            last_status = status
            yield _sse("status", json.dumps({"status": status}))
        if status in TERMINAL:
            if pending:
                yield _sse("log", pending)
            run_id = job.run_id if job else None
            yield _sse("done", json.dumps({"status": status, "run_id": run_id}))
            return
        await asyncio.sleep(POLL_S)


@router.get("/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    _job_or_404(job_id)
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(_follow(job_id), media_type="text/event-stream", headers=headers)
