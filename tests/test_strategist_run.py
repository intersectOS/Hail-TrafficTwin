"""M6 strategist on the demo window with SUMO: snapshot + fork semantics, event re-application,
determinism, preemption and holds, end-to-end recommendation, approve, decision log, CLIs."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sim.common import SYNTHETIC_LABEL, sumo_bin
from sim.scenarios.simulate import start_sumo
from strategist import decision_log as L
from strategist.approve import approve
from strategist.candidates import NO_STRATEGY_ID, side_entries
from strategist.evaluate import run_candidate
from strategist.fork import prepare_events, reapply, sumo_args
from strategist.run import recommend
from strategist.situation import resolve_situation

NUM = re.compile(r"\d+(?:\.\d+)?")
MEASURED = (
    "arrived", "travel_time_s", "depart_t", "arrival_t", "background_veh_h", "background_arrived",
    "teleports", "route_halted_max", "ambulance_edge_s", "signals_preempted", "preempted",
    "rescue_lane_edges", "junctions_held", "hold_s_total", "closed_lanes_verified", "event_log",
)  # fmt: skip


@pytest.fixture(scope="module")
def rec(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("strategist")
    report = recommend(
        "emergency_demo", seed=1, db=root / "log.sqlite", runs_dir=root / "runs", quiet=True
    )
    return {"report": report, "db": root / "log.sqlite", "root": root}


def spec_for(report: dict[str, Any], cand_id: str, run_dir: Path) -> dict[str, Any]:
    cand = next(c for c in report["candidate_specs"] if c["id"] == cand_id)
    return {**report["fork"], "candidate": cand, "run_dir": str(run_dir)}


def test_three_ranked_options_best_beats_no_strategy(rec: dict[str, Any]) -> None:
    r = rec["report"]
    assert [o["rank"] for o in r["options"]] == [1, 2, 3]
    best, ns = r["options"][0], r["no_strategy"]
    assert best["travel_time_s"] < ns["travel_time_s"] and r["best_beats_no_strategy"]
    assert all(o["candidate_id"] != NO_STRATEGY_ID for o in r["options"])
    assert len({o["route_name"] for o in r["options"]}) == 3  # distinct routes first
    scores = [o["score"] for o in r["options"]]
    assert scores == sorted(scores)
    for o in r["options"]:
        assert o["classification"] in ("auto_eligible", "approval_required")
        assert o["vs_no_strategy_s"] == o["travel_time_s"] - ns["travel_time_s"]
        assert o["travel_time_s"] >= o["free_flow_s"]
    assert r["wall_s"]["evaluation_s"] < 60


def test_outputs_record_provenance(rec: dict[str, Any]) -> None:
    r = rec["report"]
    out = rec["root"] / "runs" / r["recommendation_id"]
    saved = json.loads((out / "recommendation.json").read_text())
    assert saved["fingerprint"] == r["fingerprint"]
    md = (out / "recommendation.md").read_text()
    assert SYNTHETIC_LABEL in md and "Fictional scenario" in md
    assert r["label"] == SYNTHETIC_LABEL and r["fictional"] is True
    s = r["snapshot"]
    for key in ("state_hash", "network_hash", "demand_hash", "population_hash", "sumo_version"):
        assert s[key]
    assert r["seed"] == 1 and r["config_hash"]
    assert "A-strat-016" in r["assumption_ids"] and "A-strat-022" in r["assumption_ids"]
    snap_dir = rec["root"] / "runs" / "snapshots" / s["snapshot_id"]
    assert (snap_dir / "state.xml.gz").exists() and (snap_dir / "edge_tt.json").exists()
    assert not list(out.rglob("fcd*")), "no FCD in what-if runs"


def test_snapshot_reused_and_deterministic(rec: dict[str, Any]) -> None:
    root = rec["root"]
    again = recommend(
        "emergency_demo", seed=1, db=root / "log.sqlite", runs_dir=root / "runs", quiet=True
    )
    assert again["snapshot"]["reused"] and not rec["report"]["snapshot"]["reused"]
    assert again["fingerprint"] == rec["report"]["fingerprint"]
    assert again["options"] == rec["report"]["options"]
    assert again["recommendation_id"] != rec["report"]["recommendation_id"]


def test_state_loses_lane_closures_and_reapply_restores_them(rec: dict[str, Any]) -> None:
    r = rec["report"]
    fork = r["fork"]
    lanes = r["closed_lanes_at_t"]
    assert lanes
    conn = start_sumo(
        [sumo_bin("sumo"), *sumo_args(fork, ["--load-state", fork["state"], "--end", "260"])],
        rec["root"] / "load_check.log",
        "load-check",
    )
    try:
        assert conn.simulation.getTime() == fork["t"]
        # SUMO 1.28 saveState keeps vehicles and signal program/phase, not lane permissions
        assert all(conn.lane.getAllowed(ln) for ln in lanes)
        tls = r["snapshot"]["measured_at_t"]["tls"]
        for t, st in tls.items():
            assert conn.trafficlight.getProgram(t) == st["program"]
            assert conn.trafficlight.getPhase(t) == st["phase"]
        assert conn.vehicle.getIDCount() == r["snapshot"]["measured_at_t"]["running"]
        from sim.events.base import EventContext

        ctx = EventContext(conn=conn, tier="B", t=fork["t"])
        closed = reapply(ctx, prepare_events(fork["plans"], fork["t"]))
        assert sorted(closed) == sorted(lanes)
        assert all(not conn.lane.getAllowed(ln) for ln in lanes)
    finally:
        conn.close()
    for res in r["results"].values():
        assert sorted(res["closed_lanes_verified"]) == sorted(lanes)


def test_unsupported_active_events_are_refused() -> None:
    plans = [{"type": "rain", "id": "r", "start": 0, "end": 500, "multipliers": {}}]
    with pytest.raises(NotImplementedError, match="re-applying"):
        prepare_events(plans, 100)
    ended = prepare_events(plans, 600)
    assert ended[0].state == "done"


def test_fork_determinism_same_candidate_twice(rec: dict[str, Any], tmp_path: Path) -> None:
    r = rec["report"]
    cid = r["options"][0]["candidate_id"]
    a = run_candidate(spec_for(r, cid, tmp_path / "a"))
    b = run_candidate(spec_for(r, cid, tmp_path / "b"))
    assert {k: a[k] for k in MEASURED} == {k: b[k] for k in MEASURED}
    assert a["travel_time_s"] == r["results"][cid]["travel_time_s"]


def test_preemption_switches_and_restores_signal(rec: dict[str, Any]) -> None:
    r = rec["report"]
    pre = [c for c in r["candidate_specs"] if any(a["type"] == "preempt" for a in c["actions"])]
    assert pre, "demo routes cross the demo signal"
    for c in pre:
        res = r["results"][c["id"]]
        assert res["signals_preempted"] == 1
        (p,) = res["preempted"]
        assert p["tls"] == "GS_cluster_10109918119_4419972011" and p["held_s"] > 0


def test_side_entry_hold_applied_and_released(rec: dict[str, Any], tmp_path: Path) -> None:
    r = rec["report"]
    sit = resolve_situation("emergency_demo", None, 1)
    base = next(c for c in r["candidate_specs"] if c["id"] == NO_STRATEGY_ID)
    holds = side_entries(sit.idx, base["route"], len(base["route"]) - 1)
    assert holds
    cand = {**base, "id": "test:closure", "holds_plan": holds, "actions": [{"type": "closure"}]}
    res = run_candidate({**r["fork"], "candidate": cand, "run_dir": str(tmp_path / "hold")})
    assert res["junctions_held"] == len(holds) and res["hold_s_total"] > 0
    on = [e for e in res["event_log"] if e["action"] == "hold_on"]
    off = [e for e in res["event_log"] if e["action"] == "hold_off"]
    assert len(on) == len(off) == len(holds)


def test_explanations_cite_measured_values(rec: dict[str, Any]) -> None:
    r = rec["report"]
    res, ns = r["results"], r["results"][NO_STRATEGY_ID]
    for o in r["options"]:
        m = res[o["candidate_id"]]
        facts = o["facts"]
        nums = NUM.findall(re.sub(r"`[^`]*`", "", o["reason"]))
        assert set(nums) <= {f["text"] for f in facts.values()}, o["reason"]
        expect = {
            "tt_s": m["travel_time_s"],
            "ns_tt_s": ns["travel_time_s"],
            "horizon_s": r["horizon_s"],
            "added_veh_h": abs(o["added_veh_h"]),
            "signals": m["signals_preempted"],
            "rescue_edges": m["rescue_lane_edges"],
        }
        if ns["travel_time_s"] is not None and m["travel_time_s"] is not None:
            expect["gain_s"] = abs(ns["travel_time_s"] - m["travel_time_s"])
        if m["route_halted_max"]:
            expect["worst_halted"] = m["route_halted_max"][0]["halted"]
        for name, f in facts.items():
            if name in expect:
                assert f["value"] == pytest.approx(expect[name]), name
            elif name == "ns_edge_s":
                assert f["value"] in ns["ambulance_edge_s"].values()
            elif name == "opt_edge_s":
                assert f["value"] in m["ambulance_edge_s"].values()


def test_approve_logs_decision_and_matches_prediction(rec: dict[str, Any]) -> None:
    r, db = rec["report"], rec["db"]
    d = approve(r["recommendation_id"], option=1, actor="pytest", db=db, quiet=True)
    assert d["decision"] == "approved" and d["matches_prediction"]
    assert d["measured_travel_time_s"] == r["options"][0]["travel_time_s"]
    assert d["tripinfo_travel_time_s"] == d["measured_travel_time_s"]
    assert L.verify(db) == []
    last = L.records(db)[-1]
    assert last["kind"] == "decision" and last["actor"] == "pytest"
    assert json.loads(last["decision"])["recommendation_id"] == r["recommendation_id"]
    with pytest.raises(RuntimeError, match="already has a decision"):
        approve(r["recommendation_id"], db=db, quiet=True)


def test_reject_and_cli_smoke(rec: dict[str, Any]) -> None:
    from strategist.approve import app as approve_app
    from strategist.log import app as log_app
    from strategist.run import app as run_app

    root, db = rec["root"], rec["db"]
    runner = CliRunner()
    args = ["--scenario", "emergency_demo", "--seed", "1", "--db", str(db)]
    out = runner.invoke(run_app, [*args, "--runs-dir", str(root / "runs")])
    assert out.exit_code == 0, out.output
    assert "best beats no strategy: YES" in out.output and SYNTHETIC_LABEL in out.output
    rid = re.search(r"recommendation_id: (rec-\S+)", out.output).group(1)
    rej = runner.invoke(approve_app, [rid, "--option", "2", "--reject", "--db", str(db)])
    assert rej.exit_code == 0 and "REJECTED option 2" in rej.output
    assert json.loads(L.records(db)[-1]["decision"])["decision"] == "rejected"
    ok = runner.invoke(log_app, ["verify", "--db", str(db)])
    assert ok.exit_code == 0 and "chain intact" in ok.output
    assert runner.invoke(log_app, ["show", "--db", str(db)]).exit_code == 0
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER records_no_update")
    con.execute("UPDATE records SET actor = 'mallory' WHERE seq = 1")
    con.commit()
    con.close()
    bad = runner.invoke(log_app, ["verify", "--db", str(db)])
    assert bad.exit_code == 1 and "BROKEN" in bad.output
