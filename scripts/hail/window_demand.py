"""Tier A baseline vehicles departing in one hour, as the source routes of the tier link.

The Tier B windows get their demand by cutting Tier A routes (sim.link). Upstream used a random-trips
smoke run as the source; Hail uses the behavioural 24 h baseline instead: every vehicle that departs
in [begin, end) keeps its assigned route and has its depart time shifted by -begin, so the window
clock t = 0 is the start of that hour (08:00 for the demo hour, as strategist/scenarios assume).

    python -m scripts.hail.window_demand runs/<baseline>/routes.rou.xml.gz \
        --begin 28800 --end 32400 --out runs/hail-source-0800/routes.rou.xml

Synthetic demand, uncalibrated.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO

import typer

app = typer.Typer(add_completion=False, help=__doc__)


def _open(path: Path) -> IO[bytes]:
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def extract(src: Path, out: Path, begin: float, end: float) -> dict[str, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = seen = 0
    with _open(src) as fh, out.open("w", encoding="utf-8") as w:
        w.write("<routes>\n")
        for _ev, el in ET.iterparse(fh, events=("end",)):
            if el.tag != "vehicle":
                continue
            seen += 1
            dep = float(el.get("depart", "0"))
            route = el.find("route")
            if route is None:
                rd = el.find("routeDistribution")
                route = rd.find("route") if rd is not None else None
            if begin <= dep < end and route is not None and route.get("edges"):
                kept += 1
                w.write(
                    f'    <vehicle id="{el.get("id")}" depart="{dep - begin:.2f}" '
                    f'departLane="best" departSpeed="max">\n'
                    f'        <route edges="{route.get("edges")}"/>\n    </vehicle>\n'
                )
            el.clear()
        w.write("</routes>\n")
    return {"vehicles_seen": seen, "vehicles_kept": kept}


@app.command()
def main(
    routes: Path,
    out: Path = typer.Option(...),
    begin: float = typer.Option(28800.0, help="start of the demand hour (s after midnight)"),
    end: float = typer.Option(32400.0, help="end of the demand hour (s)"),
) -> None:
    stats = extract(routes, out, begin, end)
    typer.echo(f"{out}: {stats}")


if __name__ == "__main__":
    app()
