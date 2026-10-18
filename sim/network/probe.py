"""Peak probe: compare city network variants on the same demand in minutes, not hours.

Takes the vehicle trips of an existing Tier A baseline (`runs/<baseline>/trips.xml`, scaled vTypes
included), keeps the departures in a time window (default 05:00-09:00, the AM peak), routes them
once at free flow with duarouter on the candidate network, and runs the window in meso with the
baseline's Tier A options and capacity scaling. Reports teleports per vehicle (the baseline's
`teleport_share` definition), mean speed, delay, and the teleport hotspots.

One-shot free-flow routes load the network harder than the 3-step assignment of the baseline,
so a probe's teleport share is a relative measure between networks, not a baseline forecast.
Synthetic demand, uncalibrated.

    python -m sim.network.probe --net data/jeddah/jeddah.v2.net.xml \
        --trips runs/baseline-weekday-f0.1-s1-.../trips.xml --label v2
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, content_hash, rel, run_cmd, sumo_bin
from sim.network.teleports import hotspots

_DEPART = re.compile(r'depart="([0-9.]+)"')


def window_trips(src: Path, dst: Path, begin: float, end: float) -> int:
    """Copy everything but the trips outside [begin, end) (streaming; one `<trip .../>` per line,
    as written by sim.population.export_trips and randomTrips)."""
    n = 0
    with src.open() as fin, dst.open("w") as fout:
        for line in fin:
            s = line.lstrip()
            if s.startswith("<trip "):
                m = _DEPART.search(s)
                if m and begin <= float(m.group(1)) < end:
                    fout.write(line)
                    n += 1
            else:  # vTypes, comments, root element: copied as they are
                fout.write(line)
    return n


def parse_stats(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    out: dict[str, Any] = {}
    veh = root.find("vehicles")
    if veh is not None:
        out.update({k: int(float(v)) for k, v in veh.attrib.items()})
    tel = root.find("teleports")
    if tel is not None:
        out["teleports"] = {k: int(float(v)) for k, v in tel.attrib.items()}
    trip = root.find("vehicleTripStatistics")
    if trip is not None:
        out["trip"] = {k: float(v) for k, v in trip.attrib.items()}
    return out


def tau_options(sample: float) -> list[str]:
    from sim.population.baseline import baseline_config, scale_options

    return scale_options(sample, baseline_config())[1]


def probe(
    net: Path,
    trips: Path,
    out: Path,
    begin: int = 5 * 3600,
    end: int = 9 * 3600,
    drain: int = 3600,
    sample: float = 0.10,
    seed: int = 1,
    threads: int = 6,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`overrides` replaces values of the baseline Tier A options (diagnostics only, e.g.
    {"--time-to-teleport": "300"}); the result records them."""
    from sim.population.baseline import tier_a_options

    sim_opts = tier_a_options()
    for flag, value in (overrides or {}).items():
        if flag in sim_opts:
            sim_opts[sim_opts.index(flag) + 1] = value
        else:
            sim_opts += [flag, value]

    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    sub = out / "trips.xml"
    n_trips = window_trips(trips, sub, begin, end)
    routes = out / "routes.rou.xml.gz"
    run_cmd(
        [
            sumo_bin("duarouter"),
            "-n", str(net),
            "--route-files", str(sub),
            "-o", str(routes),
            "--ignore-errors",
            "--routing-algorithm", "astar",
            "--routing-threads", str(threads),
            "--seed", str(seed),
            "--no-step-log",
            "--no-warnings",
            "--log", str(out / "duarouter.log"),
        ],
        log=out / "probe.log",
    )  # fmt: skip
    t_route = time.perf_counter() - t0
    args = [
        sumo_bin("sumo"),
        "-n", str(net),
        "-r", str(routes),
        "--begin", str(begin),
        "--end", str(end + drain),
        "--seed", str(seed),
        "--statistic-output", str(out / "stats.xml"),
        "--log", str(out / "sumo.log"),
        *sim_opts,
        *tau_options(sample),
    ]  # fmt: skip
    run_cmd(args, log=out / "probe.log")
    t_sim = time.perf_counter() - t0 - t_route
    stats = parse_stats(out / "stats.xml")
    loaded = stats.get("loaded", 0)
    tel = stats.get("teleports", {}).get("total", 0)
    trip = stats.get("trip", {})
    hs = hotspots(out / "sumo.log", net, top=10)
    res = {
        "label": SYNTHETIC_LABEL,
        "net": rel(net),
        "net_hash": content_hash(net),
        "trips": rel(trips),
        "window": [begin, end],
        "drain_s": drain,
        "sample": sample,
        "seed": seed,
        "overrides": overrides or {},
        "trips_in_window": n_trips,
        "vehicles_loaded": loaded,
        "unroutable": n_trips - loaded,
        "inserted": stats.get("inserted"),
        "running_at_end": stats.get("running"),
        "waiting_at_end": stats.get("waiting"),
        "teleports": stats.get("teleports", {}),
        "teleport_share": round(tel / loaded, 4) if loaded else None,
        "mean_speed_kmh": round(trip.get("speed", 0.0) * 3.6, 2),
        "mean_duration_s": round(trip.get("duration", 0.0), 1),
        "mean_time_loss_s": round(trip.get("timeLoss", 0.0), 1),
        "mean_route_km": round(trip.get("routeLength", 0.0) / 1000.0, 2),
        "route_s": round(t_route, 1),
        "sim_s": round(t_sim, 1),
        "hotspots": {k: hs[k] for k in ("on_junction_internal_share", "on_guessed_ramps_share")}
        | {"by_length_m": hs["by_length_m"], "by_type": hs["by_type"], "top": hs["top"]},
    }
    (out / "probe.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    return res


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    net: Path = typer.Option(...),
    trips: Path = typer.Option(..., help="baseline trips.xml (scaled vTypes + trips)"),
    label: str = typer.Option("probe"),
    begin: int = typer.Option(5 * 3600),
    end: int = typer.Option(9 * 3600),
    drain: int = typer.Option(3600),
    sample: float = typer.Option(0.10, help="sample of the trips file (capacity scaling)"),
    seed: int = typer.Option(1),
    threads: int = typer.Option(6),
    out_dir: Path = typer.Option(REPO_ROOT / "runs" / "probes"),
    set_opt: list[str] = typer.Option(
        [], "--set", help="diagnostic SUMO option override FLAG=VALUE (repeatable)"
    ),
) -> None:
    overrides = dict(o.split("=", 1) for o in set_opt)
    out = out_dir / f"{label}-{content_hash(net)[:8]}-{begin // 3600:02d}-{end // 3600:02d}"
    res = probe(net, trips, out, begin, end, drain, sample, seed, threads, overrides)
    brief = {k: v for k, v in res.items() if k != "hotspots"}
    typer.echo(json.dumps(brief, indent=1))


if __name__ == "__main__":
    app()
