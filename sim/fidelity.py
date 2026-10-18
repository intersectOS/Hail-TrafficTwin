"""Meso-versus-micro fidelity test on a focus window (PROJECT.md 9.4).

The same routed demand (a synthetic window population, 24 h) runs in SUMO's mesoscopic model
(Tier A options) and its microscopic model (Tier B options) at several demand multiples, and the
two are compared hour by hour: trips completed, mean travel time, delay (time loss), speed and
queueing (vehicle-hours stopped on edges, from edgeData waitingTime). Writes
`runs/fidelity-<window>-s<seed>/` (fidelity.json, hourly.parquet, report.md) and
`docs/fidelity.md`, whose Caveats section the metrics report template quotes.

    python -m sim.fidelity --window demo --seed 1
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import (
    REPO_ROOT,
    SYNTHETIC_LABEL,
    config_hash,
    content_hash,
    load_yaml,
    rel,
    sumo_bin,
)
from sim.metrics import edgedata_to_parquet, md_table, parse_stats, parse_tripinfo

FID_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "fidelity.yaml"
FIDELITY_DOC = REPO_ROOT / "docs" / "fidelity.md"


def grid_districts(bbox: list[float], n: int, path: Path) -> Path:
    """Split a lon/lat bbox into n x n rectangular zones (GeoJSON)."""
    x0, y0, x1, y1 = bbox
    xs, ys = np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1)
    feats = []
    for i in range(n):
        for j in range(n):
            a, c, b, d = xs[i], xs[i + 1], ys[j], ys[j + 1]
            ring = [[a, b], [c, b], [c, d], [a, d], [a, b]]
            feats.append(
                {
                    "type": "Feature",
                    "properties": {"name_en": f"G{i}{j}", "name_ar": "", "osm_id": f"{i}{j}"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return path


def window_demand(window: dict[str, Any], net: Path, seed: int, work: Path, cfg: dict) -> Path:
    """Window population -> weekday vehicle trips -> one duarouter pass -> routes file."""
    import sim.population.synthesize as synthesize
    from sim.population import zones as Z
    from sim.population.activities import activities_config, generate
    from sim.population.export_trips import write_trips
    from sim.population.modes import assign_modes, vehicle_trips
    from sim.schemas import load_daytype

    zcfg = Z.zones_config()
    zcfg["control_total"]["value"] = int(cfg["residents"])
    zcfg["non_residential_districts"]["names"] = []
    districts = grid_districts(window["bbox"], int(cfg["grid"]), work / "districts.geojson")
    zones, zone_edges = Z.build_zones(Z.ZoneInputs(districts=districts, net=net), zcfg)
    Z.write_zones(zones, zone_edges, work / "zones", {})
    pop = synthesize.synthesize(seed, 1.0, work / "zones")
    trips = generate(pop, load_daytype("weekday"), seed, 1.0, work / "zones")
    trips = assign_modes(trips, pop, seed, "weekday", zone_dir=work / "zones")
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, seed, "weekday", speed)
    write_trips(veh, work / "trips.xml")
    routes = work / "routes.rou.xml"
    cmd = [
        sumo_bin("duarouter"), "-n", str(net), "--route-files", str(work / "trips.xml"),
        "-o", str(routes), "--routing-algorithm", str(cfg["routing_algorithm"]),
        "--ignore-errors", "--no-step-log", "--seed", str(seed),
    ]  # fmt: skip
    from sim.common import run_cmd

    run_cmd(cmd, log=work / "build.log")
    return routes


def tier_options(tier: str) -> list[str]:
    """Tier A = the baseline's meso options (with its overrides); Tier B = runner.yaml micro."""
    from sim.population.baseline import tier_a_options
    from sim.runner import flatten, runner_config

    if tier == "A":
        return tier_a_options()
    rc = runner_config()
    return [*flatten(rc["sumo_common"]), *flatten(rc["tier_B"]["options"])]


def run_tier(
    tier: str, net: Path, routes: Path, scale: float, seed: int, out: Path, cfg: dict
) -> dict[str, Any]:
    from sim.common import run_cmd
    from sim.runner import assert_tier_options, runner_config

    rc = runner_config()
    out.mkdir(parents=True, exist_ok=True)
    key = config_hash(
        {
            "routes": content_hash(routes),
            "tier": tier,
            "scale": scale,
            "seed": seed,
            "options": tier_options(tier),
        }
    )
    done = out / "key.json"
    if done.exists() and json.loads(done.read_text()).get("key") == key:
        cached = json.loads(done.read_text())
        return {
            "wall_s": cached["wall_s"],
            "tripinfo": pd.read_parquet(out / "tripinfo.parquet"),
            "stats": parse_stats(out / "stats.xml"),
            "dir": out,
        }
    add = out / "edgedata.add.xml"
    add.write_text(
        f'<additional>\n    <edgeData id="ed" freq="{cfg["edgedata_freq_s"]}" '
        'file="edgedata.xml" excludeEmpty="true"/>\n</additional>\n'
    )
    args = [
        "-n", str(net), "-r", str(routes), "--additional-files", str(add),
        "--begin", "0", "--end", str(86400 + 7200), "--seed", str(seed), "--scale", f"{scale:g}",
        "--tripinfo-output", str(out / "tripinfo.xml"),
        "--statistic-output", str(out / "stats.xml"), "--log", str(out / "sumo.log"),
        *tier_options(tier),
    ]  # fmt: skip
    assert_tier_options(tier, args, [add], rc)
    t0 = time.perf_counter()
    run_cmd([sumo_bin("sumo"), *args], log=out / "run.log")
    wall = time.perf_counter() - t0
    ti = parse_tripinfo(out / "tripinfo.xml")
    edgedata_to_parquet(out / "edgedata.xml", out / "edgedata.parquet")
    stats = parse_stats(out / "stats.xml")
    for name in ("tripinfo.xml", "edgedata.xml"):
        (out / name).unlink(missing_ok=True)
    ti.to_parquet(out / "tripinfo.parquet", index=False)
    done.write_text(json.dumps({"key": key, "wall_s": round(wall, 2)}))
    return {"wall_s": round(wall, 2), "tripinfo": ti, "stats": stats, "dir": out}


def hourly(ti: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    ti = ti[ti["depart"] < 86400].copy()
    ti["hour"] = (ti["depart"] // 3600).astype(int)
    g = ti.groupby("hour")
    out = pd.DataFrame(
        {
            "trips": g.size(),
            "travel_time_s": g["duration"].mean(),
            "delay_s": g["time_loss"].mean() + g["depart_delay"].mean(),
            "speed_kmh": g["route_m"].sum() / g["duration"].sum() * 3.6,
        }
    )
    e = edges.copy()
    e["hour"] = (e["begin"] // 3600).astype(int)
    q = e.groupby("hour")["sampledSeconds"].sum()  # vehicle-seconds on the network
    out["veh_h_on_network"] = (q / 3600.0).reindex(out.index)
    out["edge_time_loss_veh_h"] = (e.groupby("hour")["timeLoss"].sum() / 3600.0).reindex(out.index)
    return out.reindex(range(24)).fillna(0.0)


CAVEATS = """\
- SUMO's mesoscopic model only partially follows kinematic-wave (LWR) theory, models queue
  spill-back incompletely and tends to underestimate congestion (June 2026 re-assessment of
  the Eissfeldt meso model, PROJECT.md section 2). The window test below quantifies the gap on
  Jeddah's network: {gap}
- Meso has no lane changing, no lane-level queues and no explicit junction geometry; signal
  delay is an expected-delay penalty (meso-tls-penalty, A-sim-001), so junction-level delay is
  approximate.
- The test window carries internal trips only (no through traffic), so its loads are raised
  with demand multiples; city-scale interactions are not tested.
- Consequence for reports: trust baseline-versus-policy deltas more than absolute delay and
  speed, and always state the tier a result was run on.
- Demand is synthetic and uncalibrated (no Jeddah counts or travel survey).
"""


def compare(window: str, seed: int, cfg: dict | None = None) -> dict[str, Any]:
    from sim.network.build_window import load_window

    cfg = cfg or load_yaml(FID_CONFIG)
    win = load_window(window)
    net = REPO_ROOT / win["out_dir"] / f"{win['name']}.net.xml"
    out = REPO_ROOT / "runs" / f"fidelity-{window}-s{seed}"
    out.mkdir(parents=True, exist_ok=True)
    routes = window_demand(win, net, seed, out / "demand", cfg)
    rows, summary = [], []
    for scale in cfg["demand_scales"]:
        res = {}
        for tier in ("A", "B"):
            r = run_tier(tier, net, routes, float(scale), seed, out / f"x{scale:g}-{tier}", cfg)
            edges = pd.read_parquet(r["dir"] / "edgedata.parquet")
            res[tier] = (r, hourly(r["tripinfo"], edges))
        meso, micro = res["A"][1], res["B"][1]
        h = meso.add_prefix("meso_").join(micro.add_prefix("micro_"))
        h.insert(0, "scale", scale)
        h.index.name = "hour"
        rows.append(h.reset_index())
        ta, tb = res["A"][0]["tripinfo"], res["B"][0]["tripinfo"]

        def mean(df: pd.DataFrame, col: str) -> float:
            return float(df.loc[df["depart"] < 86400, col].mean())

        def tele(r: dict) -> int:
            return int(r["stats"].get("teleports", {}).get("total", 0))

        peak = int(micro["edge_time_loss_veh_h"].idxmax())
        summary.append(
            {
                "demand_x": scale,
                "trips_meso": int((ta["depart"] < 86400).sum()),
                "trips_micro": int((tb["depart"] < 86400).sum()),
                "travel_time_meso_s": round(mean(ta, "duration"), 1),
                "travel_time_micro_s": round(mean(tb, "duration"), 1),
                "delay_meso_s": round(mean(ta, "time_loss") + mean(ta, "depart_delay"), 1),
                "delay_micro_s": round(mean(tb, "time_loss") + mean(tb, "depart_delay"), 1),
                "speed_meso_kmh": round(float(ta.route_m.sum() / ta.duration.sum() * 3.6), 1),
                "speed_micro_kmh": round(float(tb.route_m.sum() / tb.duration.sum() * 3.6), 1),
                "peak_hour": peak,
                "peak_delay_meso_s": round(float(meso.loc[peak, "delay_s"]), 1),
                "peak_delay_micro_s": round(float(micro.loc[peak, "delay_s"]), 1),
                "teleports_meso": tele(res["A"][0]),
                "teleports_micro": tele(res["B"][0]),
                "wall_meso_s": res["A"][0]["wall_s"],
                "wall_micro_s": res["B"][0]["wall_s"],
            }
        )
    table = pd.concat(rows, ignore_index=True)
    table.to_parquet(out / "hourly.parquet", index=False)
    gaps = [
        f"x{s['demand_x']:g}: mean delay meso {s['delay_meso_s']} s vs micro "
        f"{s['delay_micro_s']} s, speed {s['speed_meso_kmh']} vs {s['speed_micro_kmh']} km/h"
        for s in summary
    ]
    result = {
        "label": SYNTHETIC_LABEL,
        "window": window,
        "seed": seed,
        "network": rel(net),
        "network_hash": content_hash(net),
        "summary": summary,
        "caveats": CAVEATS.format(gap="; ".join(gaps) + "."),
    }
    (out / "fidelity.json").write_text(json.dumps(result, indent=2))
    write_doc(result, table, out)
    return result


def write_doc(result: dict[str, Any], table: pd.DataFrame, out: Path) -> None:
    hourly_rows = []
    for _, r in table[table["scale"] == max(table["scale"])].iterrows():
        if r["micro_trips"] == 0 and r["meso_trips"] == 0:
            continue
        hourly_rows.append(
            {
                "hour": int(r["hour"]),
                "trips meso/micro": f"{int(r['meso_trips'])}/{int(r['micro_trips'])}",
                "delay s meso/micro": f"{r['meso_delay_s']:.1f}/{r['micro_delay_s']:.1f}",
                "speed km/h meso/micro": f"{r['meso_speed_kmh']:.1f}/{r['micro_speed_kmh']:.1f}",
                "time loss veh-h meso/micro": f"{r['meso_edge_time_loss_veh_h']:.1f}/"
                f"{r['micro_edge_time_loss_veh_h']:.1f}",
            }
        )
    text = f"""# Meso-versus-micro fidelity test (PROJECT.md 9.4)

> {SYNTHETIC_LABEL}. Window `{result["window"]}` ({result["network"]}, network
> {result["network_hash"]}), seed {result["seed"]}, weekday window population routed once and
> simulated in both tiers at several demand multiples. Reproduce:
> `uv run python -m sim.fidelity --window {result["window"]} --seed {result["seed"]}`
> (outputs in `{rel(out)}/`).

## Summary by demand multiple
{md_table(result["summary"])}

## Hourly comparison at the highest multiple
{md_table(hourly_rows)}

## Caveats
{result["caveats"]}
"""
    FIDELITY_DOC.write_text(text)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(window: str = typer.Option("demo"), seed: int = typer.Option(1)) -> None:
    res = compare(window, seed)
    typer.echo(md_table(res["summary"]))
    typer.echo(f"wrote {rel(FIDELITY_DOC)}")


if __name__ == "__main__":
    app()
