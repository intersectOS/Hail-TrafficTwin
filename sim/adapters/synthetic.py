"""Synthetic counts for the calibration round trip (NOT real data).

Simulates a "truth" demand (random trips, one seed) on a network, measures hourly edge counts and
travel times, and samples detector edges from it; then routes an unrelated candidate demand
(random trips, another seed) for routeSampler to choose from. The outputs prove the calibration
pipeline end to end where no Jeddah counts exist.

    python -m sim.adapters.synthetic --net data/demo/demo.net.xml --out runs/synthetic-demo --seed 1
    python -m sim.calibrate --counts runs/synthetic-demo/counts.csv --net data/demo/demo.net.xml \
        --routes runs/synthetic-demo/candidates.rou.xml --sample 1.0 \
        --travel-times runs/synthetic-demo/traveltimes.csv --counts-source synthetic --before
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import typer

from sim.adapters import calibrate_config
from sim.adapters.counts import CountRecord, write_counts
from sim.adapters.traveltimes import TravelTimeRecord, write_travel_times
from sim.common import SYNTHETIC_LABEL, content_hash, rel
from sim.runner import make_random_trips


def make_synthetic(
    net: Path, out: Path, seed: int = 1, mode: str = "meso", quiet: bool = False
) -> dict[str, Any]:
    from sim.calibrate import read_edgedata, simulate

    cfg = calibrate_config()
    syn = cfg["synthetic"]
    interval = int(cfg["counts"]["interval_s"])
    begin, end = int(syn["begin"]), int(syn["end"])
    tail = int(cfg["simulation"]["tail_s"])
    out.mkdir(parents=True, exist_ok=True)
    log = out / "synthetic.log"
    log.unlink(missing_ok=True)

    # truth demand -> hourly measurements
    truth = out / "truth.rou.xml"
    make_random_trips(
        net, out / "truth.trips.xml", syn["truth_trips"], seed, begin, end, truth, log
    )
    measured, _ = simulate(net, truth, out / "truth_sim", seed, begin, end + tail, mode, 1.0, None,
                        interval, log)  # fmt: skip
    entered = read_edgedata(measured, "entered", interval)
    traveltime = read_edgedata(measured, "traveltime", interval)
    hours = list(range(begin // interval, end // interval))

    # detectors: edges whose flow reaches the minimum in every counted hour
    eligible = [
        e
        for e in sorted({e for e, _ in entered})
        if all(entered.get((e, h), 0) >= syn["min_hourly_count"] for h in hours)
    ]
    rng = random.Random(seed)
    chosen = sorted(rng.sample(eligible, min(int(syn["detectors"]), len(eligible))))
    records = [
        CountRecord(f"SYN{i:03d}", edge, h, entered[(edge, h)])
        for i, edge in enumerate(chosen, start=1)
        for h in hours
    ]
    write_counts(records, out / "counts.csv")

    # travel-time segments: single detector edges (adjacent-edge corridors would need routing)
    tt_edges = chosen[: int(syn["travel_time_segments"])]
    tt_records = [
        TravelTimeRecord(f"SEG{i:03d}", (edge,), h, traveltime[(edge, h)], int(entered[(edge, h)]))
        for i, edge in enumerate(tt_edges, start=1)
        for h in hours
        if (edge, h) in traveltime
    ]
    write_travel_times(tt_records, out / "traveltimes.csv")

    # unrelated candidate routes
    candidates = out / "candidates.rou.xml"
    cand_seed = seed + int(syn["candidate_seed_offset"])
    make_random_trips(
        net, out / "candidates.trips.xml", syn["candidate_trips"], cand_seed, begin, end,
        candidates, log,
    )  # fmt: skip

    per_hour: dict[int, float] = defaultdict(float)
    for r in records:
        per_hour[r.hour] += r.count
    meta = {
        "label": f"{SYNTHETIC_LABEL} (synthetic counts for the round-trip test, not real data)",
        "network": rel(net),
        "network_hash": content_hash(net),
        "seed": seed,
        "candidate_seed": cand_seed,
        "mode": mode,
        "hours": hours,
        "eligible_edges": len(eligible),
        "detectors": len(chosen),
        "counts": len(records),
        "count_total_per_hour": {str(h): v for h, v in sorted(per_hour.items())},
        "travel_time_rows": len(tt_records),
        "truth_routes_hash": content_hash(truth),
        "candidate_routes_hash": content_hash(candidates),
        "counts_hash": content_hash(out / "counts.csv"),
    }
    (out / "synthetic.json").write_text(json.dumps(meta, indent=2))
    if not quiet:
        print(
            f"synthetic counts: {len(chosen)} detectors x {len(hours)} h = {len(records)} counts "
            f"-> {rel(out / 'counts.csv')}; candidates {rel(candidates)}"
        )
    return meta


def main(
    net: Path = typer.Option(Path("data/demo/demo.net.xml"), help="network"),
    out: Path = typer.Option(Path("runs/synthetic-demo"), help="output directory"),
    seed: int = typer.Option(1),
    mode: str = typer.Option("meso", help="meso or micro"),
) -> None:
    """Write synthetic counts, travel times and candidate routes for the calibration round trip."""
    make_synthetic(net, out, seed, mode)


if __name__ == "__main__":
    typer.run(main)
