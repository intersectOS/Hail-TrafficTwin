"""Run a policy at Tier A against the matching baseline (PROJECT.md 7, 9.6).

    python -m sim.runner --policy remote_work_30 --daytype weekday --sample 0.10 --seed 1
    python -m sim.policies.run remote_work_30 --daytype weekday            # same, direct

1. Baselines: the comparison baseline is the `--daytype` baseline; the run starts from the baseline
   of the policy's `daytype` transform if it has one (Friday, Ramadan), else from the same one.
   Both are found under `runs/` (same day type, sample, seed, network and population) or run.
2. The policy's transforms edit the starting baseline's trips and vehicles (transforms.py).
3. Incremental routing (TA-014): unchanged vehicles keep their baseline route; the others get a
   one-shot route on the starting baseline's congested travel times (+ policy penalties).
4. The final 24 h meso run uses exactly the baseline's simulation options, then KPIs
   (sim/metrics.py) and the policy report (sim/policies/report.py) in `runs/<id>/`.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, content_hash, load_yaml, rel
from sim.policies.transforms import Plan, apply
from sim.schemas import DayTypeChange, Policy, load_policy

POLICY_DIR = REPO_ROOT / "sim" / "policies"
RUN_CONFIG = POLICY_DIR / "config" / "policy_run.yaml"
RUNS_DIR = REPO_ROOT / "runs"
DEFAULT_SAMPLE = 0.10
DEFAULT_SEED = 1
LINKED_OUTPUTS = ("tripinfo.parquet", "edgedata.parquet", "emissions.parquet", "stats.xml")


def run_config(path: Path = RUN_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


def resolve_policy(policy: str | Path | Policy) -> tuple[Policy, Path | None]:
    if isinstance(policy, Policy):
        return policy, None
    path = Path(policy)
    if not path.suffix:
        path = POLICY_DIR / f"{policy}.yaml"
    return load_policy(path), path


def base_daytype(pol: Policy, compare: str) -> str:
    for t in pol.transforms:
        if isinstance(t, DayTypeChange):
            return t.daytype
    return compare


def run_name(pol: Policy, daytype: str, sample: float, seed: int) -> str:
    """runs/<policy id>, with suffixes only where the run differs from the policy's defaults."""
    name = pol.id
    if daytype != pol.daytype:
        name += f"-vs-{daytype}"
    if sample != DEFAULT_SAMPLE:
        name += f"-f{sample:g}"
    if seed != DEFAULT_SEED:
        name += f"-s{seed}"
    return name


def net_path(meta: dict[str, Any]) -> Path:
    p = Path(meta["network"])
    return p if p.is_absolute() else REPO_ROOT / p


# ---------------------------------------------------------------------------- baselines


def find_baseline(
    daytype: str, sample: float, seed: int, net: Path, runs_dir: Path, zone_dir: Path | None
) -> Path | None:
    """Newest completed baseline run for (day type, sample, seed, network, population)."""
    from sim.population.synthesize import load_or_synthesize

    nhash = content_hash(net)
    phash = load_or_synthesize(seed, sample, zone_dir).meta["population_hash"]
    found = []
    for meta_path in Path(runs_dir).glob(f"baseline-{daytype}-f{sample:g}-s{seed}-*/meta.json"):
        meta = json.loads(meta_path.read_text())
        d = meta_path.parent
        ok = meta.get("network_hash") == nhash and meta.get("population_hash") == phash
        ok &= all(
            (d / f).exists() for f in ("metrics.json", "routes.rou.xml.gz", "edgedata.parquet")
        )
        if ok:
            found.append((meta_path.stat().st_mtime, d))
    return max(found)[1] if found else None


def ensure_baseline(
    daytype: str,
    sample: float,
    seed: int,
    net: Path,
    runs_dir: Path,
    zone_dir: Path | None,
    iterations: int | None,
    quiet: bool,
) -> Path:
    found = find_baseline(daytype, sample, seed, net, runs_dir, zone_dir)
    if found is not None:
        return found
    from sim.population.baseline import run_baseline

    if not quiet:
        typer.echo(f"no {daytype} baseline (sample {sample:g}, seed {seed}) found: running it")
    meta = run_baseline(daytype, seed, sample, net, runs_dir, iterations, zone_dir=zone_dir,
                        quiet=quiet)  # fmt: skip
    return Path(runs_dir) / meta["run_id"]


def vehicle_table(veh: pd.DataFrame) -> pd.DataFrame:
    """The exported vehicle table (same columns and types as sim.population.export_trips)."""
    from sim.population.export_trips import VEHICLE_COLUMNS

    table = veh[VEHICLE_COLUMNS].copy()
    for col in ("vtype", "purpose", "segment", "mode"):
        table[col] = table[col].astype(str)
    return table


def build_plan(base_dir: Path, zone_dir: Path | None, work: Path) -> Plan:
    """The starting baseline's trips and vehicles, recomputed and checked against its hash."""
    from sim.population.activities import activities_config, load_or_generate
    from sim.population.modes import assign_modes, vehicle_trips
    from sim.population.sampling import frame_hash

    meta = json.loads((base_dir / "meta.json").read_text())
    daytype, seed, sample = meta["daytype"], int(meta["seed"]), float(meta["sample"])
    sim_end = float(meta["sim_end_s"])
    pop, trips, _ = load_or_generate(seed, sample, daytype, zone_dir)
    trips = assign_modes(trips, pop, seed, daytype, zone_dir=zone_dir)
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, seed, daytype, speed)
    veh = veh[veh["depart"] < sim_end].reset_index(drop=True)
    vhash = frame_hash(vehicle_table(veh))
    if vhash != meta["vehicles_hash"]:
        raise RuntimeError(
            f"baseline {base_dir.name} was built from other demand (vehicles hash {vhash} != "
            f"{meta['vehicles_hash']}); re-run the baseline"
        )
    return Plan(
        daytype=daytype, seed=seed, sample=sample, sim_end=sim_end, pop=pop, trips=trips,
        vehicles=veh, net=net_path(meta), work=work, zone_dir=zone_dir,
        base_routes=base_dir / "routes.rou.xml.gz",
    )  # fmt: skip


# ---------------------------------------------------------------------------- run


def run_policy(
    policy: str | Path | Policy,
    daytype: str | None = None,
    sample: float = DEFAULT_SAMPLE,
    seed: int = DEFAULT_SEED,
    runs_dir: Path | None = None,
    net: Path | None = None,
    zone_dir: Path | None = None,
    baselines_dir: Path | None = None,
    iterations: int | None = None,
    quiet: bool = False,
    force_simulate: bool = False,
    sim_seed: int | None = None,
    run_id: str | None = None,
    placebo_reroute_share: float = 0.0,
    control_ids: set[str] | None = None,
    with_control: bool = True,
) -> dict[str, Any]:
    """`sim_seed` (default: `seed`) re-seeds only the final simulation: a no-change policy with
    another sim seed measures the run-to-run noise of the meso run (replicate).

    Matched control (TA-018): one-shot routes are better than the baseline's 3-step assignment
    (re-routing 8 % of unchanged vehicles cuts city delay by ~20 %), so when a policy re-routes
    vehicles that exist in the baseline, a control run re-routes the same vehicles at their
    baseline times without the policy, and the report compares the policy with that control.
    `control_ids` makes this run such a control."""
    from sim import metrics
    from sim.common import sumo_bin, sumo_version
    from sim.metrics import xml_content_hash
    from sim.policies import routes as R
    from sim.policies.report import write_policy_report
    from sim.population.baseline import (
        baseline_config,
        run_measured,
        scale_options,
        tier_a_options,
    )
    from sim.population.export_trips import vtype_lines, write_trips
    from sim.runner import assert_tier_options, runner_config

    t0 = time.perf_counter()
    pol, pol_path = resolve_policy(policy)
    compare_day = daytype or pol.daytype
    start_day = base_daytype(pol, compare_day)
    bcfg = baseline_config()
    rcfg = run_config()
    net = Path(net or REPO_ROOT / bcfg["net"])
    runs_dir = Path(runs_dir or RUNS_DIR)
    baselines_dir = Path(baselines_dir or runs_dir)
    say = (lambda *_: None) if quiet else typer.echo
    ref_dir = ensure_baseline(compare_day, sample, seed, net, baselines_dir, zone_dir, iterations,
                              quiet)  # fmt: skip
    base_dir = (
        ref_dir
        if start_day == compare_day
        else ensure_baseline(
            start_day, sample, seed, net, baselines_dir, zone_dir, iterations, quiet
        )  # fmt: skip
    )
    base_meta = json.loads((base_dir / "meta.json").read_text())
    sim_seed = seed if sim_seed is None else sim_seed
    run_id = run_id or run_name(pol, compare_day, sample, seed)
    out = runs_dir / run_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    timings: dict[str, Any] = {}

    # 1. transforms
    say(f"[{run_id}] transforms on {base_dir.name}")
    plan = build_plan(base_dir, zone_dir, out)
    for t in pol.transforms:
        eff = apply(plan, t, pol.id)
        say(f"  {t.type}: " + ", ".join(f"{k}={v}" for k, v in eff.items() if k != "type"))
    veh = plan.finalize()
    timings["transforms_s"] = round(time.perf_counter() - t0, 1)

    # 2. which vehicles keep their baseline route
    base_v = pd.read_parquet(base_dir / "vehicles.parquet",
                             columns=["veh_id", "vtype", "depart", "o_edge", "d_edge"])  # fmt: skip
    m = veh[["veh_id", "vtype", "depart", "o_edge", "d_edge"]].merge(
        base_v, on="veh_id", how="left", suffixes=("", "_b")
    )
    # a vType change within the same vehicle class (car <-> ride-hail) keeps the route
    from sim.population.export_trips import export_config

    vclass = {k: v["vClass"] for k, v in export_config()["vtypes"].items() if isinstance(v, dict)}
    same = (
        (m["vtype"].astype(str).map(vclass) == m["vtype_b"].map(vclass))
        & (m["depart"] == m["depart_b"])
        & (m["o_edge"].astype(str) == m["o_edge_b"])
        & (m["d_edge"].astype(str) == m["d_edge_b"])
    )
    if placebo_reroute_share > 0:
        # placebo: re-route a random share of unchanged vehicles without changing their trips;
        # measures the gain one-shot routes have over the baseline's assignment (TA-018)
        ids = np.sort(m.loc[same.to_numpy(), "veh_id"].to_numpy().astype(str))
        u = np.random.default_rng(seed).random(len(ids))
        plan.force_reroute |= set(ids[u < placebo_reroute_share])
    if control_ids:
        plan.force_reroute |= set(control_ids)
    reuse = set(m.loc[same.to_numpy(), "veh_id"]) - plan.force_reroute
    need = veh[~veh["veh_id"].isin(reuse)]
    unchanged = (
        need.empty
        and len(reuse) == len(base_v)
        and not plan.extra_routes
        and not plan.additional
        and plan.net == net_path(base_meta)
    )
    scale, tau_opts = scale_options(sample, bcfg)
    run_end = float(base_meta["run_end_s"])
    sim_end = float(base_meta["sim_end_s"])
    table = vehicle_table(veh)
    table.to_parquet(out / "vehicles.parquet", index=False)
    from sim.population.sampling import frame_hash

    vhash = frame_hash(table)
    routing: dict[str, Any] = {"vehicles": len(veh), "to_route": len(need), "reused": len(reuse)}

    if unchanged and not force_simulate:
        # nothing to simulate: the policy run is the starting baseline (hard links, no copies)
        say(f"[{run_id}] no vehicle changed: outputs are those of {base_dir.name}")
        for name in LINKED_OUTPUTS:
            if (base_dir / name).exists():
                os.link(base_dir / name, out / name)
        routes_hash = base_meta.get("routes_hash")
        timings["simulation"] = {"reused_from": base_dir.name}
    else:
        new_routes = None
        if len(need):
            t1 = time.perf_counter()
            rr = rcfg["reroute"]
            interval = float(rr["weights_interval_s"])
            edges = plan.edges()
            cong = R.congested_weights(base_dir / "edgedata.parquet", edges, interval,
                                       float(rr["weights_min_ratio"]))  # fmt: skip
            nweights = R.write_weights(out / "weights.xml.gz", cong, edges, interval, run_end,
                                       plan.penalties)  # fmt: skip
            write_trips(need, out / "reroute.trips.xml", scale)
            new_routes = out / "reroute.rou.xml.gz"
            cmd = R.reroute_command(
                plan.net, out / "reroute.trips.xml", out / "weights.xml.gz", new_routes,
                out / "reroute.vtypes.xml", seed, run_end, rr,
            )  # fmt: skip
            routing["duarouter"] = run_measured(cmd, out / "reroute.log")
            routing["weights_rows"] = nweights
            timings["reroute_s"] = round(time.perf_counter() - t1, 1)
            (out / "reroute.trips.xml").unlink()
            (out / "reroute.rou.alt.xml.gz").unlink(missing_ok=True)
            (out / "weights.xml.gz").unlink()
        t2 = time.perf_counter()
        changed_type = m[same.to_numpy() & (m["vtype"].astype(str) != m["vtype_b"])]
        retype = dict(zip(changed_type["veh_id"], changed_type["vtype"].astype(str), strict=True))
        routing["retyped"] = len(retype)
        counts = R.merge_routes(plan.base_routes, new_routes, reuse, out / "routes.rou.xml.gz",
                                vtype_lines(scale), retype)  # fmt: skip
        routing |= counts
        routing["unroutable"] = len(need) - counts["rerouted"]
        routes_hash = xml_content_hash(out / "routes.rou.xml.gz")
        timings["merge_s"] = round(time.perf_counter() - t2, 1)
        add = out / "outputs.add.xml"
        add.write_text(
            "<additional>\n"
            f'    <edgeData id="ed" freq="{bcfg["edgedata_freq_s"]}" file="edgedata.xml.gz" '
            f'excludeEmpty="true" begin="0" end="{run_end:.0f}"/>\n'
            f'    <edgeData id="em" type="emissions" freq="{bcfg["emissions_freq_s"]}" '
            f'file="emissions.xml.gz" excludeEmpty="true" begin="0" end="{run_end:.0f}"/>\n'
            "</additional>\n"
        )
        route_files = [out / "routes.rou.xml.gz", *plan.extra_routes]
        additional = [add, *plan.additional]
        args = [
            "-n", str(plan.net),
            "-r", ",".join(str(p) for p in route_files),
            "--additional-files", ",".join(str(p) for p in additional),
            "--begin", str(bcfg["begin"]),
            "--end", f"{run_end:.0f}",
            "--seed", str(sim_seed),
            "--tripinfo-output", str(out / "tripinfo.xml.gz"),
            "--device.emissions.probability", "1",
            "--statistic-output", str(out / "stats.xml"),
            "--log", str(out / "sumo.log"),
            *tier_a_options(),
            *tau_opts,
        ]  # fmt: skip
        assert_tier_options("A", args, additional, runner_config())
        say(f"[{run_id}] meso run: {counts['reused']:,} baseline routes, "
            f"{counts['rerouted']:,} new routes")  # fmt: skip
        timings["simulation"] = run_measured([sumo_bin("sumo"), *args], out / "build.log")
        (out / "routes.rou.xml.gz").unlink()  # reproducible from the baseline + reroute.rou.xml.gz

    # 3. KPIs and the policy report
    t3 = time.perf_counter()
    meta = {
        "run_id": run_id,
        "label": SYNTHETIC_LABEL,
        "kind": "policy",
        "policy": pol.id,
        "policy_title": pol.title,
        "policy_file": rel(pol_path) if pol_path else None,
        "policy_hash": config_hash(pol.model_dump()),
        "tier": "A",
        "mode": "meso",
        "daytype": plan.daytype,
        "compare_daytype": compare_day,
        "date": base_meta.get("date"),
        "seed": seed,
        "sim_seed": sim_seed,
        "placebo_reroute_share": placebo_reroute_share,
        "sample": sample,
        "capacity_scale": scale,
        "config_hash": config_hash(
            {"policy": pol.model_dump(), "run": rcfg, "baseline": base_meta["config_hash"]}
        ),  # fmt: skip
        "network": rel(plan.net),
        "network_hash": content_hash(plan.net)
        if not str(plan.net).endswith(".gz")
        else xml_content_hash(plan.net),
        "population_hash": base_meta["population_hash"],
        "vehicles_hash": vhash,
        "routes_hash": routes_hash,
        "routes_deterministic": bool(base_meta.get("routes_deterministic", False)),
        "start_baseline": base_dir.name,
        "compare_baseline": ref_dir.name,
        "sumo_version": sumo_version(),
        "sim_end_s": sim_end,
        "run_end_s": run_end,
        "persons": base_meta.get("persons"),
        "vehicles": len(veh),
        "routing": routing,
        "effects": plan.effects,
        "net_change": plan.net_info,
        "timings": timings,
    }
    report = metrics.process_run(out, meta)
    # matched control for re-routed baseline vehicles (not for controls, placebos, other days)
    rerouted_existing = set(need["veh_id"]) & set(base_v["veh_id"])
    raw_ref = None
    if (with_control and rerouted_existing and control_ids is None and not placebo_reroute_share
            and start_day == compare_day):  # fmt: skip
        say(f"[{run_id}] matched control: {len(rerouted_existing):,} baseline vehicles re-routed")
        null = Policy.model_validate({
            "id": "matched_control", "kind": "policy", "daytype": compare_day,
            "title": f"Matched control for {pol.id} (same vehicles re-routed, no policy)",
            "transforms": [{"type": "remote_work", "share": 0.0, "days_per_week": 1,
                            "eligible_sectors": ["government"],
                            "assumption": "no-op transform: control run (TA-018)"}]})  # fmt: skip
        del plan.trips, plan.vehicles  # free memory before the control builds its own plan
        ctrl = run_policy(
            null, compare_day, sample, seed, runs_dir, net, zone_dir, baselines_dir, iterations,
            quiet, force_simulate=True, sim_seed=sim_seed, run_id=f"{run_id}--control",
            control_ids=rerouted_existing,
        )  # fmt: skip
        raw_ref, ref_dir = ref_dir, runs_dir / ctrl["run_id"]
        meta["control_run"] = ctrl["run_id"]
        meta["control_rerouted"] = len(rerouted_existing)
        meta["compare_baseline"] = ctrl["run_id"]
        meta["raw_baseline"] = raw_ref.name
    policy_report = write_policy_report(out, meta, report, ref_dir, pol, plan, rcfg, pol_path,
                                        raw_ref)  # fmt: skip
    timings["report_s"] = round(time.perf_counter() - t3, 1)
    timings["total_s"] = round(time.perf_counter() - t0, 1)
    meta["result"] = report["summary"]
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    for name in ("sumo.log", "build.log"):  # teleport warnings make these tens of MB
        log = out / name
        if log.exists():
            with log.open("rb") as src, gzip.open(out / f"{name}.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            log.unlink()
    say(policy_report["headline"])
    say(f"  report runs/{run_id}/policy_report.md")
    return meta


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    policy: str,
    daytype: str | None = typer.Option(None, help="baseline day type (default: the policy's)"),
    sample: float = typer.Option(DEFAULT_SAMPLE),
    seed: int = typer.Option(DEFAULT_SEED),
    runs_dir: Path = typer.Option(RUNS_DIR),
) -> None:
    run_policy(policy, daytype, sample, seed, runs_dir)


if __name__ == "__main__":
    app()
