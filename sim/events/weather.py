"""Rain: scale speedFactor, accel, decel, minGap and tau of every vType by a preset
(sim/events/weather.yaml) from start to end, then restore. Vehicles already in the window get
their individual speed factor rescaled as well (a vType's speedFactor only affects vehicles
inserted afterwards)."""

from __future__ import annotations

from typing import Any

from sim.events.base import Event, EventContext
from sim.events.config import preset
from sim.scenarios.schema import Rain

PROBE_VTYPE = "normal"  # vType whose parameters are logged before/during/after (observability)


def resolve(spec: Rain, ids: list[str]) -> dict[str, Any]:
    return {
        "type": "rain",
        "id": spec.id,
        "start": spec.start,
        "end": spec.end,
        "preset": spec.preset,
        "multipliers": preset(spec.preset, ids),
    }


class RainEvent(Event):
    def on_start(self, ctx: EventContext) -> None:
        before = ctx.weather.snapshot(PROBE_VTYPE)
        ctx.weather.apply(self.id, self.plan["multipliers"])
        during = ctx.weather.snapshot(PROBE_VTYPE)
        self.summary.update({"before": before, "during": during})
        ctx.record(self.id, "weather_on", preset=self.plan["preset"], vtype=PROBE_VTYPE, **during)

    def on_end(self, ctx: EventContext) -> None:
        ctx.weather.clear(self.id)
        after = ctx.weather.snapshot(PROBE_VTYPE)
        self.summary["after"] = after
        ctx.record(self.id, "weather_off", vtype=PROBE_VTYPE, **after)
