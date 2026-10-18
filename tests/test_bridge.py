"""Track J (Obhur bridge) tests on synthetic geometry: policy schema, link insertion, SCC
membership, through-routes, combined edits, the creek-crossing test, the detour graph and the
window demand replication. Fast; no city or window data needed."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon

import sim.bridge.network as BN
import sim.loop.network as LN
import sim.policies.edges as E
from sim.bridge.desire import Graph
from sim.bridge.geo import crosses, edges_in, window_polygon
from sim.bridge.network import (
    build_bridge_net,
    check_variant,
    connected_edges,
    span_id,
)
from sim.bridge.schema import (
    BridgeNetworkChange,
    BridgePolicy,
    bridge_config,
    bridge_transform,
    load_bridge_policy,
)
from sim.common import run_cmd, sumo_bin

POLICIES = [f"obhur_bridge_b{k}{s}" for k in (1, 2, 3) for s in ("", "_3x3")]

# Two banks 1.1 km apart (south road at 21.700 N, north road at 21.710 N), joined only at the
# east end (lon 39.130): the "head" of a synthetic creek between 21.702 and 21.708 N.
NODES = {
    "s0": (39.100, 21.700), "s1": (39.110, 21.700), "s2": (39.120, 21.700), "s3": (39.130, 21.700),
    "n0": (39.100, 21.710), "n1": (39.110, 21.710), "n2": (39.120, 21.710), "n3": (39.130, 21.710),
    "f1": (39.110, 21.695),
}  # fmt: skip
ROADS = [("s0", "s1"), ("s1", "s2"), ("s2", "s3"), ("n0", "n1"), ("n1", "n2"), ("n2", "n3"),
         ("s3", "n3")]  # fmt: skip
CREEK = Polygon([(39.095, 21.702), (39.128, 21.702), (39.128, 21.708), (39.095, 21.708)])


def crossing(lanes: int = 2, bid: str = "x1") -> dict:
    return {
        "id": bid, "name": "Test bridge", "lanes": lanes, "speed_kmh": 80,
        "approach_speed_kmh": 60, "navigation": "n/a", "source_note": "test",
        "south": {"name": "south", "abutment": [39.110, 21.7015], "connect": [[39.110, 21.700]]},
        "north": {"name": "north", "abutment": [39.110, 21.7085], "connect": [[39.110, 21.710]]},
    }  # fmt: skip


def transform(**kw: object) -> BridgeNetworkChange:
    return BridgeNetworkChange.model_validate(
        {"type": "network_change", "bridges": [crossing()], "assumption": "test", **kw}
    )


@pytest.fixture(autouse=True)
def caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for mod in (E, LN, BN):
        monkeypatch.setattr(mod, "CACHE", tmp_path / "cache")


@pytest.fixture(scope="module")
def banks(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic two-bank network (UTM 37N from lon/lat plain nodes)."""
    d = tmp_path_factory.mktemp("banks")
    nod = ["<nodes>"] + [f'  <node id="{k}" x="{x}" y="{y}"/>' for k, (x, y) in NODES.items()]
    edg = ["<edges>"]
    for a, b in ROADS:
        for f, t in ((a, b), (b, a)):
            edg.append(f'  <edge id="{f}{t}" from="{f}" to="{t}" type="highway.secondary"/>')
    edg += ['  <edge id="f1s1" from="f1" to="s1" type="highway.residential"/>',
            '  <edge id="s1f1" from="s1" to="f1" type="highway.residential"/>']  # fmt: skip
    typ = ['<types>',
           '  <type id="highway.secondary" numLanes="2" speed="13.89" priority="11"/>',
           '  <type id="highway.residential" numLanes="1" speed="8.33" priority="4"/>',
           '</types>']  # fmt: skip
    for name, lines in (("n.nod.xml", nod + ["</nodes>"]), ("n.edg.xml", edg + ["</edges>"]),
                        ("n.typ.xml", typ)):  # fmt: skip
        (d / name).write_text("\n".join(lines) + "\n")
    net = d / "banks.net.xml"
    run_cmd([sumo_bin("netconvert"), "-n", str(d / "n.nod.xml"), "-e", str(d / "n.edg.xml"),
             "-t", str(d / "n.typ.xml"), "--proj.utm", "true", "--no-turnarounds", "true",
             "-o", str(net)])  # fmt: skip
    return net


def connections(net: Path) -> set[tuple[str, str]]:
    opener = gzip.open if str(net).endswith(".gz") else open
    with opener(net, "rb") as fh:
        return {(c.get("from", ""), c.get("to", "")) for _, c in ET.iterparse(fh)
                if c.tag == "connection" and not c.get("from", "").startswith(":")}  # fmt: skip


# ---------------------------------------------------------------------------- schema


@pytest.mark.parametrize("pid", POLICIES)
def test_obhur_policies_validate(pid: str) -> None:
    pol = load_bridge_policy(pid)
    t = bridge_transform(pol)
    assert t is not None and t.type == "network_change"
    lanes = 3 if pid.endswith("_3x3") else 2
    want = {"b1": ["b1"], "b2": ["b2"], "b3": ["b1", "b2"]}[pid.split("_")[2]]
    assert [b.id for b in t.bridges] == want and {b.lanes for b in t.bridges} == {lanes}
    assert t.assumption and "A-obh-003" in t.assumption
    for b in t.bridges:
        assert 60 <= b.approach_speed_kmh <= b.speed_kmh <= 80


def test_schema_rules() -> None:
    assert transform().bridges[0].id == "x1"  # a bridge alone is a valid network_change
    with pytest.raises(ValidationError):  # nothing to do
        BridgeNetworkChange.model_validate({"type": "network_change", "assumption": "t"})
    with pytest.raises(ValidationError):  # provenance required
        BridgeNetworkChange.model_validate({"type": "network_change", "bridges": [crossing()]})
    with pytest.raises(ValidationError):  # duplicate ids
        transform(bridges=[crossing(), crossing()])
    with pytest.raises(ValidationError):  # lanes per direction 1..6
        transform(bridges=[crossing(lanes=0)])
    with pytest.raises(ValidationError):  # one network_change per policy (Track A rule)
        nc = {"type": "network_change", "bridges": [crossing()], "assumption": "t"}
        BridgePolicy.model_validate({"id": "p", "kind": "policy", "title": "p",
                                     "daytype": "weekday", "transforms": [nc, nc]})  # fmt: skip


# ---------------------------------------------------------------------------- network


def test_link_insertion_geometry_and_scc(banks: Path, tmp_path: Path) -> None:
    t = transform()
    variant, info, new = build_bridge_net(banks, t, tmp_path)
    assert variant.exists() and variant.parent == tmp_path  # not a city net: work dir
    ids = set(new["edge_id"])
    assert {span_id("x1", "S"), span_id("x1", "N")} <= ids and len(ids) == 6
    var_edges = E.load_edges(variant).set_index("edge_id")
    span = var_edges.loc[span_id("x1", "S")]
    assert span["lanes"] == 2 and span["speed"] == pytest.approx(80 / 3.6, rel=1e-3)
    # 7 thousandths of a degree of latitude between the abutments: ~774 m
    assert span["length"] == pytest.approx(774, abs=10)
    assert info["span_m"]["x1"] == pytest.approx(774, abs=10)
    land = pd.DataFrame(info["landings"]).set_index("side")
    assert land.loc["S", "node"] == "s1" and land.loc["N", "node"] == "n1"
    assert land["snap_m"].max() < 1.0
    # every passenger edge into a landing junction can turn onto the bridge
    con = connections(variant)
    assert {("s0s1", "obh_x1_S0i"), ("s2s1", "obh_x1_S0i"), ("f1s1", "obh_x1_S0i"),
            ("n0n1", "obh_x1_N0i"), ("n2n1", "obh_x1_N0i")} <= con  # fmt: skip
    chk = check_variant(banks, variant, new, tmp_path)
    assert chk["ok"] and chk["in_main_scc"] == 6 and chk["not_in_main_scc"] == []
    assert chk["through_routes"] == {"x1_SN": True, "x1_NS": True}


def test_unconnected_bridge_fails_the_scc_check(banks: Path, tmp_path: Path) -> None:
    """Without the connection patch the base edges keep their loaded connections: no way in."""
    t = transform()
    variant, _, new = build_bridge_net(banks, t, tmp_path)
    base_scc = connected_edges(banks, bridge_config())
    member = BN.scc_membership(variant, set(new["edge_id"]), base_scc)
    assert all(member.values())
    member_cut = BN.scc_membership(variant, set(new["edge_id"]), set())  # nothing to reach
    assert not any(member_cut.values())


def test_bridge_and_closure_in_one_patch(banks: Path, tmp_path: Path) -> None:
    t = transform(edits=[{"edges": ["s3n3", "n3s3"], "closed": True}])
    variant, info, _ = build_bridge_net(banks, t, tmp_path)
    ids = set(E.load_edges(variant)["edge_id"])
    assert "s3n3" not in ids and "n3s3" not in ids and "obh_x1_SN" in ids
    assert info["closed_edges"] == ["n3s3", "s3n3"]
    con = connections(variant)
    assert ("s0s1", "obh_x1_S0i") in con


def test_variant_reused_and_keyed_by_patch(banks: Path, tmp_path: Path) -> None:
    a, _, _ = build_bridge_net(banks, transform(), tmp_path)
    mtime = a.stat().st_mtime_ns
    b, _, _ = build_bridge_net(banks, transform(), tmp_path)
    assert a == b and b.stat().st_mtime_ns == mtime
    c, _, _ = build_bridge_net(banks, transform(bridges=[crossing(lanes=3)]), tmp_path)
    assert c != a


def test_snap_too_far_raises(banks: Path, tmp_path: Path) -> None:
    far = crossing()
    far["north"]["connect"] = [[39.105, 21.716]]  # ~700 m from any junction
    with pytest.raises(ValueError, match="no arterial junction within"):
        build_bridge_net(banks, transform(bridges=[far]), tmp_path)


# ---------------------------------------------------------------------------- geometry / detours


def test_creek_crossing_test() -> None:
    o_lon = np.array([39.110, 39.100, 39.110, 39.129, np.nan])
    o_lat = np.array([21.700, 21.700, 21.705, 21.700, 21.700])
    d_lon = np.array([39.110, 39.120, 39.110, 39.135, 39.110])
    d_lat = np.array([21.710, 21.700, 21.710, 21.710, 21.710])
    got = crosses(o_lon, o_lat, d_lon, d_lat, CREEK)
    # across / along the bank / starts in the water / east of the head / unknown edge
    assert got.tolist() == [True, False, False, False, False]


def test_window_polygon_holds_both_crossings() -> None:
    poly = window_polygon("obhur_creek")
    assert poly.is_valid and 0.002 < poly.area < 0.004  # ~30 km2 in square degrees at 21.7 N
    t = bridge_transform(load_bridge_policy("obhur_bridge_b3"))
    assert t is not None
    for b in t.bridges:
        for land in (b.south, b.north):
            for lon, lat in [land.abutment, *land.connect]:
                assert poly.contains(Polygon([(lon, lat), (lon + 1e-6, lat), (lon, lat + 1e-6)]))
    edges = pd.DataFrame({"edge_id": ["in", "out"], "lon": [39.12, 39.30], "lat": [21.74, 21.74]})
    assert edges_in(edges, poly) == {"in"}


def test_detour_graph(banks: Path) -> None:
    edges = E.load_edges(banks)
    g = Graph(edges)
    s0, n0 = g.ix(["s0", "n0"])
    d = g.sssp(int(s0))
    # around the head: 3 km east, 1.1 km north, 3 km west
    assert d[n0] == pytest.approx(3 * 1034 + 1107 + 3 * 1034, rel=0.02)
    r = g.sssp(int(n0), reverse=True)
    assert r[s0] == pytest.approx(d[n0])
    t = g.sssp(int(s0), "time")
    assert t[n0] == pytest.approx(d[n0] / 13.89, rel=0.02)


def test_replicate_copies_and_jitter(tmp_path: Path) -> None:
    from sim.bridge.window import replicate

    cut = tmp_path / "cut.rou.xml"
    cut.write_text(
        '<routes>\n<vehicle id="a" type="car" depart="100.00"><route edges="e1 e2"/></vehicle>\n'
        '<vehicle id="b" type="car" depart="5000.00"><route edges="e2"/></vehicle>\n</routes>\n'
    )
    out = tmp_path / "d.rou.xml"
    n = replicate(cut, out, 10, 150.0, (0.0, 3600.0), seed=1)
    assert n == 10  # b departs outside the span
    deps = [float(v.get("depart")) for _, v in ET.iterparse(out) if v.tag == "vehicle"]
    assert deps == sorted(deps) and all(0.0 <= x <= 250.0 for x in deps)
    out2 = tmp_path / "d2.rou.xml"
    replicate(cut, out2, 10, 150.0, (0.0, 3600.0), seed=1)
    assert out.read_text() == out2.read_text()  # seeded


def test_matched_control_on_synthetic_banks(
    banks: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same trips, same weights: re-routed without (control) and with the bridge; the bridge run
    uses the span and is faster per vehicle (paired by id)."""
    import sim.bridge.window as W
    from sim.population.export_trips import vtype_lines

    cfg = {**bridge_config()["window"], "warmup_s": 0, "cooldown_s": 600,
           "peaks": {"am": {"begin": "00:00", "end": "00:10"}}}  # fmt: skip
    monkeypatch.setattr(W, "wcfg", lambda: cfg)
    demand = tmp_path / "demand.rou.xml"
    veh = [f'  <vehicle id="v{i}" type="car" depart="{10 * i}"><route edges="s0s1 s1s2 s2s3 s3n3 '
           f'n3n2 n2n1 n1n0"/></vehicle>' for i in range(20)]  # fmt: skip
    demand.write_text("<routes>\n" + "\n".join(vtype_lines(1.0) + veh) + "\n</routes>\n")
    weights = tmp_path / "weights.xml"
    weights.write_text("<meandata/>\n")
    variant, _, _ = build_bridge_net(banks, transform(), tmp_path / "nets")
    out = {}
    for name, net in (("control", banks), ("bridge", variant)):
        d = tmp_path / name
        d.mkdir()
        info = W.reroute(net, demand, weights, d / "routes.rou.xml")
        assert info["routed"] == 20
        meta = W.simulate(net, d / "routes.rou.xml", d, "am", 1, {"run": name})
        assert meta["tier"] == "B" and meta["network_hash"]
        out[name] = pd.read_parquet(d / "tripinfo.parquet").set_index("veh_id")
        if name == "bridge":
            assert "obh_x1_SN" in (d / "routes.rou.xml").read_text()
    both = out["bridge"].join(out["control"], rsuffix="_c", how="inner")
    assert len(both) == 20
    assert (both["route_m"] < both["route_m_c"] - 4000).all()  # ~7.3 km around vs ~3.2 km over
    assert (both["duration"] < both["duration_c"]).all()
