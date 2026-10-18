"""Creek and catchment geometry shared by the bridge transform, the desire-line analysis and the
window evaluation: the inner creek polygon (OSM coastline), window polygons, and the vectorised
"does this origin-destination line cross the creek" test."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon, shape

from sim.bridge.schema import bridge_config
from sim.common import REPO_ROOT, load_yaml
from sim.common import rel as _resolved_rel


def repo_rel(path: Path) -> str:
    """Repo-relative path without resolving symlinks first (data/jeddah links to the main checkout
    in a worktree; sim.common.rel would return an absolute path there). As sim.link.rel."""
    absolute = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        return str(absolute.relative_to(REPO_ROOT))
    except ValueError:
        return _resolved_rel(path)


@lru_cache(maxsize=4)
def creek_polygon(path: str | None = None) -> Polygon:
    p = Path(path or REPO_ROOT / bridge_config()["creek"])
    geo = json.loads(p.read_text())
    feats = geo["features"] if geo.get("type") == "FeatureCollection" else [geo]
    return shape(feats[0]["geometry"])


@lru_cache(maxsize=8)
def window_polygon(name: str) -> Polygon:
    cfg = load_yaml(REPO_ROOT / "sim" / "network" / "windows" / f"{name}.yaml")
    if "polygon" in cfg:
        return Polygon(cfg["polygon"])
    x0, y0, x1, y1 = cfg["bbox"]
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def edges_in(edges: pd.DataFrame, poly: Polygon) -> set[str]:
    """Edges whose midpoint (edge table lon/lat) lies inside `poly`."""
    pts = shapely.points(edges["lon"].to_numpy(), edges["lat"].to_numpy())
    return set(edges.loc[shapely.contains(poly, pts), "edge_id"])


def edge_points(edges: pd.DataFrame, ids: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Midpoint lon/lat of each edge id (NaN when the id is not in the table)."""
    pos = edges.set_index("edge_id")[["lon", "lat"]]
    xy = pos.reindex(ids.astype(str).to_numpy())
    return xy["lon"].to_numpy(dtype=float), xy["lat"].to_numpy(dtype=float)


def crosses(
    o_lon: np.ndarray, o_lat: np.ndarray, d_lon: np.ndarray, d_lat: np.ndarray, poly: Polygon
) -> np.ndarray:
    """True where the straight origin-destination segment crosses `poly` with both ends outside
    it (a desire line over the water); NaN coordinates give False."""
    ok = ~(np.isnan(o_lon) | np.isnan(o_lat) | np.isnan(d_lon) | np.isnan(d_lat))
    out = np.zeros(len(o_lon), dtype=bool)
    if not ok.any():
        return out
    coords = np.stack([np.c_[o_lon[ok], o_lat[ok]], np.c_[d_lon[ok], d_lat[ok]]], axis=1)
    lines = shapely.linestrings(coords)
    shapely.prepare(poly)
    hit = shapely.intersects(poly, lines)
    inside = shapely.contains(poly, shapely.points(coords[:, 0])) | shapely.contains(
        poly, shapely.points(coords[:, 1])
    )
    out[np.flatnonzero(ok)] = hit & ~inside
    return out
