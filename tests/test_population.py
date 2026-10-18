"""M2 population and baseline tests on the committed demo window (offline, seconds).

The demo window has no district polygons, so the fixture splits its bounding box into four
quadrant zones and builds zones, a small population (8,000 residents) and a 24 h baseline from
them, with all caches redirected to a temporary directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sim.population.baseline as baseline
import sim.population.synthesize as synthesize
from sim.common import REPO_ROOT
from sim.population import zones as Z
from sim.population.activities import generate
from sim.population.export_trips import write_trips
from sim.population.modes import assign_modes, vehicle_trips
from sim.population.sampling import gravity_choice, mixture_times, stream
from sim.schemas import DayType, TimeDist, hhmm_to_s, load_daytype, validate_file

DEMO_NET = REPO_ROOT / "data" / "demo" / "demo.net.xml"
DAYTYPES = ("weekday", "friday", "saturday", "ramadan_weekday", "umrah_season")
BBOX = (39.148, 21.542, 39.166, 21.558)
RESIDENTS = 8000


def quadrant_districts(path: Path) -> Path:
    x0, y0, x1, y1 = BBOX
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    feats = []
    for i, (a, b, c, d) in enumerate(
        [(x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)]
    ):
        ring = [[a, b], [c, b], [c, d], [a, d], [a, b]]
        feats.append(
            {
                "type": "Feature",
                "properties": {"name_en": f"Q{i}", "name_ar": "", "osm_id": str(i)},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return path


@pytest.fixture(scope="session")
def demo_env(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("m2")
    cfg = Z.zones_config()
    cfg["control_total"]["value"] = RESIDENTS
    cfg["non_residential_districts"]["names"] = []
    zones, zone_edges = Z.build_zones(
        Z.ZoneInputs(districts=quadrant_districts(tmp / "d.geojson"), net=DEMO_NET), cfg
    )
    Z.write_zones(zones, zone_edges, tmp / "zones", {})
    return tmp


@pytest.fixture()
def caches(demo_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(synthesize, "CACHE_DIR", demo_env / "pop")
    monkeypatch.setattr(baseline, "ROUTE_CACHE", demo_env / "routes")
    return demo_env


# ---------------------------------------------------------------------------- schemas


@pytest.mark.parametrize("name", DAYTYPES)
def test_daytypes_validate(name: str) -> None:
    day = validate_file(REPO_ROOT / "sim" / "daytypes" / f"{name}.yaml")
    assert isinstance(day, DayType)
    assert day.id == name


def test_behavioural_block_needs_provenance() -> None:
    with pytest.raises(ValueError, match="source"):
        TimeDist(dist="normal", mean="07:00", sd_min=10, lo="06:00", hi="08:00")
    assert hhmm_to_s("25:30") == 91800.0


def test_friday_and_ramadan_shape() -> None:
    fri = load_daytype("friday")
    assert fri.special.friday and "jumuah" in fri.prayers and "school" not in fri.main_tours
    ram = load_daytype("ramadan_weekday")
    gov = ram.main_tours["government"].start
    assert ram.special.ramadan and gov.as_components()[0][1] >= hhmm_to_s("09:30")


# ---------------------------------------------------------------------------- sampling


def test_sampling_helpers_are_deterministic() -> None:
    a = mixture_times(stream(3, "x"), 1000, [(1.0, 25200.0, 600.0)], 21600.0, 28800.0)
    b = mixture_times(stream(3, "x"), 1000, [(1.0, 25200.0, 600.0)], 21600.0, 28800.0)
    assert np.array_equal(a, b) and a.min() >= 21600.0 and a.max() <= 28800.0
    dist = np.array([[0.0, 100.0], [100.0, 0.0]])
    dz = gravity_choice(stream(1, "g"), np.zeros(500, dtype=int), np.array([1.0, 1.0]), dist, 1.0)
    assert (dz == 0).mean() > 0.95  # strong decay keeps destinations local


# ---------------------------------------------------------------------------- zones


def test_zones_on_demo(demo_env: Path) -> None:
    zones, zone_edges, meta = Z.load_zones(demo_env / "zones")
    assert len(zones) == 4 and meta["population"] == RESIDENTS
    assert int(zones["population"].sum()) == RESIDENTS
    for col in [c for c in zones if c.startswith("att_")]:
        assert zones[col].sum() == pytest.approx(1.0) or zones[col].sum() == 0.0
    assert zone_edges["edge_id"].is_unique and set(zone_edges["zone_id"]) <= set(range(4))
    assert (zone_edges["home_w"] >= 0).all() and (zone_edges["act_w"] > 0).any()


# ---------------------------------------------------------------------------- population


def test_population_deterministic_and_nested(caches: Path) -> None:
    zd = caches / "zones"
    a = synthesize.synthesize(1, 1.0, zd)
    b = synthesize.synthesize(1, 1.0, zd)
    c = synthesize.synthesize(2, 1.0, zd)
    assert a.meta["population_hash"] == b.meta["population_hash"]
    assert a.meta["population_hash"] != c.meta["population_hash"]
    p = a.persons
    assert len(p) == RESIDENTS and p["person_id"].is_unique
    assert set(p["status"].astype(str)) <= {"worker", "student", "homemaker", "other"}
    assert p.loc[p["status"] == "worker", "sector"].notna().all()
    assert p.loc[p["age_group"] == "a0_5", "status"].eq("other").all()
    assert not p.loc[p["age_group"].isin(["a0_5", "a6_17"]), "licence"].any()
    assert p.loc[p["primary_zone"] >= 0, "primary_edge"].notna().all()
    small = synthesize.synthesize(1, 0.10, zd)
    big = synthesize.synthesize(1, 0.25, zd)
    assert set(small.persons["person_id"]) <= set(big.persons["person_id"])
    assert 0.05 < len(small.persons) / RESIDENTS < 0.15


def test_population_cache(caches: Path) -> None:
    zd = caches / "zones"
    first = synthesize.load_or_synthesize(1, 1.0, zd)
    again = synthesize.load_or_synthesize(1, 1.0, zd)
    assert first.meta["population_hash"] == again.meta["population_hash"]
    assert (REPO_ROOT / first.meta["dir"]).exists() or Path(first.meta["dir"]).exists()


# ---------------------------------------------------------------------------- activities


@pytest.mark.parametrize("daytype", ["weekday", "friday", "ramadan_weekday"])
def test_activities_and_vehicle_trips(caches: Path, daytype: str) -> None:
    zd = caches / "zones"
    pop = synthesize.synthesize(1, 1.0, zd)
    day = load_daytype(daytype)
    trips = generate(pop, day, 1, 1.0, zd)
    assert trips["depart"].between(0, 86400, inclusive="left").all()
    per_person = (trips["person_id"] >= 0).sum() / len(pop.persons)
    assert 1.0 < per_person < 4.5
    assert set(trips["purpose"].astype(str)) >= {"home", "mosque"}
    if day.special.school_day:
        school = trips[trips["purpose"] == "school"]
        st = day.main_tours["school"].start
        assert school["depart"].between(st.lo_s - 3600, st.hi_s).mean() > 0.9
    else:
        assert (trips["purpose"] == "school").sum() == 0
    tours = trips.groupby("tour_id")["person_id"].nunique()
    assert (tours == 1).all()
    trips = assign_modes(trips, pop, 1, daytype, zone_dir=zd)
    assert trips.groupby("tour_id")["mode"].nunique().max() == 1
    veh = vehicle_trips(trips, 1, daytype, 28.0)
    assert veh["veh_id"].is_unique
    assert (veh["depart"].diff().dropna() >= 0).all()
    assert set(veh["vtype"]) <= {"car", "ridehail", "bus"}
    assert not veh["mode"].isin(["walk", "car_passenger", "bus"]).any()
    assert 0.5 < len(veh) / len(pop.persons) < 2.0


def test_mosque_trips_follow_adhan(caches: Path) -> None:
    from sim.daytypes.prayer import prayer_times

    zd = caches / "zones"
    pop = synthesize.synthesize(1, 1.0, zd)
    day = load_daytype("weekday")
    trips = generate(pop, day, 1, 1.0, zd)
    times = prayer_times(day.date)
    out = trips[(trips["purpose"] == "mosque") & (trips["segment"] == "maghrib")]
    assert len(out) > 0
    assert (out["depart"] - times["maghrib"]).abs().max() <= 600
    assert 17 * 3600 < times["maghrib"] < 19 * 3600  # Jeddah, October


def test_trips_file_sorted(tmp_path: Path) -> None:
    v = pd.DataFrame(
        {"veh_id": ["b", "a"], "vtype": ["car", "car"], "depart": [5.0, 1.0],
         "o_edge": ["x", "y"], "d_edge": ["y", "x"]}
    )  # fmt: skip
    with pytest.raises(ValueError):
        write_trips(v, tmp_path / "t.xml")
    write_trips(v.sort_values("depart"), tmp_path / "t.xml", scale=10)
    text = (tmp_path / "t.xml").read_text()
    assert text.index('id="a"') < text.index('id="b"') and 'length="46.0"' in text


# ---------------------------------------------------------------------------- baseline


def test_baseline_demo_end_to_end_and_reproducible(caches: Path) -> None:
    kw = {
        "daytype": "weekday",
        "seed": 1,
        "sample": 1.0,
        "net": DEMO_NET,
        "runs_dir": caches / "runs",
        "iterations": 1,
        "zone_dir": caches / "zones",
        "quiet": True,
    }
    m1 = baseline.run_baseline(**kw)
    out = caches / "runs" / m1["run_id"]
    for name in ("meta.json", "metrics.json", "report.md", "tripinfo.parquet", "edgedata.parquet",
                 "metrics_hourly.parquet", "metrics_district.parquet", "plots/departures.png",
                 "plots/trip_length.png", "plots/trips_per_person.png"):  # fmt: skip
        assert (out / name).exists(), name
    metrics = json.loads((out / "metrics.json").read_text())
    s = metrics["summary"]
    assert metrics["label"] == "synthetic demand, uncalibrated"
    assert s["trips_completed"] > 0 and s["vkt"] > 0 and s["co2_t"] > 0
    assert s["teleport_share"] < 0.005
    assert "Caveats" in (out / "report.md").read_text()
    for key in ("seed", "config_hash", "population_hash", "network_hash", "sumo_version"):
        assert m1[key]
    # same seed again (routes from cache, simulation re-run): bit-identical results
    m2 = baseline.run_baseline(**kw)
    metrics2 = json.loads((out / "metrics.json").read_text())
    assert m2["timings"]["assignment"]["cached"] is True
    assert metrics2["tripinfo_hash"] == metrics["tripinfo_hash"]
    assert metrics2["summary"] == s


def test_baseline_assignment_reproducible_from_seed(
    caches: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two assignments from empty route caches give identical routes and tripinfo (9.2)."""
    kw = {
        "daytype": "weekday",
        "seed": 1,
        "sample": 1.0,
        "net": DEMO_NET,
        "iterations": 2,
        "zone_dir": caches / "zones",
        "quiet": True,
    }
    results = []
    for k in range(2):
        monkeypatch.setattr(baseline, "ROUTE_CACHE", tmp_path / f"routes{k}")
        m = baseline.run_baseline(runs_dir=tmp_path / f"runs{k}", **kw)
        assert m["timings"]["assignment"]["cached"] is False
        metrics = json.loads((tmp_path / f"runs{k}" / m["run_id"] / "metrics.json").read_text())
        results.append((m["routes_hash"], metrics["tripinfo_hash"]))
    assert results[0] == results[1]
