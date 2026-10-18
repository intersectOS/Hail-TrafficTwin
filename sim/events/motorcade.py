"""Motorcade: a convoy of N `convoy` (vClass vip) vehicles along a route, with rolling closures.

Closure mechanism (decision B-D-014). Closing the route edges themselves with lane permissions
traps every normal vehicle already on the corridor ahead of the convoy (its next edge is closed),
which deadlocks in front of the convoy. The closure is therefore applied at the junctions: for
route edge k, every other movement through its from-node (mode `all_other_movements`,
A-event-009) or every movement entering edge k from another edge (`entering_only`) is closed to
all classes except the exempt ones (convoy vClass + emergency) by restricting the movement's
internal (via) lane. Cross and turning traffic is held at the stop line (checked on SUMO 1.28);
the corridor stays open, so traffic ahead keeps moving away from the convoy.

Timing per junction k (from the convoy's actual progress, not a fixed timetable):
  hold from  ETA(lead at node k) - lead_time_s (A-event-006)
  release at tail on edge k (junction passed) + clear_time_s (A-event-007)
ETA uses the free-flow time of the remaining route at the convoy's allowed speed.
"""

from __future__ import annotations

from itertools import accumulate
from typing import Any

from traci.exceptions import TraCIException

from sim.events.base import EVENT_VEHICLE_PREFIX, Event, EventContext
from sim.events.config import model_setting, pick
from sim.events.netindex import NetIndex
from sim.scenarios.schema import Motorcade
from sim.vtypes.schema import VTypeLibrary

CONVOY_TYPE = "convoy"


def resolve(spec: Motorcade, idx: NetIndex, lib: VTypeLibrary, ids: list[str]) -> dict[str, Any]:
    vt = lib.types[CONVOY_TYPE]
    vclass = vt.vClass
    if spec.route:
        route = list(spec.route)
        idx.check_route(route, vclass)
    else:
        route = idx.fastest_path(spec.from_edge, spec.to_edge, vclass)
    sf = float(vt.params["speedFactor"].value) if "speedFactor" in vt.params else 1.0
    vmax = float(vt.params["maxSpeed"].value) if "maxSpeed" in vt.params else 55.56
    ff = idx.free_flow_times(route, sf, vmax)
    hold = pick("motorcade", "hold", spec.hold, ids)
    holds = [
        idx.junction_movements(route[k - 1] if k else None, route[k], hold)
        for k in range(len(route))
    ]
    headway = float(pick("motorcade", "headway_s", spec.headway_s, ids))
    return {
        "type": "motorcade",
        "id": spec.id,
        "start": spec.start,
        "end": None,
        "max_end": spec.start + float(spec.max_duration_s or model_setting("max_trip_s")),
        "route": route,
        "lengths_m": [idx.edge(e).getLength() for e in route],
        "ff_s": ff,
        "ff_total_s": sum(ff),
        "hold_mode": hold,
        "hold_lanes": holds,
        "vehicles": spec.vehicles,
        "vtype": CONVOY_TYPE,
        "headway_s": headway,
        "lead_time_s": float(pick("motorcade", "lead_time_s", spec.lead_time_s, ids)),
        "clear_time_s": float(pick("motorcade", "clear_time_s", spec.clear_time_s, ids)),
        "exempt_vclasses": list(model_setting("exempt_vclasses")),
        "vehicle_ids": [f"{EVENT_VEHICLE_PREFIX}{spec.id}.{i}" for i in range(spec.vehicles)],
    }


class MotorcadeEvent(Event):
    def __init__(self, plan: dict[str, Any]) -> None:
        super().__init__(plan)
        n = len(plan["route"])
        self.state_k = ["pending"] * n
        self.passed_at: list[float | None] = [None] * n
        self.ffcum = [0.0, *accumulate(plan["ff_s"])]
        self.running: set[str] = set()
        self.arrived: set[str] = set()
        self.held_log: list[dict[str, Any]] = []

    def owner(self, k: int) -> str:
        return f"{self.id}#{k}"

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
        ctx.record(self.id, "convoy_dispatched", vehicles=len(p["vehicle_ids"]), route=p["route"])

    def _progress(self, ctx: EventContext) -> tuple[int, float, int]:
        """(lead route index, lead lane position, tail route index); -1 = not departed."""
        ids = self.plan["vehicle_ids"]
        self.running |= set(ctx.departed) & set(ids)
        done = set(ctx.arrived) & set(ids)
        self.arrived |= done
        self.running -= done
        n = len(self.plan["route"])
        lead_i, lead_pos, tail_i = -1, 0.0, n
        for vid in sorted(self.running):
            try:
                i = ctx.conn.vehicle.getRouteIndex(vid)
                pos = ctx.conn.vehicle.getLanePosition(vid)
            except TraCIException:
                continue
            if i > lead_i or (i == lead_i and pos > lead_pos):
                lead_i, lead_pos = i, pos
            tail_i = min(tail_i, i)
        if len(self.running) + len(self.arrived) < len(ids):
            tail_i = -1  # someone has not departed yet
        if self.arrived and not self.running and len(self.arrived) == len(ids):
            lead_i, tail_i = n, n
        return lead_i, lead_pos, tail_i

    def _eta(self, ctx: EventContext, k: int, lead_i: int, lead_pos: float) -> float:
        p = self.plan
        if lead_i < 0:
            return max(self.start, ctx.t) + self.ffcum[k]
        if k <= lead_i:
            return ctx.t
        v = p["lengths_m"][lead_i] / p["ff_s"][lead_i] if p["ff_s"][lead_i] else 1.0
        return ctx.t + self.ffcum[k] - self.ffcum[lead_i] - lead_pos / v

    def on_step(self, ctx: EventContext) -> None:
        p = self.plan
        lead_i, lead_pos, tail_i = self._progress(ctx)
        for k in range(len(p["route"])):
            st = self.state_k[k]
            if st == "pending":
                if self._eta(ctx, k, lead_i, lead_pos) - ctx.t <= p["lead_time_s"]:
                    self.state_k[k] = "held"
                    if p["hold_lanes"][k]:
                        ctx.closures.restrict(
                            self.owner(k), p["hold_lanes"][k], p["exempt_vclasses"]
                        )
                    self.held_log.append({"k": k, "edge": p["route"][k], "hold": ctx.t})
            elif st == "held":
                if self.passed_at[k] is None and tail_i >= k:
                    self.passed_at[k] = ctx.t
                if self.passed_at[k] is not None and ctx.t >= self.passed_at[k] + p["clear_time_s"]:
                    self._release(ctx, k)

    def _release(self, ctx: EventContext, k: int) -> None:
        self.state_k[k] = "released"
        ctx.closures.release(self.owner(k))
        for row in self.held_log:
            if row["k"] == k and "release" not in row:
                row["release"] = ctx.t

    def finished(self, ctx: EventContext) -> bool:
        if ctx.t >= self.plan["max_end"]:
            return True
        return all(s == "released" for s in self.state_k) and len(self.arrived) == len(
            self.plan["vehicle_ids"]
        )

    def on_end(self, ctx: EventContext) -> None:
        for k, st in enumerate(self.state_k):
            if st == "held":
                self._release(ctx, k)
        still = sum(
            1 for lane in ctx.closures.active.values() for o in lane if o.startswith(self.id + "#")
        )
        held_s = [r["release"] - r["hold"] for r in self.held_log if "release" in r]
        self.summary.update(
            {
                "convoy_arrived": len(self.arrived),
                "convoy_vehicles": len(self.plan["vehicle_ids"]),
                "junctions_held": len(self.held_log),
                "junctions_released": sum(1 for s in self.state_k if s == "released"),
                "closures_still_active": still,
                "mean_hold_s": round(sum(held_s) / len(held_s), 1) if held_s else 0.0,
                "max_hold_s": max(held_s) if held_s else 0.0,
                "ff_total_s": round(self.plan["ff_total_s"], 1),
            }
        )
        ctx.record(self.id, "closures_lifted", **self.summary)
