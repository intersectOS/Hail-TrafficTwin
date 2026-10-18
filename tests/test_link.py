"""Tier link (sim/link.py) on the committed demo data, offline: graft, cut, GEH, windows."""

from __future__ import annotations

import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box

from sim.common import sumo_bin, sumo_env
from sim.link import (
    SERVICE_PREFIX,
    build_link_window,
    clean_exit_routes,
    cut_routes,
    geh,
    link_config,
    retime_tls,
)
from sim.network.build_window import WINDOWS_DIR, load_window

SUB_WINDOW = {"name": "sub", "bbox": [39.150, 21.545, 39.158, 21.552]}


def _connected(net_file: Path) -> dict[str, set[str]]:
    import sumolib

    net = sumolib.net.readNet(str(net_file))
    return {e.getID(): {t.getID() for t in e.getOutgoing()} for e in net.getEdges()}


@pytest.fixture(scope="module")
def demo_graft(tmp_path_factory: pytest.TempPathFactory, demo_net: Path, demo_osm: Path) -> dict:
    out = tmp_path_factory.mktemp("graft_demo")
    cfg = load_window("demo")
    meta = build_link_window(cfg, demo_net, demo_osm, out, link_config())
    return {"meta": meta, "dir": out}


def test_graft_demo_adds_connected_service_edges(demo_graft: dict) -> None:
    meta, out = demo_graft["meta"], demo_graft["dir"]
    g, v = meta["graft"], meta["validation"]
    assert g["service_edges_grafted"] > 50
    assert g["split_edges"] > 0
    assert v["sumo_load_ok"], v["sumo_load_errors"]
    assert v["city_edges_missing_count"] == 0  # every city edge id survives (first parts keep ids)
    assert v["untouched_edges_connections_changed"] == 0
    # most grafted service edges can be entered from and left to the city network
    assert v["service_connected_both_ways"] >= 0.9 * v["service_edges"]
    import json

    edgemap = json.loads((out / "demo.edgemap.json").read_text())
    succ = _connected(out / "demo.net.xml")
    for city, seq in edgemap.items():
        assert seq[0] == city
        assert all(b in succ[a] for a, b in zip(seq, seq[1:], strict=False)), city
    assert any(e.startswith(SERVICE_PREFIX) for e in succ)


@pytest.fixture(scope="module")
def tier_a_exit_routes(tmp_path_factory: pytest.TempPathFactory, demo_net: Path) -> Path:
    """Synthetic 'Tier A': demo random trips simulated in meso with exit times."""
    out = tmp_path_factory.mktemp("tiera")
    trips = Path(demo_net).with_name("demo.trips.xml")
    cmd = [
        sumo_bin("sumo"), "-n", str(demo_net), "-r", str(trips), "--end", "900",
        "--mesosim", "--meso-junction-control", "--no-step-log", "--no-warnings",
        "--vehroute-output", str(out / "vehroutes.xml"), "--vehroute-output.exit-times",
        "--vehroute-output.write-unfinished",
    ]  # fmt: skip
    subprocess.run(cmd, check=True, env=sumo_env(), capture_output=True)
    clean = out / "exit_routes.rou.xml"
    counts = clean_exit_routes(out / "vehroutes.xml", clean)
    assert counts["written"] > 100
    return clean


def test_cut_and_rewrite_valid_in_window(
    tmp_path: Path, demo_net: Path, demo_osm: Path, tier_a_exit_routes: Path
) -> None:
    lc = link_config()
    meta = build_link_window(SUB_WINDOW, demo_net, demo_osm, tmp_path, lc)
    import json

    edgemap = json.loads((tmp_path / "sub.edgemap.json").read_text())
    out = tmp_path / "sub.rou.xml"
    counts = cut_routes(tmp_path / "sub.cut.net.xml", tier_a_exit_routes, edgemap, out, 0.0, lc)
    assert counts["vehicles"] > 20
    assert meta["graft"]["service_edges_grafted"] > 0

    # SUMO loads every cut route in the grafted window without route errors
    log = tmp_path / "load.log"
    proc = subprocess.run(
        [sumo_bin("sumo"), "-n", str(tmp_path / "sub.net.xml"), "-r", str(out), "--end", "1",
         "--route-steps", "0", "--no-step-log", "--log", str(log)],
        env=sumo_env(), capture_output=True, text=True,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    text = log.read_text()
    bad = [ln for ln in text.splitlines() if ln.startswith(("Error", "Warning"))]
    assert not bad, bad[:5]

    # entry times are the Tier A exit times from the edge before the first window edge
    tier_a = {}
    for v in ET.parse(tier_a_exit_routes).getroot().iter("vehicle"):
        r = v.find("route")
        tier_a[v.get("id")] = (float(v.get("depart")), r.get("edges").split(),
                               [float(t) for t in r.get("exitTimes").split()])  # fmt: skip
    inverse = {w: c for c, seq in edgemap.items() for w in seq}
    departs = []
    for v in ET.parse(out).getroot().iter("vehicle"):
        departs.append(float(v.get("depart")))
        vid = v.get("id").split("_part")[0]
        depart, edges, exits = tier_a[vid]
        first = inverse.get(v.find("route").get("edges").split()[0])
        first = first or v.find("route").get("edges").split()[0]
        idx = edges.index(first)
        expected = depart if idx == 0 else exits[idx - 1]
        assert math.isclose(float(v.get("depart")), expected, abs_tol=0.01), vid
        assert float(v.get("depart")) >= depart
    assert departs == sorted(departs)


def test_time_shift(tmp_path: Path, demo_net: Path, tier_a_exit_routes: Path) -> None:
    from sim.network.build_window import cut_window

    cut = tmp_path / "sub.cut.net.xml"
    cut_window(demo_net, SUB_WINDOW, cut)
    a, b = tmp_path / "a.rou.xml", tmp_path / "b.rou.xml"
    cut_routes(cut, tier_a_exit_routes, {}, a, 0.0)
    cut_routes(cut, tier_a_exit_routes, {}, b, 600.0)
    da = [float(v.get("depart")) for v in ET.parse(a).getroot().iter("vehicle")]
    db = [float(v.get("depart")) for v in ET.parse(b).getroot().iter("vehicle")]
    assert len(da) == len(db) > 0
    assert all(math.isclose(y - x, 600.0, abs_tol=0.011) for x, y in zip(da, db, strict=True))


def test_geh() -> None:
    assert geh(0, 0) == 0.0
    assert geh(100, 100) == 0.0
    assert math.isclose(geh(150, 100), math.sqrt(2 * 50**2 / 250))
    assert geh(100, 150) == geh(150, 100)
    assert geh(1000, 1100) < 5 < geh(100, 200)


@pytest.mark.parametrize(
    "name", sorted(p.stem for p in WINDOWS_DIR.glob("*.yaml") if p.stem != "demo")
)
def test_window_yaml_area(name: str) -> None:
    cfg = load_window(name)
    assert cfg["out_dir"] == f"data/windows/{name}"
    geom = Polygon(cfg["polygon"]) if "polygon" in cfg else box(*cfg["bbox"])
    assert geom.is_valid
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32637", always_xy=True)
    area_km2 = shapely.transform(geom, lambda c: _project(to_utm, c)).area / 1e6
    assert 3.0 <= area_km2 <= 25.0, area_km2


def test_expected_windows_present() -> None:
    names = {p.stem for p in WINDOWS_DIR.glob("*.yaml")}
    assert {"tahlia", "kaia_corridor", "al_balad", "kau_faisaliyah"} <= names


def _project(tr: Transformer, coords):  # noqa: ANN001, ANN202 - shapely coordinate callback
    import numpy as np

    x, y = tr.transform(coords[:, 0], coords[:, 1])
    return np.column_stack([x, y])


def test_tls_retiming_additional(
    tmp_path: Path, demo_graft: dict, tier_a_exit_routes: Path
) -> None:
    """Webster retiming of the demo window's signal from its cut routes (Tier B additional)."""
    import json

    out_dir = demo_graft["dir"]
    net = out_dir / "demo.net.xml"
    edgemap = json.loads((out_dir / "demo.edgemap.json").read_text())
    routes = tmp_path / "demo.rou.xml"
    cut_routes(out_dir / "demo.cut.net.xml", tier_a_exit_routes, edgemap, routes, 0.0)
    add = tmp_path / "demo.tls.add.xml"
    meta = retime_tls(net, routes, add, link_config())
    original = {t.get("id"): t for t in ET.parse(net).getroot().iter("tlLogic")}
    new = list(ET.parse(add).getroot().iter("tlLogic"))
    assert len(new) == len(original) == len(meta["programs"]) >= 1
    for t in new:
        assert t.get("programID") == link_config()["tls"]["program_id"]
        old = [p.get("state") for p in original[t.get("id")].iter("phase")]
        assert [p.get("state") for p in t.iter("phase")] == old  # same phases, new durations
    log = tmp_path / "load.log"
    proc = subprocess.run(
        [sumo_bin("sumo"), "-n", str(net), "-r", str(routes), "-a", str(add), "--end", "60",
         "--no-step-log", "--log", str(log)],
        env=sumo_env(), capture_output=True, text=True,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert not [ln for ln in log.read_text().splitlines() if ln.startswith("Error")]
