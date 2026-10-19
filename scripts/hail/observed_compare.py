"""TomTom typical travel times next to the model, per corridor and hour (data/observed.json).

Inputs: data/observed/corridors.json and tomtom_traveltimes.json (scripts/hail/tomtom_corridors.py),
and the latest weekday Tier A baseline (runs/baseline-weekday-*/edgedata.parquet, after
`python -m api.ingest`). For each corridor and hour: TomTom's historical travel time and its
no-traffic time, and the model's mean edge traversal time summed over the corridor (edges with no
vehicle in that hour count at free flow). The congestion index is travel time / no-traffic time.
Corridor geometry is written in the same 0..10000 frame as data/roads.json, so the page can draw it.

    python -m scripts.hail.observed_compare --out _site/data/observed.json

Data: © TomTom (historical traffic); model: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import typer

from sim.common import REPO_ROOT

OBS = REPO_ROOT / "data" / "observed"
app = typer.Typer(add_completion=False, help=__doc__)


def model_hourly(run: Path, edges: set[str]) -> dict[tuple[str, int], float]:
    t = pq.read_table(run / "edgedata.parquet", columns=["begin", "edge_id", "traveltime", "sampledSeconds"]).to_pandas()
    t = t.rename(columns={"edge_id": "id"})
    t = t[t["id"].isin(edges) & np.isfinite(t["traveltime"])]
    t["hour"] = (t["begin"] // 3600).astype(int) % 24
    # vehicle-weighted mean traversal time per edge and hour
    t["w"] = t["traveltime"] * t["sampledSeconds"]
    g = t.groupby(["id", "hour"])[["w", "sampledSeconds"]].sum()
    g = g[g["sampledSeconds"] > 0]
    return {(i, h): w / s for (i, h), (w, s) in g.iterrows()}


@app.command()
def main(
    out: Path = typer.Option(...),
    roads: Path = typer.Option(..., help="data/roads.json of the site, for the drawing frame"),
    runs: Path = typer.Option(REPO_ROOT / "runs"),
) -> None:
    cors = {c["id"]: c for c in json.loads((OBS / "corridors.json").read_text())}
    obs = json.loads((OBS / "tomtom_traveltimes.json").read_text())
    frame = json.loads(roads.read_text())
    w, _s, _e, n = frame["bbox"]
    span = frame["span"]

    def q(lon: float, lat: float) -> list[int]:
        return [round((lon - w) / span * 10000), round((n - lat) / span * 10000)]

    base = sorted(runs.glob("baseline-weekday-*/edgedata.parquet"), key=lambda p: p.stat().st_mtime)
    model: dict[tuple[str, int], float] = {}
    if base:
        all_edges = {e for c in cors.values() for e in c["edges"]}
        model = model_hourly(base[-1].parent, all_edges)
    # corridor polylines from the network (simplified to every ~50 m)
    shapes: dict[str, list[int]] = {}
    net_file = REPO_ROOT / "data" / "hail" / "hail.v2.net.xml"
    if net_file.exists():
        import sumolib

        net = sumolib.net.readNet(str(net_file))
        for cid, c in cors.items():
            pts: list[int] = []
            for eid in c["edges"]:
                try:
                    shp = net.getEdge(eid).getShape()
                except KeyError:
                    continue
                for x, y in shp:
                    p = q(*net.convertXY2LonLat(x, y))
                    if len(pts) < 2 or abs(p[0] - pts[-2]) + abs(p[1] - pts[-1]) >= 4:
                        pts.extend(p)
            shapes[cid] = pts
    # free-flow time per edge from the corridor file (length / limit), for edges without vehicles
    out_rows: dict[str, Any] = {}
    for r in obs["rows"]:
        if r["day"] != "weekday" or not r.get("historic_s"):
            continue
        c = cors[r["corridor"]]
        h = int(r["hour"])
        rec = out_rows.setdefault(c["id"], {"id": c["id"], "name": c["name"], "length_m": c["length_m"],
                                            "from": q(*c["from"]), "to": q(*c["to"]),
                                            "line": shapes.get(c["id"]) or q(*c["from"]) + q(*c["to"]), "hours": {}})
        m = None
        if model:
            ff_edge = c["free_flow_s"] / max(len(c["edges"]), 1)
            m = round(sum(model.get((e, h), ff_edge) for e in c["edges"]), 1)
        rec["hours"][h] = {"tomtom_s": r["historic_s"], "free_s": r["no_traffic_s"], "model_s": m}
    data = {"source": obs.get("source"), "fetched": obs.get("fetched"), "baseline": base[-1].parent.name if base else None,
            "label_model": "synthetic demand, uncalibrated", "corridors": list(out_rows.values())}
    # one-line validation summary: share of corridor-hours where the model is within 15 % of TomTom
    pairs = [(v["model_s"], v["tomtom_s"]) for c in out_rows.values() for v in c["hours"].values() if v["model_s"]]
    if pairs:
        m, t = np.array(pairs).T
        data["agreement_15pct"] = round(float(np.mean(np.abs(m - t) <= 0.15 * t)), 3)
        data["model_over_tomtom_median"] = round(float(np.median(m / t)), 3)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    typer.echo(json.dumps({k: data.get(k) for k in ("baseline", "agreement_15pct", "model_over_tomtom_median")}
                          | {"corridors": len(out_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    app()
