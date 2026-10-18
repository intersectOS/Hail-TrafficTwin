"""TraCI-side strategy actions, stepped once per simulation step in a what-if fork.

All three are reversible and restore what they changed:
- `Preemption`: when the ambulance is within A-strat-007 of a signal on its route, movements
  losing green get yellow for A-strat-008 s, then the ambulance's links are green and every other
  link red (A-strat-009) until the ambulance has left the junction; then the saved program and
  phase are restored (`setProgram` + `setPhase`; the restored phase restarts its full duration).
- `RescueLane` (proxy for SUMO's bluelight rescue corridor, which needs the sublane model the
  saved state was not built with): one lane of each multi-lane route edge starting within
  A-strat-010 ahead is restricted to vClass emergency through the owner-based ClosureManager
  (vehicles on it change out, as with accident lane closures), and the ambulance is asked to use
  it (`vehicle.changeLane`, A-strat-012). Released as soon as the ambulance has left the edge.
- `SideEntryHold` (approval required): the internal lanes of every movement entering the route
  at the listed junctions are closed to all but vClass emergency from dispatch until
  A-strat-015 s after the ambulance passed the junction, at most A-strat-014 s.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sim.events.base import EventContext
from strategist import config as C


@dataclass
class Ambulance:
    vid: str
    present: bool = False
    route_index: int = 0
    pos_m: float = 0.0  # distance travelled along the route (internal lanes not counted)
    lane_index: int = 0
    gone: bool = False  # arrived (or removed)


class Preemption:
    def __init__(self, groups: list[dict[str, Any]], positions: list[float]) -> None:
        self.groups = [dict(g, state="pending") for g in groups]
        self.cum = positions
        self.lookahead = float(C.value("preemption", "lookahead_m"))
        self.yellow_s = float(C.value("preemption", "yellow_s"))
        self.others = str(C.value("preemption", "others_state"))
        self.activations: list[dict[str, Any]] = []

    def _target(self, cur: str, links: list[int]) -> str:
        return "".join("G" if i in links else self.others for i in range(len(cur)))

    def step(self, ctx: EventContext, amb: Ambulance) -> None:
        tl = ctx.conn.trafficlight
        for g in self.groups:
            if g["state"] == "pending":
                if not amb.present or amb.route_index > g["first_idx"]:
                    continue
                dist = self.cum[g["first_idx"] + 1] - amb.pos_m
                if dist > self.lookahead:
                    continue
                g["program"], g["phase"] = tl.getProgram(g["tls"]), tl.getPhase(g["tls"])
                cur = tl.getRedYellowGreenState(g["tls"])
                g["target"] = self._target(cur, g["links"])
                yellow = "".join(
                    "y" if c in "Gg" and t != "G" else c
                    for c, t in zip(cur, g["target"], strict=True)
                )
                g["t_on"] = ctx.t
                g["dist_on_m"] = round(dist, 1)
                g["state_on"] = cur
                if yellow != cur:
                    tl.setRedYellowGreenState(g["tls"], yellow)
                    g["state"], g["until"] = "yellow", ctx.t + self.yellow_s
                else:
                    tl.setRedYellowGreenState(g["tls"], g["target"])
                    g["state"] = "green"
                ctx.record("strategist", "preempt_on", tls=g["tls"], dist_m=g["dist_on_m"])
            if g["state"] == "yellow" and ctx.t >= g["until"]:
                tl.setRedYellowGreenState(g["tls"], g["target"])
                g["state"] = "green"
            if g["state"] in ("yellow", "green") and (amb.gone or amb.route_index > g["last_idx"]):
                self._restore(ctx, g)

    def _restore(self, ctx: EventContext, g: dict[str, Any]) -> None:
        tl = ctx.conn.trafficlight
        tl.setProgram(g["tls"], g["program"])
        tl.setPhase(g["tls"], g["phase"])
        g["state"] = "restored"
        held = ctx.t - g["t_on"]
        self.activations.append(
            {"tls": g["tls"], "junction": g["junction"], "t_on": g["t_on"], "held_s": held}
        )
        ctx.record("strategist", "preempt_off", tls=g["tls"], held_s=held)

    def finish(self, ctx: EventContext) -> None:
        for g in self.groups:
            if g["state"] in ("yellow", "green"):
                self._restore(ctx, g)

    def summary(self) -> dict[str, Any]:
        return {
            "signals_preempted": len({a["tls"] for a in self.activations}),
            "preempt_activations": len(self.activations),
            "preempt_held_s": sum(a["held_s"] for a in self.activations),
            "preempted": self.activations,
        }


class RescueLane:
    OWNER = "strategist.rescue"

    def __init__(self, lanes: list[dict[str, Any]], positions: list[float]) -> None:
        self.lanes = [dict(r, state="pending") for r in lanes]
        self.cum = positions
        self.lookahead = float(C.value("rescue_lane", "lookahead_m"))
        self.nudge_s = float(C.value("rescue_lane", "nudge_s"))
        self.used: list[str] = []

    def step(self, ctx: EventContext, amb: Ambulance) -> None:
        for r in self.lanes:
            owner = f"{self.OWNER}.{r['edge']}"
            if (
                r["state"] == "pending"
                and amb.present
                and amb.route_index <= r["idx"]
                and self.cum[r["idx"]] - amb.pos_m <= self.lookahead
            ):
                ctx.closures.restrict(owner, [r["lane"]], ["emergency"])
                r["state"] = "active"
                self.used.append(r["edge"])
            if r["state"] == "active":
                if amb.gone or amb.route_index > r["idx"]:
                    ctx.closures.release(owner)
                    r["state"] = "released"
                elif amb.route_index == r["idx"] and amb.lane_index != r["lane_index"]:
                    ctx.conn.vehicle.changeLane(amb.vid, r["lane_index"], self.nudge_s)

    def finish(self, ctx: EventContext) -> None:
        for r in self.lanes:
            if r["state"] == "active":
                ctx.closures.release(f"{self.OWNER}.{r['edge']}")
                r["state"] = "released"

    def summary(self) -> dict[str, Any]:
        return {"rescue_lane_edges": len(self.used)}


class SideEntryHold:
    OWNER = "strategist.hold"

    def __init__(self, holds: list[dict[str, Any]], t0: float) -> None:
        self.holds = [dict(h, state="pending") for h in holds]
        self.t0 = t0
        self.max_s = float(C.value("closure", "max_s"))
        self.clear_s = float(C.value("closure", "clear_s"))
        self.released: list[dict[str, Any]] = []

    def step(self, ctx: EventContext, amb: Ambulance) -> None:
        for h in self.holds:
            owner = f"{self.OWNER}.{h['junction']}"
            if h["state"] == "pending":
                ctx.closures.restrict(owner, h["via_lanes"], ["emergency"])
                h["state"], h["t_on"] = "active", ctx.t
                ctx.record(
                    "strategist", "hold_on", junction=h["junction"], lanes=len(h["via_lanes"])
                )
            if h["state"] == "active":
                if "passed_t" not in h and (amb.gone or amb.route_index >= h["idx"]):
                    h["passed_t"] = ctx.t
                due = ctx.t - self.t0 >= self.max_s or (
                    "passed_t" in h and ctx.t - h["passed_t"] >= self.clear_s
                )
                if due:
                    self._release(ctx, h)

    def _release(self, ctx: EventContext, h: dict[str, Any]) -> None:
        ctx.closures.release(f"{self.OWNER}.{h['junction']}")
        h["state"] = "released"
        self.released.append({"junction": h["junction"], "held_s": ctx.t - h["t_on"]})
        ctx.record("strategist", "hold_off", junction=h["junction"], held_s=ctx.t - h["t_on"])

    def finish(self, ctx: EventContext) -> None:
        for h in self.holds:
            if h["state"] == "active":
                self._release(ctx, h)

    def summary(self) -> dict[str, Any]:
        return {
            "junctions_held": len(self.released),
            "hold_s_total": sum(h["held_s"] for h in self.released),
        }
