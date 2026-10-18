"""Network statistics, edge GeoJSON export and building heights."""

from __future__ import annotations

import json
from pathlib import Path

import sumolib

from sim.common import REPO_ROOT, load_yaml
from sim.network.geo import building_height, read_poly
from sim.network.netinfo import edges_geojson, net_stats

HEIGHTS = load_yaml(REPO_ROOT / "sim" / "network" / "config" / "buildings.yaml")


def test_net_stats_match_sumolib(demo_net: Path) -> None:
    stats = net_stats(demo_net)
    net = sumolib.net.readNet(str(demo_net))
    assert stats.edges == len(net.getEdges())
    assert stats.traffic_lights == len(net.getTrafficLights())
    lane_km = sum(lane.getLength() for e in net.getEdges() for lane in e.getLanes()) / 1000
    assert abs(stats.lane_km - lane_km) < 0.05


def test_edges_geojson(tmp_path: Path, demo_net: Path) -> None:
    out = tmp_path / "edges.geojson"
    n = edges_geojson(demo_net, out)
    data = json.loads(out.read_text())
    assert n == len(data["features"]) == net_stats(demo_net).edges
    lon, lat = data["features"][0]["geometry"]["coordinates"][0]
    assert 39.1 < lon < 39.2 and 21.5 < lat < 21.6


def test_building_height_rules() -> None:
    per_level = HEIGHTS["metres_per_level"]["value"]
    assert building_height({"height": "12 m"}, HEIGHTS) == (12.0, "height_tag")
    assert building_height({"building:levels": "4"}, HEIGHTS) == (4 * per_level, "levels_tag")
    default = HEIGHTS["default_levels"]["value"] * per_level
    assert building_height({"height": "tall"}, HEIGHTS) == (default, "default")


def test_jeddah_poly_is_valid() -> None:
    poly = read_poly(REPO_ROOT / "data" / "osm" / "jeddah.poly")
    assert poly.is_valid
    assert poly.contains(poly.centroid)


def test_scc_on_demo(demo_net: Path) -> None:
    from sim.network.netinfo import scc_summary, strongly_connected

    assert strongly_connected({"a": {"b"}, "b": {"a", "c"}, "c": set()}) == [["b", "a"], ["c"]]
    summary = scc_summary(demo_net)
    assert summary["edges"] > 900
    # a cut window is far from strongly connected: boundary edges are entry-only or exit-only
    assert 0.3 < summary["main_component_share"] <= 1.0
    assert summary["components"] > 1
