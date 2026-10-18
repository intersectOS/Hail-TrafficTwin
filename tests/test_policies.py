"""M4 policy schema and transform tests on the demo population (offline, no city data).

The demo window has no districts, so (as in test_population.py) its bounding box is split into
four quadrant zones with 8,000 residents; caches go to a temporary directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import sim.policies.edges as E
import sim.population.synthesize as synthesize
from sim.common import REPO_ROOT
from sim.policies import transforms as T
from sim.population import zones as Z
from sim.population.activities import activities_config, generate
from sim.population.modes import assign_modes, vehicle_trips
from sim.schemas import Policy, load_daytype, load_policy, validate_file

DEMO_NET = REPO_ROOT / "data" / "demo" / "demo.net.xml"
BBOX = (39.148, 21.542, 39.166, 21.558)
RESIDENTS = 8000
POLICY_FILES = sorted((REPO_ROOT / "sim" / "policies").glob("*.yaml"))
DEMO_POLICIES = (
    "remote_work_30", "staggered_schools_60", "friday", "ramadan_weekday", "bus_line_tahlia",
    "cordon_center", "close_corniche_road", "ramadan_remote_30",
)  # fmt: skip


def quadrant_districts(path: Path) -> Path:
    x0, y0, x1, y1 = BBOX
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    feats = []
    for i, (a, b, c, d) in enumerate(
        [(x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)]
    ):
        ring = [[a, b], [c, b], [c, d], [a, d], [a, b]]
        feats.append({"type": "Feature",
                      "properties": {"name_en": f"Q{i}", "name_ar": "", "osm_id": str(i)},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})  # fmt: skip
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return path


@pytest.fixture(scope="session")
def policy_env(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("m4")
    cfg = Z.zones_config()
    cfg["control_total"]["value"] = RESIDENTS
    cfg["non_residential_districts"]["names"] = []
    zones, zone_edges = Z.build_zones(
        Z.ZoneInputs(districts=quadrant_districts(tmp / "d.geojson"), net=DEMO_NET), cfg
    )
    Z.write_zones(zones, zone_edges, tmp / "zones", {})
    return tmp


@pytest.fixture()
def env(policy_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import sim.population.baseline as baseline

    monkeypatch.setattr(synthesize, "CACHE_DIR", policy_env / "pop")
    monkeypatch.setattr(baseline, "ROUTE_CACHE", policy_env / "routes")
    monkeypatch.setattr(E, "CACHE", policy_env / "edges")
    return policy_env


def make_plan(env: Path, tmp: Path, daytype: str = "weekday") -> T.Plan:
    zd = env / "zones"
    pop = synthesize.synthesize(1, 1.0, zd)
    trips = generate(pop, load_daytype(daytype), 1, 1.0, zd)
    trips = assign_modes(trips, pop, 1, daytype, zone_dir=zd)
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, 1, daytype, speed)
    return T.Plan(daytype=daytype, seed=1, sample=1.0, sim_end=86400.0, pop=pop, trips=trips,
                  vehicles=veh, net=DEMO_NET, work=tmp, zone_dir=zd)  # fmt: skip


def remote(**kw: object) -> object:
    data = {"type": "remote_work", "share": 0.3, "days_per_week": 3,
            "eligible_sectors": ["government", "private_office"],
            "induced_trip_probability": 0.0, "assumption": "test"} | kw  # fmt: skip
    return Policy.model_validate(
        {"id": "t", "kind": "policy", "title": "t", "daytype": "weekday", "transforms": [data]}
    ).transforms[0]


# ---------------------------------------------------------------------------- schema


@pytest.mark.parametrize("path", POLICY_FILES, ids=lambda p: p.stem)
def test_policy_files_validate(path: Path) -> None:
    pol = validate_file(path)
    assert isinstance(pol, Policy) and pol.id == path.stem


def test_all_demo_policies_shipped() -> None:
    assert set(DEMO_POLICIES) <= {p.stem for p in POLICY_FILES}
    kinds = {t.type for name in DEMO_POLICIES for t in load_policy(name).transforms}
    assert {"remote_work", "staggered_hours", "daytype", "pt_line", "network_change",
            "road_pricing"} <= kinds  # fmt: skip
    composed = load_policy("ramadan_remote_30")
    assert [t.type for t in composed.transforms] == ["daytype", "remote_work"]


def test_policy_schema_rejects_bad_files() -> None:
    base = {"id": "x", "kind": "policy", "title": "x", "daytype": "weekday"}
    with pytest.raises(ValidationError, match="source"):  # no provenance
        Policy.model_validate(
            base
            | {
                "transforms": [
                    {"type": "staggered_hours", "segment": "school", "offset_minutes": 30}
                ]
            }
        )
    with pytest.raises(ValidationError, match="first"):  # daytype must come first
        Policy.model_validate(
            base
            | {
                "transforms": [
                    {
                        "type": "staggered_hours",
                        "segment": "school",
                        "offset_minutes": 30,
                        "assumption": "a",
                    },
                    {"type": "daytype", "daytype": "friday"},
                ]
            }
        )
    with pytest.raises(ValidationError, match="unknown"):  # bad sector
        remote(eligible_sectors=["farming"])
    with pytest.raises(ValidationError):  # share out of range
        remote(share=1.5)
    with pytest.raises(ValidationError, match="day type"):
        Policy.model_validate(base | {"transforms": [{"type": "daytype", "daytype": "mars"}]})
    with pytest.raises(ValidationError, match="changes nothing"):
        Policy.model_validate(base | {"transforms": [{"type": "network_change",
                                                      "edits": [{"edges": ["a"]}],
                                                      "assumption": "a"}]})  # fmt: skip


def test_validate_cli(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from sim.validate import app

    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\nkind: policy\ntitle: b\ndaytype: weekday\ntransforms: []\n")
    ok = CliRunner().invoke(app, [str(POLICY_FILES[0])])
    assert ok.exit_code == 0 and "ok" in ok.output
    res = CliRunner().invoke(app, [str(bad)])
    assert res.exit_code == 1 and "FAIL" in res.output


# ---------------------------------------------------------------------------- transforms


def test_remote_work_removes_work_tours_nested(env: Path, tmp_path: Path) -> None:
    removed = {}
    for share in (0.0, 0.2, 0.4, 1.0):
        plan = make_plan(env, tmp_path)
        before = plan.vehicles.copy()
        eligible = set(
            plan.trips.loc[plan.trips["segment"].isin(["government", "private_office"]), "tour_id"]
        )
        eff = T.remote_work(plan, remote(share=share, days_per_week=5))
        gone = set(before["tour_id"]) - set(plan.vehicles["tour_id"])
        removed[share] = gone
        assert gone <= eligible and eff["tours_removed"] == eff["remote_today"]
        assert set(plan.trips["tour_id"]).isdisjoint(gone)
        # untouched vehicles keep id, departure, origin and destination
        kept = before[~before["tour_id"].isin(gone)].set_index("veh_id")
        now = plan.vehicles.set_index("veh_id").loc[kept.index]
        assert (now["depart"] == kept["depart"]).all() and (now["o_edge"] == kept["o_edge"]).all()
        if share == 1.0:
            assert gone == eligible & set(before["tour_id"])
    assert not removed[0.0]
    assert removed[0.2] <= removed[0.4] <= removed[1.0]  # nested selection across shares


def test_remote_work_days_and_induced_trips(env: Path, tmp_path: Path) -> None:
    a = make_plan(env, tmp_path)
    ea = T.remote_work(a, remote(share=1.0, days_per_week=5, induced_trip_probability=1.0))
    assert ea["induced_tours_added"] > 0.9 * ea["remote_today"]
    added = a.trips[a.trips["segment"] == "remote_work"]
    assert set(added["leg"]) == {0, 1} and added["depart"].between(0, 86400).all()
    assert added.groupby("tour_id")["mode"].nunique().max() == 1
    assert a.finalize()["veh_id"].is_unique
    b = make_plan(env, tmp_path)
    eb = T.remote_work(b, remote(share=1.0, days_per_week=2))
    ratio = eb["remote_today"] / ea["remote_today"]
    assert 0.3 < ratio < 0.5  # 2 of 5 days


def test_staggered_hours_shifts_whole_schools(env: Path, tmp_path: Path) -> None:
    plan = make_plan(env, tmp_path)
    before = plan.vehicles.copy()
    school_tours = set(plan.trips.loc[plan.trips["segment"] == "school", "tour_id"])
    t = (
        load_policy("staggered_schools_60")
        .transforms[0]
        .model_copy(update={"share": 1.0, "spread_minutes": 0.0})
    )
    eff = T.staggered_hours(plan, t)
    assert eff["institutions_shifted"] == eff["institutions"] > 0
    m = before.merge(plan.vehicles[["veh_id", "depart"]], on="veh_id", suffixes=("", "_new"))
    hit = m["tour_id"].isin(school_tours)
    shift = np.mod(m.loc[hit, "depart_new"] - m.loc[hit, "depart"], 86400)
    assert np.allclose(shift, 3600.0) and m.loc[hit, "empty"].any()  # escort empty legs follow
    assert (m.loc[~hit, "depart_new"] == m.loc[~hit, "depart"]).all()
    half = make_plan(env, tmp_path)
    eh = T.staggered_hours(half, t.model_copy(update={"share": 0.5}))
    assert 0.25 < eh["institutions_shifted"] / eh["institutions"] < 0.75


def test_road_pricing_suppresses_and_penalises(env: Path, tmp_path: Path) -> None:
    plan = make_plan(env, tmp_path)
    xm, ym = (BBOX[0] + BBOX[2]) / 2, (BBOX[1] + BBOX[3]) / 2
    x1, y1 = BBOX[2] + 0.01, BBOX[3] + 0.01
    pol = Policy.model_validate({
        "id": "c", "kind": "policy", "title": "c", "daytype": "weekday",
        "transforms": [{"type": "road_pricing",
                        "polygon": [[xm, ym], [x1, ym], [x1, y1], [xm, y1]],
                        "charge_sar": 25, "hours": ["07:00", "19:00"], "elasticity": -1.0,
                        "base_trip_cost_sar": 25, "retime_share": 0.5,
                        "value_of_time_sar_h": 40, "assumption": "test"}]})  # fmt: skip
    n0 = len(plan.vehicles)
    eff = T.road_pricing(plan, pol.transforms[0])
    assert eff["charged_vehicles"] > 0 and eff["suppressed_share"] == pytest.approx(0.5)
    assert eff["tours_retimed_out_of_hours"] > 0 and len(plan.vehicles) < n0
    assert plan.penalties and plan.penalties[0].seconds == pytest.approx(2250.0)
    assert plan.force_reroute
    moved = plan.vehicles[plan.vehicles["veh_id"].isin(plan.force_reroute)]
    assert moved["depart"].between(7 * 3600, 19 * 3600).all()


def test_ridehail_share_with_deadhead(env: Path, tmp_path: Path) -> None:
    plan = make_plan(env, tmp_path)
    t = load_policy("ridehail_plus_10").transforms[0].model_copy(update={"convert_share": 0.5})
    eff = T.ridehail_share(plan, t)
    assert eff["tours_converted"] > 0 and eff["deadhead_vehicles_added"] > 0
    conv = plan.vehicles[plan.vehicles["veh_id"].str.startswith("d")]
    assert conv["empty"].all() and (conv["purpose"] == "deadhead").all()
    rides = plan.trips[plan.trips["tour_id"].isin(conv["tour_id"])]
    assert (rides["mode"].astype(str) == "ridehail").all()
    assert plan.finalize()["veh_id"].is_unique


def test_network_change_closes_edges(env: Path, tmp_path: Path) -> None:
    from sim.policies.netedit import apply_network_change

    plan = make_plan(env, tmp_path)
    edges = plan.edges()
    used = plan.vehicles["o_edge"].value_counts()
    target = str(used.index[0])  # close the busiest origin edge: endpoints must move
    t = Policy.model_validate({
        "id": "n", "kind": "policy", "title": "n", "daytype": "weekday",
        "transforms": [{"type": "network_change", "edits": [{"edges": [target], "closed": True},
                        {"edges": [str(edges["edge_id"].iloc[5])], "lanes": 1}],
                        "assumption": "test"}]}).transforms[0]  # fmt: skip
    eff = apply_network_change(plan, t, "n")
    assert eff["edges_closed"] == 1 and eff["endpoints_moved"] >= int(used.iloc[0])
    assert plan.net != DEMO_NET and plan.net.exists() and plan.net.parent == tmp_path
    assert target not in set(plan.edges()["edge_id"])
    assert target not in set(plan.vehicles["o_edge"]) | set(plan.vehicles["d_edge"])
    # an empty patch reproduces the base network body byte for byte
    from sim.policies.netedit import build_variant

    rt = build_variant(DEMO_NET, "<edges>\n</edges>\n", tmp_path / "rt.net.xml.gz",
                       tmp_path / "rt.log")  # fmt: skip
    import gzip

    with gzip.open(rt, "rt") as fh:
        body = fh.read().split("<net ", 1)[1]
    assert body == DEMO_NET.read_text().split("<net ", 1)[1]


def test_edge_table(env: Path) -> None:
    df = E.load_edges(DEMO_NET)
    assert df["edge_id"].is_unique and len(df) > 900
    assert df["lon"].between(BBOX[0] - 0.01, BBOX[2] + 0.01).all()
    assert df["passenger"].any() and df["bus"].any() and (df["name"] != "").any()
    assert isinstance(df, pd.DataFrame) and E.load_edges(DEMO_NET).equals(df)  # cached


def test_remote_work_share_by_sector(env: Path, tmp_path: Path) -> None:
    plan = make_plan(env, tmp_path)
    before = plan.vehicles.copy()
    seg = plan.trips.drop_duplicates("tour_id").set_index("tour_id")["segment"].astype(str)
    t = remote(share={"government": 1.0, "private_office": 0.0}, days_per_week=5)
    eff = T.remote_work(plan, t)
    gone = set(before["tour_id"]) - set(plan.vehicles["tour_id"])
    assert eff["remote_today"] > 0 and gone
    assert set(seg.loc[sorted(gone)]) == {"government"}
    gov = set(seg.index[seg == "government"]) & set(before["tour_id"])
    assert gone == gov
    with pytest.raises(ValidationError, match="not eligible"):
        remote(share={"health": 0.5}, eligible_sectors=["government"])
