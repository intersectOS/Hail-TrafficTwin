"""Data for the instant what-if page (site/whatif.html): the road graph and one hour of routes.

From the Tier A network and the latest weekday baseline run (`routes.rou.xml.gz`), writes to <out>/:

  graph.json   counts, the drawing frame, road names, class names, the sample weight
  graph.bin    TTG1, little endian, per edge (n): from-node u32, length f32, speed f32, lanes u8,
               class u8, tls u8, pad u8, name u16 (+2 pad); then successor offsets u32[n + 1] and
               successor edge ids u32[m] (turns allowed for passenger cars); then geometry offsets
               u32[n + 1] and points u16[2 * p] in a 0..65535 frame
  h<HH>.bin    TTR1: vehicles departing in hour HH: n u32, then per vehicle depart-in-hour u16
               (seconds), route length u16, route edge indices u16/u32 (by edge count)

The page reroutes the vehicles whose routes use a closed or narrowed street and recomputes link
travel times with a volume-delay function; nothing here is behavioural beyond what the baseline
routes already are. Synthetic demand, uncalibrated.

    python -m scripts.hail.whatif_data --net data/hail/hail.v2.net.xml --out _site/data/whatif
"""

from __future__ import annotations

import gzip
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import sumolib
import typer

from sim.common import REPO_ROOT

CLASSES = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "other",
]
app = typer.Typer(add_completion=False, help=__doc__)


def _cls(t: str) -> int:
    t = t.replace("highway.", "").replace("_link", "")
    return CLASSES.index(t) if t in CLASSES else len(CLASSES) - 1


def latest_baseline(runs: Path) -> Path:
    """The city weekday baseline (no policy) with routes; the largest one when several qualify."""
    c = [p.parent for p in runs.glob("baseline-weekday-*/routes.rou.xml.gz")]
    if not c:
        raise typer.BadParameter(f"no weekday baseline with routes under {runs}")

    def score(d: Path) -> tuple[int, int]:
        m = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        city = int(
            "demo" not in str(m.get("network", ""))
            and not m.get("policy")
            and not m.get("policies")
        )
        return city, (d / "routes.rou.xml.gz").stat().st_size

    return max(c, key=score)


@app.command()
def main(
    net_file: Path = typer.Option(REPO_ROOT / "data" / "hail" / "hail.v2.net.xml", "--net"),
    runs: Path = typer.Option(REPO_ROOT / "runs"),
    out: Path = typer.Option(...),
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    net = sumolib.net.readNet(str(net_file), withInternal=False)
    edges = [e for e in net.getEdges() if e.allows("passenger") and e.getFunction() != "internal"]
    idx = {e.getID(): i for i, e in enumerate(edges)}
    nodes: dict[str, int] = {}
    names: dict[str, int] = {"": 0}
    # drawing frame: lon/lat of every point, scaled to 0..65535 over the larger span
    shapes = []
    for e in edges:
        shapes.append(np.array([net.convertXY2LonLat(x, y) for x, y in e.getShape()]))
    allp = np.vstack(shapes)
    w, s = allp.min(axis=0)
    ea, n = allp.max(axis=0)
    span = float(max(ea - w, n - s))
    head = bytearray()
    succ_off = [0]
    succ: list[int] = []
    geo_off = [0]
    geo: list[int] = []
    for i, e in enumerate(edges):
        fn = e.getFromNode().getID()
        nodes.setdefault(fn, len(nodes))
        nm = e.getName() or ""
        names.setdefault(nm, len(names))
        tls = 1 if e.getToNode().getType() == "traffic_light" else 0
        head += struct.pack(
            "<IffBBBBHxx",
            nodes[fn],
            e.getLength(),
            e.getSpeed(),
            min(e.getLaneNumber(), 255),
            _cls(e.getType()),
            tls,
            0,
            names[nm],
        )
        nxt = sorted(
            {
                idx[o.getID()]
                for o in e.getOutgoing()
                if o.getID() in idx
                and any(c.getToLane().allows("passenger") for c in e.getOutgoing()[o])
            }
        )
        succ.extend(nxt)
        succ_off.append(len(succ))
        q = np.rint(
            np.column_stack(
                ((shapes[i][:, 0] - w) / span * 65535, (n - shapes[i][:, 1]) / span * 65535)
            )
        )
        q = np.clip(q, 0, 65535).astype(int)
        keep = [0] + [
            k
            for k in range(1, len(q))
            if abs(q[k][0] - q[k - 1][0]) + abs(q[k][1] - q[k - 1][1]) > 40 or k == len(q) - 1
        ]
        for k in keep:
            geo.extend((int(q[k][0]), int(q[k][1])))
        geo_off.append(len(geo) // 2)
    blob = (
        b"TTG1"
        + struct.pack("<II", len(edges), len(succ))
        + bytes(head)
        + np.array(succ_off, "<u4").tobytes()
        + np.array(succ, "<u4").tobytes()
        + np.array(geo_off, "<u4").tobytes()
        + np.array(geo, "<u2").tobytes()
    )
    (out / "graph.bin").write_bytes(blob)

    base = latest_baseline(runs)
    meta = json.loads((base / "meta.json").read_text())
    sample = float(meta.get("sample") or meta.get("config", {}).get("sample") or 1.0)
    per_hour: dict[int, list[tuple[int, list[int]]]] = {}
    with gzip.open(base / "routes.rou.xml.gz", "rb") as fh:
        for _ev, el in ET.iterparse(fh, events=("end",)):
            if el.tag != "vehicle":
                continue
            dep = float(el.get("depart", "0"))
            r = el.find("route")
            if r is None:
                rd = el.find("routeDistribution")
                r = rd.findall("route")[-1] if rd is not None else None
            if r is not None:
                ids = [idx[x] for x in r.get("edges", "").split() if x in idx]
                if len(ids) >= 2:
                    h = int(dep // 3600) % 24
                    per_hour.setdefault(h, []).append((int(dep % 3600), ids))
            el.clear()
    wide = len(edges) > 65535
    counts = {}
    for h, vs in per_hour.items():
        parts = [struct.pack("<I", len(vs))]
        for d, ids in vs:
            parts.append(struct.pack("<HH", d, len(ids)))
            parts.append(np.array(ids, "<u4" if wide else "<u2").tobytes())
        (out / f"h{h:02d}.bin").write_bytes(
            b"TTR1" + struct.pack("<B", 4 if wide else 2) + b"\0\0\0" + b"".join(parts)
        )
        counts[h] = len(vs)
    (out / "graph.json").write_text(
        json.dumps(
            {
                "label": "synthetic demand, uncalibrated",
                "baseline": base.name,
                "sample": sample,
                "weight": 1.0 / sample,
                "edges": len(edges),
                "succ": len(succ),
                "bbox": [float(w), float(s), float(ea), float(n)],
                "span": span,
                "classes": CLASSES,
                "names": sorted(names, key=names.get),
                "vehicles_per_hour": counts,
            },
            ensure_ascii=False,
        )
    )
    size = sum(p.stat().st_size for p in out.iterdir())
    typer.echo(
        f"{len(edges)} edges, {len(succ)} turns, "
        f"{sum(counts.values())} vehicles in {len(counts)} hours, "
        f"sample {sample}, {size / 1e6:.1f} MB -> {out}"
    )


if __name__ == "__main__":
    app()
