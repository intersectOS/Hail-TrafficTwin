"""M4 end-to-end policy runs on the demo window (SUMO, seconds each): report contents, the
no-change identity with the baseline, determinism, re-routing repeatability, day-type reuse,
bus line, cordon, closure and the sweep tool."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

import sim.policies.edges as E
import sim.population.baseline as baseline
import sim.population.synthesize as synthesize
from sim.common import SYNTHETIC_LABEL, run_cmd
from sim.metrics import xml_content_hash
from sim.policies import routes as R
from sim.policies.run import run_policy
from sim.schemas import Policy, load_policy
from tests.test_policies import BBOX, DEMO_NET, RESIDENTS, quadrant_districts

TAHLIA_DEMO_STOPS = [
    {"name": "west", "lon": 39.1507, "lat": 21.5495},
    {"name": "middle", "lon": 39.1571, "lat": 21.5511},
    {"name": "east", "lon": 39.1641, "lat": 21.5534},
]


@pytest.fixture(scope="module")
def penv(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict]:
    from sim.population import zones as Z

    tmp = tmp_path_factory.mktemp("m4run")
    cfg = Z.zones_config()
    cfg["control_total"]["value"] = RESIDENTS
    cfg["non_residential_districts"]["names"] = []
    zones, zone_edges = Z.build_zones(
        Z.ZoneInputs(districts=quadrant_districts(tmp / "d.geojson"), net=DEMO_NET), cfg
    )
    Z.write_zones(zones, zone_edges, tmp / "zones", {})
    mp = pytest.MonkeyPatch()
    mp.setattr(synthesize, "CACHE_DIR", tmp / "pop")
    mp.setattr(baseline, "ROUTE_CACHE", tmp / "routes")
    mp.setattr(E, "CACHE", tmp / "edges")
    kw = {"sample": 1.0, "seed": 1, "net": DEMO_NET, "zone_dir": tmp / "zones",
          "baselines_dir": tmp / "baselines", "iterations": 1, "quiet": True}  # fmt: skip
    yield {"tmp": tmp, "kw": kw}
    mp.undo()


def policy(transforms: list[dict], daytype: str = "weekday", pid: str = "demo") -> Policy:
    return Policy.model_validate({"id": pid, "kind": "policy", "title": pid, "daytype": daytype,
                                  "transforms": transforms})  # fmt: skip


def report(runs: Path, meta: dict) -> dict:
    return json.loads((runs / meta["run_id"] / "policy_report.json").read_text())


def tripinfo_hash(run_dir: Path) -> str:
    return json.loads((run_dir / "metrics.json").read_text())["tripinfo_hash"]


def test_remote_work_policy_report_and_determinism(penv: dict, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    m1 = run_policy("remote_work_30", "weekday", runs_dir=runs, **penv["kw"])
    out = runs / m1["run_id"]
    assert m1["run_id"] == "remote_work_30-f1"
    for name in ("policy_report.json", "policy_report.md", "policy_districts.parquet",
                 "metrics.json", "tripinfo.parquet", "edgedata.parquet", "meta.json"):  # fmt: skip
        assert (out / name).exists(), name
    r = report(runs, m1)
    assert (
        r["label"] == SYNTHETIC_LABEL and SYNTHETIC_LABEL in (out / "policy_report.md").read_text()
    )
    kpis = {k["kpi"]: k for k in r["kpis"]}
    assert {"mean_delay_s", "vkt", "vht", "co2_t", "nox_kg", "peak_spreading_top_hour_share",
            "throughput_peak_hour_trips", "mean_speed_kmh"} <= set(kpis)  # fmt: skip
    assert kpis["trips_completed"]["policy"] < kpis["trips_completed"]["baseline"]
    assert {"A-pol-001", "A-pol-002"} <= set(r["assumption_ids"]["policy"])
    assert r["assumption_ids"]["daytype"] and r["assumption_ids"]["baseline_model"]
    assert {"am", "pm", "hourly"} <= set(r["peak_spreading"])
    assert {"winners", "losers"} <= set(r["districts"])
    assert {"relieved", "worsened"} <= set(r["corridors"])
    eff = r["effects"][0]
    assert eff["type"] == "remote_work" and eff["remote_today"] > 0
    md = (out / "policy_report.md").read_text()
    for section in ("City KPIs", "Peak spreading", "winners and losers", "most relieved",
                    "most worsened", "Assumptions used", "Caveats"):  # fmt: skip
        assert section in md
    # same seed again, in a separate directory: identical routes and simulation
    first = tripinfo_hash(out)
    runs2 = tmp_path / "runs2"
    m2 = run_policy("remote_work_30", "weekday", runs_dir=runs2, **penv["kw"])
    assert m2["routes_hash"] == m1["routes_hash"]
    assert tripinfo_hash(runs2 / m2["run_id"]) == first


def test_null_policy_reproduces_the_baseline(penv: dict, tmp_path: Path) -> None:
    pol = policy([{"type": "remote_work", "share": 0.0, "days_per_week": 3,
                   "eligible_sectors": ["government"], "assumption": "null"}])  # fmt: skip
    meta = run_policy(pol, "weekday", runs_dir=tmp_path, force_simulate=True, **penv["kw"])
    base = penv["kw"]["baselines_dir"] / meta["compare_baseline"]
    assert meta["routing"]["rerouted"] == 0 and meta["routing"]["to_route"] == 0
    assert tripinfo_hash(tmp_path / meta["run_id"]) == tripinfo_hash(base)
    r = report(tmp_path, meta)
    assert all(k["delta"] == 0 for k in r["kpis"])


def test_daytype_policy_starts_from_that_baseline(penv: dict, tmp_path: Path) -> None:
    meta = run_policy("friday", "weekday", runs_dir=tmp_path, **penv["kw"])
    assert meta["start_baseline"].startswith("baseline-friday-")
    assert meta["compare_baseline"].startswith("baseline-weekday-")
    assert meta["timings"]["simulation"]["reused_from"] == meta["start_baseline"]
    friday = penv["kw"]["baselines_dir"] / meta["start_baseline"]
    assert tripinfo_hash(tmp_path / meta["run_id"]) == tripinfo_hash(friday)
    r = report(tmp_path, meta)
    school = {k["kpi"]: k for k in r["kpis"]}["trips_completed"]
    assert school["policy"] != school["baseline"]
    # composed: Ramadan + remote work against the Ramadan baseline
    comp = run_policy("ramadan_remote_30", "ramadan_weekday", runs_dir=tmp_path, **penv["kw"])
    assert comp["start_baseline"] == comp["compare_baseline"]
    assert comp["start_baseline"].startswith("baseline-ramadan_weekday-")
    assert comp["routing"]["reused"] > 0


def test_reroute_threads_repeatable(penv: dict, tmp_path: Path) -> None:
    """One-shot routing on fixed weights gives the same routes with 1 and 4 threads."""
    meta = run_policy("staggered_schools_60", "weekday", runs_dir=tmp_path, **penv["kw"])
    out = tmp_path / meta["run_id"]
    assert meta["routing"]["rerouted"] > 0
    # re-timed baseline vehicles were re-routed, so the report compares with a matched control
    assert meta["control_run"] == f"{meta['run_id']}--control"
    ctrl = json.loads((tmp_path / meta["control_run"] / "meta.json").read_text())
    assert ctrl["routing"]["to_route"] == meta["control_rerouted"] > 0
    r = report(tmp_path, meta)
    assert r["compare_baseline"] == meta["control_run"] and r["control"]["kpis_vs_raw_baseline"]
    assert "matched control" in (out / "policy_report.md").read_text()
    base = penv["kw"]["baselines_dir"] / meta["start_baseline"]
    edges = E.load_edges(DEMO_NET)
    cong = R.congested_weights(base / "edgedata.parquet", edges, 900, 1.0)
    R.write_weights(tmp_path / "w.xml.gz", cong, edges, 900, 93600)
    veh = pd.read_parquet(out / "vehicles.parquet").head(400)
    from sim.population.export_trips import write_trips

    write_trips(veh, tmp_path / "t.xml")
    hashes = []
    for threads in (1, 4, 4):
        cfg = {"routing_algorithm": "astar", "routing_threads": threads}
        o = tmp_path / f"r{threads}-{len(hashes)}.rou.xml"
        run_cmd(R.reroute_command(DEMO_NET, tmp_path / "t.xml", tmp_path / "w.xml.gz", o,
                                  tmp_path / "vt.xml", 1, 93600, cfg))  # fmt: skip
        hashes.append(xml_content_hash(o))
    assert len(set(hashes)) == 1


def test_bus_line_cordon_and_closure_run(penv: dict, tmp_path: Path) -> None:
    bus = policy([{"type": "pt_line", "line_id": "D1", "stops": TAHLIA_DEMO_STOPS,
                   "headway_s": 600, "catchment_m": 600, "shift_share": 1.0,
                   "assumption": "test"}], pid="bus")  # fmt: skip
    mb = run_policy(bus, "weekday", runs_dir=tmp_path, **penv["kw"])
    eff = mb["effects"][0]
    assert eff["bus_departures"] > 100 and eff["tours_in_catchment"] >= eff["tours_shifted"]
    ti = pd.read_parquet(tmp_path / mb["run_id"] / "tripinfo.parquet")
    assert (ti["vtype"] == "pt_bus").sum() > 0  # the line's buses ran in the meso run

    xm = (BBOX[0] + BBOX[2]) / 2
    cordon = load_policy("cordon_center").model_dump()
    cordon["id"] = "cordon_demo"
    cordon["transforms"][0]["polygon"] = [[xm, 21.53], [39.2, 21.53], [39.2, 21.57], [xm, 21.57]]
    mc = run_policy(Policy.model_validate(cordon), "weekday", runs_dir=tmp_path, **penv["kw"])
    ec = mc["effects"][0]
    assert ec["charged_vehicles"] > 0 and ec["vehicles_rerouted_with_penalty"] > 0
    assert mc["routing"]["rerouted"] > 0

    target = pd.read_parquet(tmp_path / mb["run_id"] / "edgedata.parquet")
    busiest = target.groupby("edge_id")["entered"].sum().idxmax()
    close = policy([{"type": "network_change", "edits": [{"edges": [busiest], "closed": True}],
                     "assumption": "test"}], pid="close")  # fmt: skip
    mn = run_policy(close, "weekday", runs_dir=tmp_path, **penv["kw"])
    assert mn["effects"][0]["vehicles_rerouted_closure"] > 0
    assert mn["network"] != str(DEMO_NET) and mn["net_change"]["closed_edges"] == [busiest]
    ed = pd.read_parquet(tmp_path / mn["run_id"] / "edgedata.parquet")
    assert busiest not in set(ed["edge_id"])


def test_sweep_writes_response_curve(penv: dict, tmp_path: Path) -> None:
    from sim.policies import sweep as S

    assert S.parse_grid("share=0.1:0.5:0.1") == ("share", [0.1, 0.2, 0.3, 0.4, 0.5])
    assert S.template("remote_work").id == "remote_work_30"
    kw = {k: v for k, v in penv["kw"].items() if k not in ("sample", "seed", "baselines_dir")}
    real = S.run_policy
    seen = []

    def point(pol, daytype, sample, seed, runs_dir, quiet=True, baselines_dir=None):  # noqa: ANN001, ANN202
        seen.append(baselines_dir)
        return real(
            pol, daytype, sample, seed, runs_dir, baselines_dir=penv["kw"]["baselines_dir"], **kw
        )

    S.run_policy = point
    try:
        df = S.sweep("remote_work", "share=0.2:0.6:0.4", sample=1.0, workers=1, runs_dir=tmp_path)
    finally:
        S.run_policy = real
    out = tmp_path / "sweep-remote_work_30-share"
    assert (out / "response_curve.csv").exists() and (out / "response_curve.png").exists()
    assert list(df["share"]) == [0.2, 0.6]
    assert df["trips_completed"].iloc[1] < df["trips_completed"].iloc[0]
    assert SYNTHETIC_LABEL in (out / "response_curve.csv").read_text().splitlines()[0]
    assert seen == [tmp_path, tmp_path]  # baselines looked up in the parent runs dir


def test_ridehail_keeps_routes_and_placebo(penv: dict, tmp_path: Path) -> None:
    m = run_policy("ridehail_plus_10", "weekday", runs_dir=tmp_path, **penv["kw"])
    r, eff = m["routing"], m["effects"][0]
    # converted tours keep their baseline routes (same vehicle class); only empty legs are new
    assert r["retyped"] > 0 and r["to_route"] == eff["deadhead_vehicles_added"]
    ti = pd.read_parquet(tmp_path / m["run_id"] / "tripinfo.parquet")
    base = penv["kw"]["baselines_dir"] / m["compare_baseline"]
    tb = pd.read_parquet(base / "tripinfo.parquet")
    assert (ti["vtype"] == "ridehail").sum() > (tb["vtype"] == "ridehail").sum() + r["retyped"] / 2
    null = policy(
        [
            {
                "type": "remote_work",
                "share": 0.0,
                "days_per_week": 3,
                "eligible_sectors": ["government"],
                "assumption": "placebo",
            }
        ],
        pid="placebo",
    )
    p = run_policy(null, "weekday", runs_dir=tmp_path, placebo_reroute_share=0.2, **penv["kw"])
    share = p["routing"]["to_route"] / p["routing"]["vehicles"]
    assert 0.15 < share < 0.25 and p["placebo_reroute_share"] == 0.2
