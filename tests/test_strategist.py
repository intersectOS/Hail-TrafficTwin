"""M6 strategist units without SUMO runs: routing graph and candidates (demo net, sumolib),
ranking with weights, measured-only explanations, classification, decision log, register."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sim.scenarios import register as sim_register
from strategist import config as C
from strategist import decision_log as L
from strategist import register as reg
from strategist.candidates import (
    NO_STRATEGY_ID,
    edge_costs,
    k_routes,
    rescue_lanes,
    signal_groups,
)
from strategist.classify import APPROVAL, AUTO, classify_option
from strategist.explain import explain
from strategist.graph import EdgeGraph, overlap
from strategist.rank import rank
from strategist.situation import Situation, find_scenario, resolve_situation

NUM = re.compile(r"\d+(?:\.\d+)?")


@pytest.fixture(scope="module")
def sit() -> Situation:
    return resolve_situation("emergency_demo", None, 1)


def ff_costs(sit: Situation, graph: EdgeGraph) -> dict[str, float]:
    return edge_costs(sit, graph, {"mean_over_window": {}})


def test_scenario_lookup_prefers_strategist_dir() -> None:
    assert find_scenario("emergency_demo").parent.name == "scenarios"
    assert "strategist" in str(find_scenario("emergency_tahlia_0830"))
    assert "sim" in str(find_scenario("emergency_tahlia"))  # falls back to sim/scenarios


def test_situation_splits_strategist_trip(sit: Situation) -> None:
    assert sit.t_dispatch == 200 and sit.trip["strategist"]
    assert [p["type"] for p in sit.plans] == ["accident"]
    assert sit.closed_lanes_at(150) == set(sit.plans[0]["closed_lanes"])
    assert sit.closed_lanes_at(50) == set()
    assert sit.key() == resolve_situation("emergency_demo", None, 1).key()
    assert sit.key() != resolve_situation("emergency_demo", None, 2).key()


def test_yen_paths_are_loopless_unique_and_ordered(sit: Situation) -> None:
    g = EdgeGraph(sit.idx, "emergency")
    cost = ff_costs(sit, g)
    src, dst = sit.trip["route"][0], sit.trip["route"][-1]
    paths = []
    for p, c in g.yen(src, dst, cost):
        paths.append((p, c))
        if len(paths) == 8:
            break
    assert len(paths) == 8
    costs = [c for _, c in paths]
    assert costs == sorted(costs)
    assert len({tuple(p) for p, _ in paths}) == 8
    for p, c in paths:
        assert len(set(p)) == len(p) and g.is_path(p) and p[0] == src and p[-1] == dst
        assert c == pytest.approx(g.path_cost(p, cost))
    # the first Yen path is the free-flow fastest path, as the default route resolver gives
    assert paths[0][0] == sit.trip["route"]


def test_k_routes_are_diverse(sit: Situation) -> None:
    g = EdgeGraph(sit.idx, "emergency")
    routes, stats = k_routes(sit, g, ff_costs(sit, g))
    assert stats["routes_found"] == len(routes) == C.value("candidates", "k_routes")
    max_ov = C.value("candidates", "max_overlap")
    for i, r in enumerate(routes):
        for prev in routes[:i]:
            assert overlap(r["edges"], prev["edges"], g.length) <= max_ov
    assert [r["name"] for r in routes] == ["Route A", "Route B", "Route C"]
    assert routes[0]["is_default"]


def test_closed_edges_are_respected(sit: Situation) -> None:
    edge = sit.trip["route"][len(sit.trip["route"]) // 2]
    lanes = sit.idx.lane_ids(edge)
    full = EdgeGraph(sit.idx, "emergency", set(lanes))
    assert edge not in full
    routes, _ = k_routes(sit, full, ff_costs(sit, full))
    assert routes and all(edge not in r["edges"] for r in routes)
    if len(lanes) > 1:  # a partial closure keeps the edge, without the closed lane's links
        part = EdgeGraph(sit.idx, "emergency", {lanes[-1]})
        assert edge in part


def test_signal_groups_and_rescue_lanes(sit: Situation) -> None:
    tls_route = ["38500585#7", "1492421522#0"]
    (g,) = signal_groups(sit.idx, tls_route)
    assert g["tls"] == "GS_cluster_10109918119_4419972011" and g["links"] == [0, 1]
    assert g["first_idx"] == g["last_idx"] == 0
    rl = rescue_lanes(sit.idx, sit.trip["route"], set(), "emergency")
    for r in rl:
        e = sit.idx.edge(r["edge"])
        assert e.getLaneNumber() >= C.value("rescue_lane", "min_open_lanes")
        assert r["lane"] == f"{r['edge']}_{r['lane_index']}"
    # a closed lane is never reserved and an edge left with one open lane gets none
    closed = set(sit.plans[0]["closed_lanes"])
    rl_closed = rescue_lanes(sit.idx, sit.trip["route"], closed, "emergency")
    assert not {r["lane"] for r in rl_closed} & closed


def _res(tt: float | None, veh_h: float, **kw: Any) -> dict[str, Any]:
    base = {
        "arrived": tt is not None,
        "travel_time_s": tt,
        "free_flow_s": 50.0,
        "background_veh_h": veh_h,
        "junctions_held": 0,
        "signals_preempted": 0,
        "rescue_lane_edges": 0,
        "hold_s_total": 0.0,
        "route_halted_max": [],
        "ambulance_edge_s": {},
    }
    return {**base, **kw}


def _cands() -> list[dict[str, Any]]:
    mk = [
        (NO_STRATEGY_ID, "default route", []),
        ("A:reroute", "Route A", [{"type": "reroute"}]),
        ("B:preempt", "Route B", [{"type": "preempt"}]),
        ("B:preempt+closure", "Route B", [{"type": "preempt"}, {"type": "closure"}]),
        ("C:reroute", "Route C", [{"type": "reroute"}]),
    ]
    return [{"id": i, "route_name": n, "actions": a} for i, n, a in mk]


def test_rank_with_weights_and_distinct_routes() -> None:
    w = C.load_weights()["values"]
    results = {
        NO_STRATEGY_ID: _res(120, 10.0),
        "A:reroute": _res(90, 10.5),
        "B:preempt": _res(80, 11.0, signals_preempted=2),
        "B:preempt+closure": _res(70, 12.0, signals_preempted=2, junctions_held=3),
        "C:reroute": _res(None, 10.0),
    }
    out = rank(_cands(), results, w, horizon_s=300)
    sc = {s["candidate_id"]: s for s in out["scores"]}
    assert sc["B:preempt"]["score"] == pytest.approx(80 + 10 * 1.0 + 1 * 2)
    assert sc["B:preempt+closure"]["score"] == pytest.approx(70 + 10 * 2.0 + 5 * 3 + 2)
    assert sc["C:reroute"]["score"] == pytest.approx(2.0 * 300)  # not arrived: penalty
    top = [s["candidate_id"] for s in out["top"]]
    assert sc["A:reroute"]["score"] == pytest.approx(90 + 10 * 0.5)
    assert top == ["B:preempt", "A:reroute", "C:reroute"]  # distinct routes first
    assert [s["rank"] for s in out["top"]] == [1, 2, 3]
    assert NO_STRATEGY_ID not in top
    plain = rank(_cands(), results, w, 300, distinct_routes=False)
    assert [s["candidate_id"] for s in plain["top"]] == [
        "B:preempt",
        "A:reroute",
        "B:preempt+closure",
    ]
    # cheaper delay weight makes the closure option win
    cheap = rank(_cands(), results, {**w, "w_delay": 0.0, "w_closure": 0.0}, 300)
    assert cheap["top"][0]["candidate_id"] == "B:preempt+closure"


def test_weights_override_file(tmp_path: Path) -> None:
    f = tmp_path / "w.yaml"
    f.write_text("weights:\n  w_delay: 30\n")
    w = C.load_weights(f)
    assert w["values"]["w_delay"] == 30.0 and w["overrides"] == {"w_delay": 30.0}
    assert w["values"]["w_time"] == 1.0 and "A-strat-022" in w["ids"]
    f.write_text("weights:\n  w_bogus: 1\n")
    with pytest.raises(ValueError, match="unknown weights"):
        C.load_weights(f)


def test_classification() -> None:
    m = {"signals_preempted": 1}
    assert classify_option([{"type": "reroute"}], m, 0.1)["classification"] == AUTO
    assert classify_option([{"type": "preempt"}], m, 0.1)["classification"] == AUTO
    cl = classify_option([{"type": "preempt"}, {"type": "closure"}], m, 0.1)
    assert cl["classification"] == APPROVAL
    assert [a["class"] for a in cl["actions"]] == [AUTO, APPROVAL]
    big = C.value("classification", "auto_max_added_veh_h") + 0.5
    assert classify_option([{"type": "rescue_lane"}], m, big)["classification"] == APPROVAL
    assert classify_option([{"type": "reroute"}], m, big)["classification"] == AUTO
    many = {"signals_preempted": C.value("classification", "auto_max_signals") + 1}
    assert classify_option([{"type": "preempt"}], many, 0.0)["classification"] == APPROVAL


def numbers_outside_ids(text: str) -> list[str]:
    return NUM.findall(re.sub(r"`[^`]*`", "", text))


def test_explanation_uses_only_measured_numbers() -> None:
    ns_cand = {"route": ["a", "b", "x", "c"], "edge_ff_s": {"a": 5, "b": 5, "x": 4, "c": 5}}
    cand = {"label": "Route B + signal preemption", "route": ["a", "b", "y", "c"]}
    ns_res = _res(173, 27.5, ambulance_edge_s={"a": 6.0, "b": 7.0, "x": 77.0, "c": 6.0})
    res = _res(
        68,
        27.2,
        signals_preempted=1,
        rescue_lane_edges=7,
        route_halted_max=[{"edge": "44795819#35", "halted": 11, "t": 1900.0}],
    )
    ex = explain(cand, res, ns_cand, ns_res, -0.3, 300, {"x": 6})
    text, facts = ex["text"], ex["facts"]
    assert text.count(". ") == 1 and text.endswith(".")  # two sentences
    allowed = {f["text"] for f in facts.values()}
    assert set(numbers_outside_ids(text)) <= allowed
    assert facts["tt_s"]["value"] == 68 and facts["ns_tt_s"]["value"] == 173
    assert facts["gain_s"]["value"] == 105
    assert facts["ns_edge_s"]["value"] == 77.0 and facts["ns_edge_halted"]["value"] == 6
    assert facts["added_veh_h"]["text"] == "0.30" and "saves" in text
    assert facts["worst_halted"]["value"] == 11
    assert "avoids `x`" in text and "because" in text
    slower = explain(cand, _res(200, 27.5), ns_cand, ns_res, 0.0, 300, {})
    assert "because" not in slower["text"] and "slower" in slower["text"]
    assert set(numbers_outside_ids(slower["text"])) <= {f["text"] for f in slower["facts"].values()}


def test_decision_log_chain_and_append_only(tmp_path: Path) -> None:
    db = tmp_path / "log.sqlite"
    a = L.append(db, "recommendation", "snap1", [{"id": "x"}], [{"s": 1.5}], {"best": "x"})
    b = L.append(db, "decision", "snap1", ["x"], [], {"rid": a["record_id"]}, {"decision": "ok"})
    c = L.append(db, "recommendation", "snap2", [], [], {})
    assert b["prev_hash"] == a["hash"] and c["prev_hash"] == b["hash"]
    assert a["prev_hash"] == L.GENESIS and L.verify(db) == []
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE records SET actor = 'mallory' WHERE seq = 1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM records WHERE seq = 2")
    con.close()
    with pytest.raises(ValueError):
        L.append(db, "gossip", "s", [], [], {})


def test_decision_log_tampering_is_detected(tmp_path: Path) -> None:
    db = tmp_path / "log.sqlite"
    for i in range(3):
        L.append(db, "recommendation", f"snap{i}", [], [{"score": i}], {"i": i})
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER records_no_update")
    con.execute("UPDATE records SET scores = '[{\"score\":99}]' WHERE seq = 2")
    con.commit()
    con.close()
    problems = L.verify(db)
    assert any("records_no_update is missing" in p for p in problems)
    assert any("seq 2" in p and "hash mismatch" in p for p in problems)
    # deleting a middle record breaks the prev_hash link of the next one
    db2 = tmp_path / "log2.sqlite"
    for i in range(3):
        L.append(db2, "recommendation", f"snap{i}", [], [], {"i": i})
    con = sqlite3.connect(db2)
    con.execute("DROP TRIGGER records_no_delete")
    con.execute("DELETE FROM records WHERE seq = 2")
    con.commit()
    con.close()
    assert any("seq 3" in p and "prev_hash" in p for p in L.verify(db2))
    assert L.verify(tmp_path / "missing.sqlite")


def test_register_block_current_and_ids_unique() -> None:
    assert reg.is_current(), "run: python -m strategist.register"
    ids = reg.ids()
    # integration (B-D-024): the strategist rows are also generated into the Track B register
    assert ids and ids <= sim_register.all_ids()
    assert set(C.setting_ids()) | set(C.load_weights()["ids"]) == ids
    text = reg.DOC.read_text()
    for pid in ids:
        assert f"| {pid} |" in text


def test_action_named_as_cause_only_with_measured_own_gain() -> None:
    ns_cand = {"route": ["a", "x"], "edge_ff_s": {"a": 5, "x": 4}}
    cand = {"label": "Route A + rescue lane", "route": ["a", "y"]}
    ns_res = _res(173, 27.5, ambulance_edge_s={"a": 6.0, "x": 77.0})
    res = _res(68, 27.2, rescue_lane_edges=7)
    # route without the lane measured 70 s: the lane's own 2 s is a measured cause
    ex = explain(cand, res, ns_cand, ns_res, 0.0, 300, {}, {"rescue_lane": _res(70, 27.2)})
    assert "the rescue lane on 7 edges saves 2 s" in ex["text"]
    assert ex["facts"]["rescue_edges_own_s"]["value"] == 2
    # same route without the lane was as fast: stated, not claimed as a cause
    ex = explain(cand, res, ns_cand, ns_res, 0.0, 300, {}, {"rescue_lane": _res(68, 27.2)})
    assert "it also reserves a rescue lane on 7 edges" in ex["text"]
    assert "saves 2 s" not in ex["text"]
    assert set(numbers_outside_ids(ex["text"])) <= {f["text"] for f in ex["facts"].values()}
