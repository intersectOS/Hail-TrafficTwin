"""Demo-window environment for Loop policies (data/demo, seconds per run).

    uv run python -m sim.loop.run loop_demo --demo

The demo window gets its own zones (Track A's fidelity setup: the window bbox split 2 x 2, 8,000
residents, A-fid-001), population and route caches and a 100 % baseline under `runs/loop-demo/`,
so nothing touches the city caches. Same mechanism as tests/test_loop_run.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sim.common import REPO_ROOT, load_yaml

DEMO = REPO_ROOT / "data" / "demo"
DEMO_RUNS = REPO_ROOT / "runs" / "loop-demo"


@contextmanager
def demo_env(root: Path = DEMO_RUNS) -> Iterator[dict[str, Any]]:
    """Zones and caches for the demo window; yields run_policy keyword arguments."""
    import sim.loop.network as N
    import sim.policies.edges as E
    import sim.population.baseline as baseline
    import sim.population.synthesize as synthesize
    from sim.fidelity import grid_districts
    from sim.population import zones as Z

    net = DEMO / "demo.net.xml"
    window = json.loads((DEMO / "demo.window.json").read_text())["definition"]
    fcfg = load_yaml(REPO_ROOT / "sim" / "population" / "config" / "fidelity.yaml")
    zone_dir = root / "zones"
    if not (zone_dir / "zones.json").exists():
        zcfg = Z.zones_config()
        zcfg["control_total"]["value"] = int(fcfg["residents"])
        zcfg["non_residential_districts"]["names"] = []
        districts = grid_districts(window["bbox"], int(fcfg["grid"]), root / "districts.geojson")
        zones, zone_edges = Z.build_zones(Z.ZoneInputs(districts=districts, net=net), zcfg)
        Z.write_zones(zones, zone_edges, zone_dir, {})
    saved = (synthesize.CACHE_DIR, baseline.ROUTE_CACHE, E.CACHE, N.CACHE)
    synthesize.CACHE_DIR, baseline.ROUTE_CACHE = root / "pop", root / "routes"
    E.CACHE = N.CACHE = root / "edges"
    try:
        yield {"net": net, "zone_dir": zone_dir, "baselines_dir": root / "baselines",
               "iterations": 1}  # fmt: skip
    finally:
        synthesize.CACHE_DIR, baseline.ROUTE_CACHE, E.CACHE, N.CACHE = saved
