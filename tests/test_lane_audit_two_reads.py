"""Lane audit attempt 2: two independent reads per crop, per-road cap, fresh holdout (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from sim.network import lane_audit as la


def _way(way_id: int, **kw) -> la.Way:
    base = dict(
        way_id=way_id,
        highway="motorway",
        oneway="yes",
        lanes_tag="3",
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


def _rec(lanes: int | None, conf: float) -> dict:
    return {"lanes_marked_side": lanes, "confidence": conf}


def test_combine_reads_requires_agreement_and_takes_lower_confidence() -> None:
    a = {1: _rec(3, 0.9), 2: _rec(3, 0.8), 3: _rec(None, 0.1), 4: _rec(2, 0.9)}
    b = {1: _rec(3, 0.6), 2: _rec(4, 0.9), 3: _rec(None, 0.1)}
    out = la.combine_reads(a, b)
    assert set(out) == {1, 2, 3}  # way 4 has only one read
    assert out[1]["agree"] and out[1]["lanes_marked_side"] == 3 and out[1]["confidence"] == 0.6
    assert not out[2]["agree"] and out[2]["lanes_marked_side"] is None
    assert out[2]["confidence"] == 0.0
    assert not out[3]["agree"]  # two nulls are not an agreed count


def test_evaluate_two_reads_chooses_threshold_on_agreed_crops_only() -> None:
    ways = [_way(i) for i in range(30)]
    a, b = {}, {}
    for i in range(20):  # 20 agreed: 17 right at 0.8, 3 wrong at 0.4
        right = i < 17
        a[i] = _rec(3 if right else 4, 0.8 if right else 0.4)
        b[i] = _rec(3 if right else 4, 0.9 if right else 0.5)
    for i in range(20, 30):  # 10 disagreements, never counted
        a[i], b[i] = _rec(3, 0.9), _rec(4, 0.9)
    rep = la.evaluate_two_reads(ways, a, b)
    assert rep["read_agreement"] == round(20 / 30, 4)
    assert rep["agreed_n"] == 20 and rep["agreed_precision_all"] == 0.85
    assert rep["threshold"] == 0.4 and rep["kept_at_threshold"] == 20 and rep["passed"]
    assert rep["single_read_exact"] == {"read-a": round(27 / 30, 4), "read-b": round(17 / 30, 4)}


def test_evaluate_two_reads_holdout_needs_min_kept_and_precision() -> None:
    ways = [_way(i) for i in range(12)]
    a = {i: _rec(3, 0.9) for i in range(12)}
    b = {i: _rec(3, 0.9 if i < 9 else 0.3) for i in range(12)}
    rep = la.evaluate_two_reads(ways, a, b, threshold=0.5)
    assert rep["kept_at_threshold"] == 9 and rep["precision_at_threshold"] == 1.0
    assert not rep["passed"]  # 9 < MIN_HOLDOUT_KEPT
    rep = la.evaluate_two_reads(ways, a, b, threshold=0.3)
    assert rep["kept_at_threshold"] == 12 and rep["passed"]


def test_stratified_sample_caps_ways_per_named_road() -> None:
    ways = [_way(i, name="Long Road") for i in range(20)]
    ways += [_way(100 + i, name=None) for i in range(4)]
    ways += [_way(200 + i, highway="trunk", name="Other Road") for i in range(10)]
    ways += [_way(300, highway="primary")]
    picked = la.stratified_calibration(
        ways, 30, seed=3, exclude=set(), classes=("motorway", "trunk"), max_per_road=5
    )
    names = [(w.highway, w.name) for w in picked]
    assert names.count(("motorway", "Long Road")) == 5
    assert names.count(("motorway", None)) == 4  # unnamed ways are not capped
    assert names.count(("trunk", "Other Road")) == 5
    assert all(w.highway in ("motorway", "trunk") for w in picked)
    again = la.stratified_calibration(
        ways, 30, seed=3, exclude=set(), classes=("motorway", "trunk"), max_per_road=5
    )
    assert [w.way_id for w in picked] == [w.way_id for w in again]


def test_audit_priority_restricted_to_classes() -> None:
    ways = [_way(1, lanes_tag=None), _way(2, lanes_tag=None, highway="primary")]
    ways.append(_way(3, lanes_tag=None, highway="trunk", length_m=900.0))
    picked = la.audit_priority(ways, cap=600, exclude=set(), classes=("motorway", "trunk"))
    assert [w.way_id for w in picked] == [1, 3]


def test_read_folders_hold_crops_only_in_two_orders(tmp_path: Path) -> None:
    ids = list(range(1, 46))
    for i in ids:
        p = tmp_path / "crops" / f"batch-{(i - 1) // 20:03d}" / f"{i}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
    (tmp_path / "ways.json").write_text("{}")
    layout = la.read_folders(tmp_path, ids, batch=20, seed=7)
    assert [len(b) for b in layout["read-a"]] == [20, 20, 5]
    assert layout["read-a"][0] == ids[:20]
    assert sorted(sum(layout["read-b"], [])) == ids and layout["read-b"][0] != ids[:20]
    files = {p.name for p in (tmp_path / "reads").rglob("*") if p.is_file()}
    assert files == {f"{i}.png" for i in ids}  # no ways.json or results beside the crops


def test_analyst_records_parses_json_lines_only() -> None:
    text = 'Here:\n{"file": "1.png", "way_id": 1, "lanes_marked_side": 3, "confidence": 0.8}\n'
    text += "```\n{broken\n"
    assert [r["way_id"] for r in la.analyst_records(text)] == [1]


def test_fix_entries_skip_disagreeing_reads() -> None:
    combined = la.combine_reads(
        {1: _rec(4, 0.9), 2: _rec(4, 0.9)}, {1: _rec(4, 0.8), 2: _rec(3, 0.9)}
    )
    tile = {"z": 19, "tile_x": 1, "tile_y": 2, "accessed": "2026-10-16"}
    entries, tally = la.fix_entries(
        [_way(1), _way(2)], combined, {1: tile, 2: tile}, 0.5, {1: 2, 2: 2}, "2026-10-16"
    )
    assert tally == {"raises": 1, "reads_disagree": 1}
    assert entries[0]["confidence"] == 0.8 and "2 independent reads agree" in entries[0]["reason"]


def test_committed_two_read_eval_is_consistent() -> None:
    """The committed attempt-2 eval only passes with a calibration threshold and a holdout that
    meets the target on enough agreed crops."""
    report = json.loads(la.EVAL_JSON.read_text())
    if report.get("protocol") != "two-reads":
        return
    if report["passed"]:
        assert report["threshold"] is not None
        hold = report["holdout"]
        assert hold["precision_at_threshold"] >= la.TARGET_PRECISION
        assert hold["kept_at_threshold"] >= la.MIN_HOLDOUT_KEPT
    else:
        assert not la.FIXES_YAML.exists()
