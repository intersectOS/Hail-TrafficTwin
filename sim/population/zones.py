"""Traffic analysis zones (TAZ) for Jeddah: districts with residents, jobs, seats and edges.

Inputs: OSM districts (`data/jeddah/districts.geojson`), building footprints, OSM POIs and
landuse (extracted from the clipped PBF with osmium) and the city network. Outputs, under
`data/population/zones/`:

- `zones.parquet`: one row per zone with population, jobs per sector, attractions, seats, centroid
- `zone_edges.parquet`: candidate origin/destination edges per zone (main SCC only) with weights
- `zones.geojson`: polygons with the zone table (viewer, plots)
- `zones.json`: provenance (input hashes, config hash, zones hash)

    python -m sim.population.zones                     # city (uses data/jeddah/*)
    python -m sim.population.zones --net data/demo/demo.net.xml --districts my.geojson ...
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
import typer
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, content_hash, file_hash, load_yaml
from sim.network.netinfo import _location, edge_graph, strongly_connected

ZONES_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "zones.yaml"
LOCAL_UTM = "EPSG:32637"  # UTM 37N covers Jeddah: metric areas and distances


def zones_config(path: Path = ZONES_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


@dataclass
class ZoneInputs:
    districts: Path
    net: Path
    buildings: Path | None = None
    pois: Path | None = None  # GeoJSONSeq from `extract_pois`, or None


# ---------------------------------------------------------------------------- geometry helpers


def _to_utm() -> Transformer:
    return Transformer.from_crs("EPSG:4326", LOCAL_UTM, always_xy=True)


def _area_m2(geom: BaseGeometry, tf: Transformer) -> float:
    def project(coords: np.ndarray) -> np.ndarray:
        return np.column_stack(tf.transform(coords[:, 0], coords[:, 1]))

    return float(shapely.transform(geom, project).area)


def load_districts(path: Path, cfg: dict[str, Any]) -> pd.DataFrame:
    data = json.loads(Path(path).read_text())
    excluded = set(cfg.get("non_residential_districts", {}).get("names", []))
    coast = set(cfg.get("coast_districts", {}).get("names", []))
    tf = _to_utm()
    rows = []
    for i, feat in enumerate(data["features"]):
        props = feat.get("properties", {})
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        name_en = props.get("name_en") or props.get("name") or f"zone {i}"
        rows.append(
            {
                "zone_id": i,
                "osm_id": str(props.get("osm_id", "")),
                "name_en": name_en,
                "name_ar": props.get("name_ar", ""),
                "geometry": geom,
                "area_km2": _area_m2(geom, tf) / 1e6,
                "residential": name_en not in excluded,
                "coast": name_en in coast,
            }
        )
    if not rows:
        raise ValueError(f"{path}: no districts")
    return pd.DataFrame(rows)


class ZoneLocator:
    """Point-in-polygon lookup (first match wins; nearest zone within `snap_m` otherwise)."""

    def __init__(self, geoms: list[BaseGeometry], snap_deg: float = 0.01) -> None:
        self.geoms = geoms
        self.tree = STRtree(geoms)
        self.snap_deg = snap_deg

    def locate(self, lons: np.ndarray, lats: np.ndarray, snap: bool = False) -> np.ndarray:
        points = [Point(x, y) for x, y in zip(lons, lats, strict=True)]
        out = np.full(len(points), -1, dtype=np.int64)
        if not points:
            return out
        pi, gi = self.tree.query(points, predicate="within")
        # first polygon per point (lowest zone id) for overlapping districts
        order = np.lexsort((gi, pi))
        pi, gi = pi[order], gi[order]
        first = np.unique(pi, return_index=True)[1]
        out[pi[first]] = gi[first]
        if snap:
            missing = np.flatnonzero(out < 0)
            if len(missing):
                idx, dist = self.tree.query_nearest(
                    [points[k] for k in missing], return_distance=True, all_matches=False
                )
                near_pts, near_geoms = idx
                ok = dist <= self.snap_deg
                out[missing[near_pts[ok]]] = near_geoms[ok]
        return out


# ---------------------------------------------------------------------------- network edges


def network_edges(net: Path, vclass: str = "passenger") -> pd.DataFrame:
    """Non-internal edges with type, length, speed and midpoint lon/lat, plus main-SCC flag."""
    dx, dy, proj = _location(net)
    rows: list[tuple[str, str, float, float, float, float, int]] = []
    current: dict[str, str] | None = None
    lane_shape: str | None = None
    length = speed = 0.0
    lanes = 0
    for event, elem in ET.iterparse(net, events=("start", "end")):
        if event == "start":
            if elem.tag == "edge":
                current = dict(elem.attrib) if elem.get("function") != "internal" else None
                lane_shape = None
                lanes = 0
            continue
        if elem.tag == "lane" and current is not None:
            lanes += 1
            if lane_shape is None:
                lane_shape = elem.get("shape", "")
                length = float(elem.get("length", 0.0))
                speed = float(elem.get("speed", 0.0))
        elif elem.tag == "edge":
            if current is not None and lane_shape:
                pts = [tuple(map(float, p.split(",")[:2])) for p in lane_shape.split()]
                mx, my = pts[len(pts) // 2] if len(pts) > 2 else _mid(pts)
                rows.append(
                    (current["id"], current.get("type", ""), length, speed, mx - dx, my - dy, lanes)
                )
            current = None
            elem.clear()
        elif elem.tag in ("junction", "connection", "tlLogic"):
            elem.clear()
    df = pd.DataFrame(rows, columns=["edge_id", "type", "length", "speed", "x", "y", "lanes"])
    if proj == "!":
        raise ValueError(f"{net}: network has no geo projection")
    to_geo = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    df["lon"], df["lat"] = to_geo.transform(df["x"].to_numpy(), df["y"].to_numpy())
    graph = edge_graph(net, vclass)
    comps = strongly_connected(graph)
    main = set(comps[0]) if comps else set()
    df["main_scc"] = df["edge_id"].isin(main)
    return df.drop(columns=["x", "y"])


def _mid(pts: list[tuple[float, ...]]) -> tuple[float, float]:
    (x0, y0), (x1, y1) = pts[0][:2], pts[-1][:2]
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


# ---------------------------------------------------------------------------- OSM POIs


def extract_pois(osm_pbf: Path, out: Path, cfg: dict[str, Any]) -> Path:
    """osmium tags-filter + export to GeoJSONSeq (points and polygons) for the configured keys."""
    keys = sorted({k for spec in cfg["osm_categories"].values() for k in spec} | {"landuse"})
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        filtered = Path(tmp) / "pois.osm.pbf"
        subprocess.run(
            ["osmium", "tags-filter", "-O", str(osm_pbf), *[f"nwr/{k}" for k in keys], "-o"]
            + [str(filtered)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["osmium", "export", "-O", "-f", "geojsonseq", "--geometry-types=point,polygon"]
            + [str(filtered), "-o", str(out)],
            check=True,
            capture_output=True,
        )
    return out


def _matches(tags: dict[str, str], spec: dict[str, Any]) -> bool:
    for key, allowed in spec.items():
        value = tags.get(key)
        if value is None:
            continue
        if allowed == "*" or value in allowed:
            return True
    return False


def iter_geojsonseq(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if line:
                yield json.loads(line)


def classify_pois(
    features: Iterable[dict[str, Any]], cfg: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split OSM features into POI points (category, lon, lat) and landuse polygons."""
    tf = _to_utm()
    pois: list[tuple[str, float, float, float]] = []
    landuse: list[tuple[str, float, float, float]] = []
    lu_map = {v: cat for cat, vals in cfg["landuse_categories"].items() for v in vals}
    for feat in features:
        tags = feat.get("properties") or {}
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        pt = geom if geom.geom_type == "Point" else geom.representative_point()
        area = 0.0 if geom.geom_type == "Point" else _area_m2(geom, tf)
        lu = lu_map.get(tags.get("landuse", ""))
        if lu and area > 0:
            landuse.append((lu, pt.x, pt.y, area))
        for cat, spec in cfg["osm_categories"].items():
            if _matches(tags, spec):
                pois.append((cat, pt.x, pt.y, area))
    cols = ["category", "lon", "lat", "area_m2"]
    return pd.DataFrame(pois, columns=cols), pd.DataFrame(landuse, columns=cols)


# ---------------------------------------------------------------------------- buildings


def residential_footprints(path: Path, cfg: dict[str, Any]) -> pd.DataFrame:
    """Representative point and weighted residential footprint area of each building."""
    weights = {
        k: float(v) for k, v in cfg["residential_building_tags"].items() if k != "assumption"
    }
    data = json.loads(Path(path).read_text())
    tf = _to_utm()
    rows = []
    for feat in data["features"]:
        w = weights.get(str((feat.get("properties") or {}).get("building")), 0.0)
        if w <= 0:
            continue
        geom = shape(feat["geometry"])
        pt = geom.representative_point()
        rows.append((pt.x, pt.y, w * _area_m2(geom, tf)))
    return pd.DataFrame(rows, columns=["lon", "lat", "area_m2"])


# ---------------------------------------------------------------------------- build


def _share(values: pd.Series) -> pd.Series:
    total = float(values.sum())
    return values / total if total > 0 else values * 0.0


def largest_remainder(weights: np.ndarray, total: int) -> np.ndarray:
    """Integer allocation of `total` proportional to `weights` (deterministic)."""
    w = np.asarray(weights, dtype=float)
    if w.sum() <= 0:
        return np.zeros(len(w), dtype=np.int64)
    exact = w / w.sum() * total
    base = np.floor(exact).astype(np.int64)
    rest = total - int(base.sum())
    order = np.lexsort((np.arange(len(w)), -(exact - base)))
    base[order[:rest]] += 1
    return base


def build_zones(inputs: ZoneInputs, cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    zones = load_districts(inputs.districts, cfg)
    locator = ZoneLocator(list(zones["geometry"]))
    n = len(zones)

    def per_zone(df: pd.DataFrame, value: str | None = None) -> np.ndarray:
        if df.empty:
            return np.zeros(n)
        zid = locator.locate(df["lon"].to_numpy(), df["lat"].to_numpy())
        ok = zid >= 0
        vals = np.ones(int(ok.sum())) if value is None else df[value].to_numpy()[ok]
        return np.bincount(zid[ok], weights=vals, minlength=n)

    # edges (main SCC only), assigned to zones; edges outside every district snap to the nearest
    edges = network_edges(inputs.net)
    edges = edges[edges["main_scc"] & (edges["length"] >= cfg["edges"]["min_length_m"])].copy()
    edges["zone_id"] = locator.locate(edges["lon"].to_numpy(), edges["lat"].to_numpy(), snap=True)
    edges = edges[edges["zone_id"] >= 0]
    home_types = set(cfg["edges"]["home_types"])
    excl = set(cfg["edges"]["activity_exclude_types"])
    is_local = edges["type"].isin(home_types)
    edges["home_w"] = np.where(is_local, edges["length"], 0.0)
    edges["act_w"] = np.where(edges["type"].isin(excl), 0.0, edges["length"])
    res_km = np.bincount(edges["zone_id"], weights=edges["home_w"], minlength=n) / 1000.0
    zones["edges"] = np.bincount(edges["zone_id"], minlength=n)
    if cfg["edges"].get("fallback_to_all", True):
        # zones with no local street still need home edges: fall back to activity edges
        no_home = np.bincount(edges["zone_id"], weights=edges["home_w"], minlength=n) <= 0
        fb = edges["zone_id"].isin(np.flatnonzero(no_home))
        edges.loc[fb, "home_w"] = edges.loc[fb, "act_w"]
    zones["residential_street_km"] = res_km

    # residential proxies
    bld = residential_footprints(inputs.buildings, cfg) if inputs.buildings else pd.DataFrame()
    zones["res_building_m2"] = per_zone(bld, "area_m2") if not bld.empty else 0.0
    pois, landuse = (
        classify_pois(iter_geojsonseq(inputs.pois), cfg)
        if inputs.pois and Path(inputs.pois).exists()
        else (pd.DataFrame(columns=["category", "lon", "lat", "area_m2"]),) * 2
    )
    for cat in cfg["landuse_categories"]:
        part = landuse[landuse["category"] == cat]
        zones[f"{cat}_area_m2"] = per_zone(part, "area_m2") if not part.empty else 0.0
    for cat in cfg["osm_categories"]:
        part = pois[pois["category"] == cat]
        zones[f"poi_{cat}"] = per_zone(part) if not part.empty else 0.0
    university_area = per_zone(pois[pois["category"] == "university"], "area_m2")

    # residents: blended proxy shares, zero in non-residential districts
    rw = cfg["residential_weights"]
    weight = (
        rw["building_footprint_area"] * _share(zones["res_building_m2"])
        + rw["residential_street_km"] * _share(zones["residential_street_km"])
        + rw["residential_landuse_area"] * _share(zones["residential_area_m2"])
    ) * zones["residential"].astype(float)
    # zones without candidate edges can neither house nor attract anyone
    act_by_zone = np.bincount(edges["zone_id"], weights=edges["act_w"], minlength=n)
    home_by_zone = np.bincount(edges["zone_id"], weights=edges["home_w"], minlength=n)
    reachable = act_by_zone > 0
    zones["res_weight"] = _share(weight * (home_by_zone > 0))
    total = int(cfg["control_total"]["value"])
    zones["population"] = largest_remainder(zones["res_weight"].to_numpy(), total)

    seats = cfg["seats"]
    zones["school_seats"] = zones["poi_school"] * float(seats["school_per_object"])
    uni = np.maximum(
        university_area / 1e6 * float(seats["university_per_area_km2"]),
        zones["poi_university"] * float(seats["university_min_seats"]),
    )
    zones["university_seats"] = uni

    # attractions per purpose/sector (shares of proxies, summed with configured coefficients)
    proxies = {f"{c}": _share(zones[f"poi_{c}"]) for c in cfg["osm_categories"]}
    proxies["commercial_area"] = _share(zones["commercial_area_m2"])
    proxies["industrial_area"] = _share(zones["industrial_area_m2"])
    proxies["population"] = _share(zones["population"].astype(float))
    proxies["coast"] = _share(zones["coast"].astype(float))
    proxies["school_seats"] = _share(zones["school_seats"])
    proxies["university_seats"] = _share(zones["university_seats"])
    for purpose, coefs in cfg["attractions"].items():
        if purpose in ("assumption", "source"):
            continue
        att = sum(float(c) * proxies[p] for p, c in coefs.items())
        zones[f"att_{purpose}"] = _share(att * reachable)

    centroids = [g.representative_point() for g in zones["geometry"]]
    zones["lon"] = [p.x for p in centroids]
    zones["lat"] = [p.y for p in centroids]
    zone_edges = edges[["edge_id", "zone_id", "type", "length", "speed", "lon", "lat"]].copy()
    zone_edges["near_bus_stop"] = near_points(
        edges["lon"].to_numpy(),
        edges["lat"].to_numpy(),
        pois.loc[pois["category"] == "bus_stop", ["lon", "lat"]].to_numpy(dtype=float),
        float(cfg["bus_catchment"]["radius_m"]),
    )
    zone_edges["home_w"] = edges["home_w"].to_numpy()
    zone_edges["act_w"] = edges["act_w"].to_numpy()
    zone_edges = zone_edges.sort_values(["zone_id", "edge_id"]).reset_index(drop=True)
    return zones, zone_edges


def near_points(lons: np.ndarray, lats: np.ndarray, pts: np.ndarray, radius_m: float) -> np.ndarray:
    """True where (lon, lat) lies within `radius_m` of any point in `pts` (lon, lat rows)."""
    out = np.zeros(len(lons), dtype=bool)
    if len(pts) == 0 or len(lons) == 0:
        return out
    tf = _to_utm()
    x, y = tf.transform(lons, lats)
    px, py = tf.transform(pts[:, 0], pts[:, 1])
    tree = STRtree([Point(a, b) for a, b in zip(px, py, strict=True)])
    idx = tree.query(
        [Point(a, b) for a, b in zip(x, y, strict=True)], predicate="dwithin", distance=radius_m
    )
    out[np.unique(idx[0])] = True
    return out


def zone_distances(zones: pd.DataFrame, detour: float) -> np.ndarray:
    """Zone-to-zone road distance estimate (m): centroid distance x detour; intrazonal = r/2."""
    tf = _to_utm()
    x, y = tf.transform(zones["lon"].to_numpy(), zones["lat"].to_numpy())
    d = np.hypot(x[:, None] - x[None, :], y[:, None] - y[None, :]) * detour
    intra = np.sqrt(zones["area_km2"].to_numpy() * 1e6 / math.pi) * 0.5 * detour
    np.fill_diagonal(d, np.maximum(intra, 300.0))
    return d


def write_zones(zones: pd.DataFrame, zone_edges: pd.DataFrame, out_dir: Path, meta: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    table = zones.drop(columns=["geometry"])
    table.to_parquet(out_dir / "zones.parquet", index=False)
    zone_edges.to_parquet(out_dir / "zone_edges.parquet", index=False)
    feats = []
    for row, geom in zip(table.to_dict("records"), zones["geometry"], strict=True):
        props = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}
        feats.append({"type": "Feature", "geometry": geom.__geo_interface__, "properties": props})
    (out_dir / "zones.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, default=_np_default)
    )
    h = pd.util.hash_pandas_object(table.round(9), index=False).to_numpy().tobytes()
    h += pd.util.hash_pandas_object(zone_edges.round(9), index=False).to_numpy().tobytes()
    import hashlib

    meta = {**meta, "zones_hash": hashlib.sha256(h).hexdigest()[:16], "label": SYNTHETIC_LABEL}
    meta["zones"] = len(table)
    meta["population"] = int(table["population"].sum())
    meta["zone_edges"] = len(zone_edges)
    (out_dir / "zones.json").write_text(json.dumps(meta, indent=2, default=_np_default))
    return meta


def _np_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def load_zones(zone_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    zone_dir = Path(zone_dir)
    meta = json.loads((zone_dir / "zones.json").read_text())
    return (
        pd.read_parquet(zone_dir / "zones.parquet"),
        pd.read_parquet(zone_dir / "zone_edges.parquet"),
        meta,
    )


def default_zone_dir() -> Path:
    return REPO_ROOT / zones_config()["out_dir"]


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    districts: Path | None = typer.Option(None),
    net: Path | None = typer.Option(None),
    buildings: Path | None = typer.Option(None),
    osm_pbf: Path | None = typer.Option(None, help="clipped PBF for POIs/landuse (osmium)"),
    pois: Path | None = typer.Option(None, help="pre-extracted POI GeoJSONSeq (skips osmium)"),
    out_dir: Path | None = typer.Option(None),
    config: Path = typer.Option(ZONES_CONFIG),
) -> None:
    cfg = zones_config(config)
    inp = cfg["inputs"]
    districts = districts or REPO_ROOT / inp["districts"]
    net = net or REPO_ROOT / inp["net"]
    buildings = buildings or REPO_ROOT / inp["buildings"]
    out_dir = out_dir or REPO_ROOT / cfg["out_dir"]
    if pois is None:
        pbf = osm_pbf or REPO_ROOT / inp["osm_pbf"]
        pois = out_dir / "osm_pois.geojsonseq"
        if pbf.exists() and not pois.exists():
            typer.echo(f"extracting POIs from {pbf} ...")
            extract_pois(pbf, pois, cfg)
    zones, zone_edges = build_zones(
        ZoneInputs(
            districts=districts,
            net=net,
            buildings=buildings if buildings.exists() else None,
            pois=pois,
        ),
        cfg,
    )
    meta = {
        "config_hash": config_hash(cfg),
        "inputs": {
            "districts": file_hash(districts),
            "net": content_hash(net),
            "buildings": file_hash(buildings) if buildings.exists() else None,
            "pois": file_hash(pois) if pois and pois.exists() else None,
        },
    }
    meta = write_zones(zones, zone_edges, out_dir, meta)
    typer.echo(
        f"{meta['zones']} zones, population {meta['population']:,}, "
        f"{meta['zone_edges']:,} candidate edges -> {out_dir} (zones_hash {meta['zones_hash']})"
    )


if __name__ == "__main__":
    app()
