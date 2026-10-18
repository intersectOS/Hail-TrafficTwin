"""Run a scenario on a focus window: window BASELINE and SCENARIO, same demand, mix and seed.

    python -m sim.runner --scenario accident_tahlia --window tahlia --seed 1
    python -m sim.scenarios run sim/scenarios/accident_tahlia.yaml --window demo

Baseline = same demand, same vType mix, same seed, same step loop, with only the probe events
(emergency trips) and none of the disruptive ones (decision B-D-012). Outputs:
runs/<id>-<window>-s<seed>-<config hash>/{baseline,scenario}/ plus meta.json and
scenario_report.{json,md}; the report and meta are copied to the stable runs/<id>/ (or
runs/<id>-<window>/ when --window overrides the scenario's window).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from sim.common import (
    REPO_ROOT,
    SYNTHETIC_LABEL,
    config_hash,
    content_hash,
    load_yaml,
    rel,
    sumo_version,
)
from sim.events.config import defaults, weather_presets
from sim.events.netindex import NetIndex
from sim.events.registry import baseline_plans, resolve_events, vtypes_needed
from sim.scenarios import kpis as K
from sim.scenarios.report import write_reports
from sim.scenarios.schema import Scenario, strategist_requested
from sim.scenarios.simulate import run_window_sim
from sim.vtypes.loader import (
    apply_mix,
    load_library,
    mix_assumption_ids,
    resolve_mix,
    type_ids,
    write_vtypes_additional,
)

SCENARIO_DIR = REPO_ROOT / "sim" / "scenarios"
RUNS_DIR = REPO_ROOT / "runs"
RUNNER_ASSUMPTIONS = ("A-sim-002",)  # time-to-teleport (sim/config/runner.yaml)


def load_scenario(ref: str | Path) -> Scenario:
    path = Path(ref)
    if not path.exists():
        path = SCENARIO_DIR / f"{ref}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"scenario {ref!r} not found (looked for {rel(path)})")
    return Scenario.model_validate(load_yaml(path))


def window_inputs(window: str) -> tuple[Path, Path, list[Path]]:
    """B-D-003: demo = committed demo window; others = cut Tier A routes from sim.link.

    Returns (net, demand, extra additional files): `<w>.tls.add.xml` (Tier B signal programs)
    is added when present. `<w>.cut.net.xml` (pre-graft) is never used."""
    if window == "demo":
        return REPO_ROOT / "data/demo/demo.net.xml", REPO_ROOT / "data/demo/demo.trips.xml", []
    base = REPO_ROOT / "data" / "windows" / window
    net, routes = base / f"{window}.net.xml", base / f"{window}.rou.xml"
    missing = [rel(p) for p in (net, routes) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"window {window!r} inputs missing: {', '.join(missing)}. Build them with "
            f"`python -m sim.link window --name {window}` and "
            f"`python -m sim.link cut --window {window}` (Track B tier link)."
        )
    tls = base / f"{window}.tls.add.xml"
    return net, routes, [tls] if tls.exists() else []


def run_settings() -> dict[str, Any]:
    return load_yaml(SCENARIO_DIR / "run.yaml")


def _execute(specs: list[dict[str, Any]], parallel: bool) -> list[dict[str, Any]]:
    if not parallel:
        return [run_window_sim(s) for s in specs]
    with ProcessPoolExecutor(max_workers=len(specs), mp_context=mp.get_context("spawn")) as ex:
        return list(ex.map(run_window_sim, specs))


def run_scenario(
    ref: str | Path,
    window: str | None = None,
    seed: int = 1,
    runs_dir: Path = RUNS_DIR,
    parallel: bool = True,
    end: float | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    t_all = time.perf_counter()
    scen = load_scenario(ref)
    w = window or scen.window
    net, demand_src, extra_adds = window_inputs(w)
    settings = run_settings()
    begin = scen.begin
    end = float(end if end is not None else scen.end)
    from sim.runner import runner_config  # runner imports this module lazily

    cfg = runner_config()
    lib = load_library()
    mix = resolve_mix(scen.vtype_mix, lib)
    idx = NetIndex(net)
    plans, event_ids = resolve_events(scen, idx, lib)
    run_cfg = {
        "scenario": scen.model_dump(mode="json"),
        "window": w,
        "begin": begin,
        "end": end,
        "seed": seed,
        "mix": mix,
        "vtypes": lib.model_dump(mode="json"),
        "plans": plans,
        "event_defaults": defaults(),
        "weather": {k: {p: v.value for p, v in d.items()} for k, d in weather_presets().items()},
        "kpis": K.kpi_rules(),
        "sumo_common": cfg["sumo_common"],
        "tier_options": cfg["tier_B"]["options"],
        "scenario_sumo_options": settings["sumo_options"],
        "extra_additionals": {rel(p): content_hash(p) for p in extra_adds},
        "edgedata_freq_s": cfg["smoke"]["edgedata_freq_s"],
    }
    chash = config_hash(run_cfg)
    run_id = f"{scen.id}-{w}-s{seed}-{chash[:8]}"
    out = runs_dir / run_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    vtypes_add = write_vtypes_additional(out / "vtypes.add.xml", mix, "B", lib)
    demand = out / "demand.rou.xml"
    demand_counts = apply_mix(demand_src, demand, lib.distribution_id)
    common = {
        "net": str(net),
        "demand": str(demand),
        "vtypes_add": str(vtypes_add),
        "begin": begin,
        "end": end,
        "seed": seed,
        "sumo_common": cfg["sumo_common"],
        "tier_options": cfg["tier_B"]["options"] + settings["sumo_options"],
        "extra_additionals": [str(p) for p in extra_adds],
        "micro_cfg": cfg,
        "edgedata_freq": cfg["smoke"]["edgedata_freq_s"],
        "distributions": [lib.distribution_id],
    }
    specs = [
        {**common, "run_dir": str(out / "baseline"), "plans": baseline_plans(plans)},
        {**common, "run_dir": str(out / "scenario"), "plans": plans},
    ]
    base_sim, scen_sim = _execute(specs, parallel)

    base_k = K.window_kpis(base_sim)
    scen_k = K.window_kpis(scen_sim)
    collapse = K.throughput_collapse_onset(base_sim, scen_sim)
    event_edges = sorted({e for p in plans for e in p.get("edges", []) + p.get("closed_edges", [])})
    assumption_ids = list(
        dict.fromkeys(
            [
                *mix_assumption_ids(scen.vtype_mix, lib),
                *type_ids(lib, vtypes_needed(plans)),
                *event_ids,
                *K.kpi_assumption_ids(),
                *RUNNER_ASSUMPTIONS,
            ]
        )
    )
    report = {
        "scenario": scen.id,
        "title": scen.label,
        "label": SYNTHETIC_LABEL,
        "fictional": scen.fictional,
        "window": w,
        "daytype": scen.daytype,
        "seed": seed,
        "begin": begin,
        "end": end,
        "baseline_definition": "same demand, vType mix, seed and step loop; probe events "
        "(emergency trips) only, no disruptive events",
        "kpis": {"baseline": base_k, "scenario": scen_k},
        "delta": K.deltas(base_k, scen_k),
        "gridlock": {
            "baseline": K.gridlock_flag(base_k, None),
            "scenario": K.gridlock_flag(scen_k, collapse),
        },
        "emergency": {
            "baseline": K.emergency_kpis(base_sim, baseline_plans(plans)),
            "scenario": K.emergency_kpis(scen_sim, plans),
        },
        "convoy": K.convoy_kpis(scen_sim, plans),
        "event_edges_flow": {
            "baseline": K.edge_flows(base_sim, event_edges),
            "scenario": K.edge_flows(scen_sim, event_edges),
        },
        "events": plans,
        "event_summaries": scen_sim["event_summaries"],
        "event_log": scen_sim["event_log"],
        "baseline_event_log": base_sim["event_log"],
        "strategist_requested": strategist_requested(scen),
        "assumption_ids": assumption_ids,
    }
    _add_emergency_vs_baseline(report)
    meta = {
        "run_id": run_id,
        "label": SYNTHETIC_LABEL,
        "kind": "scenario",
        "scenario": scen.id,
        "fictional": scen.fictional,
        "tier": "B",
        "mode": cfg["tier_B"]["mode"],
        "window": w,
        "seed": seed,
        "config_hash": chash,
        "network": rel(net),
        "network_hash": content_hash(net),
        "extra_additionals": {rel(p): content_hash(p) for p in extra_adds},
        "demand_source": rel(demand_src),
        "population_hash": content_hash(demand),
        "demand_counts": demand_counts,
        "vtype_mix": mix,
        "sumo_version": sumo_version(),
        "strategist_requested": strategist_requested(scen),
        "assumption_ids": assumption_ids,
        "wall_s": {
            "baseline_sim": base_sim["sim_wall_s"],
            "scenario_sim": scen_sim["sim_wall_s"],
            "baseline_post": base_sim["post_wall_s"],
            "scenario_post": scen_sim["post_wall_s"],
            "total": round(time.perf_counter() - t_all, 2),
            "parallel": parallel,
        },
        "fcd_rows": {"baseline": base_sim["fcd_rows"], "scenario": scen_sim["fcd_rows"]},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    write_reports(out, report, meta)
    stable = runs_dir / (scen.id if w == scen.window else f"{scen.id}-{w}")
    stable.mkdir(parents=True, exist_ok=True)
    for name in ("meta.json", "scenario_report.json", "scenario_report.md"):
        shutil.copy2(out / name, stable / name)
    (stable / "RUN_DIR").write_text(rel(out) + "\n")
    if not quiet:
        print((out / "scenario_report.md").read_text())
    return {"out": out, "stable": stable, "report": report, "meta": meta}


def _add_emergency_vs_baseline(report: dict[str, Any]) -> None:
    base = {r["vehicle"]: r for r in report["emergency"]["baseline"]}
    for r in report["emergency"]["scenario"]:
        b = base.get(r["vehicle"])
        if b and b["travel_time_s"] and r["travel_time_s"]:
            r["baseline_travel_time_s"] = b["travel_time_s"]
            r["ratio_to_baseline"] = round(r["travel_time_s"] / b["travel_time_s"], 3)
