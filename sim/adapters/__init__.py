"""Calibration data adapters (PROJECT.md 9.12).

`counts` and `traveltimes` read the open CSV formats a data partner delivers; `commercial` holds
interface-only stubs for commercial traffic APIs; `synthetic` makes counts from a simulation for the
round-trip test. Partner and commercial data is never committed: keep it outside the repo or under
the gitignored `data/` tree.
"""

from __future__ import annotations

from sim.common import REPO_ROOT, load_yaml

CALIBRATE_CONFIG = REPO_ROOT / "sim" / "adapters" / "config" / "calibrate.yaml"


def calibrate_config() -> dict:
    return load_yaml(CALIBRATE_CONFIG)
