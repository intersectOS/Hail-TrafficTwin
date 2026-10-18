"""Hourly count CSV adapter: `detector_id, edge_id, hour, count` -> SUMO edgeData.

The CSV is the format a Jeddah data partner is asked to deliver (docs/calibration.md). `hour` is
the hour of the simulated day (0 = 00:00-01:00; values above 23 cover the after-midnight tail),
`count` is vehicles per hour across all lanes of the edge.

    python -m sim.adapters.counts check counts.csv --net data/jeddah/jeddah.m2.net.xml
"""

from __future__ import annotations

import csv
import gzip
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import typer

from sim.adapters import calibrate_config

COLUMNS = ("detector_id", "edge_id", "hour", "count")


@dataclass(frozen=True)
class CountRecord:
    detector_id: str
    edge_id: str
    hour: int
    count: float


def read_counts(path: Path, max_hour: int | None = None) -> list[CountRecord]:
    """Read and validate a count CSV; raise ValueError naming the first bad row."""
    max_hour = calibrate_config()["counts"]["max_hour"] if max_hour is None else max_hour
    records: list[CountRecord] = []
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}; expected {', '.join(COLUMNS)}")
        for line, row in enumerate(reader, start=2):
            try:
                hour = int(row["hour"])
                count = float(row["count"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line}: hour and count must be numeric") from exc
            if not row["edge_id"] or not row["detector_id"]:
                raise ValueError(f"{path}:{line}: empty detector_id or edge_id")
            if not 0 <= hour <= max_hour:
                raise ValueError(f"{path}:{line}: hour {hour} outside 0..{max_hour}")
            if count < 0:
                raise ValueError(f"{path}:{line}: negative count")
            records.append(CountRecord(row["detector_id"], row["edge_id"], hour, count))
    if not records:
        raise ValueError(f"{path}: no count rows")
    return records


def write_counts(records: list[CountRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in records:
            count = int(r.count) if float(r.count).is_integer() else r.count
            writer.writerow([r.detector_id, r.edge_id, r.hour, count])


def aggregate(
    records: list[CountRecord], policy: str | None = None
) -> dict[tuple[str, int], float]:
    """One target per (edge, hour). Duplicates are averaged (A-cal-003) or summed."""
    policy = policy or calibrate_config()["counts"]["duplicate_policy"]
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in records:
        groups[(r.edge_id, r.hour)].append(r.count)
    if policy == "mean":
        return {k: sum(v) / len(v) for k, v in groups.items()}
    if policy == "sum":
        return {k: float(sum(v)) for k, v in groups.items()}
    raise ValueError(f"unknown duplicate policy {policy!r}")


def net_edge_ids(net: Path) -> set[str]:
    """Edge ids of a SUMO network (streaming; works on the 350 MB city net)."""
    opener = gzip.open if str(net).endswith(".gz") else open
    ids: set[str] = set()
    with opener(net, "rb") as fh:
        for _, elem in ET.iterparse(fh, events=("start",)):
            if elem.tag == "edge" and elem.get("function") != "internal":
                ids.add(elem.get("id", ""))
            elem.clear()
    return ids


def check_edges(records: list[CountRecord], net: Path) -> list[str]:
    """Edge ids in the counts that the network does not contain."""
    known = net_edge_ids(net)
    return sorted({r.edge_id for r in records} - known)


def write_edgedata(
    targets: dict[tuple[str, int], float], out: Path, scale: float = 1.0, interval_s: int = 3600
) -> Path:
    """Write counts as an edgeData file (one interval per hour) for routeSampler.

    `scale` converts full-population counts to the simulated sample (e.g. 0.10 for a 10 % sample).
    Values are rounded to whole vehicles, as routeSampler samples whole vehicles.
    """
    by_hour: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for (edge, hour), value in targets.items():
        by_hour[hour].append((edge, value))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("<data>\n")
        for hour in sorted(by_hour):
            begin, end = hour * interval_s, (hour + 1) * interval_s
            fh.write(f'    <interval id="counts" begin="{begin}" end="{end}">\n')
            for edge, value in sorted(by_hour[hour]):
                fh.write(f'        <edge id={quoteattr(edge)} count="{round(value * scale)}"/>\n')
            fh.write("    </interval>\n")
        fh.write("</data>\n")
    return out


def summary(records: list[CountRecord]) -> dict[str, Any]:
    targets = aggregate(records)
    return {
        "rows": len(records),
        "detectors": len({r.detector_id for r in records}),
        "edges": len({r.edge_id for r in records}),
        "hours": sorted({r.hour for r in records}),
        "targets": len(targets),
        "duplicates": len(records) - len(targets),
        "total_count": round(sum(r.count for r in records), 1),
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def check(
    csv_path: Path = typer.Argument(..., help="count CSV (detector_id, edge_id, hour, count)"),
    net: Path | None = typer.Option(None, help="network to check the edge ids against"),
) -> None:
    """Validate a count CSV and print a summary."""
    records = read_counts(csv_path)
    info = summary(records)
    if net is not None:
        info["unknown_edges"] = check_edges(records, net)
    for key, value in info.items():
        typer.echo(f"{key}: {value}")
    if info.get("unknown_edges"):
        raise typer.Exit(code=1)


@app.command()
def to_edgedata(
    csv_path: Path = typer.Argument(...),
    out: Path = typer.Option(..., help="edgeData XML to write"),
    scale: float = typer.Option(1.0, help="multiply counts (population sample share)"),
) -> None:
    """Convert a count CSV to a routeSampler edgeData file."""
    write_edgedata(aggregate(read_counts(csv_path)), out, scale)
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
