"""Loop optimisation: greedy corridor selection under the km budget, then a sweep on the selected
set, noise runs, the recommendation, and the results tables in docs/loop.md.

    python -m sim.loop.optimise                  # runs what is missing (sequential, resumable)
    python -m sim.loop.optimise --no-run         # re-render docs/loop.md from finished runs

Objective: congestion relief, the vehicle-hours saved by the vehicles that are on the road in
both runs (removed cars are not counted as savings; sim/loop/kpis.py), per USD M of capex.

1. Candidate results: sim/loop/results/evaluation.json (python -m sim.loop.evaluate, seed 1 and the
   sim-seed-2 replicates). Each candidate has two paired estimates: seed 1 against the baseline,
   seed 2 against the seed-2 baseline replicate (Track A's replicate machinery).
2. Noise: the replicate's own relief against the seed-1 baseline (same demand, different sim seed)
   is the noise of one comparison; the two-seed mean has about 1/sqrt(2) of it.
3. Greedy: candidates by mean relief per tunnel-km, added while the budget (25 km) allows, if both
   seeds agree on the sign, the mean exceeds the noise of a two-seed mean, and the alignment does
   not overlap one already chosen. The selected set is run together (no additivity assumed).
4. Sweep on the selected set. Levers: mode (shuttle / private-EV), tunnel speed and toll (YAML
   sweep lists). Uncertainties, not choices: alpha, access radius, engineering capacity and the
   time-competitive shift (A-loop-017) under measured and vendor speeds/waits.
5. Recommendation: the lever setting with the most relief per USD M at central assumptions among
   runs that pass the quality gate (pair and segment capacity exceedance <= 10 %, teleports not
   worse than the comparison by more than the replicate's teleport change, positive relief); band
   from the uncertainty runs, the noise and the capex range.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL
from sim.loop.evaluate import (
    RESULTS,
    DiskFull,
    blocked,
    load_candidates,
    make_policy,
    merge_results,
    run_one,
)
from sim.loop.schema import loop_config
from sim.policies.edges import utm_xy

LOOP_DIR = Path(__file__).resolve().parent
DOC = REPO_ROOT / "docs" / "loop.md"
RECOMMENDED = REPO_ROOT / "sim" / "policies" / "loop_recommended.yaml"
SAMPLE, SEED = 0.10, 1

Sweep = list[tuple[str, str, dict[str, Any], str, str]]


def sweep_plan(cfg: dict[str, Any]) -> Sweep:
    """(run suffix, mode, params, role, description) from the YAML sweep lists."""
    v0 = float(cfg["tunnel"]["default_speed_kmh"])
    a0 = float(cfg["shift"]["alpha"])
    r0 = float(cfg["access"]["radius_m"])
    t0 = float(cfg["private"]["toll_sar"])
    plan: Sweep = [
        (
            "",
            "shuttle",
            {},
            "lever",
            f"shuttle, central (alpha {a0:g}, {v0:g} km/h, measured capacity)",
        )
    ]
    for v in cfg["tunnel"]["speeds_kmh"]:
        if float(v) != v0:
            plan.append(
                (f"_v{v:g}", "shuttle", {"speed_kmh": float(v)}, "lever", f"shuttle at {v:g} km/h")
            )
    for toll in sorted(cfg["private"]["toll_sweep_sar"], key=lambda x: float(x) != t0):
        plan.append(
            (
                f"_private_toll{toll:g}",
                "private",
                {"toll_sar": float(toll)},
                "lever",
                f"private-EV, SAR {toll:g} toll, {v0:g} km/h",
            )
        )
    for a in cfg["shift"]["alpha_sweep"]:
        if float(a) != a0:
            sfx = f"_a{a:g}".replace(".", "p")
            plan.append(
                (sfx, "shuttle", {"alpha": float(a)}, "uncertainty", f"shift share alpha {a:g}")
            )
    for r in cfg["access"]["radius_sweep_m"]:
        if float(r) != r0:
            plan.append(
                (
                    f"_r{r:g}",
                    "shuttle",
                    {"radius_o_m": float(r), "radius_d_m": float(r)},
                    "uncertainty",
                    f"access radius {r:g} m",
                )
            )
    plan.append(
        (
            f"_private_toll{t0:g}_capeng",
            "private",
            {"toll_sar": t0, "capacity": "engineering"},
            "uncertainty",
            f"private-EV, SAR {t0:g} toll, engineering capacity (1.5 s headway)",
        )
    )
    plan.append(
        (
            "_capeng",
            "shuttle",
            {"capacity": "engineering"},
            "uncertainty",
            "engineering capacity (1.5 s headway, vendor side)",
        )
    )
    vmin, vmax = min(cfg["tunnel"]["speeds_kmh"]), max(cfg["tunnel"]["speeds_kmh"])
    plan += [
        (
            "_comp",
            "shuttle",
            {"competitive_only": True},
            "uncertainty",
            f"time-competitive shift only, measured case ({v0:g} km/h, 12.5 min wait, "
            "5.3 s headway)",
        ),
        (
            f"_comp_v{vmin:g}",
            "shuttle",
            {"competitive_only": True, "speed_kmh": float(vmin)},
            "uncertainty",
            f"time-competitive shift only, Vegas-like {vmin:g} km/h, 12.5 min wait",
        ),
        (
            "_comp_vendor",
            "shuttle",
            {"competitive_only": True, "speed_kmh": float(vmax), "capacity": "engineering"},
            "uncertainty",
            f"time-competitive shift only, vendor case ({vmax:g} km/h, 2 min wait, 1.5 s headway)",
        ),
    ]
    return plan


def stations_xy(c: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    return utm_xy([s["lon"] for s in c["stations"]], [s["lat"] for s in c["stations"]])


def overlap(a: dict[str, Any], b: dict[str, Any], cfg: dict[str, Any]) -> bool:
    from sim.loop.site import overlaps

    ax, ay = stations_xy(a)
    bx, by = stations_xy(b)
    return overlaps(pd.Series({"sx": ax, "sy": ay}), [pd.Series({"sx": bx, "sy": by})], cfg)


def relief_of(e: dict[str, Any]) -> float:
    """Relief used for decisions: the two-seed mean when the replicate exists."""
    return float(e.get("relief_mean", e["relief_vht_per_day"]))


def per_km(e: dict[str, Any]) -> float:
    return relief_of(e) / float(e["tunnel_km"]) if e["tunnel_km"] else -1e9


def pair_seeds(evals: dict[str, dict[str, Any]], runs: dict[str, dict[str, Any]]) -> None:
    """Attach the sim-seed-2 relief (vs the seed-2 baseline replicate) and the two-seed mean."""
    for e in evals.values():
        r2 = runs.get(f"{e['run_id']}-sim2")
        if r2 is None or r2.get("relief_vs_replicate") is None:
            continue
        e["relief_s2"] = int(r2["relief_vs_replicate"])
        e["relief_mean"] = round((e["relief_vht_per_day"] + e["relief_s2"]) / 2.0)


def greedy(
    cands: dict[str, dict[str, Any]],
    evals: dict[str, dict[str, Any]],
    budget: float,
    noise: float,
    cfg: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    order = sorted(evals, key=lambda c: -per_km(evals[c]))
    chosen: list[str] = []
    used = 0.0
    log = []
    for cid in order:
        e, c = evals[cid], cands[cid]
        km = float(e["tunnel_km"])
        s1, s2 = e["relief_vht_per_day"], e.get("relief_s2")
        why = "selected"
        if s2 is not None and min(s1, s2) <= 0:
            why = f"sign differs between sim seeds ({s1:,} / {s2:,})"
        elif s2 is not None and relief_of(e) <= noise / np.sqrt(2.0):
            why = f"mean {relief_of(e):,.0f} inside two-seed noise {noise / np.sqrt(2.0):,.0f}"
        elif s2 is None and s1 <= noise:
            why = f"{s1:,} inside one-seed noise {noise:,.0f}"
        elif used + km > budget:
            why = f"over budget ({used + km:.1f} > {budget:g} km)"
        elif any(overlap(c, cands[o], cfg) for o in chosen):
            why = "overlaps " + ", ".join(o for o in chosen if overlap(c, cands[o], cfg))
        if why == "selected":
            chosen.append(cid)
            used += km
        log.append(
            {
                "candidate": cid,
                "km": km,
                "relief_per_km": round(per_km(e), 1),
                "decision": why,
                "cumulative_km": round(used, 2),
            }
        )
    # knapsack correction (modified greedy): a single corridor that relieves more than the whole
    # per-km greedy set (because the budget left after the first pick fits nothing) wins
    passed = ("selected", "over budget", "overlaps")
    singles = [
        r["candidate"]
        for r in log
        if r["decision"].startswith(passed) and float(evals[r["candidate"]]["tunnel_km"]) <= budget
    ]
    if singles:
        best = max(singles, key=lambda c: relief_of(evals[c]))
        if relief_of(evals[best]) > sum(relief_of(evals[c]) for c in chosen):
            for r in log:
                if r["candidate"] in chosen and r["candidate"] != best:
                    r["decision"] = f"dropped: {best} alone relieves more"
                elif r["candidate"] == best:
                    r["decision"] = "selected (relieves more alone than the per-km greedy set)"
            chosen = [best]
            km0 = float(evals[best]["tunnel_km"])
            for r in log:
                r["cumulative_km"] = round(km0, 2) if r["candidate"] == best else None
                if r["decision"].startswith(("over budget", "selected")) and r["candidate"] != best:
                    r["decision"] = f"over budget with {best} ({km0 + r['km']:.1f} > {budget:g} km)"
    return chosen, log


def noise_runs(runs_dir: Path, base: dict[str, Any], quiet: bool) -> dict[str, Any]:
    """Baseline replicate with sim seed 2 (Track A machinery) against the seed-1 baseline."""
    from sim.loop.evaluate import baseline_replicate
    from sim.loop.kpis import relief

    meta = baseline_replicate(runs_dir, 2, SAMPLE, SEED, quiet)
    rel = relief(
        runs_dir / meta["run_id"] / "tripinfo.parquet",
        runs_dir / base["run_id"] / "tripinfo.parquet",
        SAMPLE,
        float(base["sim_end_s"]),
    )
    vht = float(meta["result"]["vht"])
    return {
        "run": meta["run_id"],
        "vht": vht,
        "vht_delta": round(vht - base["result"]["vht"]),
        "relief_delta": round(rel["relief_vht_per_day"]),
        "noise_relief": round(abs(rel["relief_vht_per_day"])),
        "teleport_share": meta["result"]["teleport_share"],
        "teleport_share_delta": round(
            meta["result"]["teleport_share"] - base["result"]["teleport_share"], 4
        ),
    }


def sweep_policy(
    suffix: str, mode: str, params: dict[str, Any], chosen: list[dict[str, Any]], tag: str
) -> Any:
    pid = f"loop_opt_{tag}{suffix}".lower()
    title = f"Loop {tag}: {' + '.join(c['id'] for c in chosen)} ({mode}; {SYNTHETIC_LABEL})"
    return make_policy(pid, title, chosen, mode, params)


def passes(rep: dict[str, Any], cfg: dict[str, Any], tele_tol: float) -> tuple[bool, str]:
    f = rep["flags"]
    lim = float(cfg["quality"]["max_capacity_exceedance"])
    ex = f.get("pair_exceedance_share") or 0.0
    seg = f.get("segment_exceedance_share") or 0.0
    if ex > lim:
        return False, f"pair capacity exceedance {ex:.1%}"
    if seg > lim:
        return False, f"tunnel segment exceedance {seg:.1%}"
    util = f.get("segment_peak_utilisation") or 0.0
    if f.get("segment_exceedance_share") is None and util > float(
        cfg["quality"]["segment_utilisation_fallback"]
    ):
        return False, f"tunnel segment peak utilisation {util:.2f} (teleport-assisted)"
    t, t0 = f.get("teleport_share"), f.get("teleport_share_compare")
    if t is not None and t0 is not None and t > t0 + tele_tol:
        return False, f"teleports {t:.3f} vs {t0:.3f}"
    if rep["relief_vht_per_day"] <= 0:
        return False, "no relief"
    return True, "ok"


# ---------------------------------------------------------------------------- rendering


def fmt(v: Any, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(h for _, h in cols) + " |"
    sep = "|" + "---|" * len(cols)
    body = ["| " + " | ".join(fmt(r.get(k)) for k, _ in cols) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def per_usd_text(relief: float, cx: dict[str, float]) -> str:
    return f"{relief / cx['central']:.1f} ({relief / cx['high']:.1f} to {relief / cx['low']:.1f})"


def rank_rows(cands: dict[str, dict[str, Any]], evals: dict[str, dict[str, Any]]) -> list[dict]:
    rows = []
    for cid, e in evals.items():
        c = cands[cid]
        rows.append(
            {
                "id": cid,
                "name": c["name"],
                "origin": c["origin"],
                "km": e["tunnel_km"],
                "stations": e["stations"],
                "pax": e["passengers_per_day"],
                "rel1": e["relief_vht_per_day"],
                "rel2": e.get("relief_s2"),
                "rel": round(relief_of(e)),
                "rel_pct": e.get("relief_pct"),
                "vht": e["vht_saved_per_day"],
                "net": e.get("net_person_hours_per_day"),
                "am": e["am_peak_delay_change_pct"],
                "per_km": round(per_km(e), 1),
                "per_usd": per_usd_text(relief_of(e), e["capex_usd_m"]),
                "capex": f"{e['capex_usd_m']['low']:,.0f}-{e['capex_usd_m']['high']:,.0f}",
                "exceed": e["flags"].get("pair_exceedance_share"),
                "seg": e["flags"].get("segment_peak_utilisation"),
                "slower": e["flags"].get("share_slower_than_car"),
                "tele": e["flags"].get("teleport_share"),
            }
        )
    rows.sort(key=lambda r: -(r["per_km"] if r["per_km"] is not None else -1e9))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


RANK_COLS = [
    ("rank", "rank"),
    ("id", "id"),
    ("name", "alignment"),
    ("origin", "origin"),
    ("km", "tunnel-km"),
    ("stations", "stations"),
    ("pax", "passengers/day"),
    ("rel1", "relief seed 1"),
    ("rel2", "relief seed 2"),
    ("rel", "relief mean"),
    ("per_km", "relief/day per km"),
    ("per_usd", "relief/day per USD M (range)"),
    ("am", "AM-peak road delay % (seed 1)"),
    ("vht", "city VHT saved (seed 1)"),
    ("net", "net person-h (seed 1)"),
    ("capex", "capex USD M"),
    ("exceed", "pair exceedance"),
    ("seg", "segment peak util."),
    ("slower", "riders slower than car"),
    ("tele", "teleports/veh"),
]

SWEEP_COLS = [
    ("config", "configuration"),
    ("role", "role"),
    ("km", "tunnel-km"),
    ("pax", "passengers or cars re-routed"),
    ("rel", "relief VHT/day"),
    ("rel_pct", "relief %"),
    ("per_usd", "relief/day per USD M"),
    ("am", "AM-peak road delay %"),
    ("net", "net person-h/day"),
    ("vht", "city VHT saved"),
    ("exceed", "pair exceedance"),
    ("segx", "segment exceedance"),
    ("seg", "segment peak util."),
    ("slower", "riders slower than car"),
    ("tele", "teleports/veh"),
    ("ok", "quality gate"),
]


def sweep_row(desc: str, role: str, rep: dict[str, Any], ok: str) -> dict[str, Any]:
    return {
        "config": desc,
        "role": role,
        "km": rep["tunnel_km"],
        "run": rep["run_id"],
        "pax": rep.get("passengers_per_day") or rep.get("cars_rerouted"),
        "rel": rep["relief_vht_per_day"],
        "rel_pct": rep.get("relief_pct"),
        "per_usd": per_usd_text(rep["relief_vht_per_day"], rep["capex_usd_m"]),
        "per_usd_central": rep["relief_per_usd_m"]["central"],
        "am": rep["am_peak_delay_change_pct"],
        "net": rep.get("net_person_hours_per_day"),
        "vht": rep["vht_saved_per_day"],
        "exceed": rep["flags"].get("pair_exceedance_share"),
        "segx": rep["flags"].get("segment_exceedance_share"),
        "seg": rep["flags"].get("segment_peak_utilisation"),
        "slower": rep["flags"].get("share_slower_than_car"),
        "tele": rep["flags"].get("teleport_share"),
        "ok": ok,
        "toll_revenue": (rep.get("private") or {}).get("toll_revenue_sar_per_day"),
        "tunnel_entries": (rep.get("private") or {}).get("tunnel_entries_per_day"),
    }


def replace_section(text: str, name: str, body: str) -> str:
    pat = re.compile(rf"(<!-- LOOP:{name} -->)(.*?)(<!-- /LOOP:{name} -->)", re.S)
    if not pat.search(text):
        raise ValueError(f"docs/loop.md has no LOOP:{name} markers")
    return pat.sub(lambda m: f"{m.group(1)}\n{body.strip()}\n{m.group(3)}", text)


# ---------------------------------------------------------------------------- main


def load_evals(cands: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict]:
    ev_doc = json.loads((RESULTS / "evaluation.json").read_text())
    evals = {
        r["candidate"]: r
        for r in ev_doc["runs"].values()
        if r.get("candidate") in cands and r["run_id"] == f"loop_{r['candidate'].lower()}"
    }
    pair_seeds(evals, ev_doc["runs"])
    return evals, ev_doc


def optimise(run: bool = True, budget: float | None = None, quiet: bool = False) -> dict[str, Any]:
    cfg = loop_config()
    budget = float(budget or cfg["budget_km"])
    runs_dir = REPO_ROOT / "runs"
    cands = load_candidates(LOOP_DIR / "candidates.yaml")
    evals, _ = load_evals(cands)
    missing = sorted(set(cands) - set(evals))
    if missing and run:
        for cid in missing:
            c = cands[cid]
            pol = make_policy(f"loop_{cid.lower()}", f"Loop {cid} {c['name']}", [c], "shuttle", {})
            rep = run_one(pol, SAMPLE, SEED, runs_dir, prune=True, quiet=quiet)
            rep["candidate"] = cid
            merge_results(RESULTS / "evaluation.json", [rep])
        evals, _ = load_evals(cands)
    base = json.loads((runs_dir / next(iter(evals.values()))["compare"] / "meta.json").read_text())
    prev_path = RESULTS / "optimise.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    noise = noise_runs(runs_dir, base, quiet) if run or not prev else prev["noise"]
    chosen_ids, glog = greedy(cands, evals, budget, noise["noise_relief"], cfg)
    chosen = [cands[c] for c in chosen_ids]
    tag = "".join(c.lower() for c in chosen_ids)
    result: dict[str, Any] = {
        "label": SYNTHETIC_LABEL,
        "budget_km": budget,
        "noise": noise,
        "greedy": glog,
        "selected": chosen_ids,
        "selected_km": round(sum(evals[c]["tunnel_km"] for c in chosen_ids), 2),
        "sweep": [],
        "placebo": None,
        "recommended": None,
    }
    reports: dict[str, dict[str, Any]] = {}
    plan = sweep_plan(cfg)
    tele_tol = max(
        abs(noise["teleport_share_delta"]), float(cfg["quality"]["teleport_tolerance_min"])
    )
    for suffix, mode, params, role, desc in plan if chosen else []:
        pol = sweep_policy(suffix, mode, params, chosen, tag)
        rep_path = runs_dir / pol.id / "loop_report.json"
        if run:
            rep = run_one(pol, SAMPLE, SEED, runs_dir, prune=True, quiet=quiet)
            merge_results(RESULTS / "optimise_runs.json", [rep])
        elif rep_path.exists():
            rep = json.loads(rep_path.read_text())
        else:
            continue
        reports[suffix] = rep
        ok, why = passes(rep, cfg, tele_tol)
        result["sweep"].append(sweep_row(desc, role, rep, why) | {"suffix": suffix, "pass": ok})
    if chosen:
        pol = sweep_policy("_placebo_a0", "shuttle", {"alpha": 0.0}, chosen, tag)
        placebo_path = runs_dir / pol.id / "loop_report.json"
        if run:
            result["placebo"] = run_one(pol, SAMPLE, SEED, runs_dir, prune=True, quiet=quiet)
        elif placebo_path.exists():
            result["placebo"] = json.loads(placebo_path.read_text())
    best = recommend(result["sweep"], cfg)
    result["recommended"] = best
    if best is not None:
        suffix, mode, params = next((s, m, p) for s, m, p, _, _ in plan if s == best["suffix"])
        pol = sweep_policy(suffix, mode, params, chosen, tag)
        rp = prev.get("replicate") or {}
        if run:
            rp = replicate(pol, runs_dir, quiet)
        elif not str(rp.get("run", "")).startswith(pol.id):
            rp = {}
        result["replicate"] = rp or None
        result["band"] = band(best, reports, noise, rp.get("relief_vs_seed2_baseline"))
        write_policy_yaml(pol, RECOMMENDED, best)
    prev_path.write_text(json.dumps(result, indent=2, default=float))
    render(result, cands, evals)
    return result


def write_policy_yaml(pol: Any, path: Path, best: dict[str, Any]) -> None:
    """The recommended configuration as a reusable policy file (python -m sim.loop.run ...)."""
    import yaml

    doc = pol.model_dump(exclude_none=True, exclude={"report"})
    doc["id"] = path.stem
    doc["title"] = f"Recommended Loop: {best['config']} ({SYNTHETIC_LABEL})"
    for t in doc["transforms"]:
        t["assumption"] = (
            "A-loop-001..020 (docs/assumptions-trackD.md); parameters from "
            "sim/loop/config/loop.yaml unless set here"
        )
    head = (
        f"# Recommended Loop configuration (python -m sim.loop.optimise; run {best['run']}).\n"
        f"# {SYNTHETIC_LABEL}. Run: uv run python -m sim.loop.run {path.stem}\n"
    )
    path.write_text(head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))


def usage(r: dict[str, Any]) -> float:
    """Daily Loop trips of a sweep row: tunnel entries (private) or passengers (shuttle)."""
    if r["suffix"].startswith("_private"):
        return float(r.get("tunnel_entries") or 0.0)
    return float(r.get("pax") or 0.0)


def recommend(sweep: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict | None:
    """Pick the option with the most relief (same corridors, so also the most per USD M) among
    those that pass the quality gate and whose Loop carries a meaningful number of trips.

    Options: shuttle (runs at different tunnel speeds pooled as replicates: shuttles never use
    surface roads, so speed cannot change road relief in this model), shuttle with ridership capped
    by the measured capacity (the alpha runs below the central alpha that pass the gate), and each
    private-EV toll. An option whose Loop carries fewer than `min_daily_trips` trips cannot cause
    city-scale relief; its measured relief is simulation noise. If no option qualifies, the best
    option is returned with its failure named. Engineering-capacity (vendor) runs that qualify are
    listed as the vendor-case alternatives."""
    cfg = cfg or loop_config()
    min_trips = float(cfg["quality"]["min_daily_trips"])
    a0 = float(cfg["shift"]["alpha"])
    levers = [r for r in sweep if r["role"] == "lever"]
    shuttle = [r for r in levers if not r["suffix"].startswith("_private")]
    options = []
    central = next((r for r in shuttle if r["suffix"] == ""), None)
    if central is not None:
        options.append(
            central
            | {
                "relief_used": round(float(np.mean([r["rel"] for r in shuttle]))),
                "pooled_from": [r["run"] for r in shuttle],
                "pooled_values": [r["rel"] for r in shuttle],
            }
        )
    for r in sweep:
        capped = r["suffix"].startswith("_a") and float(r["suffix"][2:].replace("p", ".")) < a0
        if r["suffix"].startswith("_private") and r["role"] == "lever" or capped:
            label = (
                f"{r['config']} (ridership capped by the measured capacity)"
                if capped
                else r["config"]
            )
            options.append(
                r
                | {
                    "config": label,
                    "relief_used": r["rel"],
                    "pooled_from": [r["run"]],
                    "pooled_values": [r["rel"]],
                }
            )
    if not options:
        return None
    for o in options:
        o["eligible"] = bool(o["pass"]) and usage(o) >= min_trips
        if o["pass"] and not o["eligible"]:
            o["ok"] = f"only {usage(o):,.0f} Loop trips/day (< {min_trips:,.0f}): relief is noise"
    eligible = [o for o in options if o["eligible"]]
    best = max(eligible or options, key=lambda o: o["relief_used"])
    best["alternatives"] = [
        {"config": o["config"], "relief": o["relief_used"], "gate": o["ok"]}
        for o in options
        if o is not best
    ]
    best["vendor_alternatives"] = [
        {"config": r["config"], "relief": r["rel"], "run": r["run"]}
        for r in sweep
        if "engineering" in r["config"] and r["pass"] and usage(r) >= min_trips
    ]
    if not best["eligible"]:
        best["passing_variants"] = best["vendor_alternatives"]
    return best


def band(best: dict[str, Any], reports: dict[str, dict[str, Any]], noise: dict[str, Any],
         replicate_relief: float | None = None) -> dict[str, Any]:  # fmt: skip
    """Band of the recommended option's relief: its own runs (pooled speed runs for the shuttle
    option) and its seed-2 replicate, widened by the noise of one comparison (baseline
    replicate); per USD M additionally over the capex range. Behavioural and capacity
    uncertainties (alpha, radius, engineering capacity, time-competitive shift) are reported as
    separate sweep rows, not folded in."""
    vals = list(best["pooled_values"])
    if replicate_relief is not None:
        vals.append(replicate_relief)
    lo = min(vals) - noise["noise_relief"]
    hi = max(vals) + noise["noise_relief"]
    cx = reports[best["suffix"]]["capex_usd_m"]
    rel = round(float(np.mean(vals)))
    return {
        "relief_vht_per_day": rel,
        "relief_values": vals,
        "relief_range": [round(lo), round(hi)],
        "per_usd_m_central": round(rel / cx["central"], 2),
        "per_usd_m_range": [round(lo / cx["high"] if lo > 0 else lo / cx["low"], 2),
                            round(hi / cx["low"], 2)],
        "capex_usd_m": cx,
    }  # fmt: skip


def replicate(pol: Any, runs_dir: Path, quiet: bool) -> dict[str, Any]:
    """The recommended configuration re-simulated with sim seed 2, against the seed-2 baseline."""
    from sim.loop.evaluate import baseline_replicate, pair_with_replicate

    rep = run_one(
        pol, SAMPLE, SEED, runs_dir, prune=True, sim_seed=2, run_id=f"{pol.id}-sim2", quiet=quiet
    )
    pair_with_replicate(rep, runs_dir, baseline_replicate(runs_dir, 2, SAMPLE, SEED, quiet))
    return {"run": rep["run_id"], "relief_vs_seed2_baseline": rep["relief_vs_replicate"]}


def render(
    res: dict[str, Any], cands: dict[str, dict[str, Any]], evals: dict[str, dict[str, Any]]
) -> None:
    text = DOC.read_text()
    text = replace_section(text, "ranking", table(rank_rows(cands, evals), RANK_COLS))
    cand_rows = [
        {
            "id": cid,
            "name": c["name"],
            "origin": c["origin"],
            "km": c["tunnel_km"],
            "n": len(c["stations"]),
            "stations": " · ".join(s["name"] for s in c["stations"]),
            "cap": c["captured_delay_h"],
            "trips": c["captured_trips"],
        }
        for cid, c in cands.items()
    ]
    text = replace_section(
        text,
        "candidates",
        table(
            cand_rows,
            [
                ("id", "id"),
                ("name", "alignment"),
                ("origin", "origin"),
                ("km", "tunnel-km"),
                ("n", "stations"),
                ("stations", "station sites (district or anchor)"),
                ("cap", "captured delay h/day (siting score)"),
                ("trips", "capturable trips/day"),
            ],
        ),
    )
    text = replace_section(
        text,
        "greedy",
        table(
            res["greedy"],
            [
                ("candidate", "candidate"),
                ("km", "tunnel-km"),
                ("relief_per_km", "relief/day per km"),
                ("decision", "decision"),
                ("cumulative_km", "selected km"),
            ],
        ),
    )
    sweep_md = table(res["sweep"], SWEEP_COLS) if res["sweep"] else "No corridor was selected."
    priv = [r for r in res["sweep"] if r.get("toll_revenue") is not None]
    if priv:
        sweep_md += (
            "\n\nPrivate-EV use: "
            + "; ".join(
                f"{r['config']}: {fmt(r['tunnel_entries'])} entries/day, toll revenue SAR "
                f"{fmt(r['toll_revenue'])}/day"
                for r in priv
            )
            + "."
        )
    text = replace_section(text, "sweep", sweep_md)
    n = res["noise"]
    noise_md = (
        f"- Baseline replicate (sim seed 2, `runs/{n['run']}`, no policy): relief "
        f"{n['relief_delta']:+,} VHT/day and city VHT {n['vht_delta']:+,} VHT/day against seed 1; "
        f"teleports/veh {n['teleport_share']:.3f} ({n['teleport_share_delta']:+.4f}). One "
        f"comparison is therefore uncertain by about +/- {n['noise_relief']:,} VHT/day, a "
        f"two-seed mean by about +/- {n['noise_relief'] / np.sqrt(2):,.0f}.\n"
    )
    pl = res.get("placebo") or {}
    if pl:
        noise_md += (
            f"- Network placebo (`runs/{pl['run_id']}`: tunnels and ramps built, alpha 0, "
            f"no shuttles): relief {pl['relief_vht_per_day']:+,} VHT/day (inside the "
            "noise band means the tunnel network alone does not move the surface "
            "KPIs).\n"
        )
    rp = res.get("replicate") or {}
    if rp:
        noise_md += (
            f"- Recommended configuration re-simulated with sim seed 2 (`runs/{rp['run']}`)"
            f": relief {rp['relief_vs_seed2_baseline']:,} VHT/day against the seed-2 "
            "baseline.\n"
        )
    text = replace_section(text, "noise", noise_md)
    best = res.get("recommended")
    if best:
        b = res["band"]
        pooled = f"{len(best['pooled_values'])} seed-1 run(s)" + (
            " and the seed-2 replicate" if res.get("replicate") else ""
        )
        sel = " + ".join(
            f"{c} ({cands[c]['name']}, {cands[c]['tunnel_km']} km)" for c in res["selected"]
        )
        rec_md = (
            f"**Corridors:** {sel}; {res['selected_km']} tunnel-km of the {res['budget_km']:g} km "
            f"budget.\n\n**Policy:** {best['config']} (run `runs/{best['run']}`; policy file "
            f"`sim/policies/loop_recommended.yaml`).\n\n"
            f"| item | value |\n|---|---|\n"
            f"| congestion relief, VHT/day | {b['relief_vht_per_day']:,} (mean of "
            f"{', '.join(f'{v:,}' for v in b['relief_values'])}: {pooled}; "
            f"band {b['relief_range'][0]:,} to {b['relief_range'][1]:,} with the replicate "
            f"noise) |\n"
            f"| relief per day per USD M | {b['per_usd_m_central']:.1f} at central capex "
            f"(band {b['per_usd_m_range'][0]:.1f} to {b['per_usd_m_range'][1]:.1f} with noise and "
            f"capex range) |\n"
            f"| capex USD M (low / central / high) | {b['capex_usd_m']['low']:,.0f} / "
            f"{b['capex_usd_m']['central']:,.0f} / {b['capex_usd_m']['high']:,.0f} |\n"
            f"| AM-peak road delay change | {fmt(best['am'], 2)} % |\n"
            f"| passengers (or cars re-routed) per day | {fmt(best['pax'])} |\n"
            f"| net person-hours per day | {fmt(best['net'])} |\n"
            f"| pair / segment capacity exceedance | {fmt(best['exceed'], 3)} / "
            f"{fmt(best['segx'], 3)} |\n"
            f"| riders slower than by car | {fmt(best['slower'], 3)} |\n"
            f"| teleports per vehicle | {fmt(best['tele'], 3)} |\n"
            f"| quality gate | {best['ok']} |\n"
        )
        if not best.get("eligible", best["pass"]):
            alts = "; ".join(
                f"{v['config']} ({v['relief']:,} VHT/day, `runs/{v['run']}`)"
                for v in best.get("passing_variants", [])
            )
            rec_md += (
                f"\n**Quality gate not met at central assumptions** ({best['ok']}). "
                f"Variants that pass: {alts or 'none'}.\n"
            )
        if best.get("vendor_alternatives"):
            rec_md += (
                "\nVendor-capacity case (engineering headway 1.5 s, not demonstrated): "
                + "; ".join(
                    f"{v['config']}: {v['relief']:,} VHT/day (`runs/{v['run']}`)"
                    for v in best["vendor_alternatives"]
                )
                + ".\n"
            )
        if best.get("alternatives"):
            rec_md += (
                "\nOther options: "
                + "; ".join(
                    f"{a['config']}: {a['relief']:,} VHT/day ({a['gate']})"
                    for a in best["alternatives"]
                )
                + ".\n"
            )
    elif not res["selected"]:
        rec_md = (
            "No candidate passed the greedy step (consistent, above-noise relief); there is "
            "no recommended configuration."
        )
    else:
        rec_md = "No lever configuration passed the quality gate; see the sweep table."
    text = replace_section(text, "recommendation", rec_md)
    DOC.write_text(text)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    no_run: bool = typer.Option(False, "--no-run", help="only re-render from finished runs"),
    budget_km: float | None = typer.Option(None),
) -> None:
    try:
        res = optimise(run=not no_run, budget=budget_km)
    except DiskFull as e:
        blocked("disk")
        raise typer.Exit(f"stopped: {e}") from e
    typer.echo(f"selected {res['selected']} ({res['selected_km']} km)")
    if res.get("recommended"):
        typer.echo(f"recommended: {res['recommended']['config']} ({res['recommended']['run']})")
    typer.echo("wrote docs/loop.md, sim/loop/results/optimise.json")


if __name__ == "__main__":
    app()
