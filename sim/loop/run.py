"""Run a Loop policy through Track A's policy runner and add the Loop KPIs.

    python -m sim.loop.run loop_demo --demo                 # demo window, seconds
    python -m sim.loop.run loop_recommended                 # city, 10 % sample

`sim.policies.run.run_policy` does the work (baselines, transforms, incremental routing, matched
control, meso run, policy report); this module only swaps in a transform dispatcher that also
knows `loop_shuttle` and `loop_private` (sim/loop/transforms.py) for the duration of the call, the
same run-time override pattern as Track A's baseline_launch, and caps one-shot re-routing at 4
threads (Track D machine rule). Afterwards it writes
`loop_report.json` / `.md` in the run directory (sim/loop/kpis.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from sim.loop.schema import LoopPolicy, load_loop_policy

# machine rule for Track D (shared 18 GB laptop): one-shot re-routing uses at most 4 threads;
# one-shot routing on fixed weights is thread-count independent (Track A test), so routes match.
ROUTING_THREADS = 4

app = typer.Typer(add_completion=False, help=__doc__)


@contextmanager
def loop_dispatch() -> Iterator[None]:
    import sim.policies.run as PR
    from sim.loop.transforms import apply

    orig_apply, orig_cfg = PR.apply, PR.run_config

    def run_config(path: Path = PR.RUN_CONFIG) -> dict[str, Any]:
        cfg = orig_cfg(path)
        rr = cfg["reroute"]
        cfg["reroute"] = {**rr, "routing_threads": min(int(rr["routing_threads"]), ROUTING_THREADS)}
        return cfg

    PR.apply, PR.run_config = apply, run_config
    try:
        yield
    finally:
        PR.apply, PR.run_config = orig_apply, orig_cfg


def run_loop_policy(
    policy: str | Path | LoopPolicy,
    daytype: str | None = None,
    sample: float = 0.10,
    seed: int = 1,
    runs_dir: Path | None = None,
    prune: bool = False,
    **kw: Any,
) -> dict[str, Any]:
    """Run the policy; `prune` deletes the run's edge and emission Parquet (disk) once reported."""
    from sim.loop.kpis import write_loop_report
    from sim.policies.run import RUNS_DIR, run_policy

    pol = policy if isinstance(policy, LoopPolicy) else load_loop_policy(policy)
    runs_dir = Path(runs_dir or RUNS_DIR)
    with loop_dispatch():
        meta = run_policy(pol, daytype, sample, seed, runs_dir, **kw)
    out = runs_dir / meta["run_id"]
    search = [Path(kw["baselines_dir"])] if kw.get("baselines_dir") else []
    report = write_loop_report(out, meta, pol, search)
    meta["loop"] = report
    if prune:
        # the variant network is rebuilt in ~1 min when needed again (disk is the constraint)
        variant = (meta.get("net_change") or {}).get("variant")
        if variant and "jeddah.loop-" in variant:
            from sim.common import REPO_ROOT

            path = Path(variant)
            (path if path.is_absolute() else REPO_ROOT / path).unlink(missing_ok=True)
        for name in ("edgedata.parquet", "emissions.parquet"):
            (out / name).unlink(missing_ok=True)
        ctrl = meta.get("control_run")
        if ctrl:
            for name in ("edgedata.parquet", "emissions.parquet"):
                (runs_dir / ctrl / name).unlink(missing_ok=True)
    return meta


@app.command()
def main(
    policy: str,
    daytype: str | None = typer.Option(None),
    sample: float = typer.Option(0.10),
    seed: int = typer.Option(1),
    runs_dir: Path | None = typer.Option(None),
    demo: bool = typer.Option(False, "--demo", help="run on the demo window (100 %, seconds)"),
) -> None:
    if demo:
        from sim.loop.demo import DEMO_RUNS, demo_env

        with demo_env() as kw:
            meta = run_loop_policy(policy, daytype, 1.0, seed, runs_dir or DEMO_RUNS / "runs", **kw)
    else:
        meta = run_loop_policy(policy, daytype, sample, seed, runs_dir)
    typer.echo(meta["loop"]["headline"])


if __name__ == "__main__":
    app()
