"""Resolve scenario events into plans (main process) and build runtime events (worker)."""

from __future__ import annotations

from typing import Any

from sim.events import accident, emergency, flood, motorcade, weather
from sim.events.base import Event
from sim.events.netindex import NetIndex
from sim.scenarios.schema import (
    Accident,
    EmergencyTrip,
    Evacuation,
    Flood,
    Motorcade,
    Rain,
    Scenario,
)
from sim.vtypes.schema import VTypeLibrary

PROBE_TYPES = {"emergency_trip"}  # events kept in the baseline (B-D-012)

EVENT_CLASSES: dict[str, type[Event]] = {
    "accident": accident.AccidentEvent,
    "rain": weather.RainEvent,
    "flood": flood.FloodEvent,
    "motorcade": motorcade.MotorcadeEvent,
    "emergency_trip": emergency.EmergencyEvent,
}


def resolve_events(
    scenario: Scenario, idx: NetIndex, lib: VTypeLibrary
) -> tuple[list[dict[str, Any]], list[str]]:
    """Plans (JSON-serialisable) and the register ids of the defaults they used."""
    plans: list[dict[str, Any]] = []
    ids: list[str] = []
    for ev in scenario.events:
        if isinstance(ev, Evacuation):
            raise NotImplementedError(
                f"event {ev.id}: evacuation scenarios (M7) run through sim.events.evacuation.run "
                "(sim.runner --scenario dispatches there; B-D-026)"
            )
        if isinstance(ev, Accident):
            plans.append(accident.resolve(ev, idx, ids))
        elif isinstance(ev, Rain):
            plans.append(weather.resolve(ev, ids))
        elif isinstance(ev, Flood):
            plans.append(flood.resolve(ev, idx, ids))
        elif isinstance(ev, Motorcade):
            plans.append(motorcade.resolve(ev, idx, lib, ids))
        elif isinstance(ev, EmergencyTrip):
            plans.append(emergency.resolve(ev, idx, lib, ids))
    return plans, list(dict.fromkeys(ids))


def baseline_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in plans if p["type"] in PROBE_TYPES]


def build_events(plans: list[dict[str, Any]]) -> list[Event]:
    if any(p["type"] == "evacuation" for p in plans) and "evacuation" not in EVENT_CLASSES:
        from sim.events.evacuation import register_event_classes  # lazy: avoids an import cycle

        register_event_classes()
    return [EVENT_CLASSES[p["type"]](p) for p in plans]


def vtypes_needed(plans: list[dict[str, Any]]) -> list[str]:
    return sorted({p["vtype"] for p in plans if "vtype" in p})
