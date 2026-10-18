"""Tier A 24-hour baseline: population -> vehicle trips -> duaIterate -> final meso run -> KPIs.

    python -m sim.runner --baseline --daytype weekday --sample 0.10 --seed 1

Routes are cached by (network hash, population hash, day type, seed, assignment settings) under
`data/population/routes/`, so re-running a baseline (or a policy that leaves the demand unchanged)
skips the assignment. Every run writes `runs/<id>/` with meta.json (seed, config hash, population
hash, network hash, SUMO version, runtime and peak memory), metrics.json, Parquet tables and plots.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from sim.common import (
    REPO_ROOT,
    SYNTHETIC_LABEL,
    config_hash,
    content_hash,
    load_yaml,
    python_tool_cmd,
    rel,
    sumo_bin,
    sumo_env,
    sumo_version,
)
from sim.population.activities import activities_config, load_or_generate
from sim.population.export_trips import export
from sim.population.modes import assign_modes, mode_summary, vehicle_trips
from sim.population.plots import trips_per_person_table

BASELINE_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "baseline.yaml"
ROUTE_CACHE = REPO_ROOT / "data" / "population" / "routes"


def baseline_config(path: Path = BASELINE_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


# ---------------------------------------------------------------------------- measuring


def run_measured(cmd: list[str], log: Path, cwd: Path = REPO_ROOT) -> dict[str, float]:
    """Run a command (and its children), logging output; return wall seconds and peak RSS (MB)."""
    prefix = f"{REPO_ROOT}/"
    if cwd == REPO_ROOT:
        cmd = [str(c).replace(prefix, "") for c in cmd]
    log.parent.mkdir(parents=True, exist_ok=True)
    peak = 0.0
    with log.open("a") as fh:
        fh.write(f"$ {' '.join(map(str, cmd))}\n")
        fh.flush()
        t0 = time.perf_counter()
        proc = subprocess.Popen(
            [str(c) for c in cmd], stdout=fh, stderr=subprocess.STDOUT, cwd=cwd, env=sumo_env()
        )
        done = threading.Event()

        def poll() -> None:
            nonlocal peak
            try:
                root = psutil.Process(proc.pid)
            except psutil.NoSuchProcess:
                return
            while not done.is_set():
                total = 0
                try:
                    for p in [root, *root.children(recursive=True)]:
                        with contextlib.suppress(psutil.Error):
                            total += p.memory_info().rss
                except psutil.Error:
                    pass
                peak = max(peak, total / 2**20)
                done.wait(0.5)

        watcher = threading.Thread(target=poll, daemon=True)
        watcher.start()
        code = proc.wait()
        done.set()
        watcher.join()
        wall = time.perf_counter() - t0
    if code != 0:
        raise RuntimeError(f"command failed with code {code} (see {log}): {' '.join(cmd[:3])} ...")
    return {"wall_s": round(wall, 1), "peak_rss_mb": round(peak, 1)}


# ---------------------------------------------------------------------------- SUMO options


def scale_options(sample: float, cfg: dict[str, Any]) -> tuple[float, list[str]]:
    """Capacity scale (1/sample) and the meso headway options that implement it."""
    cs = cfg["capacity_scaling"]
    if not cs.get("enabled", True) or sample >= 1.0:
        return 1.0, []
    scale = 1.0 / sample
    opts: list[str] = []
    for name, value in cs["meso_tau_defaults"].items():
        opts += [f"--meso-{name}", f"{float(value) * scale:.3f}"]
    return scale, opts


def tier_a_options(cfg: dict[str, Any] | None = None) -> list[str]:
    """Shared Tier A options (sim/config/runner.yaml) with the baseline overrides applied."""
    from sim.runner import flatten, runner_config

    cfg = cfg or baseline_config()
    rc = runner_config()
    opts = [*flatten(rc["sumo_common"]), *flatten(rc["tier_A"]["options"])]
    over = cfg.get("tier_A_overrides", {})
    replace = over.get("replace", {})
    opts = [replace.get(o, o) for o in opts]
    for flag, value in over.get("set", {}).items():
        if flag in opts:
            opts[opts.index(flag) + 1] = str(value)
        else:
            opts += [flag, str(value)]
    return opts


def dua_command(
    net: Path, trips: Path, end: int, cfg: dict[str, Any], tau_opts: list[str], seed: int
) -> list[str]:
    a = cfg["assignment"]
    rc_opts = tier_a_options(cfg)
    tls = (
        rc_opts[rc_opts.index("--meso-tls-penalty") + 1]
        if "--meso-tls-penalty" in rc_opts
        else None
    )
    ttt = rc_opts[rc_opts.index("--time-to-teleport") + 1]
    cmd = python_tool_cmd(
        "assign/duaIterate.py",
        "-n", str(net),
        "-t", str(trips),
        "-b", str(cfg["begin"]),
        "-e", str(end),
        "-l", str(a["iterations"]),
        "-a", str(a["aggregation_s"]),
        "--mesosim",
        "--meso-junctioncontrollimited"
        if "--meso-junction-control.limited" in rc_opts
        else "--meso-junctioncontrol",
        "--time-to-teleport", ttt,
        "--routing-algorithm", str(a["routing_algorithm"]),
        "--max-alternatives", str(a["max_alternatives"]),
        *[str(x) for x in a.get("extra", [])],
    )  # fmt: skip
    if tls is not None:
        cmd += ["--meso-tls-penalty", tls]
    if int(a.get("inc_base", 0)) > 0:
        cmd += ["--inc-base", str(a["inc_base"]), "--inc-max", "1"]
    # the run seed reaches every router and simulation step, so routes follow from the seed
    cmd += ["duarouter--routing-threads", str(a["routing_threads"])]
    cmd += ["duarouter--seed", str(seed), "sumo--seed", str(seed)]
    for k in range(0, len(tau_opts), 2):
        cmd += [f"sumo{tau_opts[k]}", tau_opts[k + 1]]
    cmd += ["sumo--ignore-route-errors", "true"]
    return cmd


def last_routes(work: Path, iterations: int) -> Path:
    step = work / f"{iterations - 1:03d}"
    found = sorted(p for p in step.glob("*.rou.xml*") if ".alt." not in p.name)
    if not found:
        raise FileNotFoundError(f"no routes in {step}")
    return found[0]


# ---------------------------------------------------------------------------- baseline


def run_baseline(
    daytype: str = "weekday",
    seed: int = 1,
    sample: float = 0.10,
    net: Path | None = None,
    runs_dir: Path | None = None,
    iterations: int | None = None,
    end: int | None = None,
    zone_dir: Path | None = None,
    quiet: bool = False,
    routing_threads: int | None = None,
    gz: bool = False,
) -> dict[str, Any]:
    from sim import metrics
    from sim.metrics import xml_content_hash
    from sim.runner import assert_tier_options, runner_config

    cfg = baseline_config()
    if iterations is not None:
        cfg["assignment"]["iterations"] = iterations
    if routing_threads:
        # not repeatable: the run records routes_deterministic false (TA-015)
        cfg["assignment"] = {**cfg["assignment"], "routing_threads": routing_threads}
    ext = ".xml.gz" if gz else ".xml"  # gzip: 10 % city outputs are ~3 GB uncompressed (TA-016)
    net = Path(net or REPO_ROOT / cfg["net"])
    runs_dir = Path(runs_dir or REPO_ROOT / "runs")
    sim_end = int(end if end is not None else cfg["end"])
    run_end = sim_end + int(cfg["drain_s"])
    timings: dict[str, Any] = {}

    t0 = time.perf_counter()
    pop, trips, tmeta = load_or_generate(seed, sample, daytype, zone_dir)
    trips = assign_modes(trips, pop, seed, daytype, zone_dir=zone_dir)
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, seed, daytype, speed)
    veh = veh[veh["depart"] < sim_end].reset_index(drop=True)
    timings["demand_s"] = round(time.perf_counter() - t0, 1)

    nhash = content_hash(net)
    scale, tau_opts = scale_options(sample, cfg)
    run_cfg = {
        "daytype": daytype,
        "seed": seed,
        "sample": sample,
        "end": sim_end,
        "baseline": cfg,
        "tier_A": tier_a_options(),
    }
    chash = config_hash(run_cfg)
    phash = pop.meta["population_hash"]
    run_id = f"baseline-{daytype}-f{sample:g}-s{seed}-{nhash[:8]}-{phash[:8]}-{chash[:6]}"
    out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
    log.unlink(missing_ok=True)
    demand = export(veh, out, scale)
    trips_per_person_table(
        trips["person_id"], veh.loc[~veh["empty"], "person_id"], len(pop.persons)
    ).to_parquet(out / "person_trips_per_person.parquet", index=False)

    # assignment (cached)
    route_key = config_hash(
        {
            "net": nhash,
            "population": phash,
            "daytype": daytype,
            "seed": seed,
            "vehicles": demand["vehicles_hash"],
            "assignment": cfg["assignment"],
            "scale": scale,
            "end": run_end,
            "tier_A": tier_a_options(),
        }
    )
    cache = ROUTE_CACHE / route_key
    routes = cache / "routes.rou.xml.gz"
    if routes.exists():
        timings["assignment"] = {"cached": True}
    else:
        work = cache / "dua"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        cmd = dua_command(
            net.resolve(), (out / "trips.xml").resolve(), run_end, cfg, tau_opts, seed
        )
        if not quiet:
            print(f"[{run_id}] duaIterate x{cfg['assignment']['iterations']} -> {rel(work)}")
        timings["assignment"] = run_measured(cmd, out / "dua.log", cwd=work)
        timings["assignment"]["cached"] = False
        shutil.copyfile(last_routes(work, int(cfg["assignment"]["iterations"])), routes)
        (cache / "key.json").write_text(json.dumps({"route_key": route_key, "run": run_id}))
        shutil.rmtree(work)
    shutil.copyfile(routes, out / "routes.rou.xml.gz")

    # final simulation with outputs
    add = out / "outputs.add.xml"
    add.write_text(
        "<additional>\n"
        f'    <edgeData id="ed" freq="{cfg["edgedata_freq_s"]}" file="edgedata{ext}" '
        f'excludeEmpty="true" begin="0" end="{run_end}"/>\n'
        f'    <edgeData id="em" type="emissions" freq="{cfg["emissions_freq_s"]}" '
        f'file="emissions{ext}" excludeEmpty="true" begin="0" end="{run_end}"/>\n'
        "</additional>\n"
    )
    args = [
        "-n", str(net),
        "-r", str(out / "routes.rou.xml.gz"),
        "--additional-files", str(add),
        "--begin", str(cfg["begin"]),
        "--end", str(run_end),
        "--seed", str(seed),
        "--tripinfo-output", str(out / f"tripinfo{ext}"),
        "--device.emissions.probability", "1",
        "--statistic-output", str(out / "stats.xml"),
        "--log", str(out / "sumo.log"),
        *tier_a_options(),
        *tau_opts,
    ]  # fmt: skip
    assert_tier_options("A", args, [add], runner_config())
    if not quiet:
        print(f"[{run_id}] final meso run ({run_end} s)")
    timings["simulation"] = run_measured([sumo_bin("sumo"), *args], log)

    # outputs -> Parquet, metrics, plots
    t2 = time.perf_counter()
    meta = {
        "run_id": run_id,
        "label": SYNTHETIC_LABEL,
        "kind": "baseline",
        "tier": "A",
        "mode": "meso",
        "daytype": daytype,
        "date": tmeta["date"],
        "seed": seed,
        "sample": sample,
        "capacity_scale": scale,
        "config_hash": chash,
        "network": rel(net),
        "network_hash": nhash,
        "population_hash": phash,
        "zones_hash": pop.meta["zones_hash"],
        "trips_hash": tmeta["trips_hash"],
        "vehicles_hash": demand["vehicles_hash"],
        "route_key": route_key,
        # multi-threaded duarouter is not repeatable even with a seed; such routes are reproducible
        # from the route cache only (TA-013)
        "routes_deterministic": int(cfg["assignment"]["routing_threads"]) == 1,
        "routes_hash": xml_content_hash(out / "routes.rou.xml.gz"),
        "sumo_version": sumo_version(),
        "sim_end_s": sim_end,
        "run_end_s": run_end,
        "persons": len(pop.persons),
        "vehicles": demand["vehicles"],
        "demand": mode_summary(trips, len(pop.persons)),
        "timings": timings,
    }
    report = metrics.process_run(out, meta)
    timings["postprocess_s"] = round(time.perf_counter() - t2, 1)
    timings["total_s"] = round(time.perf_counter() - t0, 1)
    meta["result"] = report["summary"]
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    if not quiet:
        print(metrics.format_summary(meta, report))
    return meta
