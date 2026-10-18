"""M7 evacuation with SUMO on the demo window: the demo command, determinism, contraflow and
signal-plan switching at run time, the strategist end to end, approve and the decision log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sim.common import SYNTHETIC_LABEL
from sim.events import evacuation as V
from sim.events.netindex import NetIndex
from strategist import decision_log as L
from strategist import evacuation as S
from tests.test_evacuation import synthetic_corridor

SCEN = "evac_demo"


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("evac")
    a = V.run(SCEN, seed=1, fcd=False, runs_dir=root / "a", quiet=True)
    b = V.run(SCEN, seed=1, fcd=True, runs_dir=root / "b", quiet=True)  # M5 path with FCD
    return {"a": a, "b": b, "root": root}


def test_demo_run_report(runs: dict[str, Any]) -> None:
    r = runs["a"]["report"]
    c = r["result"]["clearance"]
    assert r["label"] == SYNTHETIC_LABEL and r["fictional"]
    assert c["vehicles"] == 150 and c["out"] == 150
    assert 0 < c["t50_s"] <= c["t90_s"] <= c["t100_s"] <= c["horizon_s"]
    assert r["result"]["bottlenecks"] and r["result"]["bottlenecks"][0]["halted_veh_h"] > 0
    assert r["reference"]["background"]["vehicles"] == r["result"]["background"]["vehicles"]
    assert r["assumption_ids"] and all(i.startswith("A-") for i in r["assumption_ids"])
    meta = runs["a"]["meta"]
    for k in ("seed", "config_hash", "network_hash", "population_hash", "sumo_version"):
        assert meta[k] not in (None, "")
    md = (runs["a"]["out"] / "evacuation_report.md").read_text()
    assert "synthetic demand, uncalibrated" in md and "Bottleneck" in md


def test_demo_run_deterministic(runs: dict[str, Any]) -> None:
    ra, rb = runs["a"]["report"], runs["b"]["report"]
    assert ra["result"]["clearance"] == rb["result"]["clearance"]
    assert ra["result"]["background"] == rb["result"]["background"]
    assert ra["result"]["teleports"] == rb["result"]["teleports"]
    assert "window_kpis" in rb and list(Path(runs["b"]["out"]).rglob("fcd.parquet"))
    assert ra["result"]["bottlenecks"] == rb["result"]["bottlenecks"]


def _situation_with_corridor(tmp: Path) -> tuple[V.Situation, dict[str, Any]]:
    sit = V.situation(SCEN, seed=1)
    idx = NetIndex(sit.window_net)
    cor = synthetic_corridor(idx)
    built = V.build_evac_net("demo", sit.window_net, sit.demand_src, [], [cor], idx, out_dir=tmp)
    ana = {**sit.analysis, "corridors": [cor]}
    sit2 = sit.model_copy(update={"analysis": ana, "net": built["net"], "additionals": []})
    return sit2, cor


def _simulate(sit: V.Situation, plan: dict[str, Any], out: Path) -> dict[str, Any]:
    common = V.prepare_inputs(sit, out / "inputs")
    common.pop("demand_counts")
    spec = {**common, "run_dir": str(out / "run"), "plans": V.ordered_plans(sit, plan)}
    return V.simulate(spec)


def test_contraflow_switches_lanes(tmp_path: Path) -> None:
    sit, cor = _situation_with_corridor(tmp_path)
    plan = sit.plan(contraflow=[cor["exit"]])
    res = _simulate(sit, plan, tmp_path / "cf")
    log = res["event_log"]
    actions = [(e["action"], e["t"]) for e in log if e["event"] == plan["id"]]
    assert ("dormant_lanes_closed", sit.begin) in actions
    on = [t for a, t in actions if a == "contraflow_on"]
    assert on and on[0] >= plan["order_t"] + plan["setup_s"]
    summ = res["event_summaries"][plan["id"]]
    assert summ["contraflow_on"] and summ["contraflow_lanes_opened"] == 1
    assert summ["contraflow_lanes_closed"] >= 1
    # without contraflow the reversed lane stays closed and nothing is switched
    off = _simulate(sit, sit.plan(), tmp_path / "nocf")
    assert not off["event_summaries"][plan["id"]]["contraflow_on"]


def test_signal_plan_retimes_and_restores(tmp_path: Path) -> None:
    sit = V.situation(SCEN, seed=1)
    idx = NetIndex(sit.net)
    tls = idx.net.getTrafficLights()[0]
    moves = sorted({(i.getEdge().getID(), o.getEdge().getID()) for i, o, _ in tls.getConnections()})
    plan = {**sit.plan(signal_plan="evacuation"), "moves": [list(m) for m in moves]}
    res = _simulate(sit, plan, tmp_path / "sig")
    summ = res["event_summaries"][plan["id"]]
    assert summ["signals_retimed"] == [tls.getID()]
    assert summ["restored_at"] is not None  # cleared before the run end: programs restored


def test_cli_validate() -> None:
    from sim.common import REPO_ROOT

    paths = sorted(str(p) for p in (REPO_ROOT / "sim" / "scenarios").glob("evac_*.yaml")
                   if p.name != "evac_settings.yaml")  # fmt: skip
    r = CliRunner().invoke(V.app, ["validate", *paths])
    assert r.exit_code == 0, r.output
    assert r.output.count("OK") == len(paths)


@pytest.fixture(scope="module")
def rec(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("evac_strat")
    db = root / "log.sqlite"
    r = S.recommend(SCEN, seed=1, workers=4, db=db, runs_dir=root / "runs")
    return {"report": r, "db": db, "root": root}


def test_strategist_ranks_options(rec: dict[str, Any]) -> None:
    r = rec["report"]
    assert r["label"] == SYNTHETIC_LABEL and r["kind"] == "evacuation"
    ids = [c["candidate_id"] for c in r["candidates"]]
    assert S.NO_STRATEGY in ids and len(ids) == len(set(ids))
    ranks = [c["rank"] for c in r["candidates"] if c["rank"] is not None]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [c["score"] for c in r["candidates"] if c["rank"] is not None]
    assert scores == sorted(scores)
    for o in r["options"]:
        assert o["classification"] in (S.AUTO, S.APPROVAL)
        assert o["explanation"] and o["explanation"][0].startswith("Measured:")
        if any(a["type"] in ("contraflow", "evacuation_order") for a in o["actions"]):
            assert o["classification"] == S.APPROVAL
    run_dir = Path(r["run_dir"])
    run_dir = run_dir if run_dir.is_absolute() else Path.cwd() / run_dir
    assert not list((rec["root"] / "runs").rglob("fcd*")), "no FCD in what-if runs"
    assert r["no_strategy"]["clearance"]["vehicles"] == 150
    assert r["recommended"] in ids and r["fastest_clearance"] in ids
    if r["recommended"] == S.NO_STRATEGY:
        assert not any(c["beats_no_strategy"] for c in r["candidates"])
    md = (run_dir / "recommendation.md").read_text()
    assert "Recommendation:" in md and "noise" in md


def test_strategist_no_strategy_matches_demo_run(rec: dict[str, Any], runs: dict[str, Any]) -> None:
    """The no-strategy what-if and the demo command run the same simulation."""
    assert rec["report"]["no_strategy"]["clearance"] == runs["a"]["report"]["result"]["clearance"]


def test_approve_and_log(rec: dict[str, Any]) -> None:
    r, db = rec["report"], rec["db"]
    assert L.verify(db) == []
    d = S.approve(r["recommendation_id"], option=1, actor="tester", db=db)
    assert d["decision"] == "approved" and d["candidate_id"] == r["options"][0]["candidate_id"]
    assert L.verify(db) == []
    kinds = [x["kind"] for x in L.records(db)]
    assert kinds == ["recommendation", "decision"]
    with pytest.raises(RuntimeError, match="already has a decision"):
        S.approve(r["recommendation_id"], option=1, db=db)
    body = json.loads(L.records(db)[1]["decision"])
    assert body["note"].startswith("simulation and decision support only")
