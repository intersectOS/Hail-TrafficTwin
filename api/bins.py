"""Per-run bin arrays aligned to the network edge index, stored sparse (contract §10, v1.1).

Cache layout under <TT_CACHE_DIR>/runs/<run_id>/ ("sparse-v1"): the rows of the edge bins sorted
by bin, as

    edge_pos.npy     int32  [n_rows]       edge index position (-1 = edge not in the network)
    bin_offsets.npy  int64  [n_bins + 1]   rows of bin i are offsets[i]:offsets[i + 1]
    <metric>.npy     float32 [n_rows]      one per stored metric (NaN = no data)
    bins.json        the /bins metadata incl. p5/p50/p95 per metric

A dense Float32 [n_edges] bin is scattered from these on request (0.6 MB for the city; about
1 ms). A 24 h city baseline (7.6 M rows) needs ~240 MB here instead of ~1.6 GB dense. Arrays are
filled through memmaps, so a city run is never held in RAM. The source is any edge-bin Parquet
(contract or producer schema; api.schema).
"""

from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from api import settings
from api.edges import index_dir, load_edge_index
from api.schema import edge_select
from api.util import atomic_write_json, build_lock, is_stale, read_json

if TYPE_CHECKING:
    from api.runs import Run

LAYOUT = "sparse-v1"
MS_TO_KMH = 3.6  # unit conversion
PERCENTILES = (5, 50, 95)
BATCH_ROWS = 262_144
DUCKDB_MEMORY_LIMIT = "1GB"
METRICS: dict[str, str] = {
    "speed_ms": "m/s",
    "speed_kmh": "km/h",
    "speed_rel": "-",
    "density_veh_km": "veh/km",
    "occupancy_pct": "%",
    "flow_veh_h": "veh/h",
    "delay_s_per_veh": "s/veh",
    "entered": "veh",
}
DERIVED = {"speed_kmh": ("speed_ms", MS_TO_KMH)}  # metric -> (stored metric, factor)
STORED = [m for m in METRICS if m not in DERIVED]


def bins_dir(run_id: str) -> Path:
    return settings.cache_dir() / "runs" / run_id


def _allowed_speed(network_hash: str, n_edges: int) -> np.ndarray:
    """Speed limit per edge (m/s, from the edge index; NaN when 0) for derived speed_rel."""
    try:
        kmh = np.asarray(read_json(index_dir(network_hash) / "edges.json")["speed_kmh"], float)
    except (OSError, KeyError, ValueError):
        return np.full(n_edges, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(kmh > 0, kmh / MS_TO_KMH, np.nan)


def _col(batch: pa.RecordBatch, name: str) -> np.ndarray:
    arr = batch.column(name)
    if arr.null_count:
        arr = pc.fill_null(arr.cast(pa.float64()), math.nan)
    return arr.to_numpy(zero_copy_only=False).astype(np.float32)


def _values(batch: pa.RecordBatch, pos: np.ndarray, allowed: np.ndarray) -> dict[str, np.ndarray]:
    speed = _col(batch, "speed_ms")
    entered = _col(batch, "entered")
    loss = _col(batch, "time_loss_s")
    rel = _col(batch, "speed_rel")
    if np.isnan(rel).all() and len(rel):
        lim = np.where(pos >= 0, allowed[np.clip(pos, 0, None)], np.nan)
        rel = (speed / lim).astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        delay = np.where(entered > 0, loss / entered, np.nan).astype(np.float32)
    return {
        "speed_ms": speed,
        "speed_rel": rel,
        "density_veh_km": _col(batch, "density_veh_km"),
        "occupancy_pct": _col(batch, "occupancy_pct"),
        "flow_veh_h": _col(batch, "flow_veh_h"),
        "delay_s_per_veh": delay,
        "entered": entered,
    }


def _positions(arr: pa.Array, position: dict[str, int]) -> np.ndarray:
    enc = pc.dictionary_encode(arr)
    lookup = np.array([position.get(e, -1) for e in enc.dictionary.to_pylist()], dtype=np.int32)
    idx = enc.indices.to_numpy(zero_copy_only=False)
    return lookup[idx] if len(lookup) else np.full(len(idx), -1, dtype=np.int32)


def build_bins(run: Run, parquet: Path) -> dict[str, Any]:
    meta = run.meta
    from api.runs import run_network

    index = load_edge_index(run_network(run), str(meta["network_hash"]))
    n_edges = index.n_edges
    allowed = _allowed_speed(str(meta["network_hash"]), n_edges)
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        src = edge_select(parquet)
        n_rows, min_b, max_e, width0 = con.execute(
            f"SELECT count(*), min(bin_begin_s), max(bin_end_s), "
            f"min(bin_end_s - bin_begin_s) FROM ({src})"
        ).fetchone()
        begin = int(meta.get("begin_s") or 0)
        width = int(meta.get("edgedata_freq_s") or width0 or 0)
        if not width:
            raise ValueError("cannot determine the edgedata bin width")
        span = int(meta.get("sim_seconds") or 0)
        if max_e is not None:
            span = max(span, int(max_e) - begin)
        n_bins = max(1, math.ceil(span / width))
        out = bins_dir(run.run_id)
        tmp = out.with_name(f".{out.name}.building")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        mm = np.lib.format.open_memmap
        n_rows = int(n_rows)
        cap = max(n_rows, 1)  # numpy cannot memmap an empty array
        pos_all = mm(tmp / "edge_pos.npy", mode="w+", dtype="<i4", shape=(cap,))
        bin_all = mm(tmp / "bin_idx.npy", mode="w+", dtype="<i4", shape=(cap,))
        vals = {m: mm(tmp / f"{m}.npy", mode="w+", dtype="<f4", shape=(cap,)) for m in STORED}
        unmatched: set[str] = set()
        reader = con.execute(f"{src} ORDER BY bin_begin_s").to_arrow_reader(BATCH_ROWS)
        at = 0
        for batch in reader:
            k = batch.num_rows
            pos = _positions(batch.column("edge_id"), index.position)
            b = (batch.column("bin_begin_s").to_numpy(zero_copy_only=False) - begin) // width
            bad = (b < 0) | (b >= n_bins)
            if (pos < 0).any():
                ids = batch.column("edge_id").to_pylist()
                unmatched.update(ids[i] for i in np.flatnonzero(pos < 0))
            pos = np.where(bad, -1, pos).astype(np.int32)
            bin_all[at : at + k] = np.clip(b, 0, n_bins - 1)
            pos_all[at : at + k] = pos
            for m, v in _values(batch, pos, allowed).items():
                vals[m][at : at + k] = v
            at += k
    finally:
        con.close()
    offsets = np.searchsorted(np.asarray(bin_all[:at]), np.arange(n_bins + 1)).astype("<i8")
    np.save(tmp / "bin_offsets.npy", offsets)
    stats: dict[str, dict[str, float | None]] = {}
    with_data = []
    keep = np.asarray(pos_all[:at]) >= 0
    for m in STORED:
        a = vals[m]
        a.flush()
        sel = np.asarray(a[:at])[keep]
        finite = sel[np.isfinite(sel)]
        if finite.size:
            qs = np.percentile(finite, PERCENTILES)
            stats[m] = {f"p{p}": round(float(q), 4) for p, q in zip(PERCENTILES, qs, strict=True)}
            with_data.append(m)
        else:
            stats[m] = {f"p{p}": None for p in PERCENTILES}
    for m, (srcm, factor) in DERIVED.items():
        stats[m] = {
            k: (round(v * factor, 4) if v is not None else None) for k, v in stats[srcm].items()
        }
        if srcm in with_data:
            with_data.append(m)
    del vals, pos_all, bin_all
    (tmp / "bin_idx.npy").unlink()
    info = {
        "run_id": run.run_id,
        "label": settings.LABEL,
        "layout": LAYOUT,
        "bin_s": width,
        "begin_s": begin,
        "n_bins": n_bins,
        "n_edges": n_edges,
        "network_hash": meta["network_hash"],
        "metrics": list(METRICS),
        "metrics_with_data": [m for m in METRICS if m in with_data],
        "units": METRICS,
        "stats": stats,
        "rows": int(n_rows),
        "unmatched_edges": len(unmatched),
        "source": str(parquet.name),
        "dtype": "float32 little endian; NaN = no data",
    }
    # Move file by file (the run's cache dir may also hold converted edgedata/fcd Parquet);
    # bins.json goes last, so a reader never sees new metadata with old arrays.
    _mmaps.clear()
    out.mkdir(parents=True, exist_ok=True)
    (out / "bins.json").unlink(missing_ok=True)
    for f in tmp.glob("*.npy"):
        os.replace(f, out / f.name)
    atomic_write_json(out / "bins.json", info)
    shutil.rmtree(tmp, ignore_errors=True)
    return info


def ensure_bins(run: Run, force: bool = False) -> dict[str, Any]:
    from api.ingest import ensure_edgedata

    parquet = ensure_edgedata(run.data_dir, run_id=run.run_id)
    if parquet is None:
        raise FileNotFoundError("edgedata not available")
    info_path = bins_dir(run.run_id) / "bins.json"

    def fresh() -> dict[str, Any] | None:
        if force or is_stale(info_path, parquet):
            return None
        info = read_json(info_path)
        return info if info.get("layout") == LAYOUT else None

    hit = fresh()
    if hit is not None:
        return hit
    with build_lock(f"bins:{run.run_id}"):
        hit = fresh()
        if hit is not None:
            return hit
        return build_bins(run, parquet)


_mmaps: dict[tuple[str, str, float], np.ndarray] = {}


def _mmap(run_id: str, name: str) -> np.ndarray:
    path = bins_dir(run_id) / f"{name}.npy"
    key = (run_id, name, path.stat().st_mtime)  # a rebuild (any process) changes the mtime
    if key not in _mmaps:
        for old in [k for k in _mmaps if k[:2] == key[:2]]:
            del _mmaps[old]
        _mmaps[key] = np.load(path, mmap_mode="r")
    return _mmaps[key]


def bin_values(run_id: str, metric: str, i: int, n_edges: int) -> np.ndarray:
    """Dense float32 [n_edges] of one bin (NaN = no data)."""
    stored, factor = DERIVED.get(metric, (metric, 1.0))
    offsets = _mmap(run_id, "bin_offsets")
    a, b = int(offsets[i]), int(offsets[i + 1])
    pos = np.asarray(_mmap(run_id, "edge_pos")[a:b])
    vals = np.asarray(_mmap(run_id, stored)[a:b])
    ok = pos >= 0
    out = np.full(n_edges, np.nan, dtype="<f4")
    out[pos[ok]] = vals[ok] * np.float32(factor) if factor != 1.0 else vals[ok]
    return out
