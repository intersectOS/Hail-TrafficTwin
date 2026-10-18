"""Counts derived from a baseline run's edgeData, for the city-scale calibration check (NOT data).

Picks detector edges from the baseline's own `edgedata.parquet` (A-cal-006) and writes their hourly
`entered` counts, scaled from the run's population sample to full-population vehicles, in the count
CSV format. Fitting these back with `python -m sim.calibrate --daytype <same>` checks the pipeline
mechanics at city scale; it says nothing about Jeddah realism.

    python -m sim.adapters.baseline_counts --daytype weekday --hours 0-23 --out /tmp/city/counts.csv
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import duckdb
import typer

from sim.adapters import calibrate_config
from sim.adapters.counts import CountRecord, write_counts
from sim.calibrate import latest_baseline
from sim.common import SYNTHETIC_LABEL, rel
from sim.runner import RUNS_DIR


def parse_hours(spec: str) -> list[int]:
    """'0-23' or '7,8,17' -> sorted hour list."""
    hours: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        hours.update(range(int(lo), int(hi or lo) + 1))
    return sorted(hours)


def counts_from_baseline(
    run: Path, hours: list[int], out: Path, seed: int = 1, quiet: bool = False
) -> dict[str, Any]:
    cfg = calibrate_config()
    bc = cfg["baseline_counts"]
    interval = int(cfg["counts"]["interval_s"])
    sample = float(json.loads((run / "meta.json").read_text()).get("sample", 1.0))
    rows = duckdb.sql(
        f"""select edge_id, cast(floor(begin / {interval}) as int) as h, sum(entered) as n
            from read_parquet('{run / "edgedata.parquet"}')
            where begin >= {hours[0] * interval} and begin < {(hours[-1] + 1) * interval}
            group by 1, 2"""
    ).fetchall()
    flows: dict[str, dict[int, float]] = {}
    for edge, hour, n in rows:
        flows.setdefault(edge, {})[hour] = n
    eligible = sorted(
        e
        for e, v in flows.items()
        if all(v.get(h, 0) >= bc["min_each_hour"] for h in hours)
        and sum(v.get(h, 0) for h in hours) >= bc["min_mean_hour"] * len(hours)
    )
    picked = sorted(random.Random(seed).sample(eligible, min(int(bc["detectors"]), len(eligible))))
    records = [
        CountRecord(f"CITY{i:03d}", edge, h, round(flows[edge][h] / sample))
        for i, edge in enumerate(picked, start=1)
        for h in hours
    ]
    write_counts(records, out)
    meta = {
        "label": f"{SYNTHETIC_LABEL} (counts derived from a baseline run, not real data)",
        "baseline_run": run.name,
        "sample": sample,
        "hours": hours,
        "seed": seed,
        "eligible_edges": len(eligible),
        "detectors": len(picked),
        "counts": len(records),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    if not quiet:
        print(f"{len(picked)} of {len(eligible)} eligible edges, {len(records)} counts: {rel(out)}")
    return meta


def main(
    out: Path = typer.Option(..., help="count CSV to write (keep it outside the repo or in /tmp)"),
    daytype: str = typer.Option("weekday", help="baseline day type"),
    hours: str = typer.Option("0-23", help="hours, e.g. 0-23 or 10-11"),
    seed: int = typer.Option(1),
    runs_dir: Path = typer.Option(RUNS_DIR),
) -> None:
    """Write counts derived from the newest baseline of a day type."""
    counts_from_baseline(latest_baseline(daytype, runs_dir), parse_hours(hours), out, seed)


if __name__ == "__main__":
    typer.run(main)
