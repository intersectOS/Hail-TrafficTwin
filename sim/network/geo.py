"""District and building GeoJSON side outputs, extracted from the clipped OSM PBF with osmium."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import voronoi_diagram

from sim.common import run_cmd

UTM_KSA_WEST = "EPSG:32637"  # UTM zone 37N covers Jeddah; used for areas only


def read_poly(path: Path) -> Polygon:
    """Read a single-ring osmium/Osmosis .poly file."""
    coords: list[tuple[float, float]] = []
    for line in Path(path).read_text().splitlines()[2:]:
        if line.strip() == "END":
            break
        lon, lat = line.split()
        coords.append((float(lon), float(lat)))
    return Polygon(coords)


def _osmium_export(pbf: Path, filters: list[str], out: Path, geometry: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        filtered = Path(tmp) / "filtered.osm.pbf"
        run_cmd(["osmium", "tags-filter", str(pbf), *filters, "-o", str(filtered), "--overwrite"])
        run_cmd(
            [
                "osmium",
                "export",
                str(filtered),
                "-f",
                "geojsonseq",
                "--geometry-types",
                geometry,
                "-a",
                "type,id",
                "-o",
                str(out),
                "--overwrite",
            ]
        )


def _read_seq(path: Path) -> list[dict[str, Any]]:
    feats = []
    with path.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if line:
                feats.append(json.loads(line))
    return feats


def write_districts(pbf: Path, poly: Path, out: Path, cfg: dict[str, Any]) -> int:
    """Districts from admin boundary polygons; Voronoi of place nodes as a fallback."""
    city = read_poly(poly)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        seq = Path(tmp) / "adm.geojsonseq"
        _osmium_export(pbf, ["r/boundary=administrative"], seq, "polygon")
        feats = [
            f
            for f in _read_seq(seq)
            if str(f["properties"].get("admin_level")) in set(cfg["admin_levels"])
        ]
        method = "osm_admin_boundaries"
        if len(feats) < 10:
            seq = Path(tmp) / "place.geojsonseq"
            vals = ",".join(cfg["fallback_place_values"])
            _osmium_export(pbf, [f"n/place={vals}"], seq, "point")
            feats = _voronoi(_read_seq(seq), city)
            method = "voronoi_of_place_nodes"
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf = gdf[gdf.intersects(city)].copy()
    gdf["geometry"] = gdf.intersection(city)

    def col(key: str) -> pd.Series:
        return gdf[key] if key in gdf else pd.Series([None] * len(gdf), index=gdf.index)

    out_gdf = gpd.GeoDataFrame(
        {
            "osm_id": col("@type").astype(str).str[0] + col("@id").astype(str),
            "name_ar": col("name:ar").fillna(col("name")),
            "name_en": col("name:en"),
            "admin_level": col("admin_level"),
            "method": method,
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    out_gdf["area_km2"] = (out_gdf.to_crs(UTM_KSA_WEST).area / 1e6).round(3)
    out_gdf = out_gdf.sort_values("osm_id").reset_index(drop=True)
    out.unlink(missing_ok=True)
    out_gdf.to_file(out, driver="GeoJSON")
    return len(out_gdf)


def _voronoi(points: list[dict[str, Any]], city: Polygon) -> list[dict[str, Any]]:
    pts = [p for p in points if p["geometry"]["type"] == "Point"]
    if not pts:
        raise RuntimeError("no district polygons and no place nodes found")
    from shapely.geometry import Point, mapping, shape

    cells = voronoi_diagram(MultiPoint([shape(p["geometry"]) for p in pts]), envelope=city)
    feats = []
    for cell in cells.geoms:
        owner = next(p for p in pts if cell.contains(Point(p["geometry"]["coordinates"])))
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(cell.intersection(city)),
                "properties": owner["properties"],
            }
        )
    return feats


def building_height(tags: dict[str, Any], heights: dict[str, Any]) -> tuple[float, str]:
    """Height in metres and how it was derived (tag, levels or default assumption)."""
    per_level = float(heights["metres_per_level"]["value"])
    raw = str(tags.get("height", "")).replace("m", "").strip()
    try:
        if raw:
            return float(raw), "height_tag"
    except ValueError:
        pass
    try:
        levels = float(str(tags.get("building:levels", "")).strip())
        if levels > 0:
            return levels * per_level, "levels_tag"
    except ValueError:
        pass
    return float(heights["default_levels"]["value"]) * per_level, "default"


def write_buildings(pbf: Path, out: Path, heights: dict[str, Any]) -> int:
    """Building footprints with a height property, streamed to a FeatureCollection."""
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        seq = Path(tmp) / "b.geojsonseq"
        _osmium_export(pbf, ["wr/building"], seq, "polygon")
        with seq.open() as src, out.open("w") as dst:
            dst.write('{"type":"FeatureCollection","features":[\n')
            for line in src:
                line = line.strip().lstrip("\x1e")
                if not line:
                    continue
                feat = json.loads(line)
                tags = feat["properties"]
                h, how = building_height(tags, heights)
                feat["properties"] = {
                    "osm_id": tags.get("@id"),
                    "building": tags.get("building"),
                    "height_m": round(h, 1),
                    "height_source": how,
                }
                dst.write(("," if count else "") + json.dumps(feat, ensure_ascii=False) + "\n")
                count += 1
            dst.write("]}\n")
    return count


def osmium_available() -> bool:
    try:
        subprocess.run(["osmium", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False
