"""The reproducible OSM fix list: validation, resolution by OSM way id, and application."""

from __future__ import annotations

from pathlib import Path

import pytest
import sumolib
import yaml
from pydantic import ValidationError

from sim.network.fixes import DEFAULT_FIXES_DIR, Fix, apply_fixes, index_edges, load_fixes

BASE = {"reason": "test", "date": "2026-10-15", "author": "test"}


def _write(tmp: Path, fixes: list[dict]) -> Path:
    d = tmp / "fixes"
    d.mkdir(exist_ok=True)
    (d / "test.yaml").write_text(yaml.safe_dump({"fixes": fixes}))
    return d


def _two_way(net_path: Path) -> str:
    """An OSM way that has both directions in the demo network."""
    by_way = index_edges(net_path)
    for way, edges in sorted(by_way.items()):
        if any(e.startswith("-") for e in edges) and any(not e.startswith("-") for e in edges):
            return way
    raise AssertionError("no two-way OSM way in demo network")


def test_committed_fix_files_validate() -> None:
    fixes = load_fixes(DEFAULT_FIXES_DIR)
    assert len({f.id for f in fixes}) == len(fixes)


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "x", "field": "lanes", "value": 2},  # no target
        {"id": "x", "osm_way_id": 1, "edge_id": "a", "field": "lanes", "value": 2},  # two targets
        {"id": "x", "osm_way_id": 1, "field": "lanes", "value": 0},
        {"id": "x", "osm_way_id": 1, "field": "oneway", "value": "sideways"},
        {"id": "x", "osm_way_id": 1, "field": "colour", "value": "red"},
    ],
)
def test_invalid_fixes_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        Fix.model_validate({**bad, **BASE})


def test_lanes_and_speed_fix(tmp_path: Path, demo_net: Path) -> None:
    way = _two_way(demo_net)
    d = _write(
        tmp_path,
        [
            {"id": "t1", "osm_way_id": int(way), "field": "lanes", "value": 3, **BASE},
            {"id": "t2", "osm_way_id": int(way), "field": "speed", "value": 36, **BASE},
        ],
    )
    out = tmp_path / "fixed.net.xml"
    resolved = apply_fixes(demo_net, out, d)
    net = sumolib.net.readNet(str(out))
    for edge_id in resolved["t1"]:
        edge = net.getEdge(edge_id)
        assert edge.getLaneNumber() == 3
        assert edge.getSpeed() == pytest.approx(10.0, abs=0.01)


def test_oneway_and_remove_fix(tmp_path: Path, demo_net: Path) -> None:
    way = _two_way(demo_net)
    d = _write(
        tmp_path,
        [
            {"id": "t1", "osm_way_id": int(way), "field": "oneway", "value": "forward", **BASE},
        ],
    )
    out = tmp_path / "oneway.net.xml"
    resolved = apply_fixes(demo_net, out, d)
    ids = {e.getID() for e in sumolib.net.readNet(str(out)).getEdges()}
    assert not any(e in ids for e in resolved["t1"] if e.startswith("-"))
    assert any(e in ids for e in resolved["t1"] if not e.startswith("-"))

    d = _write(tmp_path, [{"id": "t2", "osm_way_id": int(way), "field": "remove", **BASE}])
    out = tmp_path / "removed.net.xml"
    resolved = apply_fixes(demo_net, out, d)
    ids = {e.getID() for e in sumolib.net.readNet(str(out)).getEdges()}
    assert resolved["t2"] and not ids & set(resolved["t2"])


def test_empty_fix_list_is_noop(tmp_path: Path, demo_net: Path) -> None:
    d = tmp_path / "none"
    d.mkdir()
    out = tmp_path / "same.net.xml"
    assert apply_fixes(demo_net, out, d) == {}
    before = {e.getID() for e in sumolib.net.readNet(str(demo_net)).getEdges()}
    after = {e.getID() for e in sumolib.net.readNet(str(out)).getEdges()}
    assert before == after


def test_stale_fix_fails_in_strict_mode(tmp_path: Path, demo_net: Path) -> None:
    d = _write(tmp_path, [{"id": "t1", "osm_way_id": 1, "field": "lanes", "value": 2, **BASE}])
    with pytest.raises(ValueError, match="matched no edge"):
        apply_fixes(demo_net, tmp_path / "x.net.xml", d)
    assert apply_fixes(demo_net, tmp_path / "y.net.xml", d, strict=False) == {"t1": []}


def test_lanes_min_only_raises(tmp_path: Path, demo_net: Path) -> None:
    from sim.network.fixes import edge_lanes

    lanes = edge_lanes(demo_net)
    by_way = index_edges(demo_net)
    way = next(w for w, es in sorted(by_way.items()) if len({lanes[e] for e in es}) > 1)
    top = max(lanes[e] for e in by_way[way])
    d = _write(
        tmp_path,
        [
            {"id": "t1", "osm_way_id": int(way), "field": "lanes_min", "value": top, **BASE},
        ],
    )
    out = tmp_path / "min.net.xml"
    resolved = apply_fixes(demo_net, out, d)
    after = edge_lanes(out)
    assert all(after[e] == top for e in resolved["t1"])
