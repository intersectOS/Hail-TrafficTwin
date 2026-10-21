"""whatif_data writes a readable graph and hourly route files for the demo baseline."""

import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts.hail import whatif_data
from sim.common import REPO_ROOT

DEMO_NET = REPO_ROOT / "data" / "demo" / "demo.net.xml"


def test_whatif_data_demo(tmp_path: Path) -> None:
    runs = REPO_ROOT / "runs"
    if not DEMO_NET.exists() or not list(runs.glob("baseline-weekday-*/routes.rou.xml.gz")):
        pytest.skip("needs the demo network and a weekday baseline run")
    res = CliRunner().invoke(
        whatif_data.app, ["--net", str(DEMO_NET), "--runs", str(runs), "--out", str(tmp_path)]
    )
    assert res.exit_code == 0, res.output
    meta = json.loads((tmp_path / "graph.json").read_text())
    blob = (tmp_path / "graph.bin").read_bytes()
    assert blob[:4] == b"TTG1"
    n, m = struct.unpack("<II", blob[4:12])
    assert n == meta["edges"] and m == meta["succ"] and n > 100
    hours = sorted(tmp_path.glob("h*.bin"))
    assert hours and all(h.read_bytes()[:4] == b"TTR1" for h in hours)
    assert sum(meta["vehicles_per_hour"].values()) > 0
