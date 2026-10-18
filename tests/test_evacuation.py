"""M7 evacuation, static parts on the demo window: spec validation, zone origins, exits, path
trees, sampling determinism, assignment, phased release, contraflow corridors and the net edit,
strategist scoring / classification, and the generated register block. No SUMO run here."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sim.common import REPO_ROOT, load_yaml
from sim.events import evacuation as V
from sim.events.netindex import NetIndex
from sim.scenarios.schema import Scenario
from strategist import evacuation as S

ZONE = [[39.1535, 21.5475], [39.1595, 21.5475], [39.1595, 21.5525], [39.1535, 21.5525]]
SPEC = {"type": "evacuation", "id": "t", "start": 300, "zone": ZONE, "vehicles": 120}
# a two-way edge pair on the demo window (same nodes) used as a synthetic contraflow corridor
CF_EDGE, CF_PARTNER = "48364777#2", "-48364777#2"


@pytest.fixture(scope="module")
def idx(demo_net: Path) -> NetIndex:
    return NetIndex(demo_net)


@pytest.fixture(scope="module")
def ana(idx: NetIndex) -> dict[str, Any]:
    spec = V.EvacSpec.model_validate({**SPEC, "exit_count": 4, "assumption": "test"})
    return V.analyse(spec, idx, seed=1)


def spec(**kw: Any) -> V.EvacSpec:
    return V.EvacSpec.model_validate({**SPEC, **kw})


def plan(ana: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return V.resolve(spec(**kw), ana, 1, 0.0, {"normal": 0.8, "slow": 0.2}, {}, 1500.0)


# --- spec ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        {"zone": ZONE[:2]},
        {"vehicles": 0},
        {"zone": [[200, 21.5], [39.1, 21.5], [39.2, 21.6]]},
        {"release_s": 600},  # behavioural override without source/assumption
        {"phasing": "random"},
        {"signal_plan": "green_wave"},
        {"unknown": 1},
    ],
)
def test_spec_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        spec(**bad)


def test_spec_override_with_assumption() -> None:
    s = spec(release_s=600, assumption="test")
    assert s.release_s == 600


@pytest.mark.parametrize("name", ["evac_demo", "evac_obhur", "evac_flood_balad"])
def test_shipped_evacuation_scenarios(name: str) -> None:
    path = REPO_ROOT / "sim" / "scenarios" / f"{name}.yaml"
    Scenario.model_validate(load_yaml(path))  # the M5 schema accepts them
    scen, s = V.load(path)
    assert scen.fictional and s.type == "evacuation"
    assert scen.begin <= s.start < scen.end


def test_load_requires_fictional(tmp_path: Path) -> None:
    raw = load_yaml(REPO_ROOT / "sim" / "scenarios" / "evac_demo.yaml")
    raw["fictional"] = False
    p = tmp_path / "x.yaml"
    import yaml

    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="fictional"):
        V.load(p)


# --- geometry and analysis ----------------------------------------------------------------------
def test_point_in_polygon_and_area() -> None:
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert V.point_in_polygon(5, 5, sq) and not V.point_in_polygon(11, 5, sq)
    assert V.polygon_area(sq) == 100.0


def test_origins_inside_zone(idx: NetIndex) -> None:
    en = V.EvacNet(idx, [tuple(p) for p in ZONE])
    origins = en.origins()
    assert origins
    for eid, w in origins:
        assert V.point_in_polygon(*V._mid(idx.edge(eid)), en.zone)
        assert w > 0 and idx.edge(eid).allows("passenger")


def test_exits_are_fringe_far_and_apart(idx: NetIndex, ana: dict[str, Any]) -> None:
    en = V.EvacNet(idx, [tuple(p) for p in ZONE])
    ends = []
    for x in ana["exits"]:
        e = idx.edge(x["edge"])
        assert not e.getAllowedOutgoing("passenger")
        end = e.getShape()[-1]
        assert en.zone_distance(*end) >= V.value("exits", "min_distance_m")
        assert x["lanes"] * x["speed_ms"] >= V.value("exits", "min_capacity")
        ends.append(end)
    for i, a in enumerate(ends):
        for b in ends[i + 1 :]:
            assert math.dist(a, b) >= V.value("exits", "min_spacing_m")


def test_tree_paths_connected_and_shortest(idx: NetIndex, ana: dict[str, Any]) -> None:
    for o in sorted(set(ana["sampled"]))[:20]:
        for x, t in ana["reach"][o].items():
            path = V.EvacNet.path(o, x, ana["trees"][x])
            assert path[0] == o and path[-1] == x
            idx.check_route(path, "passenger")
            assert sum(V.free_flow_s(idx.edge(e)) for e in path) == pytest.approx(t)


def test_sampling_is_seeded(idx: NetIndex, ana: dict[str, Any]) -> None:
    s = V.EvacSpec.model_validate({**SPEC, "exit_count": 4, "assumption": "test"})
    again = V.analyse(s, idx, seed=1)
    other = V.analyse(s, idx, seed=2)
    assert again["sampled"] == ana["sampled"] and len(ana["sampled"]) == SPEC["vehicles"]
    assert other["sampled"] != ana["sampled"]


# --- plan ---------------------------------------------------------------------------------------
def test_plan_vehicles_and_release(ana: dict[str, Any]) -> None:
    p = plan(ana)
    ids = [v[0] for v in p["vehicles"]]
    assert len(set(ids)) == SPEC["vehicles"] and all(i.startswith("ev.t.") for i in ids)
    release = V.value("event", "release_s")
    assert all(300 <= v[2] < 300 + release for v in p["vehicles"])
    assert set(p["routes"]) == {v[1] for v in p["vehicles"]}
    assert p["start"] == 0.0 and p["order_t"] == 300.0
    assert {v[5] for v in p["vehicles"]} <= {"normal", "slow"}


def test_evacuee_types_are_cars() -> None:
    from sim.vtypes.loader import load_library, resolve_mix

    lib = load_library()
    t = V.evacuee_types(resolve_mix(None, lib), lib)
    assert t and all(lib.types[n].vClass == "passenger" for n in t)
    assert sum(t.values()) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.parametrize("order", ["near_first", "far_first"])
def test_phased_release_order(ana: dict[str, Any], order: str) -> None:
    p = plan(ana, phasing=order)
    k = V.value("phasing", "sectors")
    bands = sorted({v[3] for v in p["vehicles"]})
    assert bands == list(range(k))
    window = {b: [v[2] for v in p["vehicles"] if v[3] == b] for b in bands}
    seq = bands if order == "near_first" else bands[::-1]
    for a, b in zip(seq, seq[1:], strict=False):
        assert max(window[a]) < min(window[b])
    # same overall release window as a simultaneous release
    assert all(300 <= v[2] < 300 + V.value("event", "release_s") for v in p["vehicles"])


def test_balanced_assignment_respects_detour(ana: dict[str, Any]) -> None:
    p = plan(ana, exit_assignment="balanced")
    factor = V.value("assignment", "balanced_max_detour")
    for v, o in zip(p["vehicles"], ana["sampled"], strict=True):
        x = v[4]
        best = min(ana["reach"][o].values())
        assert ana["reach"][o][x] <= factor * best + 1e-9
    near = plan(ana)
    assert p["exit_assignment"] == "balanced" and near["exit_assignment"] == "nearest"


def test_unknown_contraflow_exit_rejected(ana: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="no contraflow corridor"):
        plan(ana, contraflow=["nope"])


def test_reference_plan_has_no_evacuees(ana: dict[str, Any]) -> None:
    r = V.reference_plan(plan(ana))
    assert r["reference"] and not r["vehicles"] and not r["contraflow"]


# --- contraflow ---------------------------------------------------------------------------------
def synthetic_corridor(idx: NetIndex) -> dict[str, Any]:
    e = idx.edge(CF_EDGE)
    pred = sorted(i.getID() for i in e.getIncoming() if i.getID() != CF_PARTNER)[0]
    succ = sorted(o.getID() for o in e.getOutgoing() if o.getID() != CF_PARTNER)[0]
    return {
        "id": "cf1",
        "exit": succ,
        "edges": [
            {"edge": CF_EDGE, "base_lanes": e.getLaneNumber(), "added": 1, "partners": [CF_PARTNER]}
        ],
        "pred": pred,
        "succ": succ,
        "length_m": round(e.getLength(), 1),
        "lane_km": round(e.getLength() / 1000, 3),
        "name": "test",
        "inbound_edges": [CF_PARTNER],
        "partner_coverage": 1.0,
    }


def test_partners_same_nodes(idx: NetIndex) -> None:
    en = V.EvacNet(idx, [tuple(p) for p in ZONE])
    assert en.partners(CF_EDGE) == [CF_PARTNER]


def test_corridor_patch_lanes_and_connections(idx: NetIndex) -> None:
    c = synthetic_corridor(idx)
    edg, con = V.corridor_patch([c])
    root = ET.fromstring(edg)
    assert root.find("edge").get("numLanes") == str(c["edges"][0]["base_lanes"] + 1)
    cons = ET.fromstring(con).findall("connection")
    assert {(x.get("from"), x.get("to")) for x in cons} == {
        (c["pred"], CF_EDGE),
        (CF_EDGE, c["succ"]),
    }


def test_build_evac_net(idx: NetIndex, demo_net: Path, tmp_path: Path) -> None:
    c = synthetic_corridor(idx)
    r = V.build_evac_net("demo", demo_net, demo_net, [], [c], idx, out_dir=tmp_path)
    assert r["built"] and Path(r["net"]).exists()
    new = NetIndex(Path(r["net"]))
    base = c["edges"][0]["base_lanes"]
    e = new.edge(CF_EDGE)
    assert e.getLaneNumber() == base + 1
    added = e.getLanes()[base]
    assert added.getIncoming(), "reversed lane reachable from the corridor's predecessor"
    assert any(conn.getFromLane() == added for conn in e.getOutgoing()[new.edge(c["succ"])])
    assert new.edge(CF_PARTNER).getLaneNumber() == idx.edge(CF_PARTNER).getLaneNumber()
    again = V.build_evac_net("demo", demo_net, demo_net, [], [c], idx, out_dir=tmp_path)
    assert not again["built"] and again["key"] == r["key"]  # cached
    none = V.build_evac_net("demo", demo_net, demo_net, [], [], idx, out_dir=tmp_path)
    assert none["net"] == demo_net


# --- metrics ------------------------------------------------------------------------------------
def test_clearance_quantiles() -> None:
    summ = {
        "vehicles": 10,
        "order_t": 100.0,
        "arrival_times": [110.0 + 10 * i for i in range(10)],
        "depart_times": [100.0 + i for i in range(10)],
        "max_insertion_backlog": 0,
    }
    c = V.clearance(summ, 1000.0)
    assert (c["t50_s"], c["t90_s"], c["t100_s"]) == (50.0, 90.0, 100.0)
    summ["arrival_times"] = summ["arrival_times"][:8]
    c = V.clearance(summ, 1000.0)
    assert c["t90_s"] is None and c["t100_s"] is None and c["out_share"] == 0.8
    assert V.effective(c, "t90_s") == V.value("clearance", "not_cleared_factor") * 900.0


# --- strategist pieces --------------------------------------------------------------------------
def fake(t90: float, t100: float, delay: float, signals: int = 0) -> dict[str, Any]:
    return {
        "clearance": {"t50_s": t90 / 2, "t90_s": t90, "t100_s": t100, "horizon_s": 3000.0},
        "background": {"delay_veh_h": delay},
        "signals_retimed": ["x"] * signals,
    }


def cand(cid: str, **strategy: Any) -> dict[str, Any]:
    base = {"phasing": "simultaneous", "exit_assignment": "nearest", "contraflow": [],
            "signal_plan": "default"}  # fmt: skip
    st = {**base, **strategy}
    cors = [{"id": "cf1", "exit": "x1", "lane_km": 2.0}]
    return {"id": cid, "label": cid, "strategy": st, "actions": S.actions(st, base, cors),
            "equivalent_strategies": []}  # fmt: skip


def test_score_and_rank() -> None:
    cands = [
        S_no := cand(S.NO_STRATEGY),
        cand("balanced", exit_assignment="balanced"),
        cand("contraflow", contraflow=["x1"]),
        cand("near_first", phasing="near_first"),
    ]
    res = {
        S.NO_STRATEGY: fake(1000, 1400, 50.0),
        "balanced": fake(800, 1200, 51.0),
        "contraflow": fake(700, 1100, 60.0),
        "near_first": fake(990, 1400, 50.0),
    }
    w = S.weights()
    ranked = S.rank(cands, res, w, 3)
    by = {r["candidate_id"]: r for r in ranked}
    assert by[S.NO_STRATEGY]["rank"] is None and by[S.NO_STRATEGY]["added_veh_h"] == 0
    exp = w["w_t90"] * 700 + w["w_t100"] * 1100 + w["w_delay"] * 10.0 + w["w_contraflow"] * 2.0
    assert by["contraflow"]["score"] == pytest.approx(exp)
    staged = (V.value("phasing", "sectors") - 1) * w["w_order"]
    assert by["near_first"]["terms"]["orders"] == pytest.approx(staged)
    ranks = [r["candidate_id"] for r in ranked if r["rank"]]
    assert ranks == sorted(ranks, key=lambda c: by[c]["score"])
    assert S_no["actions"] == []


def test_classification() -> None:
    limit = V.value("strategy", "auto_max_added_veh_h")
    assert S.classify(cand("b", exit_assignment="balanced"), 0.1)["classification"] == S.AUTO
    assert S.classify(cand("b", exit_assignment="balanced"), limit + 1)["classification"] == (
        S.APPROVAL
    )
    assert S.classify(cand("s", signal_plan="evacuation"), 0.0)["classification"] == S.AUTO
    assert S.classify(cand("c", contraflow=["x1"]), -5.0)["classification"] == S.APPROVAL
    assert S.classify(cand("p", phasing="far_first"), 0.0)["classification"] == S.APPROVAL
    assert S.classify(cand(S.NO_STRATEGY), 0.0)["classification"] == "none"


def test_explanation_names_cause_only_when_measured() -> None:
    cands = [cand(S.NO_STRATEGY), cand("balanced", exit_assignment="balanced"),
             cand("both", exit_assignment="balanced", contraflow=["x1"])]  # fmt: skip
    res = {
        S.NO_STRATEGY: fake(1000, 1400, 50.0),
        "balanced": fake(800, 1200, 50.0),
        "both": fake(700, 1100, 52.0),
    }
    for r in res.values():
        r.update({"contraflow_lanes_opened": 0, "signals_retimed": [], "bottlenecks": []})
    scores = {r["candidate_id"]: r for r in S.rank(cands, res, S.weights(), 3)}
    base = cands[0]["strategy"]
    text = " ".join(S.explain(cands[2], cands, res, scores, base))
    assert "Because of contraflow" in text and "100 s slower" in text
    solo = " ".join(S.explain(cands[1], cands, res, scores, base))
    assert "Because of balanced exit guidance" in solo and "200 s slower" in solo


# --- register -----------------------------------------------------------------------------------
def test_register_block_current() -> None:
    assert V.register_current(), "run: python -m sim.events.evacuation register"


def test_registered_ids_unique_and_sourced() -> None:
    ids = [p.id for _, p in V.registered()]
    assert len(ids) == len(set(ids)) and all(i.startswith("A-evac-") for i in ids)
    assert all(p.source or p.assumption for _, p in V.registered())


def test_corridors_avoid_zone_edges() -> None:
    """Contraflow must not close or reverse an edge evacuees start on (B-D-034)."""
    from sim.scenarios.run import window_inputs

    _, s = V.load("evac_obhur")
    try:
        net, _, _ = window_inputs("obhur")
    except FileNotFoundError:
        pytest.skip("obhur window not built (gitignored data)")
    idx = NetIndex(net)
    ana = V.analyse(s, idx, seed=1)
    zone = {o for o, _ in V.EvacNet(idx, s.zone).origins()}
    assert ana["corridors"]
    for c in ana["corridors"]:
        assert not zone & set(c["inbound_edges"])
        assert not zone & {e["edge"] for e in c["edges"]}
