"""Edge index of a network: binary lon/lat geometry (edges.bin) plus attributes (edges.json).

The index order is the order of non-internal edges in the .net.xml, the same order as
`python -m sim.network.netinfo edges-geojson`. The .net.xml is streamed (the city net is 353 MB);
the root element is cleared after every top-level child so memory stays flat.
"""

from __future__ import annotations

import gzip
import struct
import xml.etree.ElementTree as ET
from array import array
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer

from api import settings
from api.util import atomic_write_bytes, atomic_write_json, build_lock, read_json

MAGIC = b"TTE1"
HEADER = struct.Struct("<4sII")
MS_TO_KMH = 3.6  # unit conversion


def index_dir(network_hash: str) -> Path:
    return settings.cache_dir() / network_hash


def _open_net(net: Path) -> Any:
    """Plain or gzipped .net.xml (Track A writes edited networks as .net.xml.gz)."""
    return gzip.open(net, "rb") if net.suffix == ".gz" else net.open("rb")


def _location(net: Path) -> tuple[float, float, str]:
    with _open_net(net) as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "location":
                dx, dy = (float(v) for v in elem.get("netOffset", "0,0").split(","))
                return dx, dy, elem.get("projParameter", "!")
    raise ValueError(f"{net}: no <location> element")


def _parse_net(net: Path) -> tuple[dict[str, list[Any]], array, array, array]:
    """Stream the net: attributes per edge plus flat x/y arrays and path start indices."""
    attrs: dict[str, list[Any]] = {
        "edge_ids": [],
        "names": [],
        "types": [],
        "lanes": [],
        "speed_kmh": [],
    }
    xs, ys = array("d"), array("d")
    starts = array("I", [0])
    with _open_net(net) as fh:
        _walk_net(fh, attrs, xs, ys, starts)
    return attrs, xs, ys, starts


def _walk_net(fh: Any, attrs: dict[str, list[Any]], xs: array, ys: array, starts: array) -> None:
    root: ET.Element | None = None
    depth = 0
    current: dict[str, str] | None = None
    shape: str | None = None
    lanes = 0
    speed = ""
    for event, elem in ET.iterparse(fh, events=("start", "end")):
        if event == "start":
            depth += 1
            if root is None:
                root = elem
            elif elem.tag == "edge" and depth == 2 and elem.get("function") != "internal":
                current = dict(elem.attrib)
                shape = elem.get("shape")
                lanes = 0
                speed = ""
            continue
        depth -= 1
        if elem.tag == "lane" and current is not None:
            lanes += 1
            if shape is None:
                shape = elem.get("shape")
            if not speed:
                speed = elem.get("speed", "")
        elif elem.tag == "edge" and current is not None:
            if shape:
                for point in shape.split():
                    a, b = point.split(",")[:2]
                    xs.append(float(a))
                    ys.append(float(b))
            starts.append(len(xs))
            attrs["edge_ids"].append(current.get("id", ""))
            attrs["names"].append(current.get("name", ""))
            attrs["types"].append(current.get("type", ""))
            attrs["lanes"].append(lanes)
            attrs["speed_kmh"].append(round(float(speed or 0) * MS_TO_KMH))
            current = None
            shape = None
        if depth == 1 and root is not None:
            root.clear()  # drop finished top-level elements (edges, junctions, connections)


def build_edge_index(net: Path, network_hash: str) -> Path:
    """Write edges.bin and edges.json for `net` under the cache; return the directory."""
    dx, dy, proj = _location(net)
    if proj == "!":
        raise ValueError(f"{net}: network has no geo projection")
    attrs, xs, ys, starts = _parse_net(net)
    to_geo = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    x = np.frombuffer(xs, dtype=np.float64) - dx
    y = np.frombuffer(ys, dtype=np.float64) - dy
    lon, lat = to_geo.transform(x, y)
    coords = np.empty((len(x), 2), dtype="<f4")
    coords[:, 0] = lon
    coords[:, 1] = lat
    n_edges = len(attrs["edge_ids"])
    blob = (
        HEADER.pack(MAGIC, n_edges, len(x))
        + np.frombuffer(starts, dtype=np.uint32).astype("<u4").tobytes()
        + coords.tobytes()
    )
    out = index_dir(network_hash)
    atomic_write_bytes(out / "edges.bin", blob)
    atomic_write_json(
        out / "edges.json",
        {"network_hash": network_hash, "n_edges": n_edges, "n_points": len(x), **attrs},
    )
    return out


def ensure_edge_index(net: Path, network_hash: str) -> Path:
    out = index_dir(network_hash)
    if (out / "edges.bin").exists() and (out / "edges.json").exists():
        return out
    with build_lock(f"edges:{network_hash}"):
        if (out / "edges.bin").exists() and (out / "edges.json").exists():
            return out
        return build_edge_index(net, network_hash)


@dataclass
class EdgeIndex:
    network_hash: str
    edge_ids: list[str]
    starts: np.ndarray  # uint32 [n_edges + 1]
    coords: np.ndarray  # float32 [n_points, 2] lon, lat

    @cached_property
    def position(self) -> dict[str, int]:
        return {e: i for i, e in enumerate(self.edge_ids)}

    @property
    def n_edges(self) -> int:
        return len(self.edge_ids)

    def path(self, i: int) -> np.ndarray:
        return self.coords[self.starts[i] : self.starts[i + 1]]

    def midpoints(self) -> np.ndarray:
        """Point at half the planar length of every path (lon/lat; NaN for empty paths)."""
        out = np.full((self.n_edges, 2), np.nan)
        for i in range(self.n_edges):
            pts = self.path(i).astype(np.float64)
            if len(pts) == 0:
                continue
            if len(pts) == 1:
                out[i] = pts[0]
                continue
            seg = np.hypot(*np.diff(pts, axis=0).T)
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            half = cum[-1] / 2
            k = min(int(np.searchsorted(cum, half, side="right")) - 1, len(seg) - 1)
            frac = (half - cum[k]) / seg[k] if seg[k] > 0 else 0.0
            out[i] = pts[k] + frac * (pts[k + 1] - pts[k])
        return out


def parse_edges_bin(blob: bytes) -> tuple[np.ndarray, np.ndarray]:
    magic, n_edges, n_points = HEADER.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError("not a TTE1 edges.bin")
    off = HEADER.size
    starts = np.frombuffer(blob, dtype="<u4", count=n_edges + 1, offset=off)
    off += 4 * (n_edges + 1)
    coords = np.frombuffer(blob, dtype="<f4", count=2 * n_points, offset=off).reshape(-1, 2)
    return starts, coords


MAX_INDEXES_IN_MEMORY = 4  # demo window + city + a couple of variants
_loaded: dict[tuple[str, float], EdgeIndex] = {}


def load_edge_index(net: Path, network_hash: str) -> EdgeIndex:
    out = ensure_edge_index(net, network_hash)
    key = (str(out), (out / "edges.bin").stat().st_mtime)
    if key not in _loaded:
        starts, coords = parse_edges_bin((out / "edges.bin").read_bytes())
        ids = read_json(out / "edges.json")["edge_ids"]
        while len(_loaded) >= MAX_INDEXES_IN_MEMORY:
            _loaded.pop(next(iter(_loaded)))
        _loaded[key] = EdgeIndex(network_hash, ids, starts, coords)
    return _loaded[key]
