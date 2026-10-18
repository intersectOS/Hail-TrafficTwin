"""Runner smoke runs on the demo window: teleports, metadata, determinism, tier guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from sim.common import content_hash
from sim.runner import assert_tier_options, run_smoke, runner_config


def test_tier_b_smoke(tmp_path: Path) -> None:
    meta = run_smoke("B", seed=1, end=900, runs_dir=tmp_path, quiet=True)
    r = meta["result"]
    assert meta["mode"] == "micro"
    assert meta["label"] == "synthetic demand, uncalibrated"
    assert r["vehicles_loaded"] > 300
    assert r["teleport_share"] < meta["teleport_share_max"]
    for key in ("seed", "config_hash", "network_hash", "population_hash", "sumo_version"):
        assert meta[key]


def test_tier_a_meso_smoke_on_demo(tmp_path: Path, demo_net: Path) -> None:
    meta = run_smoke("A", seed=1, net=demo_net, end=900, period=2.0, runs_dir=tmp_path, quiet=True)
    assert meta["mode"] == "meso"
    assert meta["result"]["teleport_share"] < meta["teleport_share_max"]


def test_same_seed_is_deterministic(tmp_path: Path) -> None:
    a = run_smoke("B", seed=7, end=600, runs_dir=tmp_path / "a", quiet=True)
    b = run_smoke("B", seed=7, end=600, runs_dir=tmp_path / "b", quiet=True)
    c = run_smoke("B", seed=8, end=600, runs_dir=tmp_path / "c", quiet=True)
    assert a["population_hash"] == b["population_hash"] != c["population_hash"]
    ta = tmp_path / "a" / a["run_id"] / "tripinfo.xml"
    tb = tmp_path / "b" / b["run_id"] / "tripinfo.xml"
    assert content_hash(ta) == content_hash(tb)


def test_micro_only_options_rejected_in_tier_a(tmp_path: Path) -> None:
    cfg = runner_config()
    with pytest.raises(ValueError, match="micro-only"):
        assert_tier_options("A", ["--fcd-output", "x.xml"], [], cfg)
    lane_level = ("--lanechange-output", "--queue-output", "--lanedata-output")
    for opt in (*lane_level, "--device.bluelight.explicit"):
        with pytest.raises(ValueError, match="micro-only"):
            assert_tier_options("A", [opt, "x"], [], cfg)
    add = tmp_path / "lane.add.xml"
    add.write_text('<additional><laneData id="l" file="l.xml"/></additional>')
    with pytest.raises(ValueError, match="laneData"):
        assert_tier_options("A", [], [add], cfg)
    assert_tier_options("B", ["--fcd-output", "x.xml"], [add], cfg)  # fine in Tier B
