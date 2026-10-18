"""Track D end-to-end tests on the demo window (SUMO, seconds each): shuttle and private-EV Loop
runs through Track A's policy runner, nested alpha selection, determinism, the matched control of
private mode, and siting + map on a demo baseline."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
import yaml

import sim.loop.network as N
import sim.policies.edges as E
import sim.population.baseline as baseline
import sim.population.synthesize as synthesize
from sim.common import SYNTHETIC_LABEL
from sim.loop.evaluate import make_policy
from sim.loop.run import run_loop_policy
from sim.loop.schema import load_loop_policy, loop_config, loop_transform
from tests.test_policies import DEMO_NET, RESIDENTS, quadrant_districts


@pytest.fixture(scope="module")
def lenv(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict]:
    from sim.population import zones as Z

    tmp = tmp_path_factory.mktemp("loop")
    cfg = Z.zones_config()
    cfg["control_total"]["value"] = RESIDENTS
    cfg["non_residential_districts"]["names"] = []
    districts = quadrant_districts(tmp / "d.geojson")
    zones, zone_edges = Z.build_zones(Z.ZoneInputs(districts=districts, net=DEMO_NET), cfg)
    Z.write_zones(zones, zone_edges, tmp / "zones", {})
    mp = pytest.MonkeyPatch()
    mp.setattr(synthesize, "CACHE_DIR", tmp / "pop")
    mp.setattr(baseline, "ROUTE_CACHE", tmp / "routes")
    mp.setattr(E, "CACHE", tmp / "edges")
    mp.setattr(N, "CACHE", tmp / "edges")
    kw = {"net": DEMO_NET, "zone_dir": tmp / "zones", "baselines_dir": tmp / "baselines",
          "iterations": 1, "quiet": True}  # fmt: skip
    yield {"tmp": tmp, "kw": kw, "districts": districts}
    mp.undo()


def run(lenv: dict, pol: object, runs: Path) -> dict:
    return run_loop_policy(pol, "weekday", 1.0, 1, runs, **lenv["kw"])


def test_shuttle_demo_report_and_determinism(lenv: dict, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    m = run(lenv, "loop_demo", runs)
    out = runs / m["run_id"]
    rep = json.loads((out / "loop_report.json").read_text())
    assert (
        rep["label"] == SYNTHETIC_LABEL and SYNTHETIC_LABEL in (out / "loop_report.md").read_text()
    )
    assert rep["mode"] == "shuttle" and rep["passengers_per_day"] > 0
    assert rep["car_vehicles_removed_per_day"] == rep["passengers_per_day"]
    assert rep["capex_usd_m"]["low"] < rep["capex_usd_m"]["central"] < rep["capex_usd_m"]["high"]
    km = sum(m["net_change"]["alignment_km"].values())
    assert rep["tunnel_km"] == pytest.approx(km, abs=0.01)
    for k in ("teleport_share", "pair_exceedance_share", "segment_peak_utilisation",
              "share_slower_than_car"):  # fmt: skip
        assert k in rep["flags"]
    # shuttles are in the simulation, removed car trips are not
    ti = pd.read_parquet(out / "tripinfo.parquet")
    sh = pd.read_parquet(out / "loop_shuttles.parquet")
    assert ti["veh_id"].str.startswith("loop_").sum() == len(sh) > 0
    pax = pd.read_parquet(out / "loop_pax.parquet")
    assert not ti["veh_id"].isin(set(pax["base_veh_id"].dropna())).any()
    assert (
        m["vehicles"]
        < json.loads(
            (lenv["kw"]["baselines_dir"] / m["compare_baseline"] / "meta.json").read_text()
        )["vehicles"]
    )
    assert m.get("control_run") is None  # nothing re-routed in shuttle mode
    # same seed twice: identical tripinfo
    m2 = run_loop_policy("loop_demo", "weekday", 1.0, 1, tmp_path / "runs2", **lenv["kw"])
    h = [json.loads((d / "metrics.json").read_text())["tripinfo_hash"]
         for d in (out, tmp_path / "runs2" / m2["run_id"])]  # fmt: skip
    assert h[0] == h[1]


def test_alpha_selects_nested_tours(lenv: dict, tmp_path: Path) -> None:
    t = loop_transform(load_loop_policy("loop_demo"))
    al = [a.model_dump() for a in t.alignments]
    common = {"radius_o_m": 450, "radius_d_m": 450, "min_trip_km": 0.6}
    shifted = {}
    for alpha in (0.3, 0.7):
        pol = make_policy(f"loop_demo_a{int(alpha * 10)}", "demo", al, "shuttle",
                          {"alpha": alpha, **common})  # fmt: skip
        m = run(lenv, pol, tmp_path / "runs")
        pax = pd.read_parquet(tmp_path / "runs" / m["run_id"] / "loop_pax.parquet")
        shifted[alpha] = set(pax["tour_id"])
    assert shifted[0.3] and shifted[0.3] < shifted[0.7]


def test_private_mode_uses_tunnel_and_matched_control(lenv: dict, tmp_path: Path) -> None:
    t = loop_transform(load_loop_policy("loop_demo_private"))
    al = [a.model_dump() for a in t.alignments]
    entries = {}
    for toll in (0.0, 10.0):
        pol = make_policy(
            f"loop_demo_toll{int(toll)}",
            "demo",
            al,
            "private",
            {"toll_sar": toll, "reroute_radius_m": 600, "min_trip_km": 0.6},
        )
        m = run(lenv, pol, tmp_path / "runs")
        rep = m["loop"]
        assert rep["cars_rerouted"] > 0
        assert m["control_run"] == f"{m['run_id']}--control"  # TA-018 matched control
        assert rep["compare"] == m["control_run"]
        entries[toll] = rep["private"]["tunnel_entries_per_day"]
    assert entries[0.0] > 0 and entries[10.0] < entries[0.0]


def demo_site_cfg() -> dict:
    cfg = loop_config()
    cfg["access"] |= {"radius_m": 450, "min_trip_km": 0.6}
    cfg["siting"] |= {
        "site_grid_m": 150,
        "site_min_separation_m": 350,
        "max_sites": 15,
        "station_spacing_m": [350, 900],
        "stations": [3, 5],
        "length_km": [1.0, 3.0],
        "snap_m": 200,
        "overlap_m": 250,
        "n_candidates": 4,
        "anchors": [{"name": "demo anchor", "lon": 39.1571, "lat": 21.5505}],
    }
    return cfg  # fmt: skip


def test_site_on_demo_baseline(lenv: dict, tmp_path: Path) -> None:
    from sim.loop.site import run_site

    run(lenv, "loop_demo", tmp_path / "runs")  # makes sure the demo baseline exists
    base = next(lenv["kw"]["baselines_dir"].glob("baseline-weekday-*"))
    cfg = demo_site_cfg()
    res = run_site(base, tmp_path / "cand.yaml", tmp_path / "map.png", tmp_path / "res", cfg,
                   lenv["districts"], lenv["kw"]["zone_dir"])  # fmt: skip
    assert 1 <= len(res) <= 4 and (tmp_path / "map.png").stat().st_size > 10_000
    doc = yaml.safe_load((tmp_path / "cand.yaml").read_text())
    assert doc["label"] == SYNTHETIC_LABEL and len(doc["candidates"]) == len(res)
    lo, hi = cfg["siting"]["stations"]
    for c in res:
        assert lo <= len(c["stations"]) <= hi and c["captured_delay_h"] >= 0
    for name in ("desire_lines.csv", "corridors.csv", "sites.csv"):
        assert (tmp_path / "res" / name).exists()
    lines = pd.read_csv(tmp_path / "res" / "desire_lines.csv")
    assert (lines["delay_h"].diff().dropna() <= 1e-9).all()  # sorted by delay
