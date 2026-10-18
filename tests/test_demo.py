"""`make demo` orchestration (sim.demo) on the demo window: manifest, skip-when-done, the smoke
`--begin` override, and the quadrant demo districts. Seconds; the policy and Tier A steps are
covered by their own modules' tests (test_policies_run.py, test_runner.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim import demo
from sim.common import SYNTHETIC_LABEL
from sim.runner import run_smoke


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo-runs")
    demo.run_demo(("tier-b", "strategist"), seed=1, runs_dir=out)
    return out


def test_manifest_records_runs(runs: Path) -> None:
    m = json.loads(demo.manifest_path(runs).read_text())
    assert m["label"] == SYNTHETIC_LABEL
    tb, st = m["steps"]["tier-b-s1"], m["steps"]["strategist-s1"]
    assert tb["runs"][0].startswith("smoke-B-s1-") and (runs / tb["runs"][0] / "fcd.xml").exists()
    assert st["runs"] == ["strategist~emergency_demo-demo-s1"]
    assert len(st["options"]) == 3 and st["options"][0]["travel_time_s"] < st["no_strategy_s"]


def test_finished_steps_are_skipped(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = demo.manifest_path(runs).read_text()
    demo.run_demo(("tier-b", "strategist"), seed=1, runs_dir=runs)
    assert "tier-b: done earlier" in capsys.readouterr().out
    assert demo.manifest_path(runs).read_text() == before


def test_unknown_step_rejected() -> None:
    from typer.testing import CliRunner

    res = CliRunner().invoke(demo.app, ["--only", "nope"])
    assert res.exit_code != 0


def test_smoke_begin_override(tmp_path: Path) -> None:
    meta = run_smoke("B", 1, end=900, begin=600, runs_dir=tmp_path, quiet=True)
    assert meta["sim_seconds"] == 300
    assert meta["result"]["vehicles_loaded"] > 0
    with pytest.raises(ValueError):
        run_smoke("B", 1, end=600, begin=600, runs_dir=tmp_path, quiet=True)


def test_quadrant_districts_cover_the_window(tmp_path: Path) -> None:
    fc = json.loads(demo.quadrant_districts(tmp_path / "d.geojson").read_text())
    assert [f["properties"]["osm_id"] for f in fc["features"]] == [f"demo-{i}" for i in range(4)]
    xs = [x for f in fc["features"] for x, _ in f["geometry"]["coordinates"][0]]
    assert min(xs) == pytest.approx(39.148) and max(xs) == pytest.approx(39.166)
