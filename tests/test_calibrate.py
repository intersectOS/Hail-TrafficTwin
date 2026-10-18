"""M8 calibration on the demo window: adapters, GEH, and the synthetic counts round trip."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from sim.adapters.commercial import (
    COMMERCIAL_ADAPTERS,
    CountSource,
    Segment,
    TravelTimeSource,
)
from sim.adapters.counts import (
    CountRecord,
    aggregate,
    check_edges,
    read_counts,
    write_counts,
    write_edgedata,
)
from sim.adapters.synthetic import make_synthetic
from sim.adapters.traveltimes import TravelTimeRecord, compare, read_travel_times
from sim.calibrate import calibrate, geh, geh_report, latest_baseline, read_edgedata, resolve_inputs
from sim.common import SYNTHETIC_LABEL


def test_geh_values() -> None:
    assert geh(100, 100) == 0.0
    assert geh(0, 0) == 0.0
    assert geh(150, 100) == pytest.approx(math.sqrt(20))
    report = geh_report({("a", 0): 100.0, ("b", 0): 100.0}, {("a", 0): 10.0, ("b", 0): 60.0}, 0.1)
    assert [r["simulated"] for r in report["rows"]] == [100.0, 600.0]
    assert report["share_geh_ok"] == 0.5 and not report["passed"]


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_count_csv_validation(tmp_path: Path) -> None:
    ok = write_csv(
        tmp_path / "ok.csv", "detector_id,edge_id,hour,count\nD1,e1,7,100\nD2,e1,7,120\n"
    )
    records = read_counts(ok)
    assert aggregate(records) == {("e1", 7): 110.0}  # A-cal-003: mean of duplicates
    assert aggregate(records, "sum") == {("e1", 7): 220.0}
    bad = {
        "missing": "detector_id,edge_id,count\nD1,e1,5\n",
        "negative": "detector_id,edge_id,hour,count\nD1,e1,7,-1\n",
        "hour": "detector_id,edge_id,hour,count\nD1,e1,99,10\n",
        "text": "detector_id,edge_id,hour,count\nD1,e1,seven,10\n",
        "empty": "detector_id,edge_id,hour,count\n",
    }
    for name, text in bad.items():
        with pytest.raises(ValueError):
            read_counts(write_csv(tmp_path / f"{name}.csv", text))


def test_edgedata_round_trip(tmp_path: Path) -> None:
    targets = {("e1", 0): 104.0, ("e2", 0): 55.0, ("e1", 3): 20.0}
    path = write_edgedata(targets, tmp_path / "c.xml", scale=0.1)
    assert read_edgedata(path, "count") == {("e1", 0): 10.0, ("e2", 0): 6.0, ("e1", 3): 2.0}
    write_counts([CountRecord("D", "x", 2, 7.0)], tmp_path / "w.csv")
    assert read_counts(tmp_path / "w.csv") == [CountRecord("D", "x", 2, 7.0)]


def test_unknown_edges_flagged(tmp_path: Path, demo_net: Path) -> None:
    records = [CountRecord("D", "no_such_edge", 7, 10.0)]
    assert check_edges(records, demo_net) == ["no_such_edge"]


def test_travel_time_compare(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "tt.csv",
        "segment_id,edge_ids,hour,travel_time_s,samples\nS1,a b,8,100,12\nS2,c,8,50,0\n",
    )
    records = read_travel_times(path)
    assert records[0] == TravelTimeRecord("S1", ("a", "b"), 8, 100.0, 12)
    result = compare(records, {("a", 8): 40.0, ("b", 8): 70.0}, tolerance=0.15)
    assert result["matched"] == 1 and result["unmatched"] == ["S2@8"]
    assert result["share_within_tolerance"] == 1.0  # 110 s vs 100 s = +10 %
    with pytest.raises(ValueError):
        read_travel_times(write_csv(tmp_path / "bad.csv", "segment_id,edge_ids,hour\nS,a,1\n"))


def test_commercial_adapters_are_stubs() -> None:
    assert set(COMMERCIAL_ADAPTERS) == {"google_routes", "tomtom", "here"}
    for cls in COMMERCIAL_ADAPTERS.values():
        adapter = cls()
        assert isinstance(adapter, TravelTimeSource)
        assert not isinstance(adapter, CountSource)
        with pytest.raises(NotImplementedError, match="never committed"):
            adapter.fetch_travel_times([Segment("s", ("e",))], date(2026, 10, 16))


def test_missing_baseline_is_explained(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--net and --routes"):
        latest_baseline("weekday", tmp_path)


def test_daytype_defaults_from_baseline(tmp_path: Path, demo_net: Path) -> None:
    base = tmp_path / "baseline-friday-f0.1-s1-x"
    base.mkdir()
    (base / "routes.rou.xml.gz").write_bytes(b"")
    (base / "meta.json").write_text(json.dumps({"network": str(demo_net), "sample": 0.1}))
    net, routes, sample, run = resolve_inputs("friday", None, None, None, tmp_path)
    assert (net, routes, sample, run) == (demo_net, base / "routes.rou.xml.gz", 0.1, base.name)


@pytest.fixture(scope="module")
def round_trip(tmp_path_factory: pytest.TempPathFactory, demo_net: Path) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("m8")
    syn = make_synthetic(demo_net, root / "syn", seed=1, quiet=True)
    kwargs: dict[str, Any] = {
        "counts": root / "syn" / "counts.csv",
        "net": demo_net,
        "routes": root / "syn" / "candidates.rou.xml",
        "sample": 1.0,
        "seed": 1,
        "counts_source": "synthetic",
        "quiet": True,
    }
    a = calibrate(
        **kwargs, travel_times=root / "syn" / "traveltimes.csv", before=True, runs_dir=root / "a"
    )
    b = calibrate(**kwargs, runs_dir=root / "b")
    half = calibrate(**{**kwargs, "sample": 0.5}, runs_dir=root / "half")
    return {"syn": syn, "a": a, "b": b, "half": half, "root": root}


def test_synthetic_counts_are_labelled(round_trip: dict[str, Any]) -> None:
    syn = round_trip["syn"]
    assert "not real data" in syn["label"]
    assert syn["detectors"] >= 30 and syn["hours"] == [0, 1]
    assert syn["truth_routes_hash"] != syn["candidate_routes_hash"]


def test_round_trip_reaches_geh_target(round_trip: dict[str, Any]) -> None:
    meta = round_trip["a"]
    g = meta["geh"]
    assert g["share_geh_ok"] >= 0.85 and g["passed"]
    assert meta["geh_before"]["share_geh_ok"] < g["share_geh_ok"]  # the fit did the work
    assert meta["calibrated_vehicles"] < meta["candidate_vehicles"]
    assert meta["travel_times"]["matched"] > 0
    assert meta["label"] == SYNTHETIC_LABEL
    for key in (
        "seed",
        "config_hash",
        "network_hash",
        "counts_hash",
        "routes_hash",
        "sumo_version",
    ):
        assert meta[key]
    out = round_trip["root"] / "a" / meta["run_id"]
    for name in ("report.md", "geh.csv", "mismatch.xml", "calibrated.rou.xml", "traveltimes.json"):
        assert (out / name).exists(), name


def test_round_trip_is_deterministic(round_trip: dict[str, Any]) -> None:
    a, b = round_trip["a"], round_trip["b"]
    assert a["calibrated_routes_hash"] == b["calibrated_routes_hash"]
    assert a["run_id"] == b["run_id"] and a["geh"] == b["geh"]


def test_synthetic_inputs_regenerate_identically(
    round_trip: dict[str, Any], tmp_path: Path, demo_net: Path
) -> None:
    again = make_synthetic(demo_net, tmp_path / "syn", seed=1, quiet=True)
    for key in ("counts_hash", "candidate_routes_hash", "truth_routes_hash"):
        assert again[key] == round_trip["syn"][key], key


def test_sample_scaling(round_trip: dict[str, Any]) -> None:
    half = round_trip["half"]
    assert half["geh"]["passed"]
    assert half["calibrated_vehicles"] < 0.6 * round_trip["a"]["calibrated_vehicles"]


def test_assumptions_block_matches_settings() -> None:
    from sim.adapters import calibrate_config

    cfg = calibrate_config()
    reg = (Path(__file__).parent.parent / "docs" / "assumptions-trackA.md").read_text()
    for aid, entry in cfg["assumptions"].items():
        assert f"| {aid} |" in reg, aid
        assert "source" in entry or "assumption" in entry, aid
    a = cfg["assumptions"]
    assert a["A-cal-001"]["value"] == [cfg["geh"]["threshold"], cfg["geh"]["target_share"]]
    assert a["A-cal-002"]["value"] == cfg["travel_time"]["tolerance"]
    assert a["A-cal-003"]["value"] == cfg["counts"]["duplicate_policy"]
    syn = cfg["synthetic"]
    hours = (syn["end"] - syn["begin"]) // cfg["counts"]["interval_s"]
    assert a["A-cal-004"]["value"] == [syn["min_hourly_count"], syn["detectors"], hours]
    assert a["A-cal-005"]["value"] == cfg["route_sampler"]["vehicle_type"]
    bc = cfg["baseline_counts"]
    assert a["A-cal-006"]["value"] == [bc["detectors"], bc["min_each_hour"], bc["min_mean_hour"]]


def test_counts_from_baseline(tmp_path: Path) -> None:
    import pandas as pd

    from sim.adapters.baseline_counts import counts_from_baseline, parse_hours

    assert parse_hours("0-2,7") == [0, 1, 2, 7]
    run = tmp_path / "baseline-weekday-x"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({"sample": 0.1}))
    rows = [  # 300 s bins: busy edge "a" (40/h), quiet edge "b" (8/h), "c" empty in hour 8
        {"begin": float(b), "edge_id": e, "entered": float(n)}
        for b in range(7 * 3600, 9 * 3600, 300)
        for e, n in (("a", 40 / 12), ("b", 8 / 12), ("c", 60 / 12 if b < 8 * 3600 else 0))
    ]
    pd.DataFrame(rows).to_parquet(run / "edgedata.parquet")
    meta = counts_from_baseline(run, [7, 8], tmp_path / "c.csv", quiet=True)
    assert meta["eligible_edges"] == 1  # b is too quiet on average, c has an empty hour
    records = read_counts(tmp_path / "c.csv")
    assert [(r.edge_id, r.hour, r.count) for r in records] == [("a", 7, 400.0), ("a", 8, 400.0)]
