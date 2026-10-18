"""Buildings GeoJSON: parsed once, each feature pre-serialised, filtered by bbox per request."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from api import settings

OSM_ATTRIBUTION = json.dumps("\u00a9 OpenStreetMap contributors (ODbL)").encode()


@dataclass
class Buildings:
    path: Path
    mtime: float
    features: list[bytes]
    bounds: np.ndarray  # [n, 4] minx, miny, maxx, maxy


def _bounds(coords: object) -> tuple[float, float, float, float]:
    arr = np.asarray(_flatten(coords), dtype=np.float64).reshape(-1, 2)
    return arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()


def _flatten(coords: object) -> list[float]:
    out: list[float] = []
    stack = [coords]
    while stack:
        c = stack.pop()
        if isinstance(c, list) and c and isinstance(c[0], int | float):
            out.extend(c[:2])
        elif isinstance(c, list):
            stack.extend(c)
    return out


_cache: Buildings | None = None
_lock = threading.Lock()


def buildings() -> Buildings:
    global _cache
    path = settings.buildings_path()
    if not path.is_file():
        raise FileNotFoundError("buildings not available")
    mtime = path.stat().st_mtime
    with _lock:
        if _cache is None or _cache.path != path or _cache.mtime != mtime:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            feats, bounds = [], []
            for f in data.get("features", []):
                geom = f.get("geometry") or {}
                if not geom.get("coordinates"):
                    continue
                feats.append(json.dumps(f, ensure_ascii=False, separators=(",", ":")).encode())
                bounds.append(_bounds(geom["coordinates"]))
            _cache = Buildings(path, mtime, feats, np.array(bounds).reshape(-1, 4))
        return _cache


def buildings_geojson(bbox: tuple[float, float, float, float] | None) -> tuple[bytes, int]:
    b = buildings()
    if bbox is None:
        sel = range(len(b.features))
    else:
        w, s, e, n = bbox
        m = b.bounds
        sel = np.flatnonzero((m[:, 0] <= e) & (m[:, 2] >= w) & (m[:, 1] <= n) & (m[:, 3] >= s))
    parts = [b.features[i] for i in sel]
    head = b'{"type":"FeatureCollection","attribution":' + OSM_ATTRIBUTION + b',"features":['
    return head + b",".join(parts) + b"]}", len(parts)
