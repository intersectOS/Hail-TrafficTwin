"""Cut a Tier B focus window out of the Tier A city network.

The window is cut from the city .net.xml (not rebuilt from OSM) so its edge ids are identical to
Tier A's; M5's cutRoutes link depends on that. Window definitions live in sim/network/windows/.

    python -m sim.network.build_window --name demo
    python -m sim.network.build_window --name demo --city-net data/jeddah/jeddah.net.xml --trips
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from sim.common import (
    REPO_ROOT,
    content_hash,
    load_yaml,
    rel,
    run_cmd,
    sumo_bin,
    sumo_version,
)
from sim.network.netinfo import net_stats

WINDOWS_DIR = REPO_ROOT / "sim" / "network" / "windows"
DEFAULT_CITY_NET = REPO_ROOT / "data" / "jeddah" / "jeddah.net.xml"
DEFAULT_CITY_PBF = REPO_ROOT / "data" / "osm" / "jeddah.osm.pbf"


def load_window(name: str) -> dict[str, Any]:
    path = WINDOWS_DIR / f"{name}.yaml"
    if not path.exists():
        raise typer.BadParameter(f"no window definition {rel(path)}")
    cfg = load_yaml(path)
    if cfg.get("name") != name:
        raise ValueError(f"{rel(path)}: name field must be {name!r}")
    if "bbox" not in cfg and "polygon" not in cfg:
        raise ValueError(f"{rel(path)}: give bbox [min_lon, min_lat, max_lon, max_lat] or polygon")
    return cfg


def boundary_arg(cfg: dict[str, Any]) -> str:
    """netconvert --keep-edges.in-geo-boundary value (corner bbox or flat polygon list)."""
    if "polygon" in cfg:
        return ",".join(f"{lon},{lat}" for lon, lat in cfg["polygon"])
    return ",".join(str(v) for v in cfg["bbox"])


def cut_window(city_net: Path, cfg: dict[str, Any], out_net: Path, log: Path | None = None) -> None:
    out_net.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sumo_bin("netconvert"),
        "--sumo-net-file",
        str(city_net),
        "--keep-edges.in-geo-boundary",
        boundary_arg(cfg),
        "--remove-edges.isolated",
        "--keep-edges.components",
        "1",
        "--output.street-names",
        "--output.original-names",
        "--no-warnings",
        "-o",
        str(out_net),
    ]
    run_cmd(cmd, log=log)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    name: str = typer.Option(..., help="window name (sim/network/windows/<name>.yaml)"),
    city_net: Path = typer.Option(DEFAULT_CITY_NET, help="Tier A network to cut from"),
    out_dir: Path | None = typer.Option(None, help="output directory (default from window YAML)"),
    trips: bool = typer.Option(True, help="also write smoke random trips for the window"),
    osm_extract: bool = typer.Option(
        False, help="also write <name>.osm.gz, the raw OSM of the window bbox (builder test input)"
    ),
    city_pbf: Path = typer.Option(DEFAULT_CITY_PBF, help="clipped city PBF for --osm-extract"),
    seed: int = typer.Option(1),
) -> None:
    cfg = load_window(name)
    if not city_net.exists():
        raise typer.BadParameter(f"{rel(city_net)} missing: run python -m sim.network.build_city")
    out = out_dir or (REPO_ROOT / cfg.get("out_dir", f"data/windows/{name}"))
    net = out / f"{name}.net.xml"
    log = REPO_ROOT / "logs" / f"build_window-{name}.log"
    cut_window(city_net, cfg, net, log=log)
    stats = net_stats(net)
    meta: dict[str, Any] = {
        "window": name,
        "definition": cfg,
        "city_net": rel(city_net),
        "city_net_hash": content_hash(city_net),
        "sumo_version": sumo_version(),
        "network": stats.as_dict(),
    }
    if trips:
        from sim.runner import make_random_trips, smoke_config

        smoke = smoke_config()["tier_B"]
        trips_file = out / f"{name}.trips.xml"
        make_random_trips(
            net,
            trips_file,
            smoke["random_trips"],
            seed=seed,
            begin=int(smoke["begin"]),
            end=int(smoke["end"]),
            log=log,
        )
        meta["trips"] = {"file": rel(trips_file), "seed": seed, "hash": content_hash(trips_file)}
    if osm_extract:
        osm_out = out / f"{name}.osm.gz"
        bbox = ",".join(str(v) for v in cfg["bbox"])
        run_cmd(
            [
                "osmium",
                "extract",
                "-b",
                bbox,
                "-s",
                "complete_ways",
                str(city_pbf),
                "-o",
                str(osm_out),
                "--overwrite",
                "--fsync",
            ],
            log=log,
        )
        meta["osm_extract"] = {"file": rel(osm_out), "source": rel(city_pbf)}
    (out / f"{name}.window.json").write_text(json.dumps(meta, indent=2))
    typer.echo(f"window {name}: {rel(net)} {json.dumps(stats.as_dict())}")


if __name__ == "__main__":
    app()
