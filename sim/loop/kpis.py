"""Loop KPIs of a policy run (`loop_report.json` / `.md` beside Track A's policy report).

City VHT saved and AM-peak delay change come from the policy report (against the matched control
when the run re-routed baseline vehicles, else the baseline). Added here: road-only VHT (shuttles
excluded), passengers served, shuttle operations, tunnel-km, capex range, VHT saved per km and per
million USD, rider door-to-door time against the same trip by car, and the quality flags
(teleports, station-pair capacity exceedance, tunnel segment utilisation, slower-than-car share).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sim.common import SYNTHETIC_LABEL
from sim.loop.schema import LoopPolicy, loop_config
from sim.loop.transforms import SHUTTLE_PREFIX


def run_dir(out: Path, name: str | None, search: list[Path] | None = None) -> Path | None:
    if not name:
        return None
    from sim.policies.run import RUNS_DIR

    for base in (out.parent, *(search or []), RUNS_DIR):
        if (base / name / "metrics.json").exists():
            return base / name
    return None


def road_vht(tripinfo: Path, sample: float, sim_end: float) -> dict[str, float]:
    ti = pd.read_parquet(tripinfo, columns=["veh_id", "depart", "duration", "time_loss",
                                            "depart_delay", "route_m"])  # fmt: skip
    ti = ti[ti["depart"] < sim_end]
    loop = ti["veh_id"].astype(str).str.startswith(SHUTTLE_PREFIX).to_numpy()
    f = 1.0 / sample
    road = ti[~loop]
    delay = road["time_loss"] + road["depart_delay"]
    am = road["depart"].between(6 * 3600, 9 * 3600, inclusive="left").to_numpy()
    return {
        "road_mean_delay_s": float(delay.mean()),
        "road_am_peak_delay_s": float(delay[am].mean()) if am.any() else float("nan"),
        "road_vht": float(road["duration"].sum() / 3600.0 * f),
        "road_vkt": float(road["route_m"].sum() / 1000.0 * f),
        "road_delay_h": float((road["time_loss"] + road["depart_delay"]).sum() / 3600.0 * f),
        "shuttle_vht": float(ti.loc[loop, "duration"].sum() / 3600.0 * f),
        "shuttle_vkt": float(ti.loc[loop, "route_m"].sum() / 1000.0 * f),
    }


def relief(out_ti: Path, ref_ti: Path, sample: float, sim_end: float) -> dict[str, float]:
    """Congestion relief: hours (travel + departure delay) saved by the vehicles that are on the
    road in both runs (same vehicle id, shuttles excluded), city-equivalent per day. Removed cars
    do not count as savings; re-routed cars (private mode) do."""
    cols = ["veh_id", "depart", "duration", "depart_delay"]

    def load(path: Path) -> pd.Series:
        ti = pd.read_parquet(path, columns=cols)
        ti = ti[(ti["depart"] < sim_end) & ~ti["veh_id"].astype(str).str.startswith(SHUTTLE_PREFIX)]
        return (ti["duration"] + ti["depart_delay"]).set_axis(ti["veh_id"].astype(str))

    a, b = load(ref_ti), load(out_ti)
    common = a.index.intersection(b.index)
    f = 1.0 / sample
    return {
        "relief_vht_per_day": float((a[common].sum() - b[common].sum()) / 3600.0 * f),
        "common_vehicles": int(len(common)),
        "common_vht_compare": float(a[common].sum() / 3600.0 * f),
    }


def capex(km: float, cfg: dict[str, Any]) -> dict[str, float]:
    c = cfg["costs"]["usd_m_per_km"]
    return {k: round(km * float(c[k]), 1) for k in ("low", "central", "high")}


def rider_times(out: Path, ref: Path | None, p: dict[str, Any]) -> dict[str, Any]:
    """Door-to-door Loop time vs the baseline car trip of the same shifted legs."""
    pax_path, sh_path = out / "loop_pax.parquet", out / "loop_shuttles.parquet"
    if not pax_path.exists() or not sh_path.exists() or ref is None:
        return {}
    pax = pd.read_parquet(pax_path)
    if pax.empty:
        return {"riders": 0}
    sh = pd.read_parquet(sh_path)
    ti = pd.read_parquet(out / "tripinfo.parquet",
                         columns=["veh_id", "duration", "depart_delay"])  # fmt: skip
    sh = sh[~sh["empty"]].merge(ti, on="veh_id", how="left")
    pair = sh.groupby(["line", "os", "ds"])[["duration", "depart_delay"]].mean()
    base = pd.read_parquet(ref / "tripinfo.parquet",
                           columns=["veh_id", "duration", "depart_delay"])  # fmt: skip
    base["car_s"] = base["duration"] + base["depart_delay"]
    m = pax.merge(pair.reset_index(), on=["line", "os", "ds"], how="left")
    m = m.merge(base[["veh_id", "car_s"]], left_on="base_veh_id", right_on="veh_id", how="left")
    walk = p["walk_speed_kmh"] / 3.6 / p["detour_factor"]
    loop_s = ((m["access_m"] + m["egress_m"]) / walk + p["wait_min"] * 60.0
              + m["depart_delay"].fillna(0.0) + m["duration"])  # fmt: skip
    ok = loop_s.notna() & m["car_s"].notna()
    return {
        "riders": len(m),
        "compared": int(ok.sum()),
        "mean_loop_door_to_door_min": round(float(loop_s[ok].mean() / 60.0), 1),
        "mean_car_min": round(float(m.loc[ok, "car_s"].mean() / 60.0), 1),
        "share_slower_than_car": round(float((loop_s[ok] > m.loc[ok, "car_s"]).mean()), 4),
        "rider_extra_hours_per_day": round(
            float((loop_s[ok] - m.loc[ok, "car_s"]).sum() / 3600.0 / p["sample"]), 1
        ),
        "mean_shuttle_ride_min": round(float(m["duration"].mean() / 60.0), 1),
        "mean_shuttle_depart_delay_s": round(float(m["depart_delay"].mean()), 1),
        "mean_access_egress_m": round(float((m["access_m"] + m["egress_m"]).mean()), 0),
    }


def loop_edgedata(out: Path) -> pd.DataFrame | None:
    """Edge data of the Loop edges only; kept as loop_edgedata.parquet so pruning the run's full
    edgedata (disk) does not lose the tunnel statistics."""
    small = out / "loop_edgedata.parquet"
    if small.exists():
        return pd.read_parquet(small)
    ed = out / "edgedata.parquet"
    if not ed.exists():
        return None
    import pyarrow.parquet as pq

    tbl = pq.read_table(ed, columns=["begin", "edge_id", "entered"]).to_pandas()
    tbl = tbl[tbl["edge_id"].astype(str).str.startswith(SHUTTLE_PREFIX)].reset_index(drop=True)
    tbl["edge_id"] = tbl["edge_id"].astype(str)
    tbl.to_parquet(small, index=False)
    return tbl


def private_usage(out: Path, sample: float, p: dict[str, Any]) -> dict[str, Any]:
    """Tunnel entries, toll revenue and tunnel segment load. Throughput above the headway
    capacity is possible only through jam teleports (120 s teleport time, A-sim-103): vehicles
    queued at a full tunnel jump through it, so exceedance marks teleport-assisted use."""
    tbl = loop_edgedata(out)
    if tbl is None:
        return {}
    downs = tbl[tbl["edge_id"].str.match(r"^loop_[A-Za-z0-9]+_D\d+$")]
    f = 1.0 / sample
    entries = float(downs["entered"].sum() * f)
    hourly = downs.groupby(np.floor(downs["begin"] / 3600.0))["entered"].sum() * f
    tunnels = tbl[tbl["edge_id"].str.match(r"^loop_[A-Za-z0-9]+_T\d+_\d+$")]
    t_hour = tunnels.groupby([np.floor(tunnels["begin"] / 3600.0), "edge_id"])["entered"].sum() * f
    cap = 3600.0 / p["headway_s"]
    over = t_hour[t_hour > cap * 1.0001]
    total = float(t_hour.sum())
    return {
        "tunnel_entries_per_day": round(entries),
        "peak_hour_entries": round(float(hourly.max())) if len(hourly) else 0,
        "toll_revenue_sar_per_day": round(entries * p["toll_sar"]),
        "segment_peak_utilisation": round(float(t_hour.max() / cap), 3) if len(t_hour) else 0.0,
        "segment_exceedance_share": round(float(over.sum() / total), 4) if total else 0.0,
        "tunnel_vehicle_km_above_capacity_share": round(float((over - cap).sum() / total), 4)
        if total
        else 0.0,
    }


def kpi(r: dict[str, Any], key: str) -> dict[str, Any]:
    for k in r["kpis"]:
        if k["kpi"] == key:
            return k
    return {}


def write_loop_report(
    out: Path,
    meta: dict[str, Any],
    pol: LoopPolicy | None = None,
    search: list[Path] | None = None,
) -> dict[str, Any]:
    cfg = loop_config()
    r = json.loads((out / "policy_report.json").read_text())
    eff = next((e for e in meta["effects"] if e.get("type") in ("loop_shuttle", "loop_private")),
               {})  # fmt: skip
    p = eff.get("params", {})
    sample, sim_end = float(meta["sample"]), float(meta["sim_end_s"])
    ref = run_dir(out, meta.get("compare_baseline"), search)
    raw = run_dir(out, meta.get("raw_baseline"), search) or ref
    km = float(sum(eff.get("network", {}).get("alignment_km", {}).values()))
    cx = capex(km, cfg)
    vht = kpi(r, "vht")
    am = kpi(r, "am_peak_mean_delay_s")
    saved = float(vht.get("baseline", 0) - vht.get("policy", 0))
    road = road_vht(out / "tripinfo.parquet", sample, sim_end)
    road_ref = road_vht(ref / "tripinfo.parquet", sample, sim_end) if ref else {}
    road_saved = road_ref.get("road_vht", np.nan) - road["road_vht"]
    am_ref = road_ref.get("road_am_peak_delay_s", np.nan)
    rel = relief(out / "tripinfo.parquet", ref / "tripinfo.parquet", sample, sim_end) if ref else {}
    rv = float(rel.get("relief_vht_per_day", np.nan))
    tele = kpi(r, "teleport_share")
    rep: dict[str, Any] = {
        "label": SYNTHETIC_LABEL,
        "run_id": meta["run_id"],
        "policy": meta.get("policy"),
        "mode": p.get("mode"),
        "alignments": sorted(eff.get("network", {}).get("alignment_km", {})),
        "compare": meta.get("compare_baseline"),
        "params": p,
        "tunnel_km": round(km, 2),
        "stations": eff.get("network", {}).get("stations"),
        "capex_usd_m": cx,
        "capex_sar_m": {k: round(v * float(cfg["costs"]["sar_per_usd"]), 1) for k, v in cx.items()},
        "relief_vht_per_day": round(rv),
        "relief_pct": round(100.0 * rv / rel["common_vht_compare"], 3) if rel else None,
        "relief_per_km": round(rv / km, 1) if km else None,
        "relief_per_usd_m": {k: round(rv / v, 2) for k, v in cx.items() if v},
        "annual_relief_vht": round(rv * float(cfg["annual_days"])),
        "vht_saved_per_day": round(saved),
        "vht_saved_pct": round(-float(vht.get("delta_pct") or 0.0), 3),
        "road_vht_saved_per_day": round(float(road_saved)),
        "shuttle_vht_per_day": round(road["shuttle_vht"]),
        "shuttle_vkt_per_day": round(road["shuttle_vkt"]),
        "am_peak_delay_change_s": round(road["road_am_peak_delay_s"] - am_ref, 1),
        "am_peak_delay_change_pct": round(100.0 * (road["road_am_peak_delay_s"] / am_ref - 1.0), 2),
        "mean_delay_change_pct": round(
            100.0 * (road["road_mean_delay_s"] / road_ref.get("road_mean_delay_s", np.nan) - 1.0), 2
        ),
        "city_am_peak_delay_change_pct": am.get("delta_pct"),
        "vkt_change_pct": kpi(r, "vkt").get("delta_pct"),
        "vht_saved_per_km": round(saved / km, 1) if km else None,
        "vht_saved_per_usd_m": {k: round(saved / v, 2) for k, v in cx.items() if v},
        "passengers_per_day": eff.get("passengers_per_day"),
        "car_vehicles_removed_per_day": round(eff.get("car_vehicles_removed", 0) / sample),
        "cars_rerouted": round(eff["cars_rerouted"] / sample) if eff.get("cars_rerouted") else None,
        "mode_choice": eff.get("mode_choice"),  # Track H: logit summary (None on the alpha path)
        "flags": {
            "teleport_share": tele.get("policy"),
            "teleport_share_compare": tele.get("baseline"),
            "pair_exceedance_share": eff.get("pair_exceedance_share"),
            "peak_pair_pph": eff.get("peak_pair_pph"),
            "segment_peak_utilisation": eff.get("segment_peak_utilisation"),
            "segment_exceedance_share": eff.get("segment_exceedance_share"),
            "connect_flags": eff.get("network", {}).get("connect_flags"),
        },
    }
    if p.get("mode") == "shuttle":
        rep["riders"] = rider_times(out, raw, p | {"sample": sample})
        extra = rep["riders"].get("rider_extra_hours_per_day")
        if extra is not None:
            rep["net_person_hours_per_day"] = round(rep["relief_vht_per_day"] - extra)
        rep["flags"]["share_slower_than_car"] = rep["riders"].get("share_slower_than_car")
    else:
        rep["private"] = private_usage(out, sample, p) if p else {}
        rep["flags"]["segment_peak_utilisation"] = rep["private"].get("segment_peak_utilisation")
        rep["flags"]["segment_exceedance_share"] = rep["private"].get("segment_exceedance_share")
    rep["headline"] = headline(rep)
    (out / "loop_report.json").write_text(json.dumps(rep, indent=2, default=float))
    (out / "loop_report.md").write_text(render_md(rep, r))
    return rep


def headline(rep: dict[str, Any]) -> str:
    c = rep["capex_usd_m"]
    per = rep["relief_per_usd_m"]
    return (
        f"{rep['policy']} ({rep['mode']}, {rep['tunnel_km']} km): congestion relief "
        f"{rep['relief_vht_per_day']:,} VHT/day ({rep['relief_pct']:+.2f} % for remaining "
        f"vehicles), {per.get('central', float('nan')):,.1f} VHT/day per USD M "
        f"(capex USD {c['low']:,.0f}-{c['high']:,.0f} M); city VHT saved "
        f"{rep['vht_saved_per_day']:,}/day; {SYNTHETIC_LABEL}"
    )


def render_md(rep: dict[str, Any], r: dict[str, Any]) -> str:
    rows = [
        ("tunnel-km / stations", f"{rep['tunnel_km']} / {rep['stations']}"),
        ("capex USD M (low / central / high)", " / ".join(
            f"{v:,.0f}" for v in rep["capex_usd_m"].values())),
        ("congestion relief: VHT saved by vehicles still on the road",
         f"{rep['relief_vht_per_day']:,} ({rep['relief_pct']} %)"),
        ("relief per day per USD M (low / central / high capex)", " / ".join(
            f"{v:,.2f}" for v in rep["relief_per_usd_m"].values())),
        ("net person-hours (relief minus riders' extra time)",
         rep.get("net_person_hours_per_day")),
        ("city VHT saved per day (incl. removed cars)",
         f"{rep['vht_saved_per_day']:,} ({rep['vht_saved_pct']:+.2f} %)"),
        ("road VHT saved per day (shuttles excluded)", f"{rep['road_vht_saved_per_day']:,}"),
        ("AM-peak (06-09) mean delay change, road vehicles",
         f"{rep['am_peak_delay_change_s']} s ({rep['am_peak_delay_change_pct']} %)"),
        ("VHT saved per day per km", rep["vht_saved_per_km"]),
        ("VHT saved per day per USD M (low / central / high capex)", " / ".join(
            f"{v:,.2f}" for v in rep["vht_saved_per_usd_m"].values())),
        ("passengers per day", rep.get("passengers_per_day")),
        ("cars re-routed (private mode)", rep.get("cars_rerouted")),
    ]  # fmt: skip
    lines = [
        f"# Loop report: {rep['policy']}",
        "",
        f"**{SYNTHETIC_LABEL}.** Compared with `{rep['compare']}`. {rep['headline']}",
        "",
        "| KPI | value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        "## Quality flags",
        "",
        "| flag | value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rep["flags"].items()],
        "",
    ]
    if rep.get("riders"):
        lines += ["## Riders (estimated door to door, not simulated as persons)", "",
                  "| item | value |", "|---|---|",
                  *[f"| {k} | {v} |" for k, v in rep["riders"].items()], ""]  # fmt: skip
    if rep.get("private"):
        lines += ["## Private-EV use", "", "| item | value |", "|---|---|",
                  *[f"| {k} | {v} |" for k, v in rep["private"].items()], ""]  # fmt: skip
    lines += ["## Parameters", "", "```json", json.dumps(rep["params"], indent=2), "```", "",
              f"Full policy report: `policy_report.md` ({r['headline']})", ""]  # fmt: skip
    return "\n".join(lines)


def rebuild(run: Path, search: list[Path] | None = None) -> dict[str, Any]:
    """Recompute loop_report.json of a finished run from its outputs (no simulation)."""
    meta = json.loads((run / "meta.json").read_text())
    old = (
        json.loads((run / "loop_report.json").read_text())
        if (run / "loop_report.json").exists()
        else {}
    )
    rep = write_loop_report(run, meta, None, search)
    for k in ("wall_s", "policy_hash", "free_gb_before", "timings"):
        if k in old:
            rep[k] = old[k]
    if rep.get("mode") == "private" and not rep.get("private") and old.get("private"):
        # edge data pruned before loop_edgedata.parquet existed: keep the earlier tunnel figures
        rep["private"] = old["private"]
        rep["flags"]["segment_peak_utilisation"] = old["private"].get("segment_peak_utilisation")
    (run / "loop_report.json").write_text(json.dumps(rep, indent=2, default=float))
    return rep


def main(runs: list[Path]) -> None:
    """python -m sim.loop.kpis runs/<loop run> ...   (recompute Loop reports)"""
    for run in runs:
        print(rebuild(run)["headline"])


if __name__ == "__main__":
    import typer

    typer.run(main)
