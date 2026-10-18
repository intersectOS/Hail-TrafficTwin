"""Policy report (PROJECT.md 7): KPIs against the matching baseline on the same seed, peak
spreading, per-district winners and losers, the most relieved and most worsened corridors, the
assumption ids used and the "synthetic demand, uncalibrated" label.

Writes `policy_report.json`, `policy_report.md` and `policy_districts.parquet` in the run dir.

    python -m sim.policies.report runs/<policy run>     # rebuild from the run's outputs
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from sim.common import REPO_ROOT, SYNTHETIC_LABEL
from sim.metrics import caveats, md_table
from sim.schemas import Policy, hhmm_to_s

ASSUMPTION_ID = re.compile(r"\bA-[a-z]+-\d{3}\b")
MIN_CORRIDOR_DELTA_VEH_H = 0.05  # display threshold (city-equivalent vehicle-hours per day)
POPULATION_CONFIGS = ("activities", "modes", "population", "zones", "export", "baseline")

# (key in metrics summary, label, unit, better when lower?)
KPIS = [
    ("mean_delay_s", "mean delay per trip", "s", True),
    ("am_peak_mean_delay_s", "AM peak (06-09) mean delay", "s", True),
    ("mean_speed_kmh", "mean speed", "km/h", False),
    ("vkt", "vehicle-km (VKT)", "km", True),
    ("vht", "vehicle-hours (VHT)", "h", True),
    ("vht_delay", "vehicle-hours of delay", "h", True),
    ("trips_completed", "vehicle trips completed", "", None),
    ("throughput_peak_hour_trips", "peak-hour departures", "veh/h", None),
    ("peak_hour", "peak hour (start)", "h", None),
    ("peak_spreading_top_hour_share", "top-hour share of trips", "", True),
    ("co2_t", "CO2", "t", True),
    ("co2_peak_hour_t", "CO2 in the peak hour", "t", True),
    ("nox_kg", "NOx", "kg", True),
    ("mean_trip_km", "mean trip length", "km", None),
    ("teleports", "teleports (quality flag)", "", True),
    ("teleport_share", "teleports per loaded vehicle", "", True),
]


def kpi_table(base: dict[str, Any], pol: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, label, unit, lower in KPIS:
        b, p = base.get(key), pol.get(key)
        if b is None or p is None:
            continue
        d = p - b
        pct = round(100.0 * d / b, 2) if b not in (0, None) and key != "peak_hour" else None
        verdict = ""
        if lower is not None and d != 0:
            verdict = "better" if (d < 0) == lower else "worse"
        rows.append({"kpi": key, "label": label, "unit": unit, "baseline": b, "policy": p,
                     "delta": round(d, 4), "delta_pct": pct, "verdict": verdict})  # fmt: skip
    return rows


def window_delay(hourly: pd.DataFrame, h0: float, h1: float) -> dict[str, float]:
    sel = hourly[(hourly["hour"] >= h0) & (hourly["hour"] < h1)]
    dep = float(sel["departures"].sum())
    delay = float((sel["departures"] * sel["mean_delay_s"]).sum() / dep) if dep else 0.0
    total = float(hourly["departures"].sum())
    return {"departures": round(dep), "share": round(dep / total, 4) if total else 0.0,
            "mean_delay_s": round(delay, 1)}  # fmt: skip


def peak_spreading(base_h: pd.DataFrame, pol_h: pd.DataFrame, cfg: dict) -> dict[str, Any]:
    am = [hhmm_to_s(x) / 3600 for x in cfg["report"]["am_peak"]]
    pm = [hhmm_to_s(x) / 3600 for x in cfg["report"]["pm_peak"]]
    peak = int(base_h.loc[base_h["departures"].idxmax(), "hour"])
    out: dict[str, Any] = {"baseline_peak_hour": peak}
    for name, h in (("am", am), ("pm", pm), ("peak_hour", [peak, peak + 1])):
        out[name] = {"baseline": window_delay(base_h, *h), "policy": window_delay(pol_h, *h)}
    hourly = base_h[["hour", "departures", "mean_delay_s"]].merge(
        pol_h[["hour", "departures", "mean_delay_s"]], on="hour", suffixes=("_base", "_policy")
    )
    out["hourly"] = hourly.round(1).to_dict("records")
    return out


def districts(base_d: pd.DataFrame, pol_d: pd.DataFrame, top: int) -> dict[str, Any]:
    cols = ["zone_id", "trips", "mean_delay_s", "mean_speed_kmh", "vkt"]
    names = [c for c in ("name_en", "name_ar", "population") if c in base_d]
    d = base_d[cols + names].merge(pol_d[cols], on="zone_id", how="outer",
                                   suffixes=("_base", "_policy"))  # fmt: skip
    d["delta_delay_s"] = d["mean_delay_s_policy"] - d["mean_delay_s_base"]
    d["delta_trips"] = d["trips_policy"].fillna(0) - d["trips_base"].fillna(0)
    # rank only districts with a meaningful number of trips (city-equivalent)
    ranked = d[(d["trips_base"].fillna(0) >= 1000) & d["delta_delay_s"].notna()]
    show = [*names[:1], "trips_base", "trips_policy", "mean_delay_s_base", "mean_delay_s_policy",
            "delta_delay_s"]  # fmt: skip
    winners = ranked.sort_values("delta_delay_s").head(top)[show]
    losers = ranked.sort_values("delta_delay_s", ascending=False).head(top)[show]
    losers = losers[losers["delta_delay_s"] > 0]
    winners = winners[winners["delta_delay_s"] < 0]
    better = int((ranked["delta_delay_s"] < 0).sum())
    worse = int((ranked["delta_delay_s"] > 0).sum())
    return {
        "table": d,
        "winners": winners.round(1).to_dict("records"),
        "losers": losers.round(1).to_dict("records"),
        "districts_better": better,
        "districts_worse": worse,
        "districts_ranked": len(ranked),
    }


def edge_time_loss(edgedata: Path) -> pd.Series:
    tbl = pq.read_table(edgedata, columns=["edge_id", "timeLoss"], read_dictionary=["edge_id"])
    df = tbl.to_pandas()
    return df.groupby("edge_id", observed=True)["timeLoss"].sum()


def corridors(
    base_dir: Path, run_dir: Path, names: pd.Series, sample: float, top: int
) -> dict[str, list[dict[str, Any]]]:
    """Time loss per corridor (street name, else edge id), city-equivalent vehicle-hours."""
    if not (base_dir / "edgedata.parquet").exists() or not (run_dir / "edgedata.parquet").exists():
        return {"relieved": [], "worsened": []}
    b = edge_time_loss(base_dir / "edgedata.parquet")
    p = edge_time_loss(run_dir / "edgedata.parquet")
    df = pd.DataFrame({"base": b, "policy": p}).fillna(0.0)
    df.index = df.index.astype(str)
    key = names.reindex(df.index).fillna("")
    df["corridor"] = np.where(key.to_numpy() != "", key.to_numpy(), df.index.to_numpy())
    g = df.groupby("corridor")[["base", "policy"]].sum() / 3600.0 / sample
    g["edges"] = df.groupby("corridor").size()
    g["delta_veh_h"] = g["policy"] - g["base"]
    g = g.rename(columns={"base": "time_loss_base_veh_h", "policy": "time_loss_policy_veh_h"})
    g = g.reset_index().astype({"time_loss_base_veh_h": float, "time_loss_policy_veh_h": float})
    g["delta_veh_h"] = g["delta_veh_h"].astype(float)
    g = g[g["delta_veh_h"].abs() >= MIN_CORRIDOR_DELTA_VEH_H]

    def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return frame.round(1).to_dict("records")

    return {
        "relieved": rows(g[g["delta_veh_h"] < 0].sort_values("delta_veh_h").head(top)),
        "worsened": rows(g[g["delta_veh_h"] > 0].sort_values("delta_veh_h", ascending=False)
                         .head(top)),
    }  # fmt: skip


def assumption_ids(policy_path: Path | None, pol: Policy, daytypes: list[str]) -> dict[str, list]:
    pol_text = policy_path.read_text() if policy_path else json.dumps(pol.model_dump())
    day_text = "".join(
        (REPO_ROOT / "sim" / "daytypes" / f"{d}.yaml").read_text() for d in sorted(set(daytypes))
    )
    pop_text = "".join(
        (REPO_ROOT / "sim" / "population" / "config" / f"{n}.yaml").read_text()
        for n in POPULATION_CONFIGS
        if (REPO_ROOT / "sim" / "population" / "config" / f"{n}.yaml").exists()
    )
    return {
        "policy": sorted(set(ASSUMPTION_ID.findall(pol_text))),
        "daytype": sorted(set(ASSUMPTION_ID.findall(day_text))),
        "baseline_model": sorted(set(ASSUMPTION_ID.findall(pop_text))),
    }


def headline(meta: dict[str, Any], kpis: list[dict[str, Any]]) -> str:
    by = {r["kpi"]: r for r in kpis}

    def pct(k: str) -> str:
        r = by.get(k)
        return f"{r['delta_pct']:+.1f} %" if r and r["delta_pct"] is not None else "n/a"

    return (
        f"Policy {meta['policy']} vs {meta['compare_daytype']} baseline [{SYNTHETIC_LABEL}]: "
        f"mean delay {pct('mean_delay_s')}, AM-peak delay {pct('am_peak_mean_delay_s')}, "
        f"VKT {pct('vkt')}, VHT {pct('vht')}, CO2 {pct('co2_t')}"
    )


POLICY_CAVEATS = """\
- Incremental routing (TA-014, A-pol-090): vehicles whose trip the policy does not touch keep their
  baseline route; new, re-timed, re-moded or affected vehicles get a one-shot shortest path on the
  starting baseline's congested travel times. There is no re-equilibration, so drivers who would
  re-route into freed (or away from added) congestion do not: deltas are first-order.
- The city baseline is gridlock-affected in both peaks (TA-011, docs/status/trackA.md): teleports
  are reported as a quality flag; read deltas in peak hours with care.
- Results are for one seed and a 10 % population sample with capacity scaling (A-sim-101,
  unvalidated); differences of a few percent are within the run-to-run noise of meso gridlock.
"""


def fmt(v: Any) -> str:
    if isinstance(v, float):
        if abs(v) < 1:
            return f"{v:.4f}".rstrip("0").rstrip(".") or "0"
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v)


def write_policy_report(
    out: Path,
    meta: dict[str, Any],
    report: dict[str, Any],
    ref_dir: Path,
    pol: Policy,
    plan: Any,
    cfg: dict[str, Any],
    policy_path: Path | None,
    raw_ref_dir: Path | None = None,
) -> dict[str, Any]:
    ref = json.loads((ref_dir / "metrics.json").read_text())
    kpis = kpi_table(ref["summary"], report["summary"])
    raw_kpis = None
    if raw_ref_dir is not None:
        raw = json.loads((raw_ref_dir / "metrics.json").read_text())
        raw_kpis = kpi_table(raw["summary"], report["summary"])
    base_h = pd.read_parquet(ref_dir / "metrics_hourly.parquet")
    pol_h = pd.read_parquet(out / "metrics_hourly.parquet")
    spread = peak_spreading(base_h, pol_h, cfg)
    dist = districts(pd.read_parquet(ref_dir / "metrics_district.parquet"),
                     pd.read_parquet(out / "metrics_district.parquet"),
                     int(cfg["report"]["top_districts"]))  # fmt: skip
    dist.pop("table").to_parquet(out / "policy_districts.parquet", index=False)
    names = plan.edges().set_index("edge_id")["name"] if plan is not None else pd.Series()
    corr = corridors(ref_dir, out, names, float(meta["sample"]), int(pol.report.top_corridors))
    ids = assumption_ids(policy_path, pol, [meta["daytype"], meta["compare_daytype"]])
    result = {
        "label": SYNTHETIC_LABEL,
        "headline": headline(meta, kpis),
        "policy": pol.id,
        "title": pol.title,
        "run_id": meta["run_id"],
        "tier": f"Tier {meta['tier']} ({meta['mode']})",
        "daytype": meta["daytype"],
        "compare_baseline": meta["compare_baseline"],
        "start_baseline": meta["start_baseline"],
        "sample": meta["sample"],
        "seed": meta["seed"],
        "kpis": kpis,
        "control": None if raw_ref_dir is None else {
            "control_run": meta.get("control_run"),
            "vehicles_rerouted_in_control": meta.get("control_rerouted"),
            "raw_baseline": raw_ref_dir.name,
            "kpis_vs_raw_baseline": raw_kpis,
            "headline_vs_raw_baseline": headline(meta, raw_kpis or []),
        },
        "peak_spreading": spread,
        "districts": dist,
        "corridors": corr,
        "effects": meta["effects"],
        "routing": meta["routing"],
        "net_change": meta.get("net_change"),
        "assumption_ids": ids,
        "provenance": {k: meta.get(k) for k in (
            "seed", "sample", "config_hash", "policy_hash", "population_hash", "network",
            "network_hash", "vehicles_hash", "routes_hash", "routes_deterministic",
            "sumo_version")},
    }  # fmt: skip
    (out / "policy_report.json").write_text(json.dumps(result, indent=2, default=str))
    (out / "policy_report.md").write_text(render_md(result, meta))
    return result


CONTROL_KPIS = ("mean_delay_s", "am_peak_mean_delay_s", "vkt", "vht", "co2_t")


def control_md(r: dict[str, Any]) -> str:
    c = r.get("control")
    if not c:
        return ""
    rows = [{"KPI": k["label"], "raw baseline": fmt(k["baseline"]), "policy": fmt(k["policy"]),
             "delta %": "" if k["delta_pct"] is None else f"{k['delta_pct']:+.1f}"}
            for k in c["kpis_vs_raw_baseline"] or [] if k["kpi"] in CONTROL_KPIS]  # fmt: skip
    return f"""
> **Compared with a matched control** (TA-018): `{c["control_run"]}` is the baseline with the same
> {fmt(c["vehicles_rerouted_in_control"])} baseline vehicles re-routed (one-shot, at their baseline
> times, no policy). One-shot routes beat the baseline's 3-step assignment, so comparing with the
> raw baseline would credit the policy with that routing gain.

<details><summary>Against the raw baseline (includes the routing gain)</summary>

{md_table(rows)}

</details>
"""


def render_md(r: dict[str, Any], meta: dict[str, Any]) -> str:
    kp = [
        {"KPI": k["label"] + (f" ({k['unit']})" if k["unit"] else ""),
         "baseline": fmt(k["baseline"]),
         "policy": fmt(k["policy"]), "delta": fmt(k["delta"]),
         "delta %": "" if k["delta_pct"] is None else f"{k['delta_pct']:+.1f}",
         "": k["verdict"]}
        for k in r["kpis"]
    ]  # fmt: skip
    sp = r["peak_spreading"]
    win_rows = []
    for name in ("am", "pm", "peak_hour"):
        b, p = sp[name]["baseline"], sp[name]["policy"]
        label = {"am": "AM peak 06-09", "pm": "PM peak 16-19"}.get(
            name, f"baseline peak hour {sp['baseline_peak_hour']:02d}:00"
        )
        win_rows.append({"window": label, "departures base": fmt(b["departures"]),
                         "departures policy": fmt(p["departures"]),
                         "share base": f"{b['share']:.1%}", "share policy": f"{p['share']:.1%}",
                         "mean delay base (s)": fmt(b["mean_delay_s"]),
                         "mean delay policy (s)": fmt(p["mean_delay_s"])})  # fmt: skip
    hourly = [
        {"hour": f"{int(h['hour']):02d}", "departures base": fmt(round(h["departures_base"])),
         "departures policy": fmt(round(h["departures_policy"])),
         "delay base (s)": fmt(h["mean_delay_s_base"]),
         "delay policy (s)": fmt(h["mean_delay_s_policy"])}
        for h in sp["hourly"]
    ]  # fmt: skip
    eff = "\n".join(
        f"- `{e['type']}`: " + ", ".join(f"{k} {fmt(v)}" for k, v in e.items() if k != "type")
        for e in r["effects"]
    )
    rt = r["routing"]
    rerouted = fmt(rt.get("rerouted", rt.get("to_route", 0)))
    ids = r["assumption_ids"]
    d = r["districts"]
    return f"""# Policy report: {r["title"]}

> **{SYNTHETIC_LABEL}.** {r["tier"]}, policy `{r["policy"]}` on day type `{r["daytype"]}` compared
> with the baseline `{r["compare_baseline"]}` (same seed {r["seed"]}, population sample
> {100 * float(r["sample"]):g} % with capacity scaling; totals scaled to the full city).
> Started from `{r["start_baseline"]}`.

**{r["headline"]}**

{control_md(r)}
## What the policy changed
{eff}

Routing: {fmt(rt.get("vehicles"))} vehicle trips; {fmt(rt.get("reused", 0))} kept their baseline
route, {rerouted} were routed anew, {fmt(rt.get("unroutable", 0))} could not be routed.

## City KPIs (policy vs baseline)
{md_table(kp)}

## Peak spreading
{md_table(win_rows)}

<details><summary>Hourly departures and mean delay</summary>

{md_table(hourly)}

</details>

## Districts: winners and losers (change in mean delay per trip by origin district)
{d["districts_better"]} of {d["districts_ranked"]} districts with at least 1,000 trips are better
off, {d["districts_worse"]} worse.

Winners
{md_table(d["winners"])}

Losers
{md_table(d["losers"])}

## Corridors (time loss, city-equivalent vehicle-hours per day)
Ten most relieved
{md_table(r["corridors"]["relieved"])}

Ten most worsened
{md_table(r["corridors"]["worsened"])}

## Assumptions used
- Policy: {", ".join(ids["policy"]) or "(none)"}
- Day type: {", ".join(ids["daytype"])}
- Baseline model: {", ".join(ids["baseline_model"])}

Register: docs/assumptions.md (Track A rows also in docs/assumptions-trackA.md).

## Provenance
{md_table([{k: fmt(v) for k, v in r["provenance"].items()}])}

## Caveats
{POLICY_CAVEATS}
### Meso fidelity (PROJECT.md 9.4)
{caveats()}
"""


def main(run_dir: Path) -> None:  # pragma: no cover - thin CLI
    import typer

    from sim.policies.run import resolve_policy, run_config
    from sim.policies.transforms import Plan  # noqa: F401

    meta = json.loads((run_dir / "meta.json").read_text())
    pol, path = resolve_policy(meta["policy_file"] or meta["policy"])
    report = json.loads((run_dir / "metrics.json").read_text())
    ref_dir = run_dir.parent / meta["compare_baseline"]

    class _P:
        def edges(self) -> pd.DataFrame:
            from sim.policies.edges import load_edges

            return load_edges(REPO_ROOT / meta["network"])

    r = write_policy_report(run_dir, meta, report, ref_dir, pol, _P(), run_config(), path)
    typer.echo(r["headline"])


if __name__ == "__main__":  # pragma: no cover
    import typer

    typer.run(main)
