"""Strategist settings and score weights from YAML (registered parameters, no magic numbers)."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from sim.common import REPO_ROOT, load_yaml
from sim.vtypes.schema import Param, params_in

STRATEGIST_DIR = REPO_ROOT / "strategist"
SETTINGS_FILE = STRATEGIST_DIR / "strategist.yaml"
WEIGHTS_FILE = STRATEGIST_DIR / "weights.yaml"
SCENARIO_DIR = STRATEGIST_DIR / "scenarios"
RUNS_DIR = REPO_ROOT / "runs" / "strategist"
DEFAULT_DB = RUNS_DIR / "decisions.sqlite"
WEIGHT_KEYS = ("w_time", "w_delay", "w_closure", "w_preempt")


@cache
def _settings_tree() -> dict[str, Any]:
    return load_yaml(SETTINGS_FILE)


def param(section: str, key: str) -> Param:
    return Param.model_validate(_settings_tree()[section][key])


def value(section: str, key: str) -> Any:
    return param(section, key).value


def model(key: str) -> Any:
    return _settings_tree()["model"][key]


def settings() -> dict[str, Any]:
    """Flat {section.key: value} of every registered setting plus the model block."""
    out: dict[str, Any] = {}
    for path, raw in params_in({k: v for k, v in _settings_tree().items() if k != "model"}):
        out[path] = raw["value"]
    out["model"] = dict(_settings_tree()["model"])
    return out


def setting_ids() -> list[str]:
    tree = {k: v for k, v in _settings_tree().items() if k != "model"}
    return [raw["id"] for _, raw in params_in(tree)]


def load_weights(path: Path | None = None) -> dict[str, Any]:
    """Default weights (with ids), optionally overridden by a file (numbers or Param dicts).

    Returns {"values": {key: float}, "ids": [...], "overrides": {key: float}, "source": str}."""
    base = load_yaml(WEIGHTS_FILE)["weights"]
    values = {k: float(Param.model_validate(base[k]).value) for k in WEIGHT_KEYS}
    ids = [Param.model_validate(base[k]).id for k in WEIGHT_KEYS]
    overrides: dict[str, float] = {}
    if path is not None:
        data = load_yaml(Path(path))
        raw = data.get("weights", data)
        unknown = set(raw) - set(WEIGHT_KEYS)
        if unknown:
            raise ValueError(f"{path}: unknown weights {sorted(unknown)}; known {WEIGHT_KEYS}")
        for k, v in raw.items():
            overrides[k] = float(Param.model_validate(v).value if isinstance(v, dict) else v)
        values.update(overrides)
    return {
        "values": values,
        "ids": ids,
        "overrides": overrides,
        "source": str(path) if path else "strategist/weights.yaml",
    }
