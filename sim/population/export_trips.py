"""Export vehicle trips to SUMO (sorted by departure) plus a vehicle table for metrics.

Only trips that put a vehicle on the road are exported (car, chauffeured, ride-hail/taxi, escort
with empty legs, school and company buses). Walk, bus-line and passenger trips stay in the
person-trip table. vTypes go to a separate additional file so capacity scaling (`scale`) can
lengthen vehicles for sampled runs without touching the trips.

    python -m sim.population.export_trips --daytype weekday --seed 1 --sample 0.10 --out runs/x
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, load_yaml
from sim.population.sampling import frame_hash

EXPORT_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "export.yaml"
VEHICLE_COLUMNS = [
    "veh_id",
    "vtype",
    "depart",
    "o_edge",
    "d_edge",
    "o_zone",
    "d_zone",
    "purpose",
    "segment",
    "mode",
    "person_id",
    "empty",
    "dist_km",
]


def export_config(path: Path = EXPORT_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


def vtype_lines(scale: float = 1.0, cfg: dict[str, Any] | None = None) -> list[str]:
    """<vType> elements; `scale` > 1 multiplies length and minGap (capacity scaling)."""
    cfg = cfg or export_config()
    lines = []
    for vid, spec in cfg["vtypes"].items():
        if vid in ("source", "assumption"):
            continue
        attrs = dict(spec)
        attrs["length"] = round(float(attrs["length"]) * scale, 2)
        attrs["minGap"] = round(float(attrs["minGap"]) * scale, 2)
        body = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())
        lines.append(f'    <vType id="{vid}" {body}/>')
    return lines


def write_vtypes(path: Path, scale: float = 1.0, cfg: dict[str, Any] | None = None) -> Path:
    """vType additional file (for tools that take vTypes separately)."""
    lines = [f"<!-- {SYNTHETIC_LABEL}; capacity scale {scale:g} -->", "<additional>"]
    lines += vtype_lines(scale, cfg)
    lines.append("</additional>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def write_trips(vehicles: pd.DataFrame, path: Path, scale: float = 1.0) -> Path:
    """SUMO <trip> file with its vTypes, sorted by departure (input must already be sorted).

    vTypes travel with the trips because duaIterate does not hand additional files to duarouter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    dep = vehicles["depart"].to_numpy()
    if len(dep) > 1 and (dep[1:] < dep[:-1]).any():
        raise ValueError("vehicles must be sorted by departure")
    with path.open("w") as fh:
        fh.write(f"<!-- {SYNTHETIC_LABEL}; capacity scale {scale:g} -->\n<routes>\n")
        fh.write("\n".join(vtype_lines(scale)) + "\n")
        for vid, vtype, depart, frm, to in zip(
            vehicles["veh_id"],
            vehicles["vtype"],
            vehicles["depart"],
            vehicles["o_edge"],
            vehicles["d_edge"],
            strict=True,
        ):
            fh.write(
                f'    <trip id="{vid}" type="{vtype}" depart="{depart:.1f}" '
                f'from="{frm}" to="{to}"/>\n'
            )
        fh.write("</routes>\n")
    return path


def export(vehicles: pd.DataFrame, out_dir: Path, scale: float = 1.0) -> dict[str, Any]:
    """Write trips.xml, vehicles.parquet and return their provenance."""
    out_dir.mkdir(parents=True, exist_ok=True)
    table = vehicles[VEHICLE_COLUMNS].copy()
    for col in ("vtype", "purpose", "segment", "mode"):
        table[col] = table[col].astype(str)
    table.to_parquet(out_dir / "vehicles.parquet", index=False)
    write_trips(table, out_dir / "trips.xml", scale)
    return {
        "trips_file": "trips.xml",
        "vehicles": len(table),
        "vehicles_hash": frame_hash(table),
        "vtypes": table["vtype"].value_counts().to_dict(),
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    daytype: str = typer.Option("weekday"),
    seed: int = typer.Option(1),
    sample: float = typer.Option(0.10),
    out: Path = typer.Option(..., help="output directory"),
) -> None:
    from sim.population.activities import activities_config, load_or_generate
    from sim.population.modes import assign_modes, vehicle_trips

    pop, trips, _ = load_or_generate(seed, sample, daytype)
    trips = assign_modes(trips, pop, seed, daytype)
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, seed, daytype, speed)
    info = export(veh, out)
    typer.echo(json.dumps(info, indent=2))


if __name__ == "__main__":
    app()
