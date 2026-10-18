"""Network v2 (Track F): measured lane defaults, the OSM pre-pass, profiles, teleport analysis."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
import sumolib
from typer.testing import CliRunner

from sim.common import file_hash, load_yaml
from sim.network import lane_defaults as ld
from sim.network.build_city import DEFAULT_PROFILE, PROFILES, app, netconvert_args
from sim.network.teleports import hotspots, parse_log

STATS = Path(__file__).resolve().parents[1] / "sim" / "network" / "types" / "jeddah-lanes.json"


def test_tag_parsing() -> None:
    assert ld.parse_int("3") == 3
    assert ld.parse_int("2;3") == 2
    assert ld.parse_int("x") is None
    assert ld.parse_speed_kmh("60") == 60
    assert ld.parse_speed_kmh("40 mph") == pytest.approx(64.37, abs=0.01)
    assert ld.parse_speed_kmh("none") is None
    assert ld.is_oneway({"highway": "motorway"})
    assert not ld.is_oneway({"highway": "motorway", "oneway": "no"})
    assert ld.is_oneway({"highway": "secondary", "junction": "roundabout"})
    assert ld.lanes_per_direction({"highway": "primary", "oneway": "yes", "lanes": "4"}) == [4.0]
    assert ld.lanes_per_direction({"highway": "primary", "lanes": "3"}) == [1.5, 1.5]
    assert ld.lanes_per_direction({"highway": "primary", "lanes": "5", "lanes:forward": "3"}) == [
        3.0,
        2.0,
    ]
    assert ld.lanes_per_direction({"highway": "primary"}) == []


def test_weighted_median_is_km_weighted() -> None:
    # one long 3-lane way outweighs three short 2-lane ways
    assert ld.weighted_quantiles([2, 2, 2, 3], [1, 1, 1, 10], [0.5]) == [3.0]
    assert ld.weighted_quantiles([2, 2, 2, 3], [1, 1, 1, 1], [0.25, 0.5, 0.75]) == [2.0, 2.0, 2.0]


def _rec(hw: str, oneway: bool, km: float, lanes: list[float], speed: float | None = None):
    return ld.WayRecord(0, hw, oneway, km, lanes, speed)


def test_defaults_need_evidence_and_two_way_lanes_do_not_borrow() -> None:
    recs = [
        _rec("secondary", True, 10, [3.0], 80),
        _rec("secondary", True, 40, [], None),  # untagged
        _rec("secondary", False, 1, [1.0], None),  # too little two-way evidence
        _rec("tertiary", True, 2, [2.0], 50),  # under MIN_TAGGED_KM
    ]
    stats = ld.class_stats(recs)
    assert stats["secondary|oneway"]["lanes_tagged_share"] == pytest.approx(0.2)
    d = ld.derive_defaults(stats)
    assert d["secondary|oneway"]["lanes"] == 3
    assert d["secondary|oneway"]["maxspeed"] == 80
    # two-way: no lanes default (typemap stays); maxspeed falls back to the class median
    assert "lanes" not in d["secondary|twoway"]
    assert d["secondary|twoway"]["maxspeed"] == 80
    assert "tertiary|oneway" not in d


def test_added_tags_never_touch_tagged_ways() -> None:
    defaults = {"secondary|oneway": {"lanes": 3, "maxspeed": 80}, "primary|twoway": {"lanes": 2}}
    assert ld.added_tags({"highway": "secondary", "oneway": "yes"}, defaults) == {
        "lanes": "3",
        "maxspeed": "80",
        "traffictwin:defaults": "A-net-301;A-net-302",
    }
    tagged = {"highway": "secondary", "oneway": "yes", "lanes": "2", "maxspeed": "60"}
    assert ld.added_tags(tagged, defaults) == {}
    # two-way: total lanes = 2 x per direction
    assert ld.added_tags({"highway": "primary"}, defaults)["lanes"] == "4"
    assert ld.added_tags({"highway": "residential"}, defaults) == {}


def _gz(path: Path) -> str:
    with gzip.open(path, "rt") as fh:
        return fh.read()


def test_prepass_on_demo_osm(tmp_path: Path, demo_osm: Path) -> None:
    defaults = json.loads(STATS.read_text())["defaults"]
    out = tmp_path / "demo.v2.osm.gz"
    counts = ld.tag_osm(demo_osm, out, defaults)
    assert counts["ways"] > 100
    assert counts["lanes_added"] > 0
    text = _gz(out)
    src = _gz(demo_osm)
    assert text.count("<way ") == src.count("<way ")
    assert text.count('k="traffictwin:defaults"') == len(
        [1 for line in text.splitlines() if 'k="traffictwin:defaults"' in line]
    )
    # deterministic
    out2 = tmp_path / "again.osm.gz"
    ld.tag_osm(demo_osm, out2, defaults)
    assert _gz(out2) == text


def test_evidence_file_matches_registered_defaults() -> None:
    d = json.loads(STATS.read_text())["defaults"]
    # A-net-301 / A-net-302 (docs/assumptions-trackF.md) state these values
    assert {k: v.get("lanes") for k, v in d.items() if k.endswith("oneway")} == {
        "motorway|oneway": 4,
        "trunk|oneway": 3,
        "primary|oneway": 3,
        "secondary|oneway": 3,
        "tertiary|oneway": 2,
        "motorway_link|oneway": 2,
        "primary_link|oneway": 1,
    }


def test_profiles() -> None:
    assert DEFAULT_PROFILE == "v2"
    assert set(PROFILES) == {"v1", "m2", "v2"}
    assert all(p.exists() for p in PROFILES.values())
    v1 = load_yaml(PROFILES["v1"])
    v2 = load_yaml(PROFILES["v2"])
    assert v1["net"] == "data/jeddah/jeddah.net.xml"  # v1 unchanged
    assert v2["net"] != v1["net"]
    assert "lane_defaults" in v2 and "lane_defaults" not in v1
    assert "--type-files" in netconvert_args(v2)


def test_build_city_v2_profile_on_demo_osm(tmp_path: Path, demo_osm: Path) -> None:
    out = tmp_path / "demo_v2.net.xml"
    fixes = tmp_path / "fixes"
    fixes.mkdir()
    args = ["--osm", str(demo_osm), "--fixes-dir", str(fixes), "--no-side-outputs"]
    r2 = CliRunner().invoke(app, [*args, "--out", str(out)])
    assert r2.exit_code == 0, r2.output
    out1 = tmp_path / "demo_v1.net.xml"
    r1 = CliRunner().invoke(app, [*args, "--network-profile", "v1", "--out", str(out1)])
    assert r1.exit_code == 0, r1.output
    meta = json.loads((tmp_path / "demo_v2.build.json").read_text())
    assert meta["profile"] == "v2"
    # the pre-pass of a custom build lives beside its output, never in the city's data/osm/
    assert Path(meta["lane_defaults"]["osm_out"]).resolve().parent == tmp_path.resolve()
    assert meta["lane_defaults"]["input_hash"] == file_hash(demo_osm)
    # demo-sized (the city has ~155k edges)
    assert meta["network"]["edges"] < 5000
    # a second build reuses the pre-pass (same input and stats hashes): no counts recorded
    r3 = CliRunner().invoke(app, [*args, "--out", str(out)])
    assert r3.exit_code == 0, r3.output
    meta3 = json.loads((tmp_path / "demo_v2.build.json").read_text())
    assert "counts" not in meta3["lane_defaults"]
    assert meta3["network"]["net_hash"] == meta["network"]["net_hash"]
    assert json.loads((tmp_path / "demo_v1.build.json").read_text())["profile"] == "v1"

    def lane_km(path: Path) -> float:
        net = sumolib.net.readNet(str(path))
        return sum(e.getLength() * e.getLaneNumber() for e in net.getEdges())

    # measured defaults widen untagged major roads: more lane-km on the same OSM
    assert lane_km(out) > lane_km(out1)


LOG = """\
Warning: Teleporting vehicle 'a'; waited too long, from edge 'e1':0, time=3700.00.
Warning: Teleporting vehicle 'b'; waited too long, from edge 'e1':1, time=3800.50.
Warning: Teleporting vehicle 'c'; waited too long, from edge ':J5_3':0, time=7300.00.
Warning: Teleporting vehicle 'd'; waited too long, from edge 'e2-AddedOffRampEdge':0, time=10.
Warning: Vehicle 'a' ends teleporting on edge 'e3', time=3710.00.
"""


def test_teleport_log_parsing(tmp_path: Path) -> None:
    log = tmp_path / "sumo.log"
    log.write_text(LOG)
    locs, reasons, hours, total = parse_log(log)
    assert total == 4
    assert locs["edge:e1"].count == 2
    assert locs["junction:J5"].count == 1
    assert hours == {1: 2, 2: 1, 0: 1}
    res = hotspots(log, None, top=2)
    assert res["top"][0]["where"] == "e1"
    assert res["on_junction_internal_share"] == 0.25
    assert res["on_guessed_ramps_share"] == 0.25


def test_probe_on_demo_window(tmp_path: Path, demo_net: Path) -> None:
    from sim.network.probe import probe, window_trips

    trips = Path(__file__).resolve().parents[1] / "data" / "demo" / "demo.trips.xml"
    sub = tmp_path / "w.xml"
    assert window_trips(trips, sub, 0, 600) == sum(
        1
        for line in trips.read_text().splitlines()
        if line.lstrip().startswith("<trip ")
        and float(line.split('depart="')[1].split('"')[0]) < 600
    )
    res = probe(demo_net, trips, tmp_path / "p", begin=0, end=600, drain=300, sample=1.0, threads=2)
    assert res["vehicles_loaded"] > 100
    assert res["unroutable"] == 0
    assert res["teleport_share"] is not None and 0 <= res["teleport_share"] < 0.05
    assert res["mean_speed_kmh"] > 0
    again = probe(
        demo_net, trips, tmp_path / "q", begin=0, end=600, drain=300, sample=1.0, threads=2
    )
    assert (
        again["teleports"] == res["teleports"] and again["mean_speed_kmh"] == res["mean_speed_kmh"]
    )
