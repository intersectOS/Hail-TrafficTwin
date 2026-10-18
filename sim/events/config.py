"""Event defaults and rain presets (YAML), with the register ids each run depends on."""

from __future__ import annotations

from functools import cache
from typing import Any

from sim.common import REPO_ROOT, load_yaml
from sim.vtypes.schema import Param

EVENTS_DIR = REPO_ROOT / "sim" / "events"
DEFAULTS_FILE = EVENTS_DIR / "events.yaml"
WEATHER_FILE = EVENTS_DIR / "weather.yaml"


@cache
def defaults() -> dict[str, Any]:
    return load_yaml(DEFAULTS_FILE)


@cache
def weather_presets() -> dict[str, dict[str, Param]]:
    raw = load_yaml(WEATHER_FILE)["presets"]
    return {name: {p: Param.model_validate(v) for p, v in d.items()} for name, d in raw.items()}


def model_setting(key: str) -> Any:
    return defaults()["model"][key]


def default(event_type: str, key: str) -> Param:
    return Param.model_validate(defaults()[event_type][key])


def pick(event_type: str, key: str, override: Any, ids: list[str]) -> Any:
    """The scenario's value if given (it carries its own source/assumption), else the
    registered default, whose id is appended to `ids`."""
    if override is not None:
        return override
    p = default(event_type, key)
    ids.append(p.id)
    return p.value


def preset(name: str, ids: list[str]) -> dict[str, float]:
    params = weather_presets()[name]
    ids.extend(p.id for p in params.values())
    return {k: float(p.value) for k, p in params.items()}
