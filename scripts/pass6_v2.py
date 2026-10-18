"""Integration pass 6: policy runs on the Tier A network v2 (synthetic demand, uncalibrated).

The v1/m2 policy runs live in runs/<policy id>, and `sim.policies.run.run_policy` deletes an
existing run directory of the same name, so every v2 run goes to runs/v2/ instead. The v2 weekday
baseline is linked there (runs/v2/<baseline id> -> the trackF worktree). Each job refuses to start
when the matching v2 baseline is missing (it would otherwise run a 2 h assignment first).

    uv run python -m scripts.pass6_v2 check
    uv run python -m scripts.pass6_v2 run <job>   # jobs: see JOBS below
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_RUNS = REPO_ROOT / "runs" / "v2"
SAMPLE, SEED = 0.10, 1

JOBS = {
    "bridge_b3": ("bridge", "obhur_bridge_b3"),
    "staggered": ("policy", "staggered_schools_60"),
    "loop_mc": ("loop_mc", "C1"),
    "remote": ("policy", "remote_work_30"),
    "cordon": ("policy", "cordon_center"),
    "bridge_b1": ("bridge", "obhur_bridge_b1"),
    # not run in pass 6 (pending): each is one more city run
    "bridge_b2": ("bridge", "obhur_bridge_b2"),
    "bridge_b3_3x3": ("bridge", "obhur_bridge_b3_3x3"),
    "loop_a0p3": ("loop", "loop_recommended"),
}

app = typer.Typer(add_completion=False, help=__doc__)


def v2_baseline() -> Path:
    from sim.policies.run import find_baseline
    from sim.population.baseline import baseline_config

    net = REPO_ROOT / baseline_config()["net"]
    found = find_baseline("weekday", SAMPLE, SEED, net, V2_RUNS, None)
    if found is None:
        raise typer.Exit(f"no v2 weekday baseline for {net.name} in {V2_RUNS}: not starting")
    return found


@app.command()
def check() -> None:
    b = v2_baseline()
    meta = json.loads((b / "meta.json").read_text())
    typer.echo(f"{b.name}: network {meta['network_hash']}, population {meta['population_hash']}")


@app.command()
def run(job: str) -> None:
    kind, target = JOBS[job]
    v2_baseline()
    if kind == "policy":
        from sim.policies.run import run_policy

        meta = run_policy(target, None, SAMPLE, SEED, V2_RUNS)
        typer.echo(f"{meta['run_id']} done")
    elif kind == "bridge":
        from sim.bridge.run import run_bridge_policy

        meta = run_bridge_policy(target, None, SAMPLE, SEED, V2_RUNS)
        typer.echo(meta["bridge"]["headline"])
    elif kind == "loop":  # assumed-share variant (alpha 0.3), Track D's recommended policy
        from sim.loop.run import run_loop_policy

        meta = run_loop_policy(target, None, SAMPLE, SEED, V2_RUNS)
        typer.echo(meta["loop"]["headline"])
    else:  # Loop C1 with the mode-choice logit (Track H), measured service case
        from sim.loop.evaluate import (
            LOOP_DIR,
            SYNTHETIC_LABEL,
            load_candidates,
            make_policy,
            merge_results,
            mode_choice_params,
            run_one,
        )

        params, suffix = mode_choice_params(LOOP_DIR / "config" / "mode_choice.yaml", None, None,
                                            None)  # fmt: skip
        c = load_candidates(LOOP_DIR / "candidates.yaml")[target]
        pid = f"loop_{target.lower()}{suffix}"
        pol = make_policy(pid, f"Loop {target} {c['name']} (shuttle, mode choice {suffix[3:]}; "
                          f"{SYNTHETIC_LABEL})", [c], "shuttle", params)  # fmt: skip
        rep = run_one(pol, SAMPLE, SEED, V2_RUNS, prune=True)
        rep["candidate"] = target
        merge_results(V2_RUNS / "evaluation_mode_choice.json", [rep])
        typer.echo(rep["headline"])


def row(report: Path) -> str:
    """One docs/policies.md-style row from a policy_report.json (vs its matched control or the
    baseline), with the absolute VHT change and the teleport share of both sides."""
    r = json.loads(report.read_text())
    k = {x["kpi"]: x for x in r["kpis"]}

    def pct(name: str) -> str:
        v = k[name]["delta_pct"]
        return "-" if v is None else f"{v:+.1f} %"

    vs = "weekday (matched control)" if r.get("control") else "weekday"
    tp = k["teleport_share"]
    return (
        f"| `{r['policy']}` | {vs} | {pct('mean_delay_s')} | {pct('am_peak_mean_delay_s')} | "
        f"{pct('vkt')} | {pct('vht')} ({k['vht']['delta']:+,.0f} h) | {pct('co2_t')} | "
        f"{pct('peak_spreading_top_hour_share')} | {pct('trips_completed')} | "
        f"{tp['baseline']:.3f} -> {tp['policy']:.3f} |"
    )


@app.command()
def summary() -> None:
    for rep in sorted(V2_RUNS.glob("*/policy_report.json")):
        typer.echo(f"{rep.parent.name}: {row(rep)}")


if __name__ == "__main__":
    app()
