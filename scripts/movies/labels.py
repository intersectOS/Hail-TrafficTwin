"""Map labels for the films: street names, district names and reviewed landmarks (MOVIES_V2).

Streets come from the same OpenStreetMap extract the network is built from (osmium cut of the
film's map area): named `highway` ways, English `name:en` preferred, the Arabic `name` as a second
line. Every way with the same Arabic name gets the English name most often paired with it in the
area (so a split carriageway named only in Arabic still gets its English line, and one road never
shows two English names). Each named
road is merged into lines and gets label anchors every few hundred metres (closer for minor
roads), each with the road's bearing there, so the renderer can rotate the label along the road.
Districts are the admin_level=10 polygons of `data/jeddah/districts.geojson`; landmarks the
reviewed `movies/landmarks.yaml`. The renderer (web/src/cinema/annotate.ts) chooses per frame
which labels fit (road-class priority, zoom gating, collision avoidance).

    uv run python -m scripts.movies.labels 39.08 21.69 39.14 21.74   # print counts for a bbox
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import typer
import yaml
from shapely.geometry import LineString, MultiLineString, box, shape
from shapely.ops import linemerge

from scripts.movies import basemap as bm
from sim.common import REPO_ROOT, run_cmd

LABELS_VERSION = "2"
LANDMARKS = REPO_ROOT / "movies" / "landmarks.yaml"
DISTRICTS = REPO_ROOT / "data" / "jeddah" / "districts.geojson"

# street class (renderer priority): 0 motorway/trunk, 1 primary, 2 secondary, 3 tertiary, 4 local
HIGHWAY_CLASS = {
    "motorway": 0,
    "trunk": 0,
    "primary": 1,
    "secondary": 2,
    "tertiary": 3,
    "residential": 4,
    "unclassified": 4,
    "living_street": 4,
}
# metres between anchors and the shortest named line that gets one, per class
ANCHOR_SPACING_M = [700.0, 550.0, 420.0, 320.0, 240.0]
MIN_LINE_M = [250.0, 200.0, 160.0, 120.0, 90.0]
M_PER_DEG_LAT = 110_574.0


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _length_m(line: LineString) -> float:
    lat = line.coords[0][1]
    kx, ky = _m_per_deg_lon(lat), M_PER_DEG_LAT
    c = list(line.coords)
    return sum(
        math.hypot((x1 - x0) * kx, (y1 - y0) * ky)
        for (x0, y0), (x1, y1) in zip(c, c[1:], strict=False)
    )


def _bearing(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    kx = _m_per_deg_lon(p0[1])
    dx, dy = (p1[0] - p0[0]) * kx, (p1[1] - p0[1]) * M_PER_DEG_LAT
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def anchors(line: LineString, spacing_m: float) -> list[list[float]]:
    """Points along the line every spacing_m (first at half a spacing), with the local bearing."""
    total = _length_m(line)
    if total <= 0:
        return []
    out = []
    d = min(spacing_m / 2, total / 2)
    while d < total:
        f = d / total
        p = line.interpolate(f, normalized=True)
        a = line.interpolate(max(0.0, f - 25.0 / total), normalized=True)
        b = line.interpolate(min(1.0, f + 25.0 / total), normalized=True)
        out.append([round(p.x, 6), round(p.y, 6), round(_bearing((a.x, a.y), (b.x, b.y)), 1)])
        d += spacing_m
    return out


def _lines(geom: Any) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def street_labels(features: list[dict[str, Any]], frame: Any) -> list[dict[str, Any]]:
    en_for_ar: dict[str, Counter] = defaultdict(Counter)
    for f in features:
        p = f.get("properties") or {}
        if p.get("name") and p.get("name:en"):
            en_for_ar[p["name"]][p["name:en"]] += 1
    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    for f in features:
        p = f.get("properties") or {}
        cls = HIGHWAY_CLASS.get(str(p.get("highway")))
        ar = p.get("name")
        if cls is None or not (ar or p.get("name:en")):
            continue
        en = en_for_ar[ar].most_common(1)[0][0] if ar in en_for_ar else p.get("name:en")
        key = (en or ar, ar if ar != en else None)
        g = groups.setdefault(key, {"cls": cls, "lines": []})
        g["cls"] = min(g["cls"], cls)
        geom = shape(f["geometry"])
        if not frame.contains(geom):
            geom = geom.intersection(frame)
        g["lines"].extend(_lines(geom))
    out = []
    for (label, ar), g in sorted(groups.items(), key=lambda kv: (kv[1]["cls"], kv[0][0])):
        cls = g["cls"]
        merged = linemerge(MultiLineString(g["lines"])) if g["lines"] else None
        pts: list[list[float]] = []
        for line in _lines(merged) if merged is not None else []:
            if _length_m(line) >= MIN_LINE_M[cls]:
                pts.extend(anchors(line, ANCHOR_SPACING_M[cls]))
        if pts:
            out.append({"en": label, "ar": ar, "cls": cls, "anchors": pts})
    return out


def district_labels(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    if not DISTRICTS.exists():
        return []
    frame = box(*bbox)
    out = []
    for f in json.loads(DISTRICTS.read_text())["features"]:
        p = f["properties"]
        pt = shape(f["geometry"]).representative_point()
        if frame.contains(pt) and (p.get("name_en") or p.get("name_ar")):
            en = p.get("name_en") or p.get("name_ar")
            ar = p.get("name_ar") if p.get("name_ar") != en else None
            out.append({"en": en, "ar": ar, "lon": round(pt.x, 5), "lat": round(pt.y, 5)})
    out.sort(key=lambda d: (d["en"], d["lon"]))
    return out


def landmark_labels(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    w, s, e, n = bbox
    items = yaml.safe_load(LANDMARKS.read_text())["landmarks"]
    keys = ("id", "en", "ar", "lon", "lat", "min_zoom", "max_zoom")
    return [{k: lm[k] for k in keys} for lm in items if w <= lm["lon"] <= e and s <= lm["lat"] <= n]


def labels_key(bbox: tuple[float, float, float, float]) -> str:
    raw = json.dumps([round(v, 4) for v in bbox] + [LABELS_VERSION, bm.BASEMAP_VERSION])
    extra = LANDMARKS.read_bytes() + (DISTRICTS.read_bytes() if DISTRICTS.exists() else b"")
    return hashlib.sha256(raw.encode() + extra).hexdigest()[:12]


def build_labels(bbox: tuple[float, float, float, float], force: bool = False) -> Path:
    """Write labels.json for bbox (w, s, e, n) under runs/movies/_labels/<key>/; return the file."""
    out = bm.basemap_dir().parent / "_labels" / labels_key(bbox) / "labels.json"
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    w, s, e, n = bbox
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        clip = tmp / "clip.osm.pbf"
        run_cmd(["osmium", "extract", "-b", f"{w},{s},{e},{n}", "-s", "smart", str(bm._pbf()),
                 "-o", str(clip), "--overwrite"])  # fmt: skip
        feats = bm._export(clip, ["w/highway"], tmp / "roads.geojsonseq", tmp)
    feats = [f for f in feats if (f.get("geometry") or {}).get("type") == "LineString"]
    data = {
        "streets": street_labels(feats, box(*bbox)),
        "districts": district_labels(bbox),
        "landmarks": landmark_labels(bbox),
    }
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return out


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(w: float, s: float, e: float, n: float, force: bool = False) -> None:
    path = build_labels((w, s, e, n), force=force)
    d = json.loads(path.read_text())
    by_cls = Counter(x["cls"] for x in d["streets"])
    typer.echo(
        f"{path}: {len(d['streets'])} named roads {dict(sorted(by_cls.items()))}, "
        f"{sum(len(x['anchors']) for x in d['streets'])} anchors, {len(d['districts'])} districts, "
        f"{len(d['landmarks'])} landmarks"
    )


if __name__ == "__main__":
    app()
