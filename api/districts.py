"""Edge -> district mapping (edge midpoint in polygon) and per-district effects.

The computed effect is the % change of the sampled-seconds-weighted mean speed per district,
run vs comparison run, over all bins: sum(speed * sampled_s) / sum(sampled_s). Only districts with
data in both runs are returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from shapely import STRtree, points
from shapely.geometry import shape

from api import settings
from api.edges import EdgeIndex
from api.schema import edge_select
from api.util import atomic_save_npy, atomic_write_json, build_lock, read_json
from sim.common import file_hash

COMPUTED_METRIC = "mean_speed_delta_pct"
PCT = 100.0  # unit conversion
NO_DISTRICT = -1


def load_districts() -> list[dict[str, Any]]:
    path = settings.districts_path()
    if not path.is_file():
        return []
    return read_json(path).get("features", [])


def district_map(index: EdgeIndex) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Per edge the district position (or -1) and the district list, cached per network."""
    path = settings.districts_path()
    if not path.is_file():
        raise FileNotFoundError("districts not available")
    dhash = file_hash(path)
    out = settings.cache_dir() / index.network_hash / f"districts-{dhash}"
    npy, meta = out / "edge_district.npy", out / "districts.json"
    with build_lock(f"districts:{index.network_hash}:{dhash}"):
        if not (npy.exists() and meta.exists()):
            feats = load_districts()
            polys = [shape(f["geometry"]) for f in feats]
            tree = STRtree(polys)
            mids = index.midpoints()
            ok = np.isfinite(mids).all(axis=1)
            assign = np.full(index.n_edges, NO_DISTRICT, dtype=np.int32)
            pts = points(mids[ok])
            pt_idx, poly_idx = tree.query(pts, predicate="within")
            where = np.flatnonzero(ok)
            # overlapping polygons: keep the first (lowest index) district per edge
            order = np.lexsort((poly_idx, pt_idx))
            pt_idx, poly_idx = pt_idx[order], poly_idx[order]
            first = np.unique(pt_idx, return_index=True)[1]
            assign[where[pt_idx[first]]] = poly_idx[first]
            atomic_save_npy(npy, assign)
            info = [
                {
                    "district_id": f["properties"].get("osm_id"),
                    "name_en": f["properties"].get("name_en"),
                    "name_ar": f["properties"].get("name_ar"),
                }
                for f in feats
            ]
            atomic_write_json(meta, info)
    return np.load(npy), read_json(meta)


def _speed_sums(parquet: Path) -> dict[str, tuple[float, float]]:
    """Per edge: (sum speed * sampled_s, sum sampled_s), streaming in DuckDB."""
    con = duckdb.connect()
    rows = con.execute(
        "SELECT edge_id, sum(speed_ms * sampled_s), sum(sampled_s) "
        f"FROM ({edge_select(parquet)}) WHERE NOT isnan(speed_ms) AND sampled_s > 0 GROUP BY 1"
    ).fetchall()
    con.close()
    return {e: (float(a), float(b)) for e, a, b in rows}


def _district_speeds(
    parquet: Path, index: EdgeIndex, assign: np.ndarray, n_districts: int
) -> tuple[np.ndarray, np.ndarray]:
    num = np.zeros(n_districts)
    den = np.zeros(n_districts)
    pos = index.position
    for edge, (a, b) in _speed_sums(parquet).items():
        i = pos.get(edge)
        if i is None or assign[i] == NO_DISTRICT:
            continue
        num[assign[i]] += a
        den[assign[i]] += b
    return num, den


def computed_effects(
    run_parquet: Path, base_parquet: Path, index: EdgeIndex
) -> list[dict[str, Any]]:
    assign, info = district_map(index)
    n = len(info)
    rn, rd = _district_speeds(run_parquet, index, assign, n)
    bn, bd = _district_speeds(base_parquet, index, assign, n)
    out = []
    for k in np.flatnonzero((rd > 0) & (bd > 0)):
        run_speed, base_speed = rn[k] / rd[k], bn[k] / bd[k]
        if base_speed <= 0:
            continue
        out.append(
            {
                "district_id": info[k]["district_id"],
                "name_en": info[k]["name_en"],
                "value": round((run_speed / base_speed - 1.0) * PCT, 3),
                "run_mean_speed_ms": round(run_speed, 3),
                "baseline_mean_speed_ms": round(base_speed, 3),
            }
        )
    out.sort(key=lambda d: str(d["district_id"]))
    return out


def districts_geojson_bytes() -> bytes:
    path = settings.districts_path()
    if not path.is_file():
        raise FileNotFoundError("districts not available")
    return path.read_bytes()


def report_effects(report: dict[str, Any], metric: str) -> list[dict[str, Any]] | None:
    """District values for `metric` from a policy report, or None if it has none."""
    rows = []
    for d in report.get("districts") or []:
        value = (d.get("metrics") or {}).get(metric)
        if value is None:
            continue
        rows.append(
            {"district_id": d.get("district_id"), "name_en": d.get("name_en"), "value": value}
        )
    return rows or None
