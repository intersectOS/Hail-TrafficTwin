"""Travel-time CSV adapter: `segment_id, edge_ids, hour, travel_time_s, samples`.

A segment is an ordered, space-separated list of SUMO edge ids (a corridor between two probe
points), `travel_time_s` the observed mean traversal time in that hour, `samples` the number of
observations behind it (0 if unknown). Travel times validate a calibrated run (share of segments
within the A-cal-002 tolerance); routeSampler itself fits counts only.

    python -m sim.adapters.traveltimes check traveltimes.csv --net data/jeddah/jeddah.m2.net.xml
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from sim.adapters import calibrate_config
from sim.adapters.counts import net_edge_ids

COLUMNS = ("segment_id", "edge_ids", "hour", "travel_time_s", "samples")


@dataclass(frozen=True)
class TravelTimeRecord:
    segment_id: str
    edge_ids: tuple[str, ...]
    hour: int
    travel_time_s: float
    samples: int


def read_travel_times(path: Path, max_hour: int | None = None) -> list[TravelTimeRecord]:
    max_hour = calibrate_config()["counts"]["max_hour"] if max_hour is None else max_hour
    records: list[TravelTimeRecord] = []
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}; expected {', '.join(COLUMNS)}")
        for line, row in enumerate(reader, start=2):
            edges = tuple(row["edge_ids"].split())
            try:
                hour = int(row["hour"])
                tt = float(row["travel_time_s"])
                samples = int(row["samples"] or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}:{line}: hour, travel_time_s, samples must be numeric"
                ) from exc
            if not edges or not row["segment_id"]:
                raise ValueError(f"{path}:{line}: empty segment_id or edge_ids")
            if not 0 <= hour <= max_hour:
                raise ValueError(f"{path}:{line}: hour {hour} outside 0..{max_hour}")
            if tt <= 0 or samples < 0:
                raise ValueError(f"{path}:{line}: travel_time_s must be > 0 and samples >= 0")
            records.append(TravelTimeRecord(row["segment_id"], edges, hour, tt, samples))
    if not records:
        raise ValueError(f"{path}: no travel-time rows")
    return records


def write_travel_times(records: list[TravelTimeRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in records:
            writer.writerow(
                [r.segment_id, " ".join(r.edge_ids), r.hour, round(r.travel_time_s, 1), r.samples]
            )


def compare(
    records: list[TravelTimeRecord],
    edge_tt: dict[tuple[str, int], float],
    tolerance: float | None = None,
) -> dict[str, Any]:
    """Compare observed segment times with simulated ones (sum of edge travel times per hour).

    `edge_tt` maps (edge id, hour) to the simulated mean travel time on the edge. Segments with an
    edge that carried no simulated traffic in that hour are reported as `unmatched`.
    """
    tolerance = calibrate_config()["travel_time"]["tolerance"] if tolerance is None else tolerance
    rows: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for r in records:
        parts = [edge_tt.get((e, r.hour)) for e in r.edge_ids]
        if any(p is None for p in parts):
            unmatched.append(f"{r.segment_id}@{r.hour}")
            continue
        sim = float(sum(p for p in parts if p is not None))
        err = (sim - r.travel_time_s) / r.travel_time_s
        rows.append(
            {
                "segment_id": r.segment_id,
                "hour": r.hour,
                "observed_s": r.travel_time_s,
                "simulated_s": round(sim, 1),
                "rel_error": round(err, 4),
                "within_tolerance": abs(err) <= tolerance,
            }
        )
    n = len(rows)
    return {
        "segment_hours": len(records),
        "segments": len({r.segment_id for r in records}),
        "matched": n,
        "unmatched": unmatched,
        "tolerance": tolerance,
        "share_within_tolerance": round(sum(r["within_tolerance"] for r in rows) / n, 4)
        if n
        else None,
        "mean_abs_rel_error": round(sum(abs(r["rel_error"]) for r in rows) / n, 4) if n else None,
        "rows": rows,
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def check(
    csv_path: Path = typer.Argument(...),
    net: Path | None = typer.Option(None, help="network to check the edge ids against"),
) -> None:
    """Validate a travel-time CSV and print a summary."""
    records = read_travel_times(csv_path)
    typer.echo(f"rows: {len(records)}")
    typer.echo(f"segments: {len({r.segment_id for r in records})}")
    typer.echo(f"hours: {sorted({r.hour for r in records})}")
    if net is not None:
        unknown = sorted({e for r in records for e in r.edge_ids} - net_edge_ids(net))
        typer.echo(f"unknown_edges: {unknown}")
        if unknown:
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
