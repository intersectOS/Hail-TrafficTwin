"""Produce the runs `make demo` shows in the viewer (settings: sim/config/demo.yaml).

    python -m sim.demo                 # every step; finished steps are skipped
    python -m sim.demo --only events   # one step (tier-b, events, strategist, evacuation,
                                       #           policy, tier-a)
    python -m sim.demo --force         # re-run even finished steps

Steps run on the committed demo window except `tier-a`, a one-hour mid-day city smoke that runs
only when data/jeddah/jeddah.net.xml exists (`make city-net` builds it). Each step records its
run ids in runs/demo-manifest.json. Synthetic demand, uncalibrated; every scenario is fictional.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, load_yaml, rel

DEMO_CONFIG = REPO_ROOT / "sim" / "config" / "demo.yaml"
RUNS_DIR = REPO_ROOT / "runs"
DEMO_NET = REPO_ROOT / "data" / "demo" / "demo.net.xml"
CITY_NET = REPO_ROOT / "data" / "jeddah" / "jeddah.net.xml"
STEPS = ("tier-b", "events", "strategist", "evacuation", "policy", "tier-a")


def demo_config() -> dict[str, Any]:
    return load_yaml(DEMO_CONFIG)


def manifest_path(runs_dir: Path) -> Path:
    return runs_dir / "demo-manifest.json"


def read_manifest(runs_dir: Path) -> dict[str, Any]:
    p = manifest_path(runs_dir)
    return json.loads(p.read_text()) if p.exists() else {"label": SYNTHETIC_LABEL, "steps": {}}


def write_manifest(runs_dir: Path, manifest: dict[str, Any]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(runs_dir).write_text(json.dumps(manifest, indent=2) + "\n")


def done(entry: dict[str, Any] | None) -> bool:
    """A step is done when it is in the manifest and every path it produced still exists."""
    return bool(entry) and all((REPO_ROOT / p).exists() for p in entry["paths"])


def ensure_demo_window() -> None:
    """The demo window is committed; re-cut it from the city network only if it went missing."""
    if DEMO_NET.exists():
        return
    if not CITY_NET.exists():
        raise typer.BadParameter(
            f"{rel(DEMO_NET)} is missing and so is {rel(CITY_NET)}: restore it with "
            "`git checkout -- data/demo` or build the city first (`make city-net`)"
        )
    import sys

    from sim.common import run_cmd

    run_cmd([sys.executable, "-m", "sim.network.build_window", "--name", "demo", "--osm-extract"])


# ---------------------------------------------------------------- steps


def step_tier_b(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any]:
    from sim.runner import run_smoke

    meta = run_smoke("B", seed, runs_dir=runs_dir, quiet=True, fcd=cfg["tier_b_smoke"]["fcd"])
    out = runs_dir / meta["run_id"]
    return {"runs": [meta["run_id"]], "paths": [rel(out / "meta.json")],
            "result": meta["result"]}  # fmt: skip


def step_events(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any]:
    from sim.scenarios.run import run_scenario

    res = run_scenario(REPO_ROOT / cfg["scenario"], seed=seed, runs_dir=runs_dir, quiet=True)
    return {"runs": [res["out"].name], "paths": [rel(res["out"] / "scenario_report.json")],
            "kpis": res["report"]["kpis"]["scenario"]}  # fmt: skip


def step_strategist(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any]:
    from strategist.run import recommend

    sroot = runs_dir / "strategist"
    rep = recommend(cfg["strategist_scenario"], seed=seed, db=sroot / "decisions.sqlite",
                    runs_dir=sroot, quiet=True)  # fmt: skip
    stable = sroot / f"{rep['scenario']}-{rep['window']}-s{seed}"
    opts = [{"rank": o["rank"], "travel_time_s": o["travel_time_s"]} for o in rep["options"]]
    return {"runs": [f"strategist~{stable.name}"], "paths": [rel(stable / "recommendation.json")],
            "options": opts, "no_strategy_s": rep["no_strategy"]["travel_time_s"]}  # fmt: skip


def step_evacuation(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any]:
    from sim.events.evacuation import run

    res = run(cfg["evacuation"], seed=seed, runs_dir=runs_dir, quiet=True)
    return {"runs": [res["out"].name], "paths": [rel(res["out"] / "evacuation_report.json")]}


@contextmanager
def demo_caches(cache: Path) -> Iterator[None]:
    """Point the population, route and edge caches at the demo cache for the policy step."""
    import sim.policies.edges as E
    import sim.population.baseline as baseline
    import sim.population.synthesize as synthesize

    saved = (synthesize.CACHE_DIR, baseline.ROUTE_CACHE, E.CACHE)
    new = (cache / "pop", cache / "routes", cache / "edges")
    synthesize.CACHE_DIR, baseline.ROUTE_CACHE, E.CACHE = new
    try:
        yield
    finally:
        synthesize.CACHE_DIR, baseline.ROUTE_CACHE, E.CACHE = saved


def quadrant_districts(path: Path) -> Path:
    """Four rectangular demo "districts" over the demo window bbox (not real districts)."""
    window = json.loads((DEMO_NET.parent / "demo.window.json").read_text())
    x0, y0, x1, y1 = window["definition"]["bbox"]
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    feats = []
    quads = [(x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)]
    for i, (a, b, c, d) in enumerate(quads):
        ring = [[a, b], [c, b], [c, d], [a, d], [a, b]]
        feats.append({"type": "Feature",
                      "properties": {"name_en": f"Demo Q{i}", "name_ar": "", "osm_id": f"demo-{i}"},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return path


def step_policy(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any]:
    from sim.policies.run import run_policy
    from sim.population import zones as Z

    p = cfg["policy"]
    cache = REPO_ROOT / p["cache_dir"]
    zcfg = Z.zones_config()
    zcfg["control_total"]["value"] = p["residents"]["value"]
    zcfg["non_residential_districts"]["names"] = []
    districts = quadrant_districts(cache / "districts.geojson")
    zones, zone_edges = Z.build_zones(Z.ZoneInputs(districts=districts, net=DEMO_NET), zcfg)
    zone_dir = cache / "zones"
    Z.write_zones(zones, zone_edges, zone_dir, {"demo": True, "label": SYNTHETIC_LABEL})
    with demo_caches(cache):
        meta = run_policy(
            p["id"], p["daytype"], p["sample"], seed, runs_dir=runs_dir, net=DEMO_NET,
            zone_dir=zone_dir, baselines_dir=runs_dir, iterations=p["iterations"], quiet=True,
            run_id=p["run_id"],
        )  # fmt: skip
    out = runs_dir / meta["run_id"]
    return {"runs": [meta["run_id"], meta["compare_baseline"]],
            "paths": [rel(out / "policy_report.json")]}  # fmt: skip


def step_tier_a(cfg: dict[str, Any], runs_dir: Path, seed: int) -> dict[str, Any] | None:
    from sim.runner import run_smoke, runner_config

    tier_a_net = REPO_ROOT / runner_config()["smoke"]["tier_A"]["net"]  # network v2 (TF-008)
    if not tier_a_net.exists():
        typer.echo(f"  tier-a: skipped, {rel(tier_a_net)} not built (make city-net)")
        return None
    a = cfg["tier_a_smoke"]
    meta = run_smoke("A", seed, end=a["end"], begin=a["begin"], period=a["period"],
                     runs_dir=runs_dir, quiet=True)  # fmt: skip
    out = runs_dir / meta["run_id"]
    return {"runs": [meta["run_id"]], "paths": [rel(out / "meta.json")],
            "result": meta["result"]}  # fmt: skip


STEP_FUNCS: dict[str, Callable[[dict[str, Any], Path, int], dict[str, Any] | None]] = {
    "tier-b": step_tier_b,
    "events": step_events,
    "strategist": step_strategist,
    "evacuation": step_evacuation,
    "policy": step_policy,
    "tier-a": step_tier_a,
}


def run_demo(
    steps: tuple[str, ...] = STEPS,
    seed: int | None = None,
    runs_dir: Path = RUNS_DIR,
    force: bool = False,
) -> dict[str, Any]:
    cfg = demo_config()
    seed = int(cfg["seed"] if seed is None else seed)
    ensure_demo_window()
    manifest = read_manifest(runs_dir)
    for name in steps:
        key = f"{name}-s{seed}"
        if not force and done(manifest["steps"].get(key)):
            typer.echo(f"  {name}: done earlier ({', '.join(manifest['steps'][key]['runs'])})")
            continue
        typer.echo(f"  {name}: running ...")
        t0 = time.perf_counter()
        entry = STEP_FUNCS[name](cfg, runs_dir, seed)
        if entry is None:
            continue
        entry["wall_s"] = round(time.perf_counter() - t0, 1)
        manifest["steps"][key] = entry
        write_manifest(runs_dir, manifest)  # after every step, so a failure keeps earlier ones
        typer.echo(f"  {name}: {entry['wall_s']} s -> {', '.join(r for r in entry['runs'] if r)}")
    return manifest


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    only: list[str] | None = typer.Option(None, "--only", help=f"steps: {', '.join(STEPS)}"),
    seed: int | None = typer.Option(None, help="default: seed in sim/config/demo.yaml"),
    runs_dir: Path = typer.Option(RUNS_DIR),
    force: bool = typer.Option(False, "--force", help="re-run finished steps"),
) -> None:
    steps = tuple(only) if only else STEPS
    bad = [s for s in steps if s not in STEPS]
    if bad:
        raise typer.BadParameter(f"unknown step(s) {bad}; choose from {STEPS}")
    typer.echo(f"TrafficTwin demo runs [{SYNTHETIC_LABEL}]")
    run_demo(steps, seed, runs_dir, force)


if __name__ == "__main__":
    app()
