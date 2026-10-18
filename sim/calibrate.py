"""M8 calibration: fit routes to hourly counts with SUMO's routeSampler.py and report GEH.

Pipeline: count CSV -> edgeData targets (scaled to the population sample) -> routeSampler.py over
candidate routes (by default the day type's baseline routes) -> re-simulate the sampled routes ->
measured edge counts -> GEH per count and the share with GEH < 5 (A-cal-001). An optional
travel-time CSV is compared with the simulated edge travel times (A-cal-002).

    python -m sim.calibrate --counts counts.csv --daytype weekday
    python -m sim.calibrate --counts counts.csv --net data/demo/demo.net.xml \
        --routes candidates.rou.xml --sample 1.0 --seed 1

No Jeddah counts exist yet: the path is dormant and proven on the demo window with synthetic counts
(`python -m sim.adapters.synthetic`). Results stay labelled "synthetic demand, uncalibrated" until a
fit against real counts has been reviewed.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import typer

from sim.adapters import calibrate_config
from sim.adapters.counts import aggregate, check_edges, read_counts, write_edgedata
from sim.adapters.traveltimes import compare, read_travel_times
from sim.common import (
    REPO_ROOT,
    SYNTHETIC_LABEL,
    config_hash,
    content_hash,
    file_hash,
    python_tool_cmd,
    rel,
    sumo_bin,
    sumo_version,
)
from sim.population.baseline import run_measured
from sim.runner import RUNS_DIR, assert_tier_options, flatten, runner_config

# ---------------------------------------------------------------------------- GEH


def geh(model: float, count: float) -> float:
    """GEH statistic for hourly flows: sqrt(2 (m - c)^2 / (m + c)); 0 when both are 0."""
    total = model + count
    return math.sqrt(2.0 * (model - count) ** 2 / total) if total > 0 else 0.0


def geh_report(
    targets: dict[tuple[str, int], float],
    simulated: dict[tuple[str, int], float],
    scale: float = 1.0,
    threshold: float | None = None,
    target_share: float | None = None,
) -> dict[str, Any]:
    """GEH of every count; `simulated` is in sample units, divided by `scale` before comparing."""
    cfg = calibrate_config()["geh"]
    threshold = cfg["threshold"] if threshold is None else threshold
    target_share = cfg["target_share"] if target_share is None else target_share
    rows = []
    for (edge, hour), count in sorted(targets.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        model = simulated.get((edge, hour), 0.0) / scale
        g = geh(model, count)
        rows.append(
            {
                "edge_id": edge,
                "hour": hour,
                "count": round(count, 1),
                "simulated": round(model, 1),
                "geh": round(g, 3),
                "ok": g < threshold,
            }
        )
    n = len(rows)
    share = sum(r["ok"] for r in rows) / n if n else 0.0
    return {
        "counts": n,
        "threshold": threshold,
        "target_share": target_share,
        "share_geh_ok": round(share, 4),
        "passed": share >= target_share,
        "mean_geh": round(sum(r["geh"] for r in rows) / n, 3) if n else None,
        "max_geh": round(max((r["geh"] for r in rows), default=0.0), 3),
        "total_count": round(sum(targets.values()), 1),
        "total_simulated": round(sum(r["simulated"] for r in rows), 1),
        "by_hour": by_hour(rows),
        "rows": rows,
    }


def by_hour(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Per-hour share of GEH-ok counts and simulated/counted volume (boundary effects show here)."""
    out: dict[str, dict[str, float]] = {}
    for hour in sorted({r["hour"] for r in rows}):
        sel = [r for r in rows if r["hour"] == hour]
        counted = sum(r["count"] for r in sel)
        out[str(hour)] = {
            "counts": len(sel),
            "share_geh_ok": round(sum(r["ok"] for r in sel) / len(sel), 4),
            "volume_ratio": round(sum(r["simulated"] for r in sel) / counted, 4)
            if counted
            else 0.0,
        }
    return out


# ---------------------------------------------------------------------------- SUMO I/O


def _open(path: Path) -> IO[bytes]:
    return gzip.open(path, "rb") if str(path).endswith(".gz") else Path(path).open("rb")


def read_edgedata(path: Path, attr: str, interval_s: int = 3600) -> dict[tuple[str, int], float]:
    """Stream an edgeData file into {(edge, hour): value}; values in one hour are summed for counts.

    For `traveltime`, the value of the interval is kept (callers use hourly edgeData).
    """
    out: dict[tuple[str, int], float] = defaultdict(float)
    hour = 0
    with _open(path) as fh:
        for event, elem in ET.iterparse(fh, events=("start", "end")):
            if event == "start" and elem.tag == "interval":
                hour = int(float(elem.get("begin", "0")) // interval_s)
            elif event == "end" and elem.tag == "edge":
                value = elem.get(attr)
                if value is not None:
                    if attr == "traveltime":
                        out[(elem.get("id", ""), hour)] = float(value)
                    else:
                        out[(elem.get("id", ""), hour)] += float(value)
                elem.clear()
    return dict(out)


def iter_vtypes(routes: Path) -> Iterator[ET.Element]:
    with _open(routes) as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "vType":
                yield elem
            elif elem.tag in ("vehicle", "trip", "flow", "person"):
                elem.clear()


def extract_vtypes(routes: Path, out: Path) -> tuple[Path | None, str | None]:
    """routeSampler writes vehicles without vType definitions: copy them to an additional file.

    Returns the file and the vType the sampled vehicles use (config `vehicle_type` if defined in
    the candidates, else the first one found), or (None, None) when the candidates define none.
    """
    seen: dict[str, str] = {}
    for vt in iter_vtypes(routes):
        seen.setdefault(vt.get("id", ""), ET.tostring(vt, encoding="unicode").strip())
    if not seen:
        return None, None
    out.write_text(
        "<additional>\n" + "".join(f"    {v}\n" for v in seen.values()) + "</additional>\n"
    )
    wanted = calibrate_config()["route_sampler"]["vehicle_type"]
    return out, wanted if wanted in seen else next(iter(seen))


def sim_options(mode: str, sample: float) -> list[str]:
    """SUMO options for the round trip: Tier A meso (with the baseline capacity scaling for a
    population sample) or Tier B micro."""
    if mode == "meso":
        from sim.population.baseline import baseline_config, scale_options, tier_a_options

        bcfg = baseline_config()
        _, tau = scale_options(sample, bcfg)
        return [*tier_a_options(bcfg), *tau]
    if mode == "micro":
        rc = runner_config()
        return [*flatten(rc["sumo_common"]), *flatten(rc["tier_B"]["options"])]
    raise ValueError(f"mode must be meso or micro, not {mode!r}")


def simulate(
    net: Path,
    routes: Path,
    out: Path,
    seed: int,
    begin: int,
    end: int,
    mode: str = "meso",
    sample: float = 1.0,
    vtypes: Path | None = None,
    interval_s: int = 3600,
    log: Path | None = None,
) -> tuple[Path, dict[str, float]]:
    """Run SUMO on `routes` with hourly edgeData; return the edgeData path and wall/peak RSS."""
    out.mkdir(parents=True, exist_ok=True)
    add = out / "measure.add.xml"
    add.write_text(
        "<additional>\n"
        f'    <edgeData id="hourly" freq="{interval_s}" file="edgedata_hourly.xml" '
        f'excludeEmpty="true" begin="{begin}" end="{end}"/>\n'
        "</additional>\n"
    )
    adds = [str(vtypes), str(add)] if vtypes else [str(add)]
    args = [
        "-n", str(net),
        "-r", str(routes),
        "--additional-files", ",".join(adds),
        "--begin", str(begin),
        "--end", str(end),
        "--seed", str(seed),
        "--statistic-output", str(out / "stats.xml"),
        *sim_options(mode, sample),
    ]  # fmt: skip
    assert_tier_options("A" if mode == "meso" else "B", args, [add], runner_config())
    timing = run_measured([sumo_bin("sumo"), *args], log or out / "sumo.log")
    return out / "edgedata_hourly.xml", timing


def run_route_sampler(
    routes: Path,
    edgedata: Path,
    out: Path,
    seed: int,
    begin: int,
    end: int,
    mismatch: Path,
    log: Path,
    vtype: str | None = None,
) -> dict[str, float]:
    cfg = calibrate_config()["route_sampler"]
    args = [
        "-r", str(routes),
        "-d", str(edgedata),
        "--edgedata-attribute", cfg["edgedata_attribute"],
        "-o", str(out),
        "--mismatch-output", str(mismatch),
        "-b", str(begin),
        "-e", str(end),
        "-s", str(seed),
        "--prefix", "cal",
        *cfg["extra_options"],
    ]  # fmt: skip
    if vtype:
        args += ["-a", f'type="{vtype}"']
    return run_measured(python_tool_cmd("routeSampler.py", *args), log)


def count_vehicles(routes: Path) -> int:
    n = 0
    with _open(routes) as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "vehicle":
                n += 1
                elem.clear()
    return n


# ---------------------------------------------------------------------------- defaults


def latest_baseline(daytype: str, runs_dir: Path = RUNS_DIR) -> Path:
    """Newest `runs/baseline-<daytype>-*` directory that holds routes and meta.json."""
    found = [
        d
        for d in runs_dir.glob(f"baseline-{daytype}-*")
        if (d / "meta.json").exists() and (d / "routes.rou.xml.gz").exists()
    ]
    if not found:
        raise FileNotFoundError(
            f"no baseline for day type {daytype!r} under {rel(runs_dir)}: run "
            f"`python -m sim.runner --baseline --daytype {daytype}` or pass --net and --routes"
        )
    return max(found, key=lambda d: (d / "meta.json").stat().st_mtime)


def resolve_inputs(
    daytype: str, net: Path | None, routes: Path | None, sample: float | None, runs_dir: Path
) -> tuple[Path, Path, float, str | None]:
    if net is not None and routes is not None:
        return net, routes, 1.0 if sample is None else sample, None
    base = latest_baseline(daytype, runs_dir)
    meta = json.loads((base / "meta.json").read_text())
    net_path = Path(meta["network"])
    net_path = net_path if net_path.is_absolute() else REPO_ROOT / net_path
    return (
        net or net_path,
        routes or base / "routes.rou.xml.gz",
        float(meta.get("sample", 1.0)) if sample is None else sample,
        base.name,
    )


# ---------------------------------------------------------------------------- pipeline


def write_geh_csv(report: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["edge_id", "hour", "count", "simulated", "geh", "ok"]
        )
        writer.writeheader()
        writer.writerows(report["rows"])


def write_markdown(meta: dict[str, Any], path: Path) -> None:
    g = meta["geh"]
    lines = [
        f"# Calibration report: {meta['run_id']}",
        "",
        f"**{meta['label']}.** Counts source: {meta['counts_source']}.",
        "",
        f"- Day type: {meta['daytype']}; seed {meta['seed']}; sample {meta['sample']}; mode "
        f"{meta['mode']}",
        f"- Candidate routes: `{meta['routes']}` ({meta['candidate_vehicles']} vehicles)",
        f"- Sampled routes: {meta['calibrated_vehicles']} vehicles",
        f"- Counts: {g['counts']} (edge, hour) targets, total {g['total_count']} veh; simulated "
        f"{g['total_simulated']} veh",
        f"- **GEH < {g['threshold']:g}: {g['share_geh_ok']:.1%}** of counts (target "
        f"{g['target_share']:.0%}): {'PASS' if g['passed'] else 'FAIL'}; mean GEH {g['mean_geh']}, "
        f"max {g['max_geh']}",
        "",
        "| hour | counts | GEH < threshold | simulated / counted volume |",
        "|---|---|---|---|",
        *(
            f"| {h} | {v['counts']} | {v['share_geh_ok']:.0%} | {v['volume_ratio']:.2f} |"
            for h, v in g["by_hour"].items()
        ),
        "",
    ]
    if meta.get("geh_before"):
        b = meta["geh_before"]
        lines.append(
            f"- Before calibration (candidate routes simulated as they are): GEH < "
            f"{b['threshold']:g} on {b['share_geh_ok']:.1%}, mean GEH {b['mean_geh']}"
        )
    if meta.get("travel_times"):
        t = meta["travel_times"]
        lines.append(
            f"- Travel times: {t['matched']}/{t['segment_hours']} segment-hours matched "
            f"({t['segments']} segments); within "
            f"+/-{t['tolerance']:.0%}: {t['share_within_tolerance']}; mean abs rel error "
            f"{t['mean_abs_rel_error']}"
        )
    lines += [
        "",
        "Per-count GEH: `geh.csv`. routeSampler under/overflow per count: `mismatch.xml`.",
        "Assumptions: A-cal-001 (GEH threshold and target), A-cal-002 (travel-time tolerance), "
        "A-cal-003 (duplicate detectors).",
        "",
    ]
    path.write_text("\n".join(lines))


def calibrate(
    counts: Path,
    daytype: str = "weekday",
    net: Path | None = None,
    routes: Path | None = None,
    sample: float | None = None,
    seed: int = 1,
    mode: str = "meso",
    travel_times: Path | None = None,
    before: bool = False,
    counts_source: str = "unspecified",
    runs_dir: Path = RUNS_DIR,
    quiet: bool = False,
) -> dict[str, Any]:
    cfg = calibrate_config()
    interval = int(cfg["counts"]["interval_s"])
    t0 = time.perf_counter()
    net, routes, sample, baseline_run = resolve_inputs(daytype, net, routes, sample, runs_dir)

    records = read_counts(counts)
    unknown = check_edges(records, net)
    if unknown:
        raise ValueError(f"{len(unknown)} count edges not in {rel(net)}: {unknown[:10]}")
    targets = aggregate(records)
    hours = sorted({h for _, h in targets})
    begin, end = hours[0] * interval, (hours[-1] + 1) * interval
    tail = int(cfg["simulation"]["tail_s"])

    counts_hash = file_hash(counts)
    run_cfg = {
        "daytype": daytype,
        "seed": seed,
        "sample": sample,
        "mode": mode,
        "calibrate": cfg,
        "routes_hash": content_hash(routes),
    }
    chash = config_hash(run_cfg)
    run_id = f"calibrate-{daytype}-s{seed}-{counts_hash[:8]}-{chash[:8]}"
    out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    log = out / "calibrate.log"
    log.unlink(missing_ok=True)
    say = (lambda msg: None) if quiet else (lambda msg: print(f"[{run_id}] {msg}"))

    edgedata = write_edgedata(
        targets, out / "counts.edgedata.xml", scale=sample, interval_s=interval
    )
    vtypes, vtype = extract_vtypes(routes, out / "vtypes.add.xml")
    calibrated = out / "calibrated.rou.xml"
    say(f"routeSampler: {len(targets)} targets over hours {hours[0]}-{hours[-1]}")
    sampler = run_route_sampler(
        routes, edgedata, calibrated, seed, begin, end, out / "mismatch.xml", log, vtype
    )

    say(f"simulating calibrated routes ({mode})")
    measured, sim_timing = simulate(
        net, calibrated, out / "sim", seed, begin, end + tail, mode, sample, vtypes, interval, log
    )
    entered = read_edgedata(measured, cfg["simulation"]["measure_attribute"], interval)
    report = geh_report(targets, entered, scale=sample)

    meta: dict[str, Any] = {
        "run_id": run_id,
        "label": SYNTHETIC_LABEL,
        "calibration_status": "fitted, not reviewed",
        "kind": "calibration",
        "daytype": daytype,
        "seed": seed,
        "sample": sample,
        "mode": mode,
        "config_hash": chash,
        "counts": rel(counts),
        "counts_hash": counts_hash,
        "counts_source": counts_source,
        "network": rel(net),
        "network_hash": content_hash(net),
        "routes": rel(routes),
        "routes_hash": run_cfg["routes_hash"],
        "baseline_run": baseline_run,
        "calibrated_routes_hash": content_hash(calibrated),
        "calibrated_vtype": vtype,
        "sumo_version": sumo_version(),
        "candidate_vehicles": count_vehicles(routes),
        "calibrated_vehicles": count_vehicles(calibrated),
        "hours": hours,
        "timings": {"route_sampler": sampler, "simulation": sim_timing},
        "geh": {k: v for k, v in report.items() if k != "rows"},
    }
    if before:
        say("simulating candidate routes unchanged (before-calibration reference)")
        ref, _ = simulate(
            net, routes, out / "sim_before", seed, begin, end + tail, mode, sample, None, interval
        )
        ref_report = geh_report(targets, read_edgedata(ref, "entered", interval), scale=sample)
        meta["geh_before"] = {k: v for k, v in ref_report.items() if k != "rows"}
    if travel_times is not None:
        tt = compare(
            read_travel_times(travel_times), read_edgedata(measured, "traveltime", interval)
        )
        meta["travel_times"] = {k: v for k, v in tt.items() if k != "rows"}
        (out / "traveltimes.json").write_text(json.dumps(tt, indent=2))
    meta["timings"]["total_s"] = round(time.perf_counter() - t0, 1)

    write_geh_csv(report, out / "geh.csv")
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    write_markdown(meta, out / "report.md")
    if not quiet:
        g = meta["geh"]
        print(
            f"[{run_id}] GEH < {g['threshold']:g} on {g['share_geh_ok']:.1%} of {g['counts']} "
            f"counts (target {g['target_share']:.0%}): {'PASS' if g['passed'] else 'FAIL'}\n"
            f"  report: {rel(out / 'report.md')}  ({SYNTHETIC_LABEL})"
        )
    return meta


def main(
    counts: Path = typer.Option(..., help="count CSV: detector_id, edge_id, hour, count"),
    daytype: str = typer.Option("weekday", help="day type; selects the baseline routes"),
    net: Path | None = typer.Option(None, help="network (default: the baseline's)"),
    routes: Path | None = typer.Option(None, help="candidate routes (default: baseline routes)"),
    sample: float | None = typer.Option(
        None, help="population sample of the candidate routes (default: baseline's, else 1.0)"
    ),
    seed: int = typer.Option(1),
    mode: str = typer.Option("meso", help="meso (Tier A) or micro (Tier B window)"),
    travel_times: Path | None = typer.Option(None, help="travel-time CSV to validate against"),
    before: bool = typer.Option(False, help="also simulate the uncalibrated candidates"),
    counts_source: str = typer.Option("unspecified", help="free text: who supplied the counts"),
    runs_dir: Path = typer.Option(RUNS_DIR),
) -> None:
    """Fit routes to counts with routeSampler.py and write a GEH report under runs/."""
    meta = calibrate(
        counts, daytype, net, routes, sample, seed, mode, travel_times, before, counts_source,
        runs_dir,
    )  # fmt: skip
    if not meta["geh"]["passed"]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    typer.run(main)
