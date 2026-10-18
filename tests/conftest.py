"""Shared fixtures: everything runs on the committed demo window (data/demo/), offline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sim.common import REPO_ROOT

DEMO = REPO_ROOT / "data" / "demo"

# The API reads districts and buildings from data/jeddah/ (gitignored, built by build_city). Tests
# use the committed demo-window extracts instead, so a fresh clone (and CI) needs no city build.
os.environ.setdefault("TT_DISTRICTS", str(DEMO / "districts.geojson"))
os.environ.setdefault("TT_BUILDINGS", str(DEMO / "buildings.geojson"))


@pytest.fixture(scope="session")
def demo_net() -> Path:
    path = DEMO / "demo.net.xml"
    assert path.exists(), "demo window missing: python -m sim.network.build_window --name demo"
    return path


@pytest.fixture(scope="session")
def demo_osm() -> Path:
    return DEMO / "demo.osm.gz"
