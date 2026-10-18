"""M5 scenario runs on the demo window (micro, TraCI): every event has an observable effect,
outputs and reports are written, runs are deterministic. Short horizons keep this under ~30 s."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from sim.common import REPO_ROOT, SYNTHETIC_LABEL
from sim.scenarios.run import run_scenario

SCEN = REPO_ROOT / "tests" / "data" / "scenarios"


@pytest.fixture(scope="module")
def all_events(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    runs = tmp_path_factory.mktemp("runs")
    return run_scenario(SCEN / "demo_all_events.yaml", seed=1, runs_dir=runs, quiet=True)


def log_of(res: dict[str, Any], event: str, action: str) -> dict[str, Any]:
    rows = [r for r in res["report"]["event_log"] if r["event"] == event and r["action"] == action]
    assert rows, f"no {event}/{action} in the event log"
    return rows[0]


def test_accident_closes_lanes_and_cuts_flow(all_events: dict[str, Any]) -> None:
    rep = all_events["report"]
    closed = log_of(all_events, "acc", "close_lanes")
    assert closed["verified_disallowed"] == 2 and closed["full_closure"]
    assert closed["rubbernecking_lanes"], "opposite carriageway found for rubbernecking"
    assert log_of(all_events, "acc", "reopen_lanes")["verified_reopened"] == 2
    edge = "1104788990"
    base, scen = (
        rep["event_edges_flow"]["baseline"][edge],
        rep["event_edges_flow"]["scenario"][edge],
    )
    assert base > 50 and scen < 0.6 * base
    assert rep["kpis"]["scenario"]["rerouted_vehicles"] > 0


def test_rain_scales_and_restores_vtypes(all_events: dict[str, Any]) -> None:
    s = all_events["report"]["event_summaries"]["rain"]
    before, during, after = s["before"], s["during"], s["after"]
    heavy = {"speedFactor": 0.94, "accel": 0.85, "decel": 0.85, "minGap": 1.2, "tau": 1.12}
    for p, m in heavy.items():
        assert during[p] == pytest.approx(before[p] * m, rel=1e-4)
    assert after == before


def test_flood_closes_expected_edges(all_events: dict[str, Any]) -> None:
    plan = next(p for p in all_events["report"]["events"] if p["type"] == "flood")
    assert {s["site"] for s in plan["sites"]} == {"TS-001", "TS-002"}  # min_confidence medium
    row = log_of(all_events, "flood", "close_sites")
    assert row["t"] == pytest.approx(430)  # start 400 + closure_delay_s 30
    assert set(row["edges"]) == set(plan["closed_edges"]) >= {"166129018#0", "1492421519#8"}
    assert row["verified_disallowed"] == len(plan["closed_lanes"])
    assert log_of(all_events, "flood", "reopen_sites")["lanes"] == len(plan["closed_lanes"])


def test_motorcade_completes_and_closures_lift(all_events: dict[str, Any]) -> None:
    s = all_events["report"]["event_summaries"]["convoy"]
    assert s["convoy_arrived"] == s["convoy_vehicles"] == 4
    assert s["junctions_held"] == s["junctions_released"] > 0
    assert s["closures_still_active"] == 0
    c = all_events["report"]["convoy"][0]
    assert c["completed"] == 4 and c["mean_travel_time_s"] >= c["free_flow_s"]


def test_emergency_trip_vs_free_flow(all_events: dict[str, Any]) -> None:
    rep = all_events["report"]
    for run in ("baseline", "scenario"):
        (r,) = rep["emergency"][run]
        assert r["completed"] and r["travel_time_s"] >= r["free_flow_s"]
        assert r["ratio_to_free_flow"] >= 1.0
    assert rep["emergency"]["scenario"][0]["ratio_to_baseline"] is not None
    assert rep["strategist_requested"] is True
    assert all_events["meta"]["strategist_requested"] is True


def test_outputs_reports_and_meta(all_events: dict[str, Any]) -> None:
    out, stable = all_events["out"], all_events["stable"]
    for run in ("baseline", "scenario"):
        d = out / run
        assert not (d / "fcd.xml").exists() and not (d / "queue.xml").exists()
        fcd = pq.read_table(d / "fcd.parquet")
        assert fcd.num_rows > 10_000 and {"time", "id", "lon", "lat", "speed"} <= set(
            fcd.column_names
        )
        assert 39.1 < fcd.column("lon")[0].as_py() < 39.2  # geo coordinates
        for name in ("tripinfo.parquet", "edgedata.parquet", "timeseries.parquet", "stats.xml"):
            assert (d / name).exists()
    for name in ("meta.json", "scenario_report.json", "scenario_report.md"):
        assert (out / name).exists() and (stable / name).exists()
    assert stable.name == "demo_all_events"
    meta = json.loads((out / "meta.json").read_text())
    for key in ("seed", "config_hash", "network_hash", "population_hash", "sumo_version"):
        assert meta[key]
    assert meta["label"] == SYNTHETIC_LABEL and meta["fictional"] is True
    assert "A-event-001" in meta["assumption_ids"] and "A-kpi-001" in meta["assumption_ids"]
    md = (out / "scenario_report.md").read_text()
    assert SYNTHETIC_LABEL in md and "| mean delay = timeLoss (s) |" in md
    k = all_events["report"]["kpis"]["scenario"]
    assert k["queue_max_m"] >= k["queue_p95_m"] >= 0 and len(k["top_queued_edges"]) == 5


def test_same_mix_assignment_in_baseline_and_scenario(all_events: dict[str, Any]) -> None:
    def types(run: str) -> dict[str, str]:
        t = pq.read_table(all_events["out"] / run / "tripinfo.parquet", columns=["id", "vType"])
        return dict(zip(t.column("id").to_pylist(), t.column("vType").to_pylist(), strict=True))

    b, s = types("baseline"), types("scenario")
    common = set(b) & set(s)
    assert len(common) > 300 and all(b[v] == s[v] for v in common)
    assert {"normal", "slow", "aggressive"} <= set(b.values())


def test_determinism(tmp_path: Path) -> None:
    a = run_scenario(SCEN / "demo_emergency.yaml", seed=3, runs_dir=tmp_path / "a", quiet=True)
    b = run_scenario(
        SCEN / "demo_emergency.yaml", seed=3, runs_dir=tmp_path / "b", quiet=True, parallel=False
    )
    for key in ("kpis", "emergency", "delta", "gridlock", "event_log"):
        assert a["report"][key] == b["report"][key]
    assert a["meta"]["population_hash"] == b["meta"]["population_hash"]
    (r,) = a["report"]["emergency"]["scenario"]
    assert r["completed"] and r["ratio_to_free_flow"] >= 1.0
