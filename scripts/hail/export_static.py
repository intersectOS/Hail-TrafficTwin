"""Export the viewer API as static files, so the viewer runs on GitHub Pages without a server.

Every GET the viewer makes is answered once through the FastAPI app (in-process, TestClient) and
written under <out>/ with a fixed path; `web/src/api.ts` reads those paths when built with
VITE_STATIC=1. Edge bins are packed per (run, metric) into one sparse, 16-bit quantised file
(`TTP1`, see `pack_bins`) so a 24 h city run stays a few MB per metric. Writes (decisions, jobs) are
not exported: the public viewer is read-only.

    python -m scripts.hail.export_static --out site/viewer/api

Synthetic demand, uncalibrated.
"""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path
from typing import Any

import numpy as np
import typer
from fastapi.testclient import TestClient

from api.main import create_app

VIEW_METRICS = ("speed_rel", "speed_kmh", "delay_s_per_veh", "density_veh_km", "flow_veh_h")
EFFECT_METRIC = "mean_speed_delta_pct"
NAN_CODE = 0xFFFF

app = typer.Typer(add_completion=False, help=__doc__)


def _write(path: Path, data: bytes | str | Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return path.stat().st_size


def pack_bins(bins: list[np.ndarray]) -> bytes:
    """TTP1: magic, n_bins, n_edges, index_bytes (u32), lo, scale (f32), offsets u32[n_bins + 1],
    then per bin: count u32, indices u16/u32[count] (padded to 4), codes u16[count] (padded to 4).
    value = lo + code * scale; code 0xFFFF and absent edges are NaN (no data)."""
    n_edges = len(bins[0]) if bins else 0
    idx_bytes = 2 if n_edges <= 0xFFFF else 4
    finite = [b[np.isfinite(b)] for b in bins]
    vals = np.concatenate(finite) if any(len(f) for f in finite) else np.zeros(1, np.float32)
    lo, hi = float(vals.min()), float(vals.max())
    scale = (hi - lo) / (NAN_CODE - 1) if hi > lo else 1.0
    parts: list[bytes] = []
    for b in bins:
        idx = np.flatnonzero(np.isfinite(b))
        codes = np.clip(np.rint((b[idx] - lo) / scale), 0, NAN_CODE - 1).astype("<u2")
        chunk = struct.pack("<I", len(idx))
        ib = idx.astype("<u2" if idx_bytes == 2 else "<u4").tobytes()
        chunk += ib + b"\0" * (-len(ib) % 4)
        cb = codes.tobytes()
        chunk += cb + b"\0" * (-len(cb) % 4)
        parts.append(chunk)
    head = b"TTP1" + struct.pack("<III", len(bins), n_edges, idx_bytes) + struct.pack("<ff", lo, scale)
    table_len = 4 * (len(bins) + 1)
    offsets, pos = [], len(head) + table_len
    for p in parts:
        offsets.append(pos)
        pos += len(p)
    offsets.append(pos)
    return head + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(parts)


def export(out: Path) -> dict[str, Any]:
    if out.exists():
        shutil.rmtree(out)
    c = TestClient(create_app())
    sizes: dict[str, int] = {}

    def get(url: str, **params: Any) -> Any:
        r = c.get(url, params=params or None)
        return r if r.status_code == 200 else None

    runs = get("/api/runs").json()
    sizes["runs.json"] = _write(out / "runs.json", runs)
    for name in ("districts",):
        r = get(f"/api/geo/{name}")
        if r is not None:
            sizes[f"geo/{name}.json"] = _write(out / "geo" / f"{name}.json", r.content)
    r = get("/api/geo/buildings")
    if r is not None:
        sizes["geo/buildings.json"] = _write(out / "geo" / "buildings.json", r.content)

    hashes = {run.get("network_hash") for run in runs if run.get("network_hash")}
    for h in sorted(hashes):
        for f in ("edges.bin", "edges.json"):
            r = get(f"/api/networks/{h}/{f}")
            if r is not None:
                sizes[f"networks/{h}/{f}"] = _write(out / "networks" / h / f, r.content)

    ids = [run["run_id"] for run in runs]
    for run in runs:
        rid = run["run_id"]
        base = out / "runs" / rid
        info = get(f"/api/runs/{rid}/bins")
        if info is not None:
            info = info.json()
            _write(base / "bins.json", info)
            for m in VIEW_METRICS:
                arrs = []
                for i in range(int(info["n_bins"])):
                    b = get(f"/api/runs/{rid}/bins/{i}", metric=m)
                    arrs.append(
                        np.frombuffer(b.content, dtype="<f4")
                        if b is not None
                        else np.full(int(info["n_edges"]), np.nan, np.float32)
                    )
                sizes[f"runs/{rid}/bins/{m}.pack"] = _write(base / "bins" / f"{m}.pack", pack_bins(arrs))
        if run.get("tier") == "B":
            end = float(run.get("sim_seconds") or 3600)
            r = get(f"/api/runs/{rid}/trajectories", begin=0, end=end, step=1)
            if r is not None:
                sizes[f"runs/{rid}/trajectories.json"] = _write(base / "trajectories.json", r.content)
        for name in ("policy-report", "scenario-report", "recommendations", "decisions"):
            r = get(f"/api/runs/{rid}/{name}")
            if r is not None:
                _write(base / f"{name}.json", r.content)
        for other in [None, *ids]:
            if other == rid:
                continue
            params = {"metric": EFFECT_METRIC, **({"baseline": other} if other else {})}
            r = get(f"/api/runs/{rid}/district-effects", **params)
            if r is not None:
                _write(base / "district-effects" / f"{other or 'none'}.json", r.content)
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    return {"runs": len(runs), "networks": len(hashes), "bytes": total, "largest": sorted(sizes.items(), key=lambda kv: -kv[1])[:10]}


@app.command()
def main(out: Path = typer.Option(Path("site/viewer/api"))) -> None:
    res = export(out)
    typer.echo(json.dumps(res, indent=1))


if __name__ == "__main__":
    app()
