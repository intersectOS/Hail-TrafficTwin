"""Track D unit tests (fast, demo window): Loop schema, parameters, tunnel network build, shuttle
generation, capacity flags, run naming and the siting geometry."""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import sim.policies.edges as E
from sim.common import REPO_ROOT
from sim.loop.evaluate import defaults, eval_id, make_policy
from sim.loop.network import build_loop_net, meso_types_file, shuttle_route
from sim.loop.params import capacity_figures, resolve_params
from sim.loop.schema import LoopPolicy, LoopShuttle, load_loop_policy, loop_config, loop_transform
from sim.loop.transforms import capacity_flags, nearest_station, shuttles
from sim.metrics import xml_content_hash

DEMO_NET = REPO_ROOT / "data" / "demo" / "demo.net.xml"
STATIONS = [
    {"name": "south-west", "lon": 39.1500, "lat": 21.5440},
    {"name": "centre", "lon": 39.1571, "lat": 21.5505},
    {"name": "north-east", "lon": 39.1640, "lat": 21.5560},
]


@pytest.fixture(autouse=True)
def edge_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(E, "CACHE", tmp_path / "edges")
    import sim.loop.network as N

    monkeypatch.setattr(N, "CACHE", tmp_path / "edges")


def test_demo_policies_validate() -> None:
    for name in ("loop_demo", "loop_demo_private"):
        pol = load_loop_policy(name)
        t = loop_transform(pol)
        assert t is not None and len(t.alignments[0].stations) == 3
        assert t.assumption and "A-loop-016" in t.assumption


def test_schema_rejects_bad_policies() -> None:
    a = {"id": "x", "stations": STATIONS}
    with pytest.raises(ValidationError):  # two loop transforms
        two = [{"type": "loop_shuttle", "alignments": [a], "assumption": "t"},
               {"type": "loop_private", "alignments": [a], "assumption": "t"}]  # fmt: skip
        LoopPolicy.model_validate({"id": "p", "kind": "policy", "title": "p",
                                   "daytype": "weekday", "transforms": two})  # fmt: skip
    with pytest.raises(ValidationError):  # duplicate alignment ids
        LoopShuttle.model_validate({"type": "loop_shuttle", "alignments": [a, a],
                                    "assumption": "t"})  # fmt: skip
    with pytest.raises(ValidationError):  # provenance required
        LoopShuttle.model_validate({"type": "loop_shuttle", "alignments": [a]})


def test_capacity_scenarios_and_defaults() -> None:
    cfg = loop_config()
    m = capacity_figures("measured", 2.0, cfg)
    assert m["pair_capacity_pph"] == 1355 and m["headway_s"] == pytest.approx(3600 * 2 / 1355, 1e-3)
    e = capacity_figures("engineering", 2.0, cfg)
    assert e["headway_s"] == 1.5 and e["pair_capacity_pph"] == pytest.approx(4800)
    t = loop_transform(load_loop_policy("loop_demo"))
    p = resolve_params(t)
    assert p["alpha"] == 0.5 and p["radius_o_m"] == 450 and p["min_trip_km"] == 0.6
    assert p["occupancy"] == cfg["shuttle"]["occupancy"] and p["capacity"] == "measured"
    tp = loop_transform(load_loop_policy("loop_demo_private"))
    pp = resolve_params(tp)
    assert pp["toll_penalty_s"] == pytest.approx(10 / 40 * 3600)


def tunnel_lanes(net: Path) -> dict[str, str]:
    import xml.etree.ElementTree as ET

    out = {}
    with gzip.open(net) as fh:
        for _, el in ET.iterparse(fh):
            if el.tag == "lane" and el.get("id", "").startswith("loop_"):
                out[el.get("id")] = el.get("allow", "")
    return out


def ramp_connections(net: Path) -> int:
    with gzip.open(net, "rt") as fh:
        return sum(1 for line in fh if "<connection " in line and 'to="loop_demo_D' in line
                   and 'from=":' not in line)  # fmt: skip


@pytest.mark.parametrize("mode", ["shuttle", "private"])
def test_build_loop_net_on_demo(mode: str, tmp_path: Path) -> None:
    from sim.loop.schema import Alignment

    before = xml_content_hash(DEMO_NET)
    al = [Alignment.model_validate({"id": "demo", "stations": STATIONS})]
    edges = E.load_edges(DEMO_NET)
    net, st, info = build_loop_net(DEMO_NET, al, mode, 90.0, tmp_path, edges)
    assert net.parent == tmp_path and net.name.startswith("demo.loop-") and net.exists()
    assert xml_content_hash(DEMO_NET) == before  # base network untouched
    assert len(st) == 3 and (st["connect_m"] < 800).all() and info["stations"] == 3
    assert 1.5 < info["alignment_km"]["demo"] < 3.0
    lanes = tunnel_lanes(net)
    want = "custom1" if mode == "shuttle" else "passenger"
    # 2 x 2 tunnel edges + 3 down + 3 up ramps, one lane each, restricted to the mode's class
    assert len(lanes) == 10 and all(a == want for a in lanes.values())
    n_conn = ramp_connections(net)
    assert (n_conn > 0) if mode == "private" else (n_conn == 0)
    again, _, _ = build_loop_net(DEMO_NET, al, mode, 90.0, tmp_path, edges)
    assert again == net  # reused, same key


def test_shuttle_route_and_meso_types(tmp_path: Path) -> None:
    assert shuttle_route("A", 0, 2) == ["loop_A_D0", "loop_A_T0_1", "loop_A_T1_2", "loop_A_U2"]
    assert shuttle_route("A", 2, 1) == ["loop_A_D2", "loop_A_T2_1", "loop_A_U1"]
    text = meso_types_file(tmp_path / "m.add.xml", 5.0, 0.1).read_text()
    assert 'tauff="50.000"' in text and "loop_tunnel" in text and "loop_ramp" in text


def test_pool_dispatch_window() -> None:
    from sim.loop.transforms import pool

    t = np.array([0.0, 100.0, 1000.0, 1010.0, 1020.0, 5000.0])
    assert pool(t, 2, 180.0) == [(100.0, 2), (1010.0, 2), (1200.0, 1), (5180.0, 1)]
    assert pool(t, 3, 50.0) == [(50.0, 1), (150.0, 1), (1020.0, 3), (5050.0, 1)]


def test_nearest_station() -> None:
    idx, d = nearest_station(np.array([0.0, 900.0, np.nan]), np.array([0.0, 0.0, 0.0]),
                             np.array([0.0, 1000.0]), np.array([0.0, 0.0]))  # fmt: skip
    assert list(idx[:2]) == [0, 1] and d[1] == pytest.approx(100) and np.isinf(d[2])


def test_shuttles_fill_by_occupancy_and_reposition() -> None:
    pax = pd.DataFrame({"line": "A", "os": [0, 0, 0, 0, 0, 2], "ds": [2, 2, 2, 2, 2, 0],
                        "t_station": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]})  # fmt: skip
    seg = {("A", 0): 1000.0, ("A", 1): 1500.0}
    p = {"occupancy": 2.0, "empty_reposition_factor": 0.0, "dwell_s": 30.0, "speed_kmh": 90.0,
         "max_pool_wait_s": 180.0}  # fmt: skip
    sh = shuttles(pax, seg, p, seed=1)
    loaded = sh[~sh["empty"]]
    assert loaded["pax"].sum() == 6 and len(loaded) == 4  # 5 pax -> 3 shuttles, 1 pax -> 1
    first = loaded[(loaded["os"] == 0)].sort_values("depart")
    # full shuttles leave with their last passenger; the lone last one after the max wait
    assert list(first["depart"]) == [20.0, 40.0, 230.0]
    assert set(loaded["ride_m"]) == {2500.0}
    p["empty_reposition_factor"] = 1.0
    sh2 = shuttles(pax, seg, p, seed=1)
    back = sh2[sh2["empty"]]
    assert len(back) == 4 and (back["pax"] == 0).all()
    assert set(zip(back["os"], back["ds"], strict=True)) == {(2, 0), (0, 2)}
    assert sh2["veh_id"].is_unique
    assert shuttles(pax, seg, p, seed=1).equals(sh2)  # deterministic


def test_capacity_flags() -> None:
    # 200 sampled passengers in one hour = 2,000/h city-equivalent at 10 % > 1,355 capacity
    pax = pd.DataFrame({"line": "A", "os": 0, "ds": 1, "t_station": np.linspace(0, 3500, 200)})
    sh = pd.DataFrame({"line": "A", "os": 0, "ds": 1, "depart": np.linspace(0, 3500, 100)})
    p = {"pair_capacity_pph": 1355.0, "headway_s": 3600 * 2 / 1355}
    f = capacity_flags(pax, sh, p, 0.1)
    assert f["pair_exceedance_share"] == pytest.approx((2000 - 1355) / 2000, abs=1e-3)
    assert f["segment_peak_utilisation"] == pytest.approx(1000 / (1355 / 2), rel=1e-3)
    assert f["segment_exceedance_share"] == 1.0


def test_eval_ids_name_what_differs() -> None:
    cfg = loop_config()
    d = defaults(cfg)
    assert eval_id("C1", "shuttle", {"alpha": 0.5, "speed_kmh": None}, d) == "loop_c1"
    assert eval_id("C1", "shuttle", {"alpha": 0.3}, d) == "loop_c1_a0p3"
    assert eval_id("S", "private", {"toll_sar": 25.0, "speed_kmh": 160.0}, d) == (
        "loop_s_private_v160_toll25"
    )
    pol = make_policy("loop_x", "x", [{"id": "C1", "stations": STATIONS}], "shuttle",
                      {"alpha": 0.3, "speed_kmh": None})  # fmt: skip
    t = loop_transform(pol)
    assert isinstance(t, LoopShuttle) and t.alpha == 0.3 and t.speed_kmh is None


def test_station_placement_respects_spacing() -> None:
    from sim.loop.site import place_stations

    cfg = loop_config()
    sites = pd.DataFrame({"x": [0.0, 12000.0, 4600.0, 6000.0], "y": [0.0, 0.0, 300.0, 2500.0],
                          "score_h": [5.0, 5.0, 100.0, 1000.0], "anchor": ""})  # fmt: skip
    sx, sy, ids = place_stations(sites.iloc[0], sites.iloc[1], sites, cfg)
    sp = np.hypot(np.diff(sx), np.diff(sy))
    lo, hi = cfg["siting"]["station_spacing_m"]
    assert 4 <= len(sx) <= 8 and (sp >= lo * 0.95).all() and (sp <= hi * 1.05).all()
    assert ids[0] == 0 and ids[-1] == 1 and 2 in ids  # snapped to the nearby site
    assert 3 not in ids  # 2.5 km off the line: beyond the snap distance
    too_long = pd.DataFrame({"x": [0.0, 40000.0], "y": [0.0, 0.0], "score_h": 1.0, "anchor": ""})
    assert place_stations(too_long.iloc[0], too_long.iloc[1], too_long, cfg) is None


def fake_eval(cid: str, km: float, saved: int, exceed: float = 0.0) -> dict:
    cx = {"low": km * 15, "central": km * 25, "high": km * 40}
    return {
        "candidate": cid, "run_id": f"loop_{cid.lower()}", "tunnel_km": km, "stations": 5,
        "relief_vht_per_day": saved, "relief_pct": 1.0, "net_person_hours_per_day": saved,
        "relief_per_usd_m": {k: saved / v for k, v in cx.items()},
        "passengers_per_day": 1000, "vht_saved_per_day": saved, "vht_saved_pct": 1.0,
        "road_vht_saved_per_day": saved, "am_peak_delay_change_pct": -1.0,
        "vht_saved_per_km": saved / km, "capex_usd_m": cx,
        "vht_saved_per_usd_m": {k: saved / v for k, v in cx.items()},
        "flags": {"pair_exceedance_share": exceed, "teleport_share": 0.40,
                  "teleport_share_compare": 0.41, "share_slower_than_car": 0.5},
    }  # fmt: skip


def line(cid: str, lon0: float) -> dict:
    st = [{"name": f"s{k}", "lon": lon0, "lat": 21.45 + 0.02 * k} for k in range(5)]
    return {"id": cid, "name": cid, "origin": "data", "tunnel_km": 10.0, "stations": st,
            "captured_delay_h": 1.0, "captured_trips": 1}  # fmt: skip


def test_greedy_budget_overlap_and_noise() -> None:
    from sim.loop.optimise import greedy

    cfg = loop_config()
    cands = {"A": line("A", 39.15), "B": line("B", 39.15005), "C": line("C", 39.25),
             "D": line("D", 39.35), "E": line("E", 39.45)}  # fmt: skip
    ev = {"A": fake_eval("A", 10, 50_000), "B": fake_eval("B", 10, 49_000),  # B overlaps A
          "C": fake_eval("C", 10, 30_000), "D": fake_eval("D", 10, 20_000),  # D over budget
          "E": fake_eval("E", 4, 500)}  # E inside noise  # fmt: skip
    chosen, log = greedy(cands, ev, 25.0, 1000.0, cfg)
    assert chosen == ["A", "C"]
    why = {r["candidate"]: r["decision"] for r in log}
    assert why["B"].startswith("overlaps A") and "budget" in why["D"] and "noise" in why["E"]


def test_quality_gate_and_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sim.loop.optimise as O

    cfg = loop_config()
    ok, _ = O.passes(fake_eval("A", 10, 1000), cfg, 0.01)
    bad, why = O.passes(fake_eval("A", 10, 1000, exceed=0.3), cfg, 0.01)
    assert ok and not bad and "capacity" in why
    doc = tmp_path / "loop.md"
    names = ("candidates", "ranking", "greedy", "sweep", "recommendation", "noise")
    doc.write_text("\n".join(f"<!-- LOOP:{n} -->\nold\n<!-- /LOOP:{n} -->" for n in names))
    monkeypatch.setattr(O, "DOC", doc)
    cands = {"A": line("A", 39.15)}
    ev = {"A": fake_eval("A", 10, 5000)}
    row = O.sweep_row("shuttle central", "lever", {**ev["A"], "run_id": "loop_opt_a"}, "ok")
    row |= {"suffix": "", "pass": True}
    best = O.recommend([row])
    assert best is not None and best["relief_used"] == 5000
    res = {"greedy": [{"candidate": "A", "km": 10, "relief_per_km": 500, "decision": "selected",
                       "cumulative_km": 10}], "sweep": [row], "selected": ["A"],
           "selected_km": 10, "budget_km": 25,
           "noise": {"run": "n", "vht_delta": 100, "relief_delta": -100, "noise_relief": 100,
                     "teleport_share": 0.5, "teleport_share_delta": 0.001},
           "recommended": best,
           "band": {"relief_vht_per_day": 5000, "relief_range": [4000, 6000],
                    "relief_values": [5000],
                    "per_usd_m_central": 20.0, "per_usd_m_range": [10.0, 40.0],
                    "capex_usd_m": ev["A"]["capex_usd_m"]}}  # fmt: skip
    O.render(res, cands, ev)
    text = doc.read_text()
    assert "old" not in text and "shuttle central" in text and "| 1 | A |" in text
    assert "band 4,000 to 6,000" in text


def test_greedy_knapsack_correction() -> None:
    from sim.loop.optimise import greedy

    cfg = loop_config()
    cands = {"A": line("A", 39.15), "B": line("B", 39.30)}
    ev = {"A": fake_eval("A", 10, 30_000), "B": fake_eval("B", 20, 50_000)}  # A wins per km
    chosen, log = greedy(cands, ev, 25.0, 1000.0, cfg)
    assert chosen == ["B"]  # A then B does not fit; B alone relieves more than A
    why = {r["candidate"]: r["decision"] for r in log}
    assert why["A"].startswith("dropped") and why["B"].startswith("selected")


def test_recommend_pools_shuttle_speeds_and_filters_noise_options() -> None:
    import sim.loop.optimise as O

    def row(
        suffix: str,
        rel: int,
        ok: bool,
        role: str = "lever",
        use: int = 30_000,
        config: str | None = None,
    ) -> dict:
        return {"suffix": suffix, "rel": rel, "pass": ok, "ok": "ok" if ok else "segment",
                "role": role, "config": config or (suffix or "central"), "run": f"r{suffix}",
                "pax": use, "tunnel_entries": use}  # fmt: skip

    sweep = [row("", 50_000, False), row("_v50", 40_000, False), row("_v160", 90_000, False),
             row("_private_toll10", 55_000, True, use=16_000),
             row("_private_toll25", 60_000, True, use=750),
             row("_a0p3", 57_000, True, "uncertainty"), row("_a0p7", 80_000, False, "uncertainty"),
             row("_capeng", 61_000, True, "uncertainty",
                 config="engineering capacity")]  # fmt: skip
    best = O.recommend(sweep)
    assert best["suffix"] == "_a0p3" and "capped" in best["config"] and best["eligible"]
    alts = {a["config"]: a for a in best["alternatives"]}
    assert alts["central"]["relief"] == 60_000  # pooled mean of the three speed runs
    assert "noise" in alts["_private_toll25"]["gate"]  # 750 trips/day cannot cause the relief
    assert [v["config"] for v in best["vendor_alternatives"]] == ["engineering capacity"]
    # nothing eligible: the best option is still returned, with the failure named
    worst = O.recommend([row("", 50_000, False)])
    assert worst is not None and not worst["eligible"]
