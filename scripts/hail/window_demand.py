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


def extract(
    src: Path, out: Path, begin: float, end: float, expand: int = 1, jitter_s: float = 300.0, seed: int = 1
) -> dict[str, int]:
    """Keep vehicles departing in [begin, end). With expand = k > 1 (a 1/k population sample),
    each kept vehicle is written k times on the same route, the copies' departures spread uniformly
    over +/- jitter_s (seeded) and clipped to the hour, so the window carries full-city volumes
    (A-link-hail-001, the same expansion the capacity scaling makes in Tier A)."""
    import random

    rng = random.Random(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = seen = 0
    rows: list[tuple[float, str, str]] = []
    with _open(src) as fh:
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
                vid, edges = el.get("id"), route.get("edges")
                for k in range(expand):
                    d = dep - begin if k == 0 else dep - begin + rng.uniform(-jitter_s, jitter_s)
                    d = min(max(d, 0.0), end - begin - 1)
                    rows.append((d, vid if k == 0 else f"{vid}.x{k}", edges))
            el.clear()
    rows.sort(key=lambda r: r[0])
    with out.open("w", encoding="utf-8") as w:
        w.write("<routes>\n")
        for d, vid, edges in rows:
            w.write(
                f'    <vehicle id="{vid}" depart="{d:.2f}" departLane="best" departSpeed="max">\n'
                f'        <route edges="{edges}"/>\n    </vehicle>\n'
            )
        w.write("</routes>\n")
    return {"vehicles_seen": seen, "vehicles_kept": kept, "vehicles_written": len(rows), "expand": expand}


@app.command()
def main(
    routes: Path,
    out: Path = typer.Option(...),
    begin: float = typer.Option(28800.0, help="start of the demand hour (s after midnight)"),
    end: float = typer.Option(32400.0, help="end of the demand hour (s)"),
    expand: int = typer.Option(1, help="copies per vehicle (1/sample) to restore full volumes"),
    seed: int = typer.Option(1),
) -> None:
    stats = extract(routes, out, begin, end, expand=expand, seed=seed)
    typer.echo(f"{out}: {stats}")


if __name__ == "__main__":
    app()
