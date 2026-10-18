"""Evacuation strategist (M7, PROJECT.md 9.9): generate evacuation strategies, simulate each one,
rank them by clearance time with side-effect penalties, explain and classify them, and log the
recommendation in the hash-chained decision log. Synthetic demand, uncalibrated; fictional
scenarios only. Simulation and decision support only: nothing is ever actuated.

    python -m strategist.evacuation run --scenario evac_obhur --seed 1
    python -m strategist.evacuation approve <recommendation_id> [--option n] [--reject]

Strategy levers (one evacuation, same evacuees and departure window in every candidate):
phasing order (simultaneous | near_first | far_first: bands by free-flow time to the exit),
exit assignment (nearest | balanced guidance), contraflow sets (corridors by exit) and the signal
plan (default | evacuation green extension). Candidates are a screening design: each lever alone
against the no-strategy run (the scenario as written), then combinations with balanced guidance
(decision B-D-029). Each candidate is a full window run from the scenario's begin with light
outputs (no FCD), not a fork of a saved state: flood closures and weather active at the order
time cannot be re-applied after loadState (M6 B-D-017), and the strategy changes vehicles that
do not exist yet at the order time.

score = w_t90 x T90 + w_t100 x T100 (s after the order; not reached = A-evac-026 x horizon)
      + w_delay x max(0, background veh-h added versus no strategy) + w_contraflow x lane-km
      + w_signal x signals retimed + w_order x extra staged orders                 (lower = better)
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, content_hash, rel
from sim.events import evacuation as V
from sim.events.netindex import NetIndex
from strategist import decision_log as L
from strategist.config import DEFAULT_DB

RUNS_DIR = REPO_ROOT / "runs" / "strategist" / "evac"
LEVER_NAMES = {
    "phasing": "the phased release",
    "exit_assignment": "balanced exit guidance",
    "contraflow": "contraflow",
    "signal_plan": "the evacuation signal plan",
}
AUTO = "auto_eligible"
APPROVAL = "approval_required"
NO_STRATEGY = "no_strategy"
REPLICATE = "no_strategy_replicate"
WEIGHT_KEYS = ("w_t90", "w_t100", "w_delay", "w_contraflow", "w_signal", "w_order")
LEVER_LABELS = {
    "phasing": {"near_first": "near-first phased release", "far_first": "far-first phased release"},
    "exit_assignment": {"balanced": "balanced exit guidance"},
    "signal_plan": {"evacuation": "evacuation signal plan"},
}


def weights() -> dict[str, float]:
    return {k: float(V.value("strategy", k)) for k in WEIGHT_KEYS}


def weight_ids() -> list[str]:
    keys = (*WEIGHT_KEYS, "noise_replicates", "auto_max_added_veh_h")
    return [V.param("strategy", k).id for k in keys]


# --- candidates ---------------------------------------------------------------------------------
def _label(strategy: dict[str, Any], base: dict[str, Any], corridors: dict[str, str]) -> str:
    parts = []
    for lever in ("phasing", "exit_assignment", "signal_plan"):
        if strategy[lever] != base[lever]:
            parts.append(LEVER_LABELS[lever].get(strategy[lever], f"{lever}={strategy[lever]}"))
    if strategy["contraflow"] != base["contraflow"]:
        cf = strategy["contraflow"]
        if cf:
            parts.append("contraflow " + " + ".join(corridors.get(x, x) for x in cf))
        else:
            parts.append("no contraflow")
    return ", ".join(parts) or "no strategy (scenario as written)"


def candidates(sit: V.Situation) -> list[dict[str, Any]]:
    """Screening design (B-D-029). Signal-plan candidates only where evacuation routes cross a
    signal; contraflow with nearest exits only for corridors towards exits that are used."""
    base = sit.strategy()
    cors = sit.analysis["corridors"]
    all_cf = [c["exit"] for c in cors]
    near_plan = sit.plan(exit_assignment="nearest")
    bal_plan = sit.plan(exit_assignment="balanced")
    used_near = [x for x in all_cf if near_plan["assigned"].get(x)]
    sig_near = bool(near_plan["moves"])
    sig_bal = bool(bal_plan["moves"])
    specs: list[tuple[str, dict[str, Any]]] = [
        (NO_STRATEGY, {}),
        ("near_first", {"phasing": "near_first"}),
        ("far_first", {"phasing": "far_first"}),
        ("balanced", {"exit_assignment": "balanced"}),
    ]
    if sig_near:
        specs.append(("signals", {"signal_plan": "evacuation"}))
    if used_near:
        specs.append(("contraflow", {"contraflow": used_near, "exit_assignment": "nearest"}))
    if all_cf:
        specs.append(("balanced_cf", {"exit_assignment": "balanced", "contraflow": all_cf}))
    if sig_bal:
        specs.append(
            ("balanced_signals", {"exit_assignment": "balanced", "signal_plan": "evacuation"})
        )
    full = {"exit_assignment": "balanced", "contraflow": all_cf}
    if sig_bal:
        full["signal_plan"] = "evacuation"
    if all_cf and sig_bal:
        specs.append(("balanced_cf_signals", dict(full)))
    specs.append(("near_first_full", {**full, "phasing": "near_first"}))
    specs.append(("far_first_full", {**full, "phasing": "far_first"}))
    names = {c["exit"]: f"{c['id']} ({c['name']})" for c in cors}
    out: list[dict[str, Any]] = []
    effects: dict[str, dict[str, Any]] = {}
    for cid, upd in specs:
        strategy = {**base, **upd}
        plan = sit.plan(**strategy)
        effect = config_hash(
            {
                "vehicles": plan["vehicles"],
                "routes": plan["routes"],
                "contraflow": plan["contraflow"],
                "signals": plan["signal_plan"] if plan["moves"] else "default",
            }
        )
        if effect in effects:  # same evacuees, routes and measures as an earlier candidate
            effects[effect]["equivalent_strategies"].append(strategy)
            continue
        cand = {
            "id": cid,
            "label": _label(strategy, base, names),
            "strategy": strategy,
            "actions": actions(strategy, base, cors),
            "equivalent_strategies": [],
        }
        effects[effect] = cand
        out.append(cand)
    return out


def actions(
    strategy: dict[str, Any], base: dict[str, Any], corridors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out = []
    if strategy["phasing"] != "simultaneous":
        out.append({"type": "evacuation_order", "detail": f"staged release {strategy['phasing']}"})
    if strategy["exit_assignment"] != "nearest":
        out.append({"type": "exit_guidance", "detail": strategy["exit_assignment"]})
    if strategy["signal_plan"] != "default":
        out.append({"type": "signal_plan", "detail": strategy["signal_plan"]})
    if strategy["contraflow"]:
        lane_km = sum(c["lane_km"] for c in corridors if c["exit"] in strategy["contraflow"])
        out.append(
            {
                "type": "contraflow",
                "detail": [c["id"] for c in corridors if c["exit"] in strategy["contraflow"]],
                "lane_km": round(lane_km, 3),
            }
        )
    return out


# --- evaluation ---------------------------------------------------------------------------------
def evaluate(
    sit: V.Situation, cands: list[dict[str, Any]], out: Path, workers: int | None = None
) -> dict[str, dict[str, Any]]:
    common = V.prepare_inputs(sit, out / "inputs")
    common.pop("demand_counts")
    plans = {c["id"]: sit.plan(**c["strategy"]) for c in cands}
    specs = [
        {
            **common,
            "run_dir": str(out / "candidates" / c["id"]),
            "plans": V.ordered_plans(sit, plans[c["id"]]),
        }
        for c in cands
    ]
    # noise replicate (A-evac-035): the no-strategy plan (same evacuees and departure times)
    # with another SUMO seed, so only the run-to-run randomness of driving differs
    ids = [c["id"] for c in cands]
    specs.append(
        {
            **common,
            "seed": sit.seed + int(V.model("replicate_seed_offset")),
            "run_dir": str(out / "candidates" / REPLICATE),
            "plans": V.ordered_plans(sit, plans[NO_STRATEGY]),
        }
    )
    ids.append(REPLICATE)
    plans[REPLICATE] = plans[NO_STRATEGY]
    n = workers or int(V.model("max_workers"))
    results = V.execute(V.simulate, specs, workers=n)
    idx = NetIndex(sit.net)
    return {
        cid: {
            **V.summarize_run(sit, plans[cid], r, idx),
            "run_dir": rel(Path(r["run_dir"])),
        }
        for cid, r in zip(ids, results, strict=True)
    }


def noise_band(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Absolute differences between the no-strategy run and its replicate (one replicate: a
    crude estimate of run-to-run noise, A-evac-035)."""
    a, b = results[NO_STRATEGY], results[REPLICATE]

    def diff(key: str) -> float | None:
        if a["clearance"][key] is None and b["clearance"][key] is None:
            return None  # neither run reaches this level: not measurable
        return round(abs(V.effective(a["clearance"], key) - V.effective(b["clearance"], key)), 1)

    return {
        "t90_s": diff("t90_s"),
        "t100_s": diff("t100_s"),
        "delay_veh_h": round(
            abs(a["background"]["delay_veh_h"] - b["background"]["delay_veh_h"]), 3
        ),
        "replicate_seed": None,
    }


def score(res: dict[str, Any], base: dict[str, Any], cand: dict[str, Any],
          w: dict[str, float], noise: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    c = res["clearance"]
    added = round(res["background"]["delay_veh_h"] - base["background"]["delay_veh_h"], 3)
    excess = round(max(0.0, added - (noise or {}).get("delay_veh_h", 0.0)), 3)
    lane_km = sum(a.get("lane_km", 0.0) for a in cand["actions"] if a["type"] == "contraflow")
    staged = (
        int(V.value("phasing", "sectors")) - 1
        if cand["strategy"]["phasing"] != ("simultaneous")
        else 0
    )
    terms = {
        "t90": w["w_t90"] * V.effective(c, "t90_s"),
        "t100": w["w_t100"] * V.effective(c, "t100_s"),
        "delay": w["w_delay"] * excess,  # penalty only, beyond the noise band (A-evac-029/035)
        "contraflow": w["w_contraflow"] * lane_km,
        "signals": w["w_signal"] * len(res["signals_retimed"]),
        "orders": w["w_order"] * staged,
    }
    return {
        "added_veh_h": added,
        "added_beyond_noise_veh_h": excess,
        "terms": {k: round(v, 3) for k, v in terms.items()},
        "score": round(sum(terms.values()), 3),
    }


def classify(cand: dict[str, Any], added: float) -> dict[str, Any]:
    """Contraflow and staged evacuation orders always need approval (A-strat-020); exit
    guidance and the signal plan are reversible and auto-eligible within A-evac-033."""
    limit = float(V.value("strategy", "auto_max_added_veh_h"))
    per = []
    for a in cand["actions"]:
        if a["type"] in ("contraflow", "evacuation_order"):
            per.append({"type": a["type"], "class": APPROVAL, "rule": "always (A-strat-020)"})
        elif added > limit:
            per.append(
                {"type": a["type"], "class": APPROVAL,
                 "rule": f"adds {added:.2f} veh-h > {limit} (A-evac-033)"}
            )  # fmt: skip
        else:
            per.append({"type": a["type"], "class": AUTO, "rule": "reversible, within A-evac-033"})
    cls = APPROVAL if any(a["class"] == APPROVAL for a in per) else AUTO
    return {"classification": cls if per else "none", "actions": per}


def rank(cands: list[dict[str, Any]], results: dict[str, dict[str, Any]],
         w: dict[str, float], top_n: int,
         noise: dict[str, Any] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    base = results[NO_STRATEGY]
    rows = []
    for c in cands:
        s = score(results[c["id"]], base, c, w, noise)
        rows.append({"candidate_id": c["id"], "label": c["label"], **s})
    rows.sort(key=lambda r: (r["score"], r["candidate_id"]))
    pos = 1
    for r in rows:
        if r["candidate_id"] == NO_STRATEGY:
            r["rank"] = None
            continue
        r["rank"] = pos
        pos += 1
    return rows


# --- explanations (measured facts only, as M6 B-D-022) -------------------------------------------
def _lever_off(strategy: dict[str, Any], base: dict[str, Any], lever: str) -> dict[str, Any]:
    return {**strategy, lever: base[lever]}


def explain(
    cand: dict[str, Any],
    cands: list[dict[str, Any]],
    results: dict[str, Any],
    scores: dict[str, dict[str, Any]],
    base_strategy: dict[str, Any],
) -> list[str]:
    res = results[cand["id"]]
    c = res["clearance"]
    b = results[NO_STRATEGY]["clearance"]
    lines = []

    def fmt(v: float | None) -> str:
        return "not reached" if v is None else f"{v:.0f} s"

    lines.append(
        f"Measured: 50 % out after {fmt(c['t50_s'])}, 90 % after {fmt(c['t90_s'])}, 100 % after "
        f"{fmt(c['t100_s'])} (no strategy: {fmt(b['t50_s'])}, {fmt(b['t90_s'])}, "
        f"{fmt(b['t100_s'])})."
    )
    d90 = V.effective(c, "t90_s") - V.effective(b, "t90_s")
    if c["t90_s"] is None:
        lines.append(
            f"Does not get 90 % out before the run ends ({c['out']} of {c['vehicles']} out)"
            + (", nor does no strategy." if b["t90_s"] is None else ".")
        )
    elif b["t90_s"] is None:
        lines.append("Gets 90 % out, which no strategy does not before the run ends.")
    elif d90 < 0:
        lines.append(f"Clears 90 % {abs(d90) / 60:.1f} min faster than no strategy.")
    elif d90 > 0:
        lines.append(f"Clears 90 % {d90 / 60:.1f} min slower than no strategy.")
    by_strategy = {
        json.dumps(st, sort_keys=True): x["id"]
        for x in cands
        for st in [x["strategy"], *x["equivalent_strategies"]]
    }
    for lever in ("phasing", "exit_assignment", "contraflow", "signal_plan"):
        if cand["strategy"][lever] == base_strategy[lever]:
            continue
        other = by_strategy.get(json.dumps(_lever_off(cand["strategy"], base_strategy, lever),
                                           sort_keys=True))  # fmt: skip
        if other is None or other == cand["id"]:
            continue
        oc = results[other]["clearance"]
        if oc["t90_s"] is None or c["t90_s"] is None:
            lines.append(
                f"{LEVER_NAMES[lever][0].upper()}{LEVER_NAMES[lever][1:]}: 90 % not reached "
                f"{'with' if c['t90_s'] is None else 'without'} it; out by the run end "
                f"{c['out']} with it, {oc['out']} without it ({other})."
            )
            continue
        saving = V.effective(oc, "t90_s") - V.effective(c, "t90_s")
        name = LEVER_NAMES[lever]
        if saving > 0:
            lines.append(
                f"Because of {name}: the same option without it ({other}) was measured "
                f"{saving:.0f} s slower to 90 %."
            )
        else:
            when = f"{abs(saving):.0f} s sooner" if saving < 0 else "at the same time"
            lines.append(
                f"{name[0].upper()}{name[1:]} did not help here: without it ({other}) 90 % was "
                f"reached {when}."
            )
    added = scores[cand["id"]]["added_veh_h"]
    lines.append(
        f"Background traffic: {added:+.2f} vehicle-hours of delay versus no strategy "
        f"({res['background']['delay_veh_h']:.1f} veh-h in total)."
    )
    if res["contraflow_lanes_opened"]:
        lines.append(
            f"Contraflow reversed {res['contraflow_lanes_opened']} lane segments and closed "
            f"{res['contraflow_lanes_closed']} inbound lanes to everyone but emergency vehicles."
        )
    if res["signals_retimed"]:
        lines.append(f"{len(res['signals_retimed'])} signal(s) ran the evacuation plan.")
    if res["bottlenecks"]:
        bn = res["bottlenecks"][0]
        lines.append(
            f"Worst bottleneck: `{bn['edge']}` {bn['name'] or bn['type']} "
            f"({bn['halted_veh_h']} halted veh-h, up to {bn['max_halted_veh']} vehicles)."
        )
    return lines


# --- recommend ----------------------------------------------------------------------------------
def fingerprint(results: dict[str, dict[str, Any]]) -> str:
    return config_hash(
        {k: [r["clearance"], r["background"]["delay_veh_h"]] for k, r in sorted(results.items())}
    )


def recommend(scenario: str, window: str | None = None, seed: int = 1, workers: int | None = None,
              only: list[str] | None = None, db: Path = DEFAULT_DB, runs_dir: Path = RUNS_DIR,
              end: float | None = None, log: bool = True) -> dict[str, Any]:  # fmt: skip
    t0 = time.perf_counter()
    sit = V.situation(scenario, window, seed, end)
    cands = candidates(sit)
    if only:
        cands = [c for c in cands if c["id"] in only or c["id"] == NO_STRATEGY]
    key = config_hash(
        {
            "scenario": sit.scenario.model_dump(mode="json"),
            "window": sit.window,
            "seed": seed,
            "end": sit.end,
            "net": content_hash(sit.net),
            "candidates": cands,
            "settings": V._tree(),
        }
    )
    out = runs_dir / f"{sit.scenario.id}-{sit.window}-s{seed}-{key[:8]}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    t_sit = time.perf_counter() - t0
    results = evaluate(sit, cands, out, workers)
    t_eval = time.perf_counter() - t0 - t_sit
    w = weights()
    top_n = int(V.model("top_n"))
    noise = noise_band(results)
    noise["replicate_seed"] = seed + int(V.model("replicate_seed_offset"))
    ranked = rank(cands, results, w, top_n, noise)
    scores = {r["candidate_id"]: r for r in ranked}
    by_id = {c["id"]: c for c in cands}
    base_strategy = sit.strategy()
    table = []
    for r in ranked:
        c = by_id[r["candidate_id"]]
        res = results[c["id"]]
        cls = classify(c, r["added_beyond_noise_veh_h"])
        d90 = V.effective(res["clearance"], "t90_s") - V.effective(
            results[NO_STRATEGY]["clearance"], "t90_s"
        )
        table.append(
            {
                **r,
                "strategy": c["strategy"],
                "actions": c["actions"],
                "classification": cls["classification"],
                "action_classes": cls["actions"],
                "clearance": res["clearance"],
                "t90_vs_no_strategy_s": round(d90, 1),
                "t90_within_noise": noise["t90_s"] is not None and abs(d90) <= noise["t90_s"],
                "background_delay_veh_h": res["background"]["delay_veh_h"],
                "contraflow_lane_km": sum(a.get("lane_km", 0) for a in c["actions"]),
                "signals_retimed": len(res["signals_retimed"]),
                "teleports": res["teleports"],
                "bottlenecks": res["bottlenecks"],
                "run_dir": res["run_dir"],
                "sim_wall_s": res["sim_wall_s"],
                "explanation": explain(c, cands, results, scores, base_strategy),
            }
        )
    base = next(t for t in table if t["candidate_id"] == NO_STRATEGY)
    for t in table:
        t["beats_no_strategy"] = t["rank"] is not None and t["score"] < base["score"]
    options = [t for t in table if t["rank"] is not None][:top_n]
    fastest = min(
        (t for t in table if t["rank"] is not None),
        key=lambda t: (
            V.effective(t["clearance"], "t90_s") + V.effective(t["clearance"], "t100_s"),
            t["candidate_id"],
        ),  # fmt: skip
        default=None,
    )
    best = options[0] if options else None
    beats = bool(best and best["score"] < base["score"])
    beats_t90 = bool(
        best
        and best["clearance"]["t90_s"] is not None
        and best["t90_vs_no_strategy_s"] < -(noise["t90_s"] or 0.0)
    )
    snapshot_id = f"evac:{sit.scenario.id}:{sit.window}:s{seed}:{key[:16]}"
    report: dict[str, Any] = {
        "kind": "evacuation",
        "label": SYNTHETIC_LABEL,
        "scenario": sit.scenario.id,
        "title": sit.scenario.label,
        "fictional": sit.scenario.fictional,
        "window": sit.window,
        "seed": seed,
        "end": sit.end,
        "order_t": float(sit.spec.start),
        "vehicles": sit.spec.vehicles,
        "snapshot_id": snapshot_id,
        "run_dir": rel(out),
        "network": rel(sit.net),
        "network_hash": content_hash(sit.net),
        "evac_net": sit.evac_net,
        "corridors": [
            {k: v for k, v in c.items() if k != "edges"} | {"edges": len(c["edges"])}
            for c in sit.analysis["corridors"]
        ],  # fmt: skip
        "exits": sit.analysis["exits"],
        "weights": w,
        "assumption_ids": list(
            dict.fromkeys(
                [*V.event_ids(), *weight_ids(), *sit.analysis["assumption_ids"], *sit.other_ids]
            )
        ),
        "candidates": table,
        "options": options,
        "no_strategy": base,
        "best_beats_no_strategy": beats,
        "recommended": options[0]["candidate_id"] if beats else NO_STRATEGY,
        "fastest_clearance": fastest["candidate_id"] if fastest else None,
        "best_beats_no_strategy_t90_beyond_noise": beats_t90,
        "noise": noise,
        "replicate": {k: results[REPLICATE][k] for k in ("clearance", "background", "teleports")},
        "fingerprint": fingerprint(results),
        "wall_s": {
            "situation": round(t_sit, 1),
            "evaluation": round(t_eval, 1),
            "total": round(time.perf_counter() - t0, 1),
            "workers": workers or int(V.model("max_workers")),
        },
    }
    if log:
        entry = L.append(
            db,
            "recommendation",
            snapshot_id,
            [{"id": c["id"], "strategy": c["strategy"]} for c in cands],
            [
                {"candidate_id": t["candidate_id"], "score": t["score"], "rank": t["rank"]}
                for t in table
            ],  # fmt: skip
            {
                "kind": "evacuation",
                "run_dir": rel(out),
                "options": [
                    {
                        "rank": o["rank"],
                        "candidate_id": o["candidate_id"],
                        "classification": o["classification"],
                    }
                    for o in options
                ],  # fmt: skip
                "fingerprint": report["fingerprint"],
            },
            actor="strategist",
        )
        report["recommendation_id"] = entry["record_id"]
        report["log_hash"] = entry["hash"]
        report["decision_log"] = rel(db)
    (out / "recommendation.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "recommendation.md").write_text(render_md(report))
    stable = runs_dir / f"{sit.scenario.id}-{sit.window}"
    stable.mkdir(parents=True, exist_ok=True)
    for name in ("recommendation.json", "recommendation.md"):
        shutil.copy2(out / name, stable / name)
    (stable / "RUN_DIR").write_text(rel(out) + "\n")
    return report


def _band(v: float | None, unit: str) -> str:
    return "n/a (neither run reaches it)" if v is None else f"+/- {v:.0f} {unit}"


def _s(v: float | None) -> str:
    return "not reached" if v is None else f"{v:,.0f}"


def render_md(r: dict[str, Any]) -> str:
    lines = [
        f"# Evacuation strategies: {r['scenario']} ({r['window']} window)",
        "",
        f"**{r['label']}.** Fictional scenario. Seed {r['seed']}; order at {r['order_t']:.0f} s; "
        f"{r['vehicles']:,} evacuee vehicles; run `{r['run_dir']}`.",
        "",
        f"{r['title']}",
        "",
        "Times are seconds after the evacuation order. Score = "
        f"{r['weights']['w_t90']} x T90 + {r['weights']['w_t100']} x T100 + penalties "
        "(lower is better; weights in sim/scenarios/evac_settings.yaml). Noise band from a "
        "replicate of the no-strategy run with another SUMO seed: "
        f"T90 {_band(r['noise']['t90_s'], 's')}, T100 {_band(r['noise']['t100_s'], 's')}, "
        f"background delay +/- {r['noise']['delay_veh_h']:.1f} veh-h; delay is penalised only "
        "beyond it; (~) = T90 within the noise band of no strategy.",
        "",
        "| rank | option | T50 | T90 | T100 | out | teleports | bg delay added (veh-h) "
        "| contraflow lane-km | signals | score | class |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in [*r["candidates"], {**r["replicate"], "replicate": True}]:
        c = t["clearance"]
        if t.get("replicate"):
            dd = t["background"]["delay_veh_h"] - r["no_strategy"]["background_delay_veh_h"]
            lines.append(
                f"| noise | no strategy, SUMO seed {r['noise']['replicate_seed']} | "
                f"{_s(c['t50_s'])} | {_s(c['t90_s'])} | {_s(c['t100_s'])} | "
                f"{c['out']}/{c['vehicles']} | {t['teleports']} | {dd:+.2f} | - | - | - | - |"
            )
            continue
        lines.append(
            f"| {t['rank'] or '-'} | {t['candidate_id']}: {t['label']} | {_s(c['t50_s'])} | "
            f"{_s(c['t90_s'])}{' (~)' if t['t90_within_noise'] and t['rank'] else ''} | "
            f"{_s(c['t100_s'])} | {c['out']}/{c['vehicles']} | "
            f"{t['teleports']} | {t['added_veh_h']:+.2f} | {t['contraflow_lane_km']:.2f} | "
            f"{t['signals_retimed']} | "
            f"{t['score']:,.0f} | {t['classification']} |"
        )
    if r["recommended"] == NO_STRATEGY:
        rec_line = (
            "**Recommendation: no strategy.** No option beats the evacuation as written on score; "
            "the ranked options below are alternatives, each worse than no strategy."
        )
    else:
        rec_line = f"**Recommendation: option 1 (`{r['recommended']}`).**"
    fast = next((t for t in r["candidates"] if t["candidate_id"] == r["fastest_clearance"]), None)
    if fast:
        nb = r["no_strategy"]["clearance"]
        vs = (
            f"T90 {fast['t90_vs_no_strategy_s']:+.0f} s versus no strategy"
            if nb["t90_s"] is not None and fast["clearance"]["t90_s"] is not None
            else f"T90 {_s(fast['clearance']['t90_s'])} s (no strategy: {_s(nb['t90_s'])})"
        )
        rec_line += (
            f" Fastest clearance (T90 + T100): `{fast['candidate_id']}`, {vs}, score "
            f"{fast['score']:,.0f} versus {r['no_strategy']['score']:,.0f} (penalty terms: "
            + ", ".join(
                f"{k} {v:,.0f}" for k, v in fast["terms"].items() if k not in ("t90", "t100") and v
            )  # fmt: skip
            + ")."
        )
    lines += ["", rec_line, "", "## Top options", ""]
    for o in r["options"]:
        lines.append(
            f"### {o['rank']}. {o['label']} (`{o['candidate_id']}`, {o['classification']}"
            f"{'' if o['beats_no_strategy'] else ', worse than no strategy'})"
        )
        lines.append("")
        lines += [f"- {x}" for x in o["explanation"]]
        for a in o["action_classes"]:
            lines.append(f"- Action `{a['type']}`: {a['class']} ({a['rule']})")
        lines.append("")
    base = r["no_strategy"]
    lines += [
        "## No strategy: bottleneck edges",
        "",
        "| edge | name | type | lanes | halted veh-h | max halted |",
        "|---|---|---|---|---|---|",
    ]
    for b in base["bottlenecks"]:
        lines.append(
            f"| `{b['edge']}` | {b['name'] or ''} | {b['type']} | {b['lanes']} | "
            f"{b['halted_veh_h']} | {b['max_halted_veh']} |"
        )
    lines += [
        "",
        "Best option beats no strategy on score: "
        f"{'yes' if r['best_beats_no_strategy'] else 'no'}; "
        "on T90 beyond the noise band: "
        f"{'yes' if r['best_beats_no_strategy_t90_beyond_noise'] else 'no'}.",
        f"Wall time: situation {r['wall_s']['situation']} s, {len(r['candidates'])} what-ifs "
        f"{r['wall_s']['evaluation']} s ({r['wall_s']['workers']} workers), total "
        f"{r['wall_s']['total']} s. Fingerprint {r['fingerprint']}.",
    ]
    if r.get("recommendation_id"):
        lines.append(
            f"Decision log: recommendation `{r['recommendation_id']}` in `{r['decision_log']}`; "
            f"approve with `python -m strategist.evacuation approve {r['recommendation_id']} "
            "--option 1`. Nothing is applied without that step."
        )
    lines += ["", "Assumptions: " + ", ".join(r["assumption_ids"]), ""]
    return "\n".join(lines)


# --- approve ------------------------------------------------------------------------------------
def approve(recommendation_id: str, option: int = 1, actor: str = "operator",
            reject: bool = False, db: Path = DEFAULT_DB) -> dict[str, Any]:  # fmt: skip
    """Record a human decision on a ranked option (simulation only: nothing is actuated)."""
    problems = L.verify(db)
    if problems:
        raise RuntimeError(f"decision log {db} fails verification: {problems}")
    rec = L.get(db, recommendation_id)
    if rec is None or rec["kind"] != "recommendation":
        raise KeyError(f"no recommendation {recommendation_id!r} in {db}")
    body = json.loads(rec["recommendation"])
    if body.get("kind") != "evacuation":
        raise ValueError(f"{recommendation_id} is not an evacuation recommendation")
    if L.decisions_for(db, recommendation_id):
        raise RuntimeError(f"recommendation {recommendation_id} already has a decision")
    run_dir = REPO_ROOT / body["run_dir"]
    report = json.loads((run_dir / "recommendation.json").read_text())
    if report.get("log_hash") != rec["hash"]:
        raise RuntimeError("recommendation.json does not match its decision-log record")
    opts = {o["rank"]: o for o in report["options"]}
    if option not in opts:
        raise ValueError(f"option {option} not in the ranked options {sorted(opts)}")
    chosen = opts[option]
    decision = {
        "label": SYNTHETIC_LABEL,
        "kind": "evacuation",
        "recommendation_id": recommendation_id,
        "decision": "rejected" if reject else "approved",
        "option_rank": option,
        "candidate_id": chosen["candidate_id"],
        "option_label": chosen["label"],
        "strategy": chosen["strategy"],
        "classification": chosen["classification"],
        "predicted_clearance": chosen["clearance"],
        "note": "simulation and decision support only; nothing is actuated (PROJECT.md 11)",
    }
    entry = L.append(
        db,
        "decision",
        rec["snapshot_id"],
        [chosen["candidate_id"]],
        [{"candidate_id": chosen["candidate_id"], "score": chosen["score"]}],
        {"recommendation_id": recommendation_id, "recommendation_hash": rec["hash"]},
        decision,
        actor=actor,
    )
    return {**decision, "decision_id": entry["record_id"], "log_hash": entry["hash"]}


# --- CLI ----------------------------------------------------------------------------------------
app = typer.Typer(add_completion=False, help=__doc__)


@app.command("run")
def run_cmd(
    scenario: str = typer.Option(..., "--scenario"),
    window: str | None = typer.Option(None, "--window"),
    seed: int = typer.Option(1, "--seed"),
    workers: int | None = typer.Option(None, "--workers"),
    only: str | None = typer.Option(None, "--only", help="comma-separated candidate ids"),
    end: float | None = typer.Option(None, "--end"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
    no_log: bool = typer.Option(False, "--no-log", help="do not write the decision log"),
) -> None:
    r = recommend(
        scenario, window, seed, workers, only.split(",") if only else None, db, end=end,
        log=not no_log,
    )  # fmt: skip
    typer.echo(render_md(r))


@app.command("approve")
def approve_cmd(
    recommendation_id: str,
    option: int = typer.Option(1, "--option"),
    actor: str = typer.Option("operator", "--actor"),
    reject: bool = typer.Option(False, "--reject"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
) -> None:
    d = approve(recommendation_id, option, actor, reject, db)
    typer.echo(json.dumps(d, indent=2, default=str))


if __name__ == "__main__":
    app()
