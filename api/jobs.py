"""Simulation jobs: `python -m sim.runner --smoke ...` as a subprocess, then ingest the new run.

State lives in memory and in <TT_LOGS_DIR>/api-jobs/<job_id>.json (survives an API restart);
the job's output goes to <TT_LOGS_DIR>/api-jobs/<job_id>.log.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from api import settings
from api.util import atomic_write_json, read_json
from sim.common import REPO_ROOT

OUTPUTS_RE = re.compile(r"^\s*outputs\s+(.+?)/?\s*$")
TERMINAL = ("done", "failed")


class JobRequest(BaseModel):
    kind: Literal["smoke"] = "smoke"
    tier: Literal["A", "B"]
    seed: int = Field(ge=0)
    end: int | None = Field(default=None, gt=0)
    period: float | None = Field(default=None, gt=0)
    fcd: bool = False

    @model_validator(mode="after")
    def _fcd_tier_b_only(self) -> JobRequest:
        if self.fcd and self.tier != "B":
            raise ValueError("fcd is Tier B only")
        return self


@dataclass
class Job:
    job_id: str
    request: dict[str, Any]
    status: str = "running"
    run_id: str | None = None
    returncode: int | None = None
    error: str | None = None
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = settings.LABEL
        return d


_jobs: dict[str, Job] = {}
_guard = threading.Lock()


def jobs_dir() -> Path:
    return settings.logs_dir() / "api-jobs"


def log_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.log"


def _save(job: Job) -> None:
    atomic_write_json(jobs_dir() / f"{job.job_id}.json", asdict(job))


def get_job(job_id: str) -> Job | None:
    if not re.fullmatch(r"[0-9a-f]{12,32}", job_id):
        return None
    with _guard:
        job = _jobs.get(job_id)
    if job is None:
        path = jobs_dir() / f"{job_id}.json"
        if path.is_file():
            job = Job(**read_json(path))
            if job.status not in TERMINAL:  # the API restarted while it ran
                job.status, job.error = "failed", "API restarted during the job"
    return job


def running_count() -> int:
    with _guard:
        return sum(1 for j in _jobs.values() if j.status not in TERMINAL)


def command(req: JobRequest, runs: Path) -> list[str]:
    cmd = [sys.executable, "-m", "sim.runner", "--smoke", "--tier", req.tier, "--seed"]
    cmd += [str(req.seed), "--runs-dir", str(runs)]
    if req.end is not None:
        cmd += ["--end", str(req.end)]
    if req.period is not None:
        cmd += ["--period", str(req.period)]
    if req.fcd:
        cmd.append("--fcd")
    return cmd


def _find_run_id(log: Path, runs: Path, before: set[str]) -> str | None:
    for line in reversed(log.read_text(errors="replace").splitlines()):
        m = OUTPUTS_RE.match(line)
        if m:
            name = Path(m.group(1)).name
            if (runs / name).is_dir():
                return name
    new = sorted(p.name for p in runs.iterdir() if p.is_dir() and p.name not in before)
    return new[-1] if new else None


def _run(job: Job, req: JobRequest, runs: Path, log: Path) -> None:
    from api.ingest import ingest_run

    before = {p.name for p in runs.iterdir()} if runs.is_dir() else set()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        with log.open("a", encoding="utf-8") as fh:
            cmd = command(req, runs)
            fh.write("$ " + " ".join(cmd) + "\n")
            fh.flush()
            proc = subprocess.run(cmd, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env)
        job.returncode = proc.returncode
        job.run_id = _find_run_id(log, runs, before)
        if proc.returncode != 0:
            job.status, job.error = "failed", f"runner exited with {proc.returncode}"
        elif job.run_id is None:
            job.status, job.error = "failed", "run directory not found"
        else:
            with log.open("a", encoding="utf-8") as fh:

                def emit(msg: str) -> None:
                    fh.write(msg + "\n")
                    fh.flush()

                ingest_run(runs / job.run_id, log=emit)
            job.status = "done"
    except Exception as exc:  # noqa: BLE001 - the job reports any failure
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"error: {job.error}\n")
    _save(job)


def start_job(req: JobRequest) -> Job:
    runs = settings.runs_dir()
    runs.mkdir(parents=True, exist_ok=True)
    jobs_dir().mkdir(parents=True, exist_ok=True)
    job = Job(job_id=uuid.uuid4().hex[:16], request=req.model_dump())
    log = log_path(job.job_id)
    log.touch()
    with _guard:
        _jobs[job.job_id] = job
    _save(job)
    threading.Thread(target=_run, args=(job, req, runs, log), daemon=True).start()
    return job
