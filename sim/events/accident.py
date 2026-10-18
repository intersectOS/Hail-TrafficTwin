"""Accident: close N lanes of an edge (or the whole edge) for a duration, with optional
rubbernecking (reduced speed limit) on the opposite-direction edge(s).

Lane closure = `lane.setAllowed(lane, [])` on the closed lanes (no class may use them, including
emergency vehicles: the lanes are physically blocked). Vehicles already on a closed lane change
out of it (checked on SUMO 1.28). When every lane of an edge is closed and `reroute` is true,
vehicles whose remaining route uses the edge reroute (A-event-003). SUMO lane index 0 is the
rightmost lane, so `side: left` closes the highest indices first.
"""

from __future__ import annotations

from typing import Any

from sim.events.base import Event, EventContext
from sim.events.config import model_setting, pick
from sim.events.netindex import NetIndex
from sim.scenarios.schema import Accident


def resolve(spec: Accident, idx: NetIndex, ids: list[str]) -> dict[str, Any]:
    idx.edge(spec.edge)  # raises with a clear message if the edge is not in the window
    parts = idx.split_parts(spec.edge) if spec.include_split_parts else [spec.edge]
    side = pick("accident", "side", spec.side, ids)
    reroute = bool(pick("accident", "reroute", spec.reroute, ids))
    closed: list[str] = []
    full = True
    for eid in parts:
        lanes = idx.lane_ids(eid)
        n = len(lanes) if spec.lanes_closed == "all" else min(int(spec.lanes_closed), len(lanes))
        order = lanes if side == "right" else list(reversed(lanes))
        closed += order[:n]
        full = full and n == len(lanes)
    rubber: dict[str, float] = {}
    factor = None
    if spec.rubbernecking:
        factor = float(pick("accident", "rubbernecking_factor", spec.rubbernecking_factor, ids))
        for eid in parts:
            for rev in idx.reverse_edges(
                eid,
                model_setting("opposite_search_m"),
                model_setting("opposite_sample_m"),
                tuple(model_setting("opposite_exclude_types")),
            ):
                for lane in idx.edge(rev).getLanes():
                    rubber[lane.getID()] = lane.getSpeed()
    return {
        "type": "accident",
        "id": spec.id,
        "start": spec.start,
        "end": spec.end,
        "edges": parts,
        "closed_lanes": closed,
        "full_closure": full,
        "side": side,
        "reroute": reroute and full,
        "rubbernecking_factor": factor,
        "rubbernecking_lanes": rubber,  # lane -> original speed limit (m/s)
    }


class AccidentEvent(Event):
    def on_start(self, ctx: EventContext) -> None:
        p = self.plan
        ctx.closures.restrict(self.id, p["closed_lanes"], [], reroute=p["reroute"])
        for lane, v in p["rubbernecking_lanes"].items():
            ctx.conn.lane.setMaxSpeed(lane, v * p["rubbernecking_factor"])
        disallowed = [ln for ln in p["closed_lanes"] if not ctx.conn.lane.getAllowed(ln)]
        self.summary["lanes_closed_verified"] = len(disallowed)
        self.summary["rubbernecking_speed_ms"] = {
            ln: round(ctx.conn.lane.getMaxSpeed(ln), 3) for ln in p["rubbernecking_lanes"]
        }
        ctx.record(
            self.id,
            "close_lanes",
            lanes=p["closed_lanes"],
            verified_disallowed=len(disallowed),
            full_closure=p["full_closure"],
            rerouted=ctx.closures.rerouted,
            rubbernecking_lanes=sorted(p["rubbernecking_lanes"]),
        )

    def on_end(self, ctx: EventContext) -> None:
        lanes = ctx.closures.release(self.id)
        for lane, v in self.plan["rubbernecking_lanes"].items():
            ctx.conn.lane.setMaxSpeed(lane, v)
        reopened = [ln for ln in lanes if ctx.conn.lane.getAllowed(ln)]
        self.summary["lanes_reopened_verified"] = len(reopened)
        ctx.record(self.id, "reopen_lanes", lanes=lanes, verified_reopened=len(reopened))
