"""Lane audit from imagery: tile maths, sampling, calibration scoring and the fix list (offline)."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
import yaml

from sim.network import lane_audit as la
from sim.network.fixes import apply_fixes, index_edges, load_fixes


def _way(way_id: int = 1, **kw) -> la.Way:
    base = dict(
        way_id=way_id,
        highway="primary",
        oneway="yes",
        lanes_tag=None,
        lanes_forward=None,
        lanes_backward=None,
        name=None,
        length_m=500.0,
        lon=39.16,
        lat=21.55,
        bearing=0.0,
    )
    base.update(kw)
    return la.Way(**base)


# ------------------------------------------------------------- tile maths


def test_tile_of_matches_slippy_map_formula() -> None:
    # z1: the four quadrants; Jeddah is in the north-east one
    assert la.tile_of(39.16, 21.55, 1) == (1, 0)
    # z19 tile for Tahlia Street, cross-checked with the OSM slippy-map formula
    x, y = la.tile_of(39.16, 21.55, 19)
    assert (x, y) == (319174, 229992)


def test_metres_per_pixel_at_jeddah_zoom19() -> None:
    assert la.metres_per_pixel(21.55, 19) == pytest.approx(0.2778, abs=0.001)


def test_tiles_for_crop_cover_rotated_crop() -> None:
    xs, ys, radius = la.tiles_for_crop(39.16, 21.55, 19, 512)
    assert radius >= 512 / 2 * 2**0.5
    gx, gy = la.global_pixel(39.16, 21.55, 19)
    assert xs.start * 256 <= gx - radius and (xs.stop) * 256 >= gx + radius
    assert ys.start * 256 <= gy - radius and (ys.stop) * 256 >= gy + radius


def test_midpoint_and_bearing() -> None:
    north = [(39.0, 21.0), (39.0, 21.01)]
    lon, lat, bearing = la.midpoint_and_bearing(north)
    assert lon == pytest.approx(39.0)
    assert lat == pytest.approx(21.005, abs=1e-5)
    assert bearing == pytest.approx(0.0, abs=0.01) or bearing == pytest.approx(360.0, abs=0.01)
    east = [(39.0, 21.0), (39.01, 21.0), (39.02, 21.0)]
    lon, _, bearing = la.midpoint_and_bearing(east)
    assert lon == pytest.approx(39.01, abs=1e-6)
    assert bearing == pytest.approx(90.0, abs=0.1)


def test_sample_point_uses_longest_segment() -> None:
    # short east-going stub, then a long north-going segment: sample in the middle of the long one
    coords = [(39.0, 21.0), (39.001, 21.0), (39.001, 21.02)]
    lon, lat, bearing = la.sample_point(coords)
    assert lon == pytest.approx(39.001, abs=1e-6)
    assert lat == pytest.approx(21.01, abs=1e-4)
    assert bearing == pytest.approx(0.0, abs=0.01) or bearing == pytest.approx(360.0, abs=0.01)


def test_way_from_feature_reverses_bearing_for_oneway_minus_one() -> None:
    feat = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[39.0, 21.0], [39.0, 21.01]]},
        "properties": {"@id": 7, "highway": "secondary", "oneway": "-1"},
    }
    way = la.way_from_feature(feat)
    assert way is not None and way.oneway == "-1"
    assert way.bearing == pytest.approx(180.0, abs=0.1)
    feat["properties"]["highway"] = "residential"
    assert la.way_from_feature(feat) is None


# ------------------------------------------------------------- truth and selection


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"oneway": "yes", "lanes_tag": "3"}, 3),
        ({"oneway": "no", "lanes_tag": "4"}, 2),
        ({"oneway": "no", "lanes_tag": "3"}, None),
        ({"oneway": "no", "lanes_tag": "3", "lanes_forward": "2"}, 2),
        ({"oneway": "yes", "lanes_tag": "2;3"}, None),
        ({"oneway": "yes"}, None),
    ],
)
def test_expected_lanes(kw: dict, expected: int | None) -> None:
    assert _way(**kw).expected_lanes() == expected


def _pool() -> list[la.Way]:
    ways = []
    i = 0
    for cls in la.CLASSES:
        for tagged in (True, False):
            for _ in range(12):
                i += 1
                ways.append(
                    _way(i, highway=cls, lanes_tag="3" if tagged else None, length_m=100.0 + i)
                )
    return ways


def test_stratified_calibration_is_balanced_deterministic_and_tagged() -> None:
    ways = _pool()
    a = la.stratified_calibration(ways, 40, seed=1, exclude=set())
    b = la.stratified_calibration(ways, 40, seed=1, exclude=set())
    assert [w.way_id for w in a] == [w.way_id for w in b]
    assert len(a) == 40 and all(w.tagged for w in a)
    counts = {c: sum(w.highway == c for w in a) for c in la.CLASSES}
    assert counts == dict.fromkeys(la.CLASSES, 10)


def test_audit_priority_orders_by_class_then_length_and_caps() -> None:
    ways = _pool()
    picked = la.audit_priority(ways, cap=20, exclude={13})
    assert len(picked) == 20 and not any(w.tagged for w in picked)
    assert [w.highway for w in picked] == ["motorway"] * 11 + ["trunk"] * 9
    assert picked[0].length_m > picked[1].length_m
    assert 13 not in {w.way_id for w in picked}


# ------------------------------------------------------------- calibration scoring


def test_choose_threshold_takes_largest_coverage_meeting_precision() -> None:
    pairs = [(0.9, True)] * 16 + [(0.9, False)] * 2 + [(0.5, True)] * 2 + [(0.5, False)] * 10
    curve = la.precision_curve(pairs)
    chosen = la.choose_threshold(curve, target=0.8, min_kept=15)
    assert chosen is not None and chosen["threshold"] == 0.9
    assert chosen["precision"] == pytest.approx(16 / 18, abs=1e-4)
    assert la.choose_threshold(curve, target=0.95, min_kept=15) is None


def test_choose_threshold_skips_unstable_dip() -> None:
    curve = [
        {"threshold": 0.4, "kept": 26, "precision": 0.81},
        {"threshold": 0.5, "kept": 20, "precision": 0.80},
        {"threshold": 0.55, "kept": 17, "precision": 0.76},  # dip above 0.4 and 0.5
        {"threshold": 0.6, "kept": 15, "precision": 0.80},
        {"threshold": 0.7, "kept": 5, "precision": 0.60},  # too few crops: ignored
    ]
    assert la.choose_threshold(curve, target=0.8, min_kept=15)["threshold"] == 0.6


def test_score_at_holdout() -> None:
    ways = [_way(i, lanes_tag="2") for i in range(1, 11)]
    results = {
        i: {"lanes_marked_side": 2 if i <= 6 else 3, "confidence": 0.9 if i <= 8 else 0.3}
        for i in range(1, 11)
    }
    hold = la.score_at(ways, results, 0.5)
    assert (hold["kept"], hold["correct"]) == (8, 6)
    assert hold["precision"] == pytest.approx(0.75) and hold["coverage"] == pytest.approx(0.8)


def test_evaluate_reports_agreement_and_confusion() -> None:
    ways = [_way(i, lanes_tag="3", highway="trunk") for i in range(1, 21)]
    results = {
        i: {"way_id": i, "lanes_marked_side": 3 if i <= 17 else 2, "confidence": 0.8}
        for i in range(1, 21)
    }
    report = la.evaluate(ways, results)
    assert report["agreement_all"] == pytest.approx(0.85)
    assert report["passed"] and report["threshold"] == 0.8
    assert report["by_class"]["trunk"]["confusion_truth_to_pred"]["3"] == {"3": 17, "2": 3}
    assert report["error_pred_minus_truth"] == {"-1": 3}


def test_read_results_ignores_non_json_lines(tmp_path: Path) -> None:
    (tmp_path / "b0.jsonl").write_text(
        'preamble\n{"file": "5.png", "way_id": 5, "lanes_marked_side": 3, "confidence": 0.9}\n'
    )
    assert la.read_results(tmp_path)[5]["lanes_marked_side"] == 3


# ------------------------------------------------------------- fix list


def test_fix_entries_threshold_and_field_choice() -> None:
    ways = [_way(i) for i in (1, 2, 3, 4, 5)]
    results = {
        1: {"lanes_marked_side": 4, "confidence": 0.9},  # raises -> lanes_min
        2: {"lanes_marked_side": 1, "confidence": 0.9},  # lowers -> lanes
        3: {"lanes_marked_side": 2, "confidence": 0.9},  # equals default -> no entry
        4: {"lanes_marked_side": 5, "confidence": 0.5},  # below threshold
        5: {"lanes_marked_side": 3, "confidence": 0.9},  # not in network
    }
    tile = {"z": 19, "tile_x": 10, "tile_y": 20, "accessed": "2026-10-16"}
    manifest = dict.fromkeys(range(6), tile)
    defaults = {1: 2, 2: 2, 3: 2, 4: 2}
    entries, tally = la.fix_entries(ways, results, manifest, 0.7, defaults, "2026-10-16")
    assert [(e["osm_way_id"], e["field"], e["value"]) for e in entries] == [
        (1, "lanes_min", 4),
        (2, "lanes", 1),
    ]
    assert tally == {
        "raises": 1,
        "lowers": 1,
        "confirms_default": 1,
        "below_threshold": 1,
        "not_in_network": 1,
    }
    assert entries[0]["source"] == "Esri World Imagery tile z19/10/20, accessed 2026-10-16"
    assert entries[0]["method"] == "imagery-analyst"


def test_imagery_fixes_validate_and_apply_on_demo(demo_net: Path, tmp_path: Path) -> None:
    by_way = index_edges(demo_net)
    way = next(int(w) for w, edges in sorted(by_way.items()) if len(edges) >= 1)
    defaults = la.way_default_lanes(demo_net, {way})
    assert way in defaults
    target = defaults[way] + 1
    entries, _ = la.fix_entries(
        [_way(way)],
        {way: {"lanes_marked_side": target, "confidence": 0.95}},
        {way: {"z": 19, "tile_x": 1, "tile_y": 2, "accessed": "2026-10-16"}},
        0.7,
        defaults,
        "2026-10-16",
    )
    fixes_dir = tmp_path / "fixes"
    fixes_dir.mkdir()
    out_yaml = fixes_dir / la.FIXES_YAML.name
    la.write_fix_yaml(entries, "# test\n", out_yaml)
    fixes = load_fixes(fixes_dir)
    assert fixes[0].confidence == 0.95 and fixes[0].method == "imagery-analyst"
    out = tmp_path / "demo.lanes.net.xml"
    resolved = apply_fixes(demo_net, out, fixes_dir)
    lanes_after = la.way_default_lanes(out, {way})
    assert resolved[f"IMG-{way}"] and lanes_after[way] == target


def test_committed_imagery_files_are_consistent() -> None:
    """If the audit outputs are committed, they agree: fixes only exist with a passed eval."""
    if not la.FIXES_YAML.exists():
        pytest.skip("no imagery fix list committed yet")
    import json

    report = json.loads(la.EVAL_JSON.read_text())
    assert report["passed"] and report["agreement_at_threshold"] >= la.TARGET_PRECISION
    entries = (yaml.safe_load(la.FIXES_YAML.read_text()) or {}).get("fixes", [])
    assert all(e["confidence"] >= report["threshold"] for e in entries)
    assert all(
        e["method"] == "imagery-analyst" and e["source"].startswith(la.TILE_SOURCE) for e in entries
    )


# ------------------------------------------------------------- inventory and crops


@pytest.mark.skipif(shutil.which("osmium") is None, reason="osmium-tool not installed")
def test_inventory_on_demo_extract(demo_osm: Path, tmp_path: Path) -> None:
    seq = la.export_major_ways(demo_osm, tmp_path)
    ways = la.read_geojsonseq(seq)
    assert ways and {w.highway for w in ways} <= set(la.CLASSES)
    summary = la.inventory_summary(ways)
    assert sum(v["ways"] for v in summary.values()) == len(ways)
    assert all(0 <= w.bearing < 360 and w.length_m > 0 for w in ways)


class _FakeCache:
    """Synthetic tiles: a vertical road stripe at the sample point, no network access."""

    def __init__(self, way: la.Way) -> None:
        self.gx, self.gy = la.global_pixel(way.lon, way.lat, la.ZOOM)

    def get(self, z: int, x: int, y: int) -> bytes:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (256, 256), (200, 180, 150))
        d = ImageDraw.Draw(img)
        sx = self.gx - x * 256
        d.rectangle([sx - 20, 0, sx + 20, 255], fill=(40, 40, 40))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()


def test_make_crop_geometry(tmp_path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    way = _way(42, bearing=0.0)
    rec = la.make_crop(way, _FakeCache(way), tmp_path / "42.png")  # type: ignore[arg-type]
    img = pil.open(tmp_path / "42.png")
    size = la.CROP_PX * la.OUT_SCALE
    assert img.size == (size, size + la.CAPTION_PX)
    # road stripe (dark) is at the centre column, away from the markers
    centre = img.getpixel((size // 2 + 10, size // 2))
    edge = img.getpixel((10, size // 2))
    assert sum(centre) < sum(edge)
    assert rec["way_id"] == 42 and (rec["tile_x"], rec["tile_y"]) == la.tile_of(39.16, 21.55, 19)
