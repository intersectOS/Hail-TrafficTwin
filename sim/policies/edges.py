"""Edge table of a SUMO network for policies: id, street name, type, lanes, speed, length,
vehicle classes (passenger on any lane, bus on lane 0) and start / middle / end coordinates
(lon, lat). Streams the .net.xml (plain or gzipped) once and caches the table as Parquet keyed by
the network content hash under `data/policies/`.

    python -m sim.policies.edges data/jeddah/jeddah.m2.net.xml
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd
import typer
from pyproj import Transformer

from sim.common import REPO_ROOT

CACHE = REPO_ROOT / "data" / "policies"
COLUMNS = ["edge_id", "name", "type", "from_node", "to_node", "lanes", "speed", "length",
           "passenger", "bus", "lon0", "lat0", "lon", "lat", "lon1", "lat1"]  # fmt: skip


def open_xml(path: Path) -> IO[bytes]:
    return gzip.open(path, "rb") if str(path).endswith(".gz") else Path(path).open("rb")


def net_hash(path: Path) -> str:
    from sim.metrics import xml_content_hash

    return xml_content_hash(Path(path))


def _allows(lane: ET.Element, vclass: str) -> bool:
    allow, disallow = lane.get("allow"), lane.get("disallow")
    if allow is not None:
        return vclass in allow.split() or allow == "all"
    return disallow is None or vclass not in disallow.split()


def parse_edges(net: Path) -> pd.DataFrame:
    rows: list[tuple] = []
    offset = (0.0, 0.0)
    proj = "!"
    current: dict[str, str] | None = None
    first: ET.Element | None = None
    lanes = 0
    passenger = bus0 = False
    with open_xml(net) as fh:
        for event, elem in ET.iterparse(fh, events=("start", "end")):
            if event == "start":
                if elem.tag == "edge":
                    current = dict(elem.attrib) if elem.get("function") != "internal" else None
                    first, lanes, passenger, bus0 = None, 0, False, False
                elif elem.tag == "location":
                    ox, oy = (float(v) for v in elem.get("netOffset", "0,0").split(","))
                    offset = (ox, oy)
                    proj = elem.get("projParameter", "!")
                continue
            if elem.tag == "lane" and current is not None:
                lanes += 1
                passenger = passenger or _allows(elem, "passenger")
                if first is None:
                    first = elem
                    bus0 = _allows(elem, "bus")
                continue
            if elem.tag == "edge":
                if current is not None and first is not None:
                    shape = current.get("shape") or first.get("shape", "")
                    pts = [tuple(map(float, p.split(",")[:2])) for p in shape.split()]
                    mid = pts[len(pts) // 2] if len(pts) > 2 else (
                        (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2
                    )  # fmt: skip
                    rows.append((
                        current["id"], current.get("name", ""), current.get("type", ""),
                        current.get("from", ""), current.get("to", ""), lanes,
                        float(first.get("speed", 0.0)), float(first.get("length", 0.0)),
                        passenger, bus0, *pts[0], *mid, *pts[-1],
                    ))  # fmt: skip
                current, first = None, None
                elem.clear()
            elif elem.tag in ("junction", "connection", "tlLogic", "roundabout"):
                elem.clear()
    cols = [*COLUMNS[:10], "x0", "y0", "x", "y", "x1", "y1"]
    df = pd.DataFrame(rows, columns=cols)
    if proj == "!":
        raise ValueError(f"{net}: network has no geo projection")
    to_geo = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    for sfx in ("0", "", "1"):
        x = df[f"x{sfx}"].to_numpy() - offset[0]
        y = df[f"y{sfx}"].to_numpy() - offset[1]
        df[f"lon{sfx}"], df[f"lat{sfx}"] = to_geo.transform(x, y)
    return df[COLUMNS]


def load_edges(net: Path, cache: Path | None = None) -> pd.DataFrame:
    """Cached edge table for `net`."""
    cache = Path(cache or CACHE)
    path = cache / f"edges-{net_hash(net)}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = parse_edges(net)
    cache.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def utm_xy(lons: np.ndarray, lats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Metric coordinates (UTM 37N covers Jeddah) for distance checks."""
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32637", always_xy=True)
    x, y = tf.transform(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
    return np.asarray(x), np.asarray(y)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(net: Path) -> None:
    df = load_edges(net)
    typer.echo(f"{len(df):,} edges, {df['name'].ne('').mean():.1%} named")


if __name__ == "__main__":
    app()
