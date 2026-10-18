"""Teleport hotspots from a SUMO log: where vehicles teleport, on what kind of road, and when.

Streams the log (city logs are ~40 MB) and the network (no sumolib load). Internal junction edges
(`:<junction>_<n>`) are attributed to their junction; normal edges to the edge.

    python -m sim.network.teleports hotspots runs/<run>/sumo.log --net data/jeddah/jeddah.v2.net.xml
    python -m sim.network.teleports hotspots runs/<run>/sumo.log --net ... --json out.json --top 10
"""

from __future__ import annotations

import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
from pyproj import Transformer

from sim.network.netinfo import _location

TELEPORT_RE = re.compile(
    r"Teleporting vehicle '[^']+'; (?P<reason>[^,]+), (?:from )?(?:edge|lane) "
    r"'(?P<where>[^']+)'(?::\d+)?, time=(?P<time>[0-9]+(?:\.[0-9]+)?)"
)

LENGTH_EDGES = (25, 50, 75, 100, 200, 500)
LENGTH_BINS = (
    [f"<{LENGTH_EDGES[0]}"]
    + [f"{a}-{b}" for a, b in zip(LENGTH_EDGES, LENGTH_EDGES[1:], strict=False)]
    + [f">={LENGTH_EDGES[-1]}"]
)


def _length_bin(length: float) -> str:
    for i, edge in enumerate(LENGTH_EDGES):
        if length < edge:
            return LENGTH_BINS[i]
    return LENGTH_BINS[-1]


LonLat = Callable[[float, float], "tuple[float, float] | None"]


@dataclass
class EdgeInfo:
    type: str = ""
    lanes: int = 0
    speed: float = 0.0
    length: float = 0.0
    name: str = ""
    to_node: str = ""


@dataclass
class Location:
    key: str
    kind: str  # "edge" or "junction"
    count: int = 0
    hours: Counter[int] = field(default_factory=Counter)


def _open(path: Path) -> Any:
    return gzip.open(path, "rt") if path.suffix == ".gz" else path.open()


def parse_log(log: Path) -> tuple[dict[str, Location], Counter[str], Counter[int], int]:
    """Teleports per location (edge, or junction for internal edges), per reason, per hour."""
    locs: dict[str, Location] = {}
    reasons: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    total = 0
    with _open(log) as fh:
        for line in fh:
            if "Teleporting vehicle" not in line:
                continue
            m = TELEPORT_RE.search(line)
            if not m:
                continue
            total += 1
            where = m["where"]
            if where.startswith(":"):
                # internal edge ':<junction>_<index>' belongs to the junction
                key, kind = where[1:].rsplit("_", 1)[0], "junction"
            else:
                key, kind = where, "edge"
            hour = int(float(m["time"]) // 3600)
            loc = locs.setdefault(f"{kind}:{key}", Location(key=key, kind=kind))
            loc.count += 1
            loc.hours[hour] += 1
            reasons[m["reason"].strip()] += 1
            hours[hour] += 1
    return locs, reasons, hours, total


def net_index(
    net: Path, edges: set[str], junctions: set[str]
) -> tuple[dict[str, EdgeInfo], dict[str, tuple[float, float, str]]]:
    """Attributes of the wanted edges; position (net x, y) and type of the wanted junctions."""
    info: dict[str, EdgeInfo] = {}
    jpos: dict[str, tuple[float, float, str]] = {}
    cur: EdgeInfo | None = None
    for event, elem in ET.iterparse(net, events=("start", "end")):
        tag = elem.tag
        if event == "start":
            if tag == "edge" and elem.get("id") in edges:
                cur = EdgeInfo(
                    type=elem.get("type", ""), name=elem.get("name", ""), to_node=elem.get("to", "")
                )
                info[elem.get("id", "")] = cur
            continue
        if tag == "lane" and cur is not None:
            cur.lanes += 1
            cur.speed = float(elem.get("speed", 0.0))
            cur.length = float(elem.get("length", 0.0))
        elif tag == "edge":
            cur = None
            elem.clear()
        elif tag == "junction":
            jid = elem.get("id", "")
            if jid in junctions:
                jpos[jid] = (float(elem.get("x", 0)), float(elem.get("y", 0)), elem.get("type", ""))
            elem.clear()
    return info, jpos


def _to_lonlat(net: Path) -> LonLat:
    dx, dy, proj = _location(net)
    if proj == "!":
        return lambda x, y: None
    tf = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)

    def conv(x: float, y: float) -> tuple[float, float] | None:
        lon, lat = tf.transform(x - dx, y - dy)
        return round(lon, 5), round(lat, 5)

    return conv


def hotspots(log: Path, net: Path | None, top: int = 10) -> dict[str, Any]:
    locs, reasons, hours, total = parse_log(log)
    ranked = sorted(locs.values(), key=lambda loc: (-loc.count, loc.key))
    head = ranked[:top]
    info: dict[str, EdgeInfo] = {}
    jpos: dict[str, tuple[float, float, str]] = {}
    lonlat: LonLat = lambda x, y: None  # noqa: E731
    if net is not None:
        info, _ = net_index(net, {loc.key for loc in ranked if loc.kind == "edge"}, set())
        wanted = {loc.key for loc in head if loc.kind == "junction"}
        wanted |= {info[loc.key].to_node for loc in head if loc.key in info}
        _, jpos = net_index(net, set(), wanted)
        lonlat = _to_lonlat(net)
    on_internal = sum(loc.count for loc in ranked if loc.kind == "junction")
    by_type: Counter[str] = Counter()
    by_lanes: Counter[int] = Counter()
    by_length: Counter[str] = Counter()
    ramps = 0
    for loc in ranked:
        if loc.kind == "edge":
            e = info.get(loc.key)
            by_type[e.type if e else "?"] += loc.count
            by_lanes[e.lanes if e else -1] += loc.count
            by_length[_length_bin(e.length) if e else "?"] += loc.count
            if "-Added" in loc.key and "RampEdge" in loc.key:
                ramps += loc.count
        else:
            by_type["(junction internal)"] += loc.count
    rows = []
    for loc in head:
        row: dict[str, Any] = {
            "where": loc.key,
            "kind": loc.kind,
            "teleports": loc.count,
            "share": round(loc.count / total, 4) if total else 0.0,
            "peak_hours": [h for h, _ in loc.hours.most_common(3)],
        }
        pos = jpos.get(loc.key)
        if loc.kind == "edge" and loc.key in info:
            e = info[loc.key]
            row.update(
                type=e.type,
                lanes=e.lanes,
                speed_kmh=round(e.speed * 3.6),
                length_m=round(e.length),
                name=e.name,
                to_junction=e.to_node,
            )
            pos = jpos.get(e.to_node)
        elif pos:
            row["junction_type"] = pos[2]
        if pos:
            row["lonlat"] = lonlat(pos[0], pos[1])
        rows.append(row)

    def share(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    return {
        "log": str(log),
        "teleports": total,
        "locations": len(locs),
        "top_n_share": share(sum(r["teleports"] for r in rows)),
        "on_junction_internal_share": share(on_internal),
        "on_guessed_ramps_share": share(ramps),
        "reasons": dict(reasons.most_common()),
        "by_hour": {h: hours[h] for h in sorted(hours)},
        "by_type": dict(by_type.most_common(15)),
        "by_lanes": {str(k): v for k, v in sorted(by_lanes.items())},
        "by_length_m": {k: by_length[k] for k in [*LENGTH_BINS, "?"] if by_length[k]},
        "top": rows,
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.callback()
def _cli() -> None:
    """Teleport analysis."""


@app.command("hotspots")
def hotspots_cmd(
    log: Path,
    net: Path | None = typer.Option(None, help="network for edge types, lanes and positions"),
    top: int = typer.Option(10),
    json_out: Path | None = typer.Option(None, "--json"),
) -> None:
    res = hotspots(log, net, top)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "top"}, indent=1))
    for r in res["top"]:
        typer.echo(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    app()
