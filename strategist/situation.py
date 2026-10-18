"""Resolve a strategist situation: scenario + window + seed -> inputs, event plans, dispatch time.

The situation is the scenario's background events (crash, rain, ...) plus ONE emergency trip
flagged `strategist: true`; its start is the dispatch time T at which the window state is saved.
Scenario ids resolve from strategist/scenarios/ first, then sim/scenarios/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sim.common import config_hash, content_hash, rel
from sim.events.netindex import NetIndex
from sim.events.registry import resolve_events
from sim.runner import runner_config
from sim.scenarios.run import SCENARIO_DIR as SIM_SCENARIO_DIR
from sim.scenarios.run import load_scenario, run_settings, window_inputs
from sim.scenarios.schema import EmergencyTrip, Scenario
from sim.vtypes.loader import load_library, resolve_mix
from sim.vtypes.schema import VTypeLibrary
from strategist.config import SCENARIO_DIR

LANE_CLOSING_TYPES = ("accident", "flood")  # plans whose `closed_lanes` are closed to everyone


def find_scenario(ref: str | Path) -> Path:
    path = Path(ref)
    if path.exists():
        return path
    for d in (SCENARIO_DIR, SIM_SCENARIO_DIR):
        cand = d / f"{ref}.yaml"
        if cand.exists():
            return cand
    raise FileNotFoundError(
        f"scenario {ref!r} not found in strategist/scenarios/ or sim/scenarios/"
    )


@dataclass
class Situation:
    scenario: Scenario
    scenario_path: Path
    window: str
    seed: int
    net: Path
    demand_src: Path
    extra_adds: list[Path]
    lib: VTypeLibrary
    mix: dict[str, float]
    plans: list[dict[str, Any]]  # background plans (everything but the strategist trip)
    trip: dict[str, Any]  # resolved strategist emergency trip (default fastest route)
    assumption_ids: list[str]
    idx: NetIndex
    runner_cfg: dict[str, Any] = field(default_factory=dict)
    sumo_options: list[Any] = field(default_factory=list)

    @property
    def t_dispatch(self) -> float:
        return float(self.trip["start"])

    def active_plans(self, t: float) -> list[dict[str, Any]]:
        out = []
        for p in self.plans:
            end = p.get("end")
            if float(p["start"]) <= t and (end is None or t < float(end)):
                out.append(p)
        return out

    def closed_lanes_at(self, t: float) -> set[str]:
        lanes: set[str] = set()
        for p in self.active_plans(t):
            if p["type"] in LANE_CLOSING_TYPES and t >= float(p.get("closure_start", p["start"])):
                lanes |= set(p.get("closed_lanes", []))
        return lanes

    def hashes(self) -> dict[str, str]:
        return {
            "network_hash": content_hash(self.net),
            "demand_hash": content_hash(self.demand_src),
            "extra_additionals": ",".join(f"{rel(p)}:{content_hash(p)}" for p in self.extra_adds),
        }

    def snapshot_key_material(self) -> dict[str, Any]:
        """Everything that changes the saved state at T."""
        return {
            "scenario_events": self.plans,
            "window": self.window,
            "seed": self.seed,
            "t": self.t_dispatch,
            "begin": self.scenario.begin,
            "mix": self.mix,
            "vtypes": self.lib.model_dump(mode="json"),
            "sumo_common": self.runner_cfg["sumo_common"],
            "tier_options": self.runner_cfg["tier_B"]["options"],
            "scenario_sumo_options": self.sumo_options,
            **self.hashes(),
        }

    def key(self) -> str:
        return config_hash(self.snapshot_key_material())


def strategist_trip(scen: Scenario) -> EmergencyTrip:
    trips = [e for e in scen.events if isinstance(e, EmergencyTrip) and e.strategist]
    if len(trips) != 1:
        raise ValueError(
            f"scenario {scen.id}: needs exactly one emergency_trip with strategist: true "
            f"(found {len(trips)})"
        )
    if trips[0].vehicles != 1:
        raise ValueError("strategist trips dispatch a single vehicle (vehicles: 1)")
    return trips[0]


def resolve_situation(ref: str | Path, window: str | None, seed: int) -> Situation:
    path = find_scenario(ref)
    scen = load_scenario(path)
    w = window or scen.window
    net, demand_src, extra = window_inputs(w)
    lib = load_library()
    mix = resolve_mix(scen.vtype_mix, lib)
    idx = NetIndex(net)
    trip_spec = strategist_trip(scen)
    plans, ids = resolve_events(scen, idx, lib)
    trip = next(p for p in plans if p["id"] == trip_spec.id)
    background = [p for p in plans if p["id"] != trip_spec.id]
    if trip["start"] <= scen.begin:
        raise ValueError("the strategist trip must start after the scenario begin (warm-up)")
    return Situation(
        scenario=scen,
        scenario_path=path,
        window=w,
        seed=seed,
        net=net,
        demand_src=demand_src,
        extra_adds=extra,
        lib=lib,
        mix=mix,
        plans=background,
        trip=trip,
        assumption_ids=ids,
        idx=idx,
        runner_cfg=runner_config(),
        sumo_options=run_settings()["sumo_options"],
    )
