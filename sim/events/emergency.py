"""Emergency trip: emergency vehicle(s) (vType `emergency`, bluelight device) from A to B at T.

Probe event: it also runs in the window baseline, so its travel time can be compared with and
without the other events (decision B-D-012). The route is fixed when the plan is resolved
(sumolib fastest path for vClass emergency), identical in baseline and scenario; a full closure
on it triggers the normal reroute logic. Free-flow reference = sum over route edges of
length / min(speed limit x vType speedFactor, vType maxSpeed), i.e. SUMO's allowed vehicle
speed per lane; internal junction lanes are not counted, so measured / free-flow >= 1.
`strategist: true` is only recorded in M5 (M6 acts on it).
"""

from __future__ import annotations

from typing import Any

from sim.events.base import EVENT_VEHICLE_PREFIX, Event, EventContext
from sim.events.config import model_setting, pick
from sim.events.netindex import NetIndex
from sim.scenarios.schema import EmergencyTrip
from sim.vtypes.schema import VTypeLibrary

EMERGENCY_TYPE = "emergency"


def resolve(
    spec: EmergencyTrip, idx: NetIndex, lib: VTypeLibrary, ids: list[str]
) -> dict[str, Any]:
    vt = lib.types[EMERGENCY_TYPE]
    route = idx.fastest_path(spec.from_edge, spec.to_edge, vt.vClass)
    sf = float(vt.params["speedFactor"].value) if "speedFactor" in vt.params else 1.0
    vmax = float(vt.params["maxSpeed"].value) if "maxSpeed" in vt.params else 55.56
    ff = idx.free_flow_times(route, sf, vmax)
    headway = (
        float(pick("emergency_trip", "headway_s", spec.headway_s, ids))
        if spec.vehicles > 1
        else 0.0
    )
    return {
        "type": "emergency_trip",
        "id": spec.id,
        "start": spec.start,
        "end": None,
        "max_end": spec.start + float(spec.max_duration_s or model_setting("max_trip_s")),
        "route": route,
        "route_length_m": round(sum(idx.edge(e).getLength() for e in route), 2),
        "ff_total_s": sum(ff),
        "vtype": EMERGENCY_TYPE,
        "vehicles": spec.vehicles,
        "headway_s": headway,
        "strategist": spec.strategist,
        "vehicle_ids": [f"{EVENT_VEHICLE_PREFIX}{spec.id}.{i}" for i in range(spec.vehicles)],
    }


class EmergencyEvent(Event):
    probe = True

    def __init__(self, plan: dict[str, Any]) -> None:
        super().__init__(plan)
        self.arrived: dict[str, float] = {}

    def on_start(self, ctx: EventContext) -> None:
        p = self.plan
        rid = f"{EVENT_VEHICLE_PREFIX}{self.id}.route"
        ctx.conn.route.add(rid, p["route"])
        for i, vid in enumerate(p["vehicle_ids"]):
            ctx.conn.vehicle.add(
                vid,
                rid,
                typeID=p["vtype"],
                depart=f"{self.start + i * p['headway_s']:.1f}",
                departLane="best",
                departSpeed="max",
            )
        ctx.record(
            self.id,
            "dispatch",
            vehicles=p["vehicle_ids"],
            route_edges=len(p["route"]),
            ff_s=round(p["ff_total_s"], 1),
            strategist=p["strategist"],
        )

    def on_step(self, ctx: EventContext) -> None:
        for vid in set(ctx.arrived) & set(self.plan["vehicle_ids"]):
            self.arrived[vid] = ctx.t
            ctx.record(self.id, "arrived", vehicle=vid)

    def finished(self, ctx: EventContext) -> bool:
        return ctx.t >= self.plan["max_end"] or len(self.arrived) == len(self.plan["vehicle_ids"])

    def on_end(self, ctx: EventContext) -> None:
        self.summary.update({"arrived": len(self.arrived), "ff_total_s": self.plan["ff_total_s"]})
