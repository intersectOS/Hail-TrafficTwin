"""Window cutter: edge ids stay identical to the source network (needed for the M5 tier link)."""

from __future__ import annotations

from pathlib import Path

import pytest
import sumolib

from sim.network.build_window import boundary_arg, cut_window, load_window


def test_demo_window_definition() -> None:
    cfg = load_window("demo")
    min_lon, min_lat, max_lon, max_lat = cfg["bbox"]
    assert min_lon < max_lon and min_lat < max_lat
    assert boundary_arg(cfg).count(",") == 3


def test_polygon_boundary_arg() -> None:
    cfg = {"polygon": [[39.1, 21.5], [39.2, 21.5], [39.2, 21.6]]}
    assert boundary_arg(cfg) == "39.1,21.5,39.2,21.5,39.2,21.6"


def test_unknown_window() -> None:
    with pytest.raises(Exception, match="no window definition"):
        load_window("does_not_exist")


def test_cut_subwindow_keeps_ids(tmp_path: Path, demo_net: Path) -> None:
    cfg = {"name": "sub", "bbox": [39.150, 21.545, 39.158, 21.552]}
    out = tmp_path / "sub.net.xml"
    cut_window(demo_net, cfg, out)
    src = {e.getID() for e in sumolib.net.readNet(str(demo_net)).getEdges()}
    sub = sumolib.net.readNet(str(out))
    ids = {e.getID() for e in sub.getEdges()}
    assert 10 < len(ids) < len(src)
    assert ids <= src
    for edge in sub.getEdges():
        lon, lat = sub.convertXY2LonLat(*edge.getFromNode().getCoord())
        assert 39.14 < lon < 39.17 and 21.54 < lat < 21.56
