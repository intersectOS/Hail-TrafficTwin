"""The city builder, run end to end on the demo window's raw OSM."""

from __future__ import annotations

import json
from pathlib import Path

import sumolib
from typer.testing import CliRunner

from sim.common import load_yaml
from sim.network.build_city import DEFAULT_CONFIG, app, netconvert_args


def test_netconvert_args_flatten_and_typemaps() -> None:
    args = netconvert_args(load_yaml(DEFAULT_CONFIG))
    assert "--tls.guess-signals" in args
    assert args[args.index("--junctions.join-dist") + 1] == "20"
    type_files = args[args.index("--type-files") + 1].split(",")
    assert len(type_files) == 2
    assert all(Path(t).exists() for t in type_files)


def test_build_city_on_demo_osm(tmp_path: Path, demo_osm: Path) -> None:
    out = tmp_path / "demo_city.net.xml"
    fixes = tmp_path / "fixes"
    fixes.mkdir()
    result = CliRunner().invoke(
        app,
        ["--osm", str(demo_osm), "--out", str(out), "--fixes-dir", str(fixes), "--no-side-outputs"],
    )
    assert result.exit_code == 0, result.output
    net = sumolib.net.readNet(str(out))
    assert len(net.getEdges()) > 200
    assert net.hasGeoProj()
    # Tier A type overlay drops service roads
    assert not any(e.getType() == "highway.service" for e in net.getEdges())
    meta = json.loads((tmp_path / "demo_city.build.json").read_text())
    assert meta["network"]["edges"] == len(net.getEdges())
    assert meta["fixes"] == {}
