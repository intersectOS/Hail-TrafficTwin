"""Emergency strategist: snapshot -> candidates -> parallel what-ifs -> rank -> explain -> log.

    python -m strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1
    python -m strategist.run --scenario emergency_demo --seed 1 --weights my_weights.yaml

Prints the ranked top 3 (ambulance time vs no strategy and vs free flow, side effects,
classification, reason) and the recommendation id; writes
runs/strategist/<recommendation id>/recommendation.{json,md} and appends a `recommendation`
record to the decision log. Nothing is applied: options are applied (approval-required ones
only) with `python -m strategist.approve <recommendation id>`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import typer

from sim.common import SYNTHETIC_LABEL, config_hash, rel
from strategist import config as C
from strategist import decision_log as L
from strategist.candidates import NO_STRATEGY_ID, build_candidates
from strategist.classify import classify_option
from strategist.evaluate import evaluate
from strategist.explain import explain
from strategist.rank import rank
from strategist.situation import resolve_situation
from strategist.snapshot import STATE_FILE, base_spec, get_snapshot, load_edge_tt

CANDIDATE_KEYS = (
    "id", "label", "route_name", "route_rank", "route", "actions", "ff_s", "length_m", "cost_s",
    "halted_at_t", "worst_edge_at_t", "worst_edge_halted_at_t",
)  # fmt: skip
MEASURED_KEYS = (
    "arrived", "travel_time_s", "free_flow_s", "ratio_to_free_flow", "background_veh_h",
    "background_arrived", "teleports", "route_halted_max", "ambulance_edge_s",
    "signals_preempted", "preempt_activations", "preempt_held_s", "preempted",
    "rescue_lane_edges", "junctions_held", "hold_s_total", "closed_lanes_verified",
)  # fmt: skip


def fork_specs(
    sit: Any, snap_dir: Path, candidates: list[dict[str, Any]], out_dir: Path
) -> list[dict[str, Any]]:
    base = {
        **base_spec(sit, snap_dir),
        "state": str(snap_dir / STATE_FILE),
        "t": sit.t_dispatch,
        "horizon_s": float(C.value("evaluation", "horizon_s")),
        "plans": sit.plans,
        "trip": sit.trip,
    }
    return [
        {**base, "candidate": c, "run_dir": str(out_dir / "whatif" / c["id"].replace(":", "_"))}
        for c in candidates
    ]


def fingerprint(results: dict[str, dict[str, Any]]) -> str:
    """Hash of every measured what-if field: equal across runs <=> deterministic."""
    return config_hash({k: {m: r[m] for m in MEASURED_KEYS} for k, r in sorted(results.items())})


def without_runs(
    cand: dict[str, Any], cands: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any] | None]:
    """For each preempt / rescue_lane action of `cand`: the measured result of the candidate on
    the same route with exactly that action removed (the no-strategy run for the default route),
    or None if no such run was evaluated."""
    types = {a["type"] for a in cand["actions"]}
    out: dict[str, dict[str, Any] | None] = {}
    for kind in ("preempt", "rescue_lane"):
        if kind not in types:
            continue
        want = types - {kind}
        match = next(
            (
                o
                for o in cands
                if o["route"] == cand["route"] and {a["type"] for a in o["actions"]} == want
            ),
            None,
        )
        out[kind] = results.get(match["id"]) if match else None
    return out


def recommend(
    scenario: str,
    window: str | None = None,
    seed: int = 1,
    weights_file: Path | None = None,
    fresh: bool = False,
    db: Path = C.DEFAULT_DB,
    runs_dir: Path = C.RUNS_DIR,
    parallel: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    t_all = time.perf_counter()
    wall: dict[str, Any] = {}
    t = time.perf_counter()
    sit = resolve_situation(scenario, window, seed)
    wall["situation_s"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    snap, snap_dir, reused = get_snapshot(sit, fresh, root=runs_dir / "snapshots")
    wall["snapshot_s"] = round(time.perf_counter() - t, 2)
    wall["snapshot_reused"] = reused
    wall["snapshot_build_s"] = snap["wall_s"]
    t = time.perf_counter()
    weights = C.load_weights(weights_file)
    built = build_candidates(sit, snap, load_edge_tt(snap_dir))
    cands = built["candidates"]
    wall["candidates_s"] = round(time.perf_counter() - t, 2)

    rec_id = L.new_id("recommendation")
    out = runs_dir / rec_id
    out.mkdir(parents=True, exist_ok=True)
    specs = fork_specs(sit, snap_dir, cands, out)
    t = time.perf_counter()
    res_list = evaluate(specs, parallel=parallel)
    wall["evaluation_s"] = round(time.perf_counter() - t, 2)
    wall["what_if_runs"] = len(specs)
    wall["what_if_wall_s"] = {r["candidate_id"]: r["wall_s"] for r in res_list}

    t = time.perf_counter()
    results = {r["candidate_id"]: r for r in res_list}
    horizon = float(C.value("evaluation", "horizon_s"))
    ranked = rank(cands, results, weights["values"], horizon)
    by_id = {c["id"]: c for c in cands}
    ns_cand, ns_res = by_id[NO_STRATEGY_ID], results[NO_STRATEGY_ID]
    halted_t = snap["measured_at_t"]["halted_by_edge"]
    for sc in ranked["scores"]:
        c = by_id[sc["candidate_id"]]
        sc["classification"] = classify_option(c["actions"], results[c["id"]], sc["added_veh_h"])[
            "classification"
        ]
    options = []
    for s in ranked["top"]:
        c, r = by_id[s["candidate_id"]], results[s["candidate_id"]]
        cls = classify_option(c["actions"], r, s["added_veh_h"])
        ex = explain(
            c,
            r,
            ns_cand,
            ns_res,
            s["added_veh_h"],
            horizon,
            halted_t,
            without_runs(c, cands, results),
        )
        tt, ns_tt = r["travel_time_s"], ns_res["travel_time_s"]
        options.append(
            {
                "rank": s["rank"],
                "candidate_id": c["id"],
                "label": c["label"],
                "route_name": c["route_name"],
                "actions": c["actions"],
                "classification": cls["classification"],
                "action_classes": cls["actions"],
                "arrived": r["arrived"],
                "travel_time_s": tt,
                "no_strategy_tt_s": ns_tt,
                "vs_no_strategy_s": (tt - ns_tt) if tt is not None and ns_tt is not None else None,
                "free_flow_s": r["free_flow_s"],
                "vs_free_flow_s": round(tt - r["free_flow_s"], 2) if tt is not None else None,
                "default_free_flow_s": ns_res["free_flow_s"],
                "added_veh_h": s["added_veh_h"],
                "signals_preempted": r["signals_preempted"],
                "rescue_lane_edges": r["rescue_lane_edges"],
                "junctions_held": r["junctions_held"],
                "score": s["score"],
                "score_terms": s["terms"],
                "reason": ex["text"],
                "facts": ex["facts"],
            }
        )
    best = options[0] if options else None
    beats = bool(
        best
        and best["travel_time_s"] is not None
        and (ns_res["travel_time_s"] is None or best["travel_time_s"] < ns_res["travel_time_s"])
    )
    wall["rank_explain_s"] = round(time.perf_counter() - t, 2)
    wall["total_s"] = round(time.perf_counter() - t_all, 2)
    wall["warm_total_s"] = round(wall["total_s"] - (0 if reused else wall["snapshot_s"]), 2)
    run_cfg = {
        "settings": C.settings(),
        "weights": weights["values"],
        "scenario": sit.scenario.model_dump(mode="json"),
        "window": sit.window,
        "seed": seed,
    }
    chash = config_hash(run_cfg)
    snapshot_info = {
        "snapshot_id": snap["snapshot_id"],
        "reused": reused,
        "state_file": snap["state_file"],
        "state_hash": snap["state_hash"],
        "t_dispatch": snap["t_dispatch"],
        "network_hash": snap["network_hash"],
        "demand_hash": snap["demand_hash"],
        "population_hash": snap["population_hash"],
        "sumo_version": snap["sumo_version"],
        "measured_at_t": {k: v for k, v in snap["measured_at_t"].items() if k != "halted_by_edge"},
    }
    summary_cands = [{k: c.get(k) for k in CANDIDATE_KEYS} for c in cands]
    log_rec = {
        "run_dir": rel(out),
        "scenario": sit.scenario.id,
        "window": sit.window,
        "seed": seed,
        "config_hash": chash,
        "state_hash": snap["state_hash"],
        "best_label": best["label"] if best else None,
        "best_beats_no_strategy": beats,
        "no_strategy_tt_s": ns_res["travel_time_s"],
        "options": [
            {
                k: o[k]
                for k in (
                    "rank",
                    "candidate_id",
                    "label",
                    "classification",
                    "travel_time_s",
                    "added_veh_h",
                    "score",
                    "reason",
                )
            }
            for o in options
        ],
    }
    entry = L.append(
        db,
        "recommendation",
        snap["snapshot_id"],
        summary_cands,
        ranked["scores"],
        log_rec,
        None,
        actor="strategist",
        record_id=rec_id,
    )
    report = {
        "label": SYNTHETIC_LABEL,
        "recommendation_id": rec_id,
        "run_dir": rel(out),
        "log_hash": entry["hash"],
        "db": str(db),
        "scenario": sit.scenario.id,
        "title": sit.scenario.label,
        "fictional": sit.scenario.fictional,
        "window": sit.window,
        "seed": seed,
        "config_hash": chash,
        "snapshot": snapshot_info,
        "weights": weights,
        "horizon_s": horizon,
        "routes": built["routes"],
        "route_stats": built["route_stats"],
        "closed_lanes_at_t": built["closed_lanes_at_t"],
        "no_strategy": {
            "travel_time_s": ns_res["travel_time_s"],
            "arrived": ns_res["arrived"],
            "free_flow_s": ns_res["free_flow_s"],
            "background_veh_h": ns_res["background_veh_h"],
            "route_halted_max": ns_res["route_halted_max"],
            "ambulance_edge_s": ns_res["ambulance_edge_s"],
        },
        "options": options,
        "best_beats_no_strategy": beats,
        "candidates": summary_cands,
        "results": {k: {m: r[m] for m in MEASURED_KEYS} for k, r in results.items()},
        "scores": ranked["scores"],
        "fingerprint": fingerprint(results),
        "assumption_ids": list(
            dict.fromkeys([*sit.assumption_ids, *C.setting_ids(), *weights["ids"]])
        ),
        "wall_s": wall,
        "fork": {k: v for k, v in specs[0].items() if k not in ("candidate", "run_dir")},
        "candidate_specs": cands,
    }
    (out / "recommendation.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "recommendation.md").write_text(render_md(report))
    stable = runs_dir / f"{sit.scenario.id}-{sit.window}-s{seed}"
    stable.mkdir(parents=True, exist_ok=True)
    for name in ("recommendation.json", "recommendation.md"):
        (stable / name).write_text((out / name).read_text())
    if not quiet:
        typer.echo(render_text(report))
    return report


def _fmt_s(v: float | None) -> str:
    return "-" if v is None else f"{v:.0f} s"


def _signed(v: float | None, unit: str = " s", fmt: str = "+.0f") -> str:
    return "-" if v is None else f"{format(v, fmt)}{unit}"


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def render_text(r: dict[str, Any]) -> str:
    ns, w, s = r["no_strategy"], r["wall_s"], r["snapshot"]
    snap_state = "reused" if s["reused"] else "built"
    build = (
        "reused" if w["snapshot_reused"] else f"built: warm-up {w['snapshot_build_s']['warm_up']} s"
    )
    rid = r["recommendation_id"]
    head = f"{'#':<2} {'option':<52} {'class':<18} {'ambulance':>9} {'vs none':>8} {'vs ff':>7}"
    lines = [
        f"Strategist recommendation {rid}  [{r['label']}]"
        + ("  FICTIONAL scenario" if r["fictional"] else ""),
        f"  {r['scenario']} on {r['window']}, seed {r['seed']}, dispatch "
        f"t={s['t_dispatch']:.0f} s, snapshot {s['snapshot_id']} ({snap_state}), "
        f"{s['sumo_version']}",
        f"  no strategy: ambulance {_fmt_s(ns['travel_time_s'])} on the default route "
        f"(free flow {ns['free_flow_s']:.1f} s); {w['what_if_runs']} what-if runs, "
        f"horizon {r['horizon_s']:.0f} s",
        "",
        f"  {head} {'+veh-h':>7} {'score':>7}",
    ]
    for o in r["options"]:
        lines.append(
            f"  {o['rank']:<2} {o['label'][:52]:<52} {o['classification']:<18} "
            f"{_fmt_s(o['travel_time_s']):>9} {_signed(o['vs_no_strategy_s']):>8} "
            f"{_signed(o['vs_free_flow_s']):>7} {o['added_veh_h']:>+7.2f} {o['score']:>7.1f}"
        )
        lines.append(f"     {o['reason']}")
    lines += [
        "",
        f"  best beats no strategy: {'YES' if r['best_beats_no_strategy'] else 'NO'}",
        f"  wall: situation {w['situation_s']} s, snapshot {w['snapshot_s']} s ({build}), "
        f"candidates {w['candidates_s']} s, evaluation {w['evaluation_s']} s, "
        f"rank+explain {w['rank_explain_s']} s; total {w['total_s']} s "
        f"(from saved state {w['warm_total_s']} s)",
        f"  recommendation_id: {rid}  (apply: python -m strategist.approve {rid})",
        f"  outputs: {r['run_dir']}/recommendation.{{json,md}}",
    ]
    return "\n".join(lines)


def render_md(r: dict[str, Any]) -> str:
    ns, s, w, rs = r["no_strategy"], r["snapshot"], r["wall_s"], r["route_stats"]
    fict = " Fictional scenario (PROJECT.md section 11)." if r["fictional"] else ""
    closed = ", ".join(r["closed_lanes_at_t"]) or "none"
    weights = ", ".join(f"{k} = {v}" for k, v in r["weights"]["values"].items())
    out = [
        f"# Strategist recommendation `{r['recommendation_id']}`",
        "",
        f"**{r['label']}**.{fict}",
        "",
        f"{r['title']}. Scenario `{r['scenario']}` on window `{r['window']}`, seed {r['seed']}, "
        f"dispatch t = {s['t_dispatch']:.0f} s. Snapshot `{s['snapshot_id']}` (state hash "
        f"`{s['state_hash']}`, network hash `{s['network_hash']}`, demand hash "
        f"`{s['demand_hash']}`), config hash `{r['config_hash']}`, {s['sumo_version']}. "
        f"Decision-log record hash `{r['log_hash']}`.",
        "",
        f"No strategy (default route, no interventions): ambulance "
        f"{_fmt_s(ns['travel_time_s'])}, free flow {ns['free_flow_s']:.1f} s. Horizon "
        f"{r['horizon_s']:.0f} s after dispatch; {w['what_if_runs']} what-if runs.",
        "",
        _table_row(
            ["rank", "option", "classification", "ambulance TT", "vs no strategy"]
            + ["vs free flow", "added veh-h", "signals", "score"]
        ),
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for o in r["options"]:
        out.append(
            _table_row(
                [str(o["rank"]), o["label"], o["classification"], _fmt_s(o["travel_time_s"])]
                + [_signed(o["vs_no_strategy_s"]), _signed(o["vs_free_flow_s"])]
                + [f"{o['added_veh_h']:+.2f}", str(o["signals_preempted"]), f"{o['score']:.1f}"]
            )
        )
    out += ["", "## Reasons", ""]
    out += [f"{o['rank']}. {o['reason']}" for o in r["options"]]
    out += [
        "",
        "## All what-if runs",
        "",
        _table_row(
            ["candidate", "classification", "ambulance TT", "background veh-h", "added veh-h"]
            + ["signals", "rescue edges", "junctions held", "teleports", "score"]
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sc in r["scores"]:
        m = r["results"][sc["candidate_id"]]
        out.append(
            _table_row(
                [f"`{sc['candidate_id']}`", sc["classification"], _fmt_s(m["travel_time_s"])]
                + [f"{m['background_veh_h']:.3f}", f"{sc['added_veh_h']:+.3f}"]
                + [str(m["signals_preempted"]), str(m["rescue_lane_edges"])]
                + [str(m["junctions_held"]), str(m["teleports"]), f"{sc['score']:.1f}"]
            )
        )
    out += [
        "",
        f"Routes: {rs['routes_found']} of k = {rs['k']} found after {rs['paths_examined']} Yen "
        f"paths; lanes closed at T: {closed}.",
        "",
        f"Wall time: situation {w['situation_s']} s, snapshot {w['snapshot_s']} s "
        f"({'reused' if w['snapshot_reused'] else 'built'}), candidates {w['candidates_s']} s, "
        f"evaluation {w['evaluation_s']} s, rank + explain {w['rank_explain_s']} s, total "
        f"{w['total_s']} s.",
        "",
        f"Weights ({r['weights']['source']}): {weights}. Determinism fingerprint "
        f"`{r['fingerprint']}`.",
        "",
        f"Assumptions used ({len(r['assumption_ids'])}): {', '.join(r['assumption_ids'])}.",
        "",
    ]
    return "\n".join(out)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    scenario: str = typer.Option(
        ..., help="scenario id (strategist/scenarios, then sim/scenarios) or path"
    ),
    window: str | None = typer.Option(None, help="focus window; overrides the scenario's"),
    seed: int = typer.Option(1),
    weights: Path | None = typer.Option(None, help="weights override YAML"),
    fresh: bool = typer.Option(False, help="rebuild the snapshot even if cached"),
    db: Path = typer.Option(C.DEFAULT_DB, help="decision log (SQLite)"),
    runs_dir: Path = typer.Option(C.RUNS_DIR, help="output root (snapshots, recommendations)"),
    serial: bool = typer.Option(False, help="evaluate candidates one after the other"),
) -> None:
    report = recommend(scenario, window, seed, weights, fresh, db, runs_dir, parallel=not serial)
    if not report["options"]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
