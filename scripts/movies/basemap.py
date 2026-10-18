"""Offline basemap for the films: 3D buildings, water and sea from the Geofabrik PBF.

Everything is cut from `data/osm/gcc-states-latest.osm.pbf` (or the clipped Jeddah PBF when the
big extract is missing) for the camera's bounding box with osmium, then written as compact JSON
under `runs/movies/_basemap/<bbox hash>/` (reused by every film over the same area):

- buildings.json  {"n": .., "heights": [..], "rings": [[[lon, lat], ..], ..]} (outer rings)
- water.json      {"polygons": [[ring, hole, ..], ..]}: inland water plus the sea, which is built
                  by polygonizing the coastline against the box (OSM coastlines keep land on the
                  left, so faces on the right of the nearest coastline segment are sea)

Heights: `height` tag, else `building:levels` x A-mov-002, else A-mov-001. No tile servers.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import typer
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, shape
from shapely.ops import linemerge, polygonize, unary_union

from scripts.movies.spec import load_settings
from sim.common import REPO_ROOT, run_cmd

PBF_CANDIDATES = [
    REPO_ROOT / "data" / "osm" / "gcc-states-latest.osm.pbf",
    REPO_ROOT / "data" / "osm" / "jeddah.osm.pbf",
]
COORD_DECIMALS = 6
SIMPLIFY_DEG = 0.00001  # ~1 m: drops collinear vertices, keeps footprints
SEA_PAD_DEG = 1.5  # sea faces touching the box edge continue this far beyond it (no hard edge)
BASEMAP_VERSION = "2"


def basemap_dir() -> Path:
    return REPO_ROOT / "runs" / "movies" / "_basemap"


def bbox_key(bbox: tuple[float, float, float, float]) -> str:
    raw = json.dumps([round(v, 4) for v in bbox] + [BASEMAP_VERSION])
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _pbf() -> Path:
    for p in PBF_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("no OSM PBF under data/osm/ (run `make city-net` first)")


def parse_height(tags: dict[str, Any], default_m: float, per_level_m: float) -> float:
    raw = str(tags.get("height", "") or "").lower().replace("m", "").replace(",", ".").strip()
    try:
        h = float(raw)
        if h > 0:
            return h
    except ValueError:
        pass
    try:
        levels = float(str(tags.get("building:levels", "") or "").strip())
        if levels > 0:
            return levels * per_level_m
    except ValueError:
        pass
    return default_m


def _read_seq(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if line:
                out.append(json.loads(line))
    return out


def _export(pbf: Path, filters: list[str], out: Path, tmp: Path) -> list[dict[str, Any]]:
    filtered = tmp / f"{out.stem}.osm.pbf"
    run_cmd(["osmium", "tags-filter", str(pbf), *filters, "-o", str(filtered), "--overwrite"])
    run_cmd(["osmium", "export", str(filtered), "-f", "geojsonseq", "-o", str(out), "--overwrite"])
    return _read_seq(out)


def _round_ring(coords: Any) -> list[list[float]]:
    return [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)] for x, y in coords]


def _polys(geom: Any) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        return [g for sub in geom.geoms for g in _polys(sub)]
    return []


def sea_faces(lines: list[LineString], frame: Polygon) -> list[Polygon]:
    """Faces of `frame` cut by coastlines that lie on the water (right-hand) side."""
    clipped = [ln.intersection(frame) for ln in lines]
    parts: list[LineString] = []
    for g in clipped:
        if g.is_empty:
            continue
        if g.geom_type == "LineString":
            parts.append(g)
        elif g.geom_type == "MultiLineString":
            parts.extend(g.geoms)
    if not parts:
        return []
    merged = linemerge(MultiLineString(parts))
    coast = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    faces = list(polygonize(unary_union([frame.exterior, *coast])))
    sea = []
    for face in faces:
        p = face.representative_point()
        line = min(coast, key=lambda c: c.distance(p))
        d = line.project(line.interpolate(line.project(p)))
        a = line.interpolate(max(d - 1e-5, 0))
        b = line.interpolate(min(d + 1e-5, line.length))
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        if cross < 0:  # right of the coastline direction = water
            sea.append(extend_beyond(face, frame, SEA_PAD_DEG))
    return sea


def extend_beyond(face: Polygon, frame: Polygon, pad: float) -> Polygon:
    """Continue a face past every box side it runs along, so pitched views show no edge."""
    w, s, e, n = frame.bounds
    sides = {
        "w": (LineString([(w, s), (w, n)]), box(w - pad, s - pad, w, n + pad)),
        "e": (LineString([(e, s), (e, n)]), box(e, s - pad, e + pad, n + pad)),
        "s": (LineString([(w, s), (e, s)]), box(w - pad, s - pad, e + pad, s)),
        "n": (LineString([(w, n), (e, n)]), box(w - pad, n, e + pad, n + pad)),
    }
    out = face
    for line, band in sides.values():
        shared = face.boundary.intersection(line)
        if shared.length > 0.1 * line.length:
            out = out.union(band)
    return out if out.geom_type == "Polygon" else max(_polys(out), key=lambda g: g.area)


def build_basemap(bbox: tuple[float, float, float, float], force: bool = False) -> Path:
    """Write buildings.json and water.json for bbox (w, s, e, n); return the directory."""
    out = basemap_dir() / bbox_key(bbox)
    if not force and (out / "water.json").exists() and (out / "buildings.json").exists():
        return out
    cfg = load_settings()["buildings"]
    default_m = float(cfg["default_height_m"]["value"])
    per_level = float(cfg["metres_per_level"]["value"])
    w, s, e, n = bbox
    frame = box(w, s, e, n)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        clip = tmp / "clip.osm.pbf"
        run_cmd(
            [
                "osmium",
                "extract",
                "-b",
                f"{w},{s},{e},{n}",
                "-s",
                "smart",
                str(_pbf()),
                "-o",
                str(clip),
                "--overwrite",
            ]
        )
        feats = _export(clip, ["wr/building"], tmp / "b.geojsonseq", tmp)
        rows = []
        for f in feats:
            geom = shape(f["geometry"])
            for poly in _polys(geom.intersection(frame) if not frame.contains(geom) else geom):
                poly = poly.simplify(SIMPLIFY_DEG, preserve_topology=True)
                if poly.is_empty or poly.area <= 0:
                    continue
                h = parse_height(f.get("properties") or {}, default_m, per_level)
                rows.append((poly.area, round(h, 1), _round_ring(poly.exterior.coords)))
        rows.sort(key=lambda r: (-r[0], r[2][0]))  # largest first, deterministic tie-break
        rows = rows[: int(cfg["max_features"])]
        buildings = {
            "n": len(rows),
            "heights": [r[1] for r in rows],
            "rings": [r[2] for r in rows],
        }
        water_feats = _export(
            clip,
            [
                "nwr/natural=water,bay,coastline",
                "wr/landuse=reservoir,basin",
                "wr/waterway=riverbank,dock",
            ],
            tmp / "w.geojsonseq",
            tmp,
        )
    coast_lines: list[LineString] = []
    water_polys: list[Polygon] = []
    for f in water_feats:
        geom = shape(f["geometry"])
        props = f.get("properties") or {}
        if props.get("natural") == "coastline" and geom.geom_type in (
            "LineString",
            "MultiLineString",
        ):
            coast_lines.extend([geom] if geom.geom_type == "LineString" else list(geom.geoms))
        elif geom.geom_type in ("Polygon", "MultiPolygon"):
            water_polys.extend(_polys(geom.intersection(frame)))
    sea = sea_faces(coast_lines, frame)
    polys = []
    for poly in [*sea, *water_polys]:
        poly = poly.simplify(SIMPLIFY_DEG * 5, preserve_topology=True)
        if poly.is_empty:
            continue
        polys.append(
            [_round_ring(poly.exterior.coords), *(_round_ring(r.coords) for r in poly.interiors)]
        )
    water = {"polygons": polys, "sea_faces": len(sea), "coastlines": len(coast_lines)}
    (out / "buildings.json").write_text(json.dumps(buildings, separators=(",", ":")))
    (out / "water.json").write_text(json.dumps(water, separators=(",", ":")))
    (out / "basemap.json").write_text(
        json.dumps(
            {
                "bbox": bbox,
                "buildings": len(rows),
                "water_polygons": len(polys),
                "sea_faces": len(sea),
                "pbf": _pbf().name,
            },
            indent=1,
        )
    )
    return out


def pad_bbox(points: list[tuple[float, float]], margin: float) -> tuple[float, float, float, float]:
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons) - margin, min(lats) - margin, max(lons) + margin, max(lats) + margin)


def view_extent(lon: float, lat: float, zoom: float, width: int, height: int) -> float:
    """Half-diagonal of a top-down view in degrees (upper bound for pitched views is applied
    by the caller)."""
    deg_per_px = 360.0 / (512.0 * 2**zoom)
    return 0.5 * math.hypot(width, height) * deg_per_px


app = typer.Typer(add_completion=False)


@app.command()
def main(
    bbox: str = typer.Argument(..., help="w,s,e,n"),
    force: bool = False,
) -> None:
    """Build (or reuse) the basemap for a bounding box."""
    w, s, e, n = (float(v) for v in bbox.split(","))
    out = build_basemap((w, s, e, n), force=force)
    typer.echo((out / "basemap.json").read_text())


if __name__ == "__main__":
    app()


__all__ = ["Point", "build_basemap", "pad_bbox", "parse_height", "sea_faces", "view_extent"]
