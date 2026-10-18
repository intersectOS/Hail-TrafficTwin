"""Validate or run an Obhur bridge policy at Tier A (city) through Track A's policy runner.

    python -m sim.bridge.run obhur_bridge_b1 --validate             # schema, variant, SCC, routes
    python -m sim.bridge.run obhur_bridge_b1 --daytype weekday      # city, 10 % sample, seed 1

`sim.policies.run.run_policy` does the work (baselines, incremental routing, the matched control of
TA-018, meso run, policy report); this module swaps in a transform dispatcher that also builds
crossings (sim/bridge/transforms.py) for the duration of the call, the same run-time override
pattern as Track D's `sim.loop.run`. Afterwards it writes `bridge_report.json` / `.md` (span
volumes, the Obhur districts) next to the policy report.
All results: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from sim.bridge.schema import BridgePolicy, bridge_transform, load_bridge_policy
from sim.common import REPO_ROOT, SYNTHETIC_LABEL

# shared 18 GB laptop: one-shot re-routing uses at most 4 threads (thread-count independent)
ROUTING_THREADS = 4
OBHUR_DISTRICTS = (
    "Abhur Ash Shamaliyah", "Abhur Al Janubiyah", "Al Amwaj", "Al Loaloa", "Ash Sheraa",
    "Al Yaqoot", "Al Fardous", "As Swaryee", "Az Zomorod", "Al Murjaan", "Al Basateen",
)  # fmt: skip

app = typer.Typer(add_completion=False, help=__doc__)


@contextmanager
def bridge_dispatch() -> Iterator[None]:
    import sim.policies.run as PR
    from sim.bridge.transforms import apply

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


def validate(policy: str | Path, net: Path | None = None, route_check: bool = True,
             work: Path | None = None) -> dict[str, Any]:  # fmt: skip
    """Schema, variant build on the baseline network (or `net`), SCC membership, through-routes."""
    from sim.bridge.network import build_bridge_net, check_variant
    from sim.population.baseline import baseline_config

    pol = load_bridge_policy(policy)
    t = bridge_transform(pol)
    if t is None:
        raise ValueError(f"{pol.id}: no bridges in the network_change transform")
    net = Path(net or REPO_ROOT / baseline_config()["net"])
    work = Path(work or REPO_ROOT / "runs" / "bridge-nets" / pol.id)
    variant, info, new = build_bridge_net(net, t, work)
    check = check_variant(net, variant, new, work, route_check)
    return {"policy": pol.id, "base": info["base"], "variant": info["variant"],
            "span_m": info["span_m"], "approach_m": info["approach_m"],
            "landings": info["landings"], "check": check, "ok": check["ok"]}  # fmt: skip


def span_volumes(run_dir: Path, sample: float, am: tuple[float, float], pm: tuple[float, float],
                 prefix: str = "obh_") -> pd.DataFrame:  # fmt: skip
    """Vehicles per day and per peak on each new edge (edgedata `entered` x 1/sample)."""
    window = [("edge_id", ">=", prefix), ("edge_id", "<", prefix + "~")]
    cols = ["begin", "edge_id", "entered"]
    ed = pd.read_parquet(run_dir / "edgedata.parquet", columns=cols, filters=window)
    if ed.empty:
        return pd.DataFrame(columns=["edge_id", "day", "am_peak", "pm_peak"])
    ed["veh"] = ed["entered"] / sample
    day = ed.groupby("edge_id")["veh"].sum()

    def peak(h: tuple[float, float]) -> pd.Series:
        return ed[ed["begin"].between(h[0], h[1] - 1)].groupby("edge_id")["veh"].sum()

    out = pd.DataFrame({"day": day, "am_peak": peak(am), "pm_peak": peak(pm)}).fillna(0.0)
    return out.round(0).reset_index()


def write_bridge_report(run_dir: Path, meta: dict[str, Any], pol: BridgePolicy) -> dict[str, Any]:
    from sim.policies.run import run_config

    rep = run_config()["report"]

    def hours(span: list[str]) -> tuple[float, float]:
        h0, h1 = (int(s.split(":")[0]) * 3600 + int(s.split(":")[1]) * 60 for s in span)
        return float(h0), float(h1)

    am, pm = hours(rep["am_peak"]), hours(rep["pm_peak"])
    vols = span_volumes(run_dir, float(meta["sample"]), am, pm)
    spans = vols[vols["edge_id"].str.fullmatch(r"obh_[a-z0-9]+_(SN|NS)")]
    pr = json.loads((run_dir / "policy_report.json").read_text())
    dist = pd.read_parquet(run_dir / "policy_districts.parquet")
    names = [c for c in ("name_en", "name_ar", "name") if c in dist.columns]
    names = names or list(dist.columns[:3])
    obhur = dist[dist[names].astype(str).apply(
        lambda r: any(n in " ".join(r) for n in OBHUR_DISTRICTS), axis=1)]  # fmt: skip
    report = {
        "label": SYNTHETIC_LABEL,
        "policy": pol.id,
        "run_id": meta["run_id"],
        "compare": meta.get("compare_baseline"),
        "headline": pr.get("headline"),
        "span_volumes": spans.to_dict("records"),
        "all_new_edges": vols.to_dict("records"),
        "obhur_districts": obhur.to_dict("records"),
        "kpis": pr.get("kpis"),
    }
    (run_dir / "bridge_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                                           default=str))  # fmt: skip
    lines = [
        f"# {pol.title}",
        "",
        f"*{SYNTHETIC_LABEL}*. Run `{meta['run_id']}` vs `{meta.get('compare_baseline')}`.",
        "",
        str(pr.get("headline", "")),
        "",
        "| span edge | vehicles/day | AM peak (3 h) | PM peak (3 h) |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r.edge_id} | {r.day:,.0f} | {r.am_peak:,.0f} | {r.pm_peak:,.0f} |"
        for r in spans.itertuples()
    ]
    if not obhur.empty:
        cols = [c for c in ("name_en", "trips_base", "mean_delay_s_base", "mean_delay_s_policy",
                            "delta_delay_s", "delta_trips") if c in obhur.columns]  # fmt: skip
        cols = cols or list(obhur.columns)
        lines += ["", "## Obhur districts", "", "| " + " | ".join(cols) + " |",
                  "|" + "---|" * len(cols)]  # fmt: skip
        lines += [
            "| " + " | ".join(f"{v:,.1f}" if isinstance(v, float) else str(v) for v in r) + " |"
            for r in obhur[cols].itertuples(index=False)
        ]
    (run_dir / "bridge_report.md").write_text("\n".join(lines) + "\n")
    return report


def run_bridge_policy(
    policy: str | Path | BridgePolicy,
    daytype: str | None = None,
    sample: float = 0.10,
    seed: int = 1,
    runs_dir: Path | None = None,
    **kw: Any,
) -> dict[str, Any]:
    from sim.policies.run import RUNS_DIR, run_policy

    pol = policy if isinstance(policy, BridgePolicy) else load_bridge_policy(policy)
    runs_dir = Path(runs_dir or RUNS_DIR)
    with bridge_dispatch():
        meta = run_policy(pol, daytype, sample, seed, runs_dir, **kw)
    meta["bridge"] = write_bridge_report(runs_dir / meta["run_id"], meta, pol)
    return meta


@app.command()
def main(
    policy: str,
    daytype: str | None = typer.Option(None),
    sample: float = typer.Option(0.10),
    seed: int = typer.Option(1),
    runs_dir: Path | None = typer.Option(None),
    validate_only: bool = typer.Option(False, "--validate", help="build and check only, no run"),
    net: Path | None = typer.Option(None, help="--validate: base network (default: baseline's)"),
    route_check: bool = typer.Option(True, help="--validate: duarouter through-route check"),
) -> None:
    if validate_only:
        res = validate(policy, net, route_check)
        typer.echo(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        if not res["ok"]:
            raise typer.Exit(1)
        return
    meta = run_bridge_policy(policy, daytype, sample, seed, runs_dir)
    typer.echo(meta["bridge"]["headline"])


if __name__ == "__main__":
    app()
