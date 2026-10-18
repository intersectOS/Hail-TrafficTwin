"""Parameter sweep of one policy (PROJECT.md section 7, P1): run a grid in parallel processes and
write a response curve (CSV + PNG), e.g. "what remote share halves the morning peak?".

    python -m sim.policies.sweep --policy remote_work --param share=0.1:0.5:0.1 --sample 0.10

`--policy` is a policy id / YAML path, or a transform type (then the demo policy that contains it,
e.g. remote_work -> remote_work_30). `--param name=start:stop:step` (stop inclusive) sets a field of
the first transform that has it (`type.field` picks the transform type). Each point is a full
policy run (sim/policies/run.py) under `runs/sweep-<policy>-<param>/`.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import SYNTHETIC_LABEL
from sim.policies.run import (
    DEFAULT_SAMPLE,
    DEFAULT_SEED,
    POLICY_DIR,
    RUNS_DIR,
    resolve_policy,
    run_config,
    run_policy,
)
from sim.schemas import Policy

CURVE_KPIS = [
    ("am_peak_mean_delay_s", "AM-peak (06-09) mean delay (s)"),
    ("mean_delay_s", "mean delay per trip (s)"),
    ("vkt", "vehicle-km per day"),
    ("co2_t", "CO2 per day (t)"),
]


def parse_grid(spec: str) -> tuple[str, list[float]]:
    name, _, rng = spec.partition("=")
    parts = [float(x) for x in rng.split(":")]
    if not name or len(parts) != 3 or parts[2] <= 0:
        raise typer.BadParameter("--param must look like name=start:stop:step")
    start, stop, step = parts
    n = int(np.floor((stop - start) / step + 1e-9)) + 1
    return name, [round(start + k * step, 10) for k in range(n)]


def template(policy: str) -> Policy:
    """A policy file, or the demo policy whose only transform has this type."""
    path = Path(policy)
    if path.suffix or (POLICY_DIR / f"{policy}.yaml").exists():
        return resolve_policy(policy)[0]
    for f in sorted(POLICY_DIR.glob("*.yaml")):
        try:
            pol = resolve_policy(f)[0]
        except ValueError:  # another track's policy kind (e.g. Track J bridges), not a template
            continue
        if [t.type for t in pol.transforms] == [policy]:
            return pol
    raise typer.BadParameter(f"no policy or single-transform demo policy for {policy!r}")


def with_value(pol: Policy, param: str, value: float) -> Policy:
    kind, _, field = param.rpartition(".")
    data = pol.model_dump()
    for t in data["transforms"]:
        if (not kind or t["type"] == kind) and field in t:
            t[field] = value
            break
    else:
        raise typer.BadParameter(f"no transform of {pol.id} has a field {param!r}")
    tag = f"{value:g}".replace(".", "p").replace("-", "m")
    data["id"] = f"{pol.id}_{field}_{tag}"
    data["title"] = f"{pol.title} [{field} = {value:g}]"
    return Policy.model_validate(data)


def _point(args: tuple[dict[str, Any], str, float, int, str, str]) -> dict[str, Any]:
    pol_data, daytype, sample, seed, runs_dir, baselines_dir = args
    pol = Policy.model_validate(pol_data)
    # baselines come from the main runs directory, never from the sweep directory
    meta = run_policy(pol, daytype, sample, seed, Path(runs_dir), quiet=True,
                      baselines_dir=Path(baselines_dir))  # fmt: skip
    report = json.loads((Path(runs_dir) / meta["run_id"] / "policy_report.json").read_text())
    return {"run_id": meta["run_id"], "kpis": report["kpis"]}


def sweep(
    policy: str,
    param: str,
    daytype: str | None = None,
    sample: float = DEFAULT_SAMPLE,
    seed: int = DEFAULT_SEED,
    workers: int | None = None,
    runs_dir: Path = RUNS_DIR,
    keep_edgedata: bool = False,
) -> pd.DataFrame:
    base = template(policy)
    name, values = parse_grid(param)
    daytype = daytype or base.daytype
    out = runs_dir / f"sweep-{base.id}-{name.replace('.', '_')}"
    out.mkdir(parents=True, exist_ok=True)
    points = [with_value(base, name, v) for v in values]
    workers = workers or int(run_config()["sweep"]["workers"])
    t0 = time.perf_counter()
    jobs = [(p.model_dump(), daytype, sample, seed, str(out), str(runs_dir)) for p in points]
    if workers <= 1:
        results = [_point(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_point, jobs))
    rows = []
    for value, res in zip(values, results, strict=True):
        row: dict[str, Any] = {name: value, "run_id": res["run_id"]}
        for k in res["kpis"]:
            row[f"{k['kpi']}"] = k["policy"]
            row[f"{k['kpi']}_baseline"] = k["baseline"]
            row[f"{k['kpi']}_delta_pct"] = k["delta_pct"]
        rows.append(row)
        if not keep_edgedata:  # disk: the curve needs only the KPIs
            for f in ("edgedata.parquet", "emissions.parquet"):
                (out / res["run_id"] / f).unlink(missing_ok=True)
    df = pd.DataFrame(rows)
    df.attrs["label"] = SYNTHETIC_LABEL
    csv = out / "response_curve.csv"
    with csv.open("w") as fh:
        fh.write(f"# {SYNTHETIC_LABEL}; policy {base.id}, {name} sweep, day type {daytype}, "
                 f"sample {sample:g}, seed {seed}\n")  # fmt: skip
        df.to_csv(fh, index=False)
    plot_curve(df, name, base, out / "response_curve.png", sample, seed)
    (out / "sweep.json").write_text(json.dumps({
        "label": SYNTHETIC_LABEL, "policy": base.id, "param": name, "values": values,
        "daytype": daytype, "sample": sample, "seed": seed, "workers": workers,
        "wall_s": round(time.perf_counter() - t0, 1),
        "runs": [r["run_id"] for r in results]}, indent=2))  # fmt: skip
    return df


def plot_curve(df: pd.DataFrame, name: str, pol: Policy, path: Path, sample: float, seed: int):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    for ax, (key, label) in zip(axes.flat, CURVE_KPIS, strict=True):
        if key not in df:
            ax.set_visible(False)
            continue
        ax.plot(df[name], df[key], marker="o", color="#2a6f97", label="policy")
        base = df[f"{key}_baseline"].iloc[0]
        ax.axhline(base, color="#888888", linestyle="--", linewidth=1, label="baseline")
        if key == "am_peak_mean_delay_s":
            ax.axhline(base / 2, color="#c44e52", linestyle=":", linewidth=1, label="half baseline")
        ax.set_xlabel(name)
        ax.set_title(label, fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, frameon=False)
    fig.suptitle(f"{pol.title}: response to {name}\n{SYNTHETIC_LABEL}; Tier A meso, "
                 f"sample {100 * sample:g} %, seed {seed}", fontsize=10)  # fmt: skip
    fig.savefig(path, dpi=120)
    plt.close(fig)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    policy: str = typer.Option(..., help="policy id/path or transform type"),
    param: str = typer.Option(..., help="name=start:stop:step (stop inclusive)"),
    daytype: str | None = typer.Option(None, help="baseline day type (default: the policy's)"),
    sample: float = typer.Option(DEFAULT_SAMPLE),
    seed: int = typer.Option(DEFAULT_SEED),
    workers: int | None = typer.Option(None, help="parallel processes (default: config)"),
    runs_dir: Path = typer.Option(RUNS_DIR),
) -> None:
    df = sweep(policy, param, daytype, sample, seed, workers, runs_dir)
    cols = [c for c in df.columns if c.split("_delta")[0] in dict(CURVE_KPIS) or c == df.columns[0]]
    typer.echo(df[cols].to_string(index=False))


if __name__ == "__main__":
    app()
