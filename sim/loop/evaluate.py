"""Evaluate Loop candidates: one Tier A policy run per candidate against the matched baseline.

    python -m sim.loop.evaluate --candidates sim/loop/candidates.yaml
    python -m sim.loop.evaluate --candidates sim/loop/candidates.yaml --ids C1,C3 --alpha 0.3
    python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1
    python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --demo

Default configuration (brief): shuttle mode, alpha 0.5, speed 90 km/h, measured capacity, 10 %
weekday sample, seed 1. Runs are sequential (one city-scale run at a time) and resumable: a run
whose `loop_report.json` was made from the same policy (hash) is reused. Before each run the free
disk space is checked; under 3 GB the evaluation stops and the track status says
`LOOP: blocked - disk`. Results are merged into sim/loop/results/evaluation.json.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import typer
import yaml

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash
from sim.loop.schema import LoopPolicy, loop_config

LOOP_DIR = Path(__file__).resolve().parent
RESULTS = LOOP_DIR / "results"
DISK = Path("/System/Volumes/Data")
MIN_FREE_GB = 3.0
NOOP = {"type": "remote_work", "share": 0.0, "days_per_week": 1, "eligible_sectors": ["government"],
        "assumption": "no-op transform: replicate run (TA-018 noise)"}  # fmt: skip


class DiskFull(RuntimeError):
    pass


def free_gb(path: Path = DISK) -> float:
    p = path if path.exists() else REPO_ROOT
    return shutil.disk_usage(p).free / 1e9


def load_candidates(path: Path) -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(Path(path).read_text())
    return {c["id"]: c for c in doc["candidates"]}


def make_policy(pid: str, title: str, alignments: list[dict[str, Any]], mode: str,
                params: dict[str, Any], daytype: str = "weekday") -> LoopPolicy:  # fmt: skip
    """A Loop policy over `alignments` ({id, name, stations}) with explicit parameters."""
    t: dict[str, Any] = {
        "type": f"loop_{mode}",
        "alignments": [
            {"id": a["id"], "name": a.get("name", ""), "stations": a["stations"]}
            for a in alignments
        ],  # fmt: skip
        "assumption": "A-loop-001..020: parameters from sim/loop/config/loop.yaml unless set here",
        **{k: v for k, v in params.items() if v is not None},
    }
    return LoopPolicy.model_validate({"id": pid, "kind": "policy", "title": title,
                                      "daytype": daytype, "transforms": [t]})  # fmt: skip


def policy_hash(pol: LoopPolicy) -> str:
    return config_hash(pol.model_dump(exclude_none=True))


def run_one(pol: LoopPolicy, sample: float, seed: int, runs_dir: Path, prune: bool,
            sim_seed: int | None = None, run_id: str | None = None, quiet: bool = False,
            force: bool = False,
            extra: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """Run (or reuse) one Loop policy; returns its loop report plus run metadata. `extra`: more
    run_loop_policy keyword arguments (the demo environment)."""
    from sim.loop.run import run_loop_policy
    from sim.policies.run import run_name

    rid = run_id or run_name(pol, pol.daytype, sample, seed)
    h = policy_hash(pol)
    if not force:
        rep_path = runs_dir / rid / "loop_report.json"
        meta_path = runs_dir / rid / "meta.json"
        if rep_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            rep = json.loads(rep_path.read_text())
            if rep.get("policy_hash") == h and meta.get("sim_seed", seed) == (sim_seed or seed):
                rep["reused"] = True
                return rep
    gb = free_gb()
    if gb < MIN_FREE_GB:
        raise DiskFull(f"{gb:.1f} GB free < {MIN_FREE_GB} GB")
    t0 = time.perf_counter()
    kw: dict[str, Any] = {"quiet": quiet, **(extra or {})}
    if sim_seed is not None:
        kw |= {"sim_seed": sim_seed, "force_simulate": True}
    if run_id:
        kw["run_id"] = run_id
    meta = run_loop_policy(pol, None, sample, seed, runs_dir, prune=prune, **kw)
    rep = dict(meta["loop"])
    rep["wall_s"] = round(time.perf_counter() - t0, 1)
    rep["policy_hash"] = h
    rep["free_gb_before"] = round(gb, 1)
    rep["timings"] = meta.get("timings")
    (runs_dir / meta["run_id"] / "loop_report.json").write_text(
        json.dumps(rep, indent=2, default=float)
    )
    return rep


def merge_results(path: Path, reports: list[dict[str, Any]]) -> dict[str, Any]:
    doc = json.loads(path.read_text()) if path.exists() else {"label": SYNTHETIC_LABEL, "runs": {}}
    for r in reports:
        doc["runs"][r["run_id"]] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=float))
    return doc


def eval_id(cid: str, mode: str, params: dict[str, Any], defaults: dict[str, Any]) -> str:
    """loop_c1 for the default configuration; suffixes name what differs."""
    pid = f"loop_{cid.lower()}"
    if mode != "shuttle":
        pid += f"_{mode}"
    for k, short in (("alpha", "a"), ("speed_kmh", "v"), ("radius_o_m", "r"),
                     ("capacity", "cap"), ("toll_sar", "toll")):  # fmt: skip
        v = params.get(k)
        if v is not None and v != defaults.get(k):
            val = f"{v:g}" if isinstance(v, float | int) else str(v)
            pid += f"_{short}{val.replace('.', 'p')}"
    return pid


def defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "alpha": float(cfg["shift"]["alpha"]),
        "speed_kmh": float(cfg["tunnel"]["default_speed_kmh"]),
        "radius_o_m": float(cfg["access"]["radius_m"]),
        "capacity": cfg["capacity"]["default"],
        "toll_sar": float(cfg["private"]["toll_sar"]),
    }


def baseline_replicate(runs_dir: Path, sim_seed: int, sample: float = 0.10, seed: int = 1,
                       quiet: bool = False) -> dict[str, Any]:  # fmt: skip
    """The weekday baseline re-simulated with another sim seed, no policy (Track A's replicate
    machinery, TA-018 noise check); reused when present. Returns its meta.json."""
    from sim.policies.run import run_policy
    from sim.schemas import Policy

    rid = f"loop_noise_baseline_s{sim_seed}"
    meta_path = runs_dir / rid / "meta.json"
    if not meta_path.exists():
        gb = free_gb()
        if gb < MIN_FREE_GB:
            raise DiskFull(f"{gb:.1f} GB free < {MIN_FREE_GB} GB")
        null = Policy.model_validate({
            "id": "loop_noise", "kind": "policy", "daytype": "weekday",
            "title": f"Baseline replicate, simulation seed {sim_seed} (noise band)",
            "transforms": [NOOP]})  # fmt: skip
        run_policy(null, "weekday", sample, seed, runs_dir, quiet=quiet, force_simulate=True,
                   sim_seed=sim_seed, run_id=rid)  # fmt: skip
        for name in ("edgedata.parquet", "emissions.parquet"):
            (runs_dir / rid / name).unlink(missing_ok=True)
    return json.loads(meta_path.read_text())


def pair_with_replicate(rep: dict[str, Any], runs_dir: Path, rep_base: dict[str, Any]) -> None:
    """Seed-2 estimates against the seed-2 baseline replicate (paired), written into `rep`."""
    from sim.loop.kpis import relief

    out = runs_dir / rep["run_id"]
    meta = json.loads((out / "meta.json").read_text())
    rep["vht_saved_vs_replicate"] = round(
        float(rep_base["result"]["vht"]) - float(meta["result"]["vht"])
    )
    rel = relief(out / "tripinfo.parquet", runs_dir / rep_base["run_id"] / "tripinfo.parquet",
                 float(meta["sample"]), float(meta["sim_end_s"]))  # fmt: skip
    rep["relief_vs_replicate"] = round(rel["relief_vht_per_day"])
    rep["replicate_baseline"] = rep_base["run_id"]


def rebuild_results(results: Path) -> None:
    """Recompute the Loop report of every finished run in `results` (no simulation)."""
    from sim.loop.kpis import rebuild

    runs_dir = REPO_ROOT / "runs"
    doc = json.loads(results.read_text())
    for rid, old in list(doc["runs"].items()):
        if not (runs_dir / rid / "meta.json").exists():
            continue
        rep = rebuild(runs_dir / rid)
        for k in ("candidate", "sim_seed", "replicate_baseline"):
            if k in old:
                rep[k] = old[k]
        if rep.get("replicate_baseline"):
            base = json.loads((runs_dir / rep["replicate_baseline"] / "meta.json").read_text())
            pair_with_replicate(rep, runs_dir, base)
        doc["runs"][rid] = rep
        typer.echo(rep["headline"])
    results.write_text(json.dumps(doc, indent=2, default=float))


def blocked(reason: str) -> None:
    from sim.loop.status import append_status

    append_status(f"LOOP: blocked - {reason}")


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    candidates: Path = typer.Option(LOOP_DIR / "candidates.yaml"),
    ids: str | None = typer.Option(None, help="comma-separated candidate ids (default: all)"),
    mode: str = typer.Option("shuttle"),
    alpha: float | None = typer.Option(None),
    speed: float | None = typer.Option(None),
    radius: float | None = typer.Option(None),
    capacity: str | None = typer.Option(None),
    toll: float | None = typer.Option(None),
    sample: float = typer.Option(0.10),
    seed: int = typer.Option(1),
    keep_outputs: bool = typer.Option(False, help="keep edge/emission Parquet of each run"),
    sim_seed: int | None = typer.Option(None, help="replicate: re-simulate with this sim seed"),
    rebuild: bool = typer.Option(False, "--rebuild", help="recompute reports of finished runs"),
    force: bool = typer.Option(False, "--force", help="re-run even if a matching run exists"),
    results: Path = typer.Option(RESULTS / "evaluation.json"),
    mode_choice: Path | None = typer.Option(None, "--mode-choice", help="mode-choice YAML: the "
                                            "logit replaces alpha (shuttle mode, Track H)"),
    service: str | None = typer.Option(None, help="mode-choice service case (default: the YAML's)"),
    demo: bool = typer.Option(False, "--demo", help="mode choice on the demo window (seconds)"),
) -> None:  # fmt: skip
    if rebuild:
        rebuild_results(results)
        return
    if mode_choice is not None:
        if results == RESULTS / "evaluation.json":
            results = RESULTS / "evaluation_mode_choice.json"  # Track D's results stay untouched
        mode_choice_main(mode_choice, service, demo, ids, candidates, speed, capacity, sample,
                         seed, keep_outputs, force, results, sim_seed)  # fmt: skip
        return
    if demo:
        raise typer.BadParameter("--demo needs --mode-choice")
    cfg = loop_config()
    cands = load_candidates(candidates)
    todo = [c.strip() for c in ids.split(",")] if ids else list(cands)
    params: dict[str, Any] = {"alpha": alpha, "speed_kmh": speed, "capacity": capacity}
    if mode == "shuttle":
        params |= {"radius_o_m": radius, "radius_d_m": radius}
        params.pop("toll_sar", None)
    else:
        params = {"speed_kmh": speed, "capacity": capacity, "toll_sar": toll}
    runs_dir = REPO_ROOT / "runs"
    rep_base = None
    if sim_seed is not None and sim_seed != seed:
        try:
            rep_base = baseline_replicate(runs_dir, sim_seed, sample, seed)
        except DiskFull as e:
            blocked("disk")
            raise typer.Exit(f"stopped: {e}") from e
    for cid in todo:
        c = cands[cid]
        pid = eval_id(cid, mode, params, defaults(cfg))
        pol = make_policy(pid, f"Loop {cid} {c['name']} ({mode}; {SYNTHETIC_LABEL})", [c], mode,
                          params)  # fmt: skip
        typer.echo(f"[{pid}] {c['name']}, {c['tunnel_km']} km; {free_gb():.1f} GB free")
        try:
            if rep_base is None:
                rep = run_one(pol, sample, seed, runs_dir, prune=not keep_outputs, force=force)
            else:
                rep = run_one(pol, sample, seed, runs_dir, prune=not keep_outputs,
                              sim_seed=sim_seed, run_id=f"{pid}-sim{sim_seed}",
                              force=force)  # fmt: skip
        except DiskFull as e:
            blocked("disk")
            raise typer.Exit(f"stopped: {e}") from e
        rep["candidate"] = cid
        rep["sim_seed"] = sim_seed or seed
        if rep_base is not None:
            # paired estimate: policy and baseline both simulated with this sim seed
            pair_with_replicate(rep, runs_dir, rep_base)
        merge_results(results, [rep])
        typer.echo("  " + rep["headline"])


def mode_choice_params(path: Path, service: str | None, speed: float | None,
                       capacity: str | None) -> tuple[dict[str, Any], str]:  # fmt: skip
    """Transform parameters of a mode-choice run and the id suffix naming service and config."""
    from sim.loop.mode_choice import load_mode_choice, mc_hash

    mc = load_mode_choice(path)
    svc = service or mc["service"]
    if svc not in mc["services"] or not isinstance(mc["services"][svc], dict):
        raise typer.BadParameter(f"unknown service {svc!r} in {path}")
    s = mc["services"][svc]
    p = Path(path).resolve()
    rel = str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)
    params = {"speed_kmh": speed or float(s["speed_kmh"]), "capacity": capacity or s["capacity"],
              "mode_choice": rel}  # fmt: skip
    return params, f"_mc{svc}_{mc_hash(mc)}"


def mode_choice_main(path: Path, service: str | None, demo: bool, ids: str | None,
                     candidates: Path, speed: float | None, capacity: str | None, sample: float,
                     seed: int, keep_outputs: bool, force: bool, results: Path,
                     sim_seed: int | None = None) -> None:  # fmt: skip
    """Shuttle-mode runs whose shifted tours come from the mode-choice logit (Track H): the same
    transform, network, shuttles and reports as the alpha path; only the shift decision differs."""
    params, suffix = mode_choice_params(path, service, speed, capacity)
    runs_dir, cands = REPO_ROOT / "runs", None
    if demo:
        from sim.loop.demo import DEMO_RUNS
        from sim.loop.schema import load_loop_policy

        t = load_loop_policy("loop_demo").transforms[0]
        cands = {
            "demo": {
                "id": t.alignments[0].id,
                "name": t.alignments[0].name,
                "tunnel_km": "-",
                "stations": [s.model_dump() for s in t.alignments[0].stations],
            }
        }
        params |= {"radius_o_m": t.radius_o_m, "radius_d_m": t.radius_d_m,
                   "min_trip_km": t.min_trip_km}  # fmt: skip
        runs_dir, sample = DEMO_RUNS / "runs", 1.0
        if results == RESULTS / "evaluation_mode_choice.json":
            results = DEMO_RUNS / "evaluation_mode_choice.json"
    cands = cands or load_candidates(candidates)
    rep_base = None
    if sim_seed is not None and sim_seed != seed and not demo:
        try:
            rep_base = baseline_replicate(runs_dir, sim_seed, sample, seed)
        except DiskFull as e:
            blocked("disk")
            raise typer.Exit(f"stopped: {e}") from e
    todo = [c.strip() for c in ids.split(",")] if ids and not demo else list(cands)
    for cid in todo:
        c = cands[cid]
        pid = f"loop_{cid.lower()}{suffix}"
        if params["capacity"] != "measured" or params["speed_kmh"] != 90:
            pid += f"_v{params['speed_kmh']:g}_cap{params['capacity']}"
        pol = make_policy(pid, f"Loop {cid} {c['name']} (shuttle, mode choice {suffix[3:]}; "
                          f"{SYNTHETIC_LABEL})", [c], "shuttle", params)  # fmt: skip
        typer.echo(f"[{pid}] {c['name']}, {c['tunnel_km']} km; {free_gb():.1f} GB free")
        try:
            if demo:
                from sim.loop.demo import demo_env

                with demo_env() as kw:
                    rep = run_one(pol, sample, seed, runs_dir, prune=not keep_outputs,
                                  force=force, extra=kw)  # fmt: skip
            elif rep_base is None:
                rep = run_one(pol, sample, seed, runs_dir, prune=not keep_outputs, force=force)
            else:
                rep = run_one(pol, sample, seed, runs_dir, prune=not keep_outputs,
                              sim_seed=sim_seed, run_id=f"{pid}-sim{sim_seed}",
                              force=force)  # fmt: skip
        except DiskFull as e:
            blocked("disk")
            raise typer.Exit(f"stopped: {e}") from e
        rep["candidate"] = cid
        rep["sim_seed"] = sim_seed or seed
        if rep_base is not None:
            pair_with_replicate(rep, runs_dir, rep_base)
        merge_results(results, [rep])
        typer.echo("  " + rep["headline"])
        mc = rep.get("mode_choice") or {}
        typer.echo(
            f"  mode choice: {mc.get('riders_per_day')} riders/day "
            f"({mc.get('riders_capped_per_day')} capped; "
            f"{mc.get('eligible_legs')} eligible legs in the sample); {rep['run_id']}"
        )


if __name__ == "__main__":
    app()
