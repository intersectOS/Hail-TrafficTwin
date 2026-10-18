"""Runtime side of events: the TraCI context, shared closure and weather managers, Event base.

Events are scheduled by simulation time: `on_start` when t >= start, `on_step` every step while
active, `on_end` when `finished()` (or at the horizon). All of this is Tier B (micro) only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from traci.exceptions import TraCIException

EVENT_VEHICLE_PREFIX = "ev."  # ids of vehicles added by events: ev.<event id>.<n>


def lane_edge(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


@dataclass
class EventContext:
    conn: Any  # traci.connection.Connection
    tier: str
    t: float = 0.0
    departed: tuple[str, ...] = ()
    arrived: tuple[str, ...] = ()
    log: list[dict[str, Any]] = field(default_factory=list)
    # vTypeDistribution ids: TraCI lists them among vTypes, but getters/setters on a
    # distribution act on a randomly drawn member type, so they must never be touched
    distributions: frozenset[str] = frozenset()
    closures: ClosureManager | None = None
    weather: WeatherManager | None = None

    def __post_init__(self) -> None:
        if self.tier != "B":
            raise ValueError("TraCI events are Tier B (microscopic) only")
        self.closures = ClosureManager(self)
        self.weather = WeatherManager(self)

    def record(self, event_id: str, action: str, **details: Any) -> None:
        self.log.append({"t": self.t, "event": event_id, "action": action, **details})


class ClosureManager:
    """Lane permission restrictions stacked by owner; restores the original permissions.

    Effective allowed classes of a lane = original allowed classes intersected with every active
    owner's allowed set (empty set = closed to everyone; TraCI `setAllowed(lane, [])` disallows
    all classes in SUMO 1.28, verified). Owners flagged `reroute` make vehicles whose remaining
    route crosses a fully closed edge reroute (at closure time and at departure).
    """

    def __init__(self, ctx: EventContext) -> None:
        self.ctx = ctx
        self.orig: dict[str, tuple[str, ...]] = {}
        self.active: dict[str, dict[str, frozenset[str]]] = {}  # lane -> owner -> allowed
        self.reroute_owners: set[str] = set()
        self.reroute_failures = 0
        self.rerouted = 0
        self._lane_count: dict[str, int] = {}

    def _apply(self, lane: str) -> None:
        conn = self.ctx.conn
        owners = self.active.get(lane, {})
        if not owners:
            conn.lane.setAllowed(lane, list(self.orig[lane]))
            return
        allowed = set(self.orig[lane])
        for s in owners.values():
            allowed &= s
        conn.lane.setAllowed(lane, sorted(allowed))

    def restrict(
        self, owner: str, lanes: list[str], allowed: list[str] | None = None, reroute: bool = False
    ) -> None:
        conn = self.ctx.conn
        for lane in lanes:
            if lane not in self.orig:
                self.orig[lane] = tuple(conn.lane.getAllowed(lane))
            self.active.setdefault(lane, {})[owner] = frozenset(allowed or [])
            self._apply(lane)
        if reroute:
            self.reroute_owners.add(owner)
            self.reroute_all()

    def release(self, owner: str) -> list[str]:
        released = []
        for lane, owners in self.active.items():
            if owner in owners:
                del owners[owner]
                self._apply(lane)
                released.append(lane)
        self.reroute_owners.discard(owner)
        return released

    def closed_edges(self) -> dict[str, frozenset[str]]:
        """Edges fully closed by a rerouting owner -> classes still allowed on them."""
        by_edge: dict[str, list[str]] = {}
        for lane, owners in self.active.items():
            if lane.startswith(":") or not (set(owners) & self.reroute_owners):
                continue
            by_edge.setdefault(lane_edge(lane), []).append(lane)
        out: dict[str, frozenset[str]] = {}
        for edge, lanes in by_edge.items():
            if edge not in self._lane_count:
                self._lane_count[edge] = self.ctx.conn.edge.getLaneNumber(edge)
            if len(lanes) == self._lane_count[edge]:
                allowed: set[str] = set()
                for lane in lanes:
                    a = set(self.orig[lane])
                    for s in self.active[lane].values():
                        a &= s
                    allowed |= a
                out[edge] = frozenset(allowed)
        return out

    def _maybe_reroute(self, vid: str, closed: dict[str, frozenset[str]]) -> None:
        conn = self.ctx.conn
        try:
            route = conn.vehicle.getRoute(vid)
            idx = conn.vehicle.getRouteIndex(vid)
            ahead = [e for e in route[max(idx, 0) + 1 :] if e in closed]
            if not ahead:
                return
            vclass = conn.vehicle.getVehicleClass(vid)
            if all(vclass in closed[e] for e in ahead):
                return
            conn.vehicle.rerouteTraveltime(vid)
            new_ahead = set(conn.vehicle.getRoute(vid)[max(idx, 0) + 1 :]) & set(closed)
            if new_ahead:
                self.reroute_failures += 1
            else:
                self.rerouted += 1
        except TraCIException:
            self.reroute_failures += 1

    def reroute_all(self) -> None:
        closed = self.closed_edges()
        if closed:
            for vid in self.ctx.conn.vehicle.getIDList():
                self._maybe_reroute(vid, closed)

    def on_step(self) -> None:
        if not self.reroute_owners or not self.ctx.departed:
            return
        closed = self.closed_edges()
        if closed:
            for vid in self.ctx.departed:
                self._maybe_reroute(vid, closed)


WEATHER_PARAMS = ("speedFactor", "accel", "decel", "minGap", "tau")


class WeatherManager:
    """Scales vType parameters by preset multipliers; a stack so overlapping events nest.

    Types keep their original values; vehicles already in the network get their individual speed
    factor rescaled (a type's speedFactor only affects vehicles inserted later)."""

    def __init__(self, ctx: EventContext) -> None:
        self.ctx = ctx
        self.stack: list[tuple[str, dict[str, float]]] = []
        self.orig: dict[str, dict[str, float]] = {}
        self.current: dict[str, float] = dict.fromkeys(WEATHER_PARAMS, 1.0)

    def _get(self, vtype: str, p: str) -> float:
        return float(getattr(self.ctx.conn.vehicletype, f"get{p[0].upper()}{p[1:]}")(vtype))

    def _set(self, vtype: str, p: str, v: float) -> None:
        getattr(self.ctx.conn.vehicletype, f"set{p[0].upper()}{p[1:]}")(vtype, v)

    def _set_effective(self, mult: dict[str, float]) -> None:
        conn = self.ctx.conn
        for vtype in conn.vehicletype.getIDList():
            if vtype in self.ctx.distributions:
                continue
            if vtype not in self.orig:
                self.orig[vtype] = {p: self._get(vtype, p) for p in WEATHER_PARAMS}
            for p in WEATHER_PARAMS:
                self._set(vtype, p, self.orig[vtype][p] * mult.get(p, 1.0))
        ratio = mult.get("speedFactor", 1.0) / self.current["speedFactor"]
        if ratio != 1.0:
            for vid in conn.vehicle.getIDList():
                conn.vehicle.setSpeedFactor(vid, conn.vehicle.getSpeedFactor(vid) * ratio)
        self.current = {p: mult.get(p, 1.0) for p in WEATHER_PARAMS}

    def apply(self, owner: str, mult: dict[str, float]) -> None:
        self.stack.append((owner, mult))
        self._set_effective(mult)

    def clear(self, owner: str) -> None:
        self.stack = [(o, m) for o, m in self.stack if o != owner]
        self._set_effective(self.stack[-1][1] if self.stack else {})

    def snapshot(self, vtype: str) -> dict[str, float]:
        return {p: round(self._get(vtype, p), 6) for p in WEATHER_PARAMS}


class Event:
    """Base class. `plan` is the resolved, JSON-serialisable event description."""

    probe = False  # probe events (emergency trips) also run in the baseline

    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan
        self.id: str = plan["id"]
        self.start: float = float(plan["start"])
        self.end: float | None = plan.get("end")
        self.state = "pending"
        self.summary: dict[str, Any] = {}

    def on_start(self, ctx: EventContext) -> None:  # pragma: no cover - interface
        pass

    def on_step(self, ctx: EventContext) -> None:
        pass

    def on_end(self, ctx: EventContext) -> None:  # pragma: no cover - interface
        pass

    def finished(self, ctx: EventContext) -> bool:
        return self.end is not None and ctx.t >= self.end

    def dispatch(self, ctx: EventContext) -> None:
        if self.state == "pending" and ctx.t >= self.start:
            self.state = "active"
            ctx.record(self.id, "start", type=self.plan["type"])
            self.on_start(ctx)
        if self.state == "active":
            self.on_step(ctx)
            if self.finished(ctx):
                self.close(ctx)

    def close(self, ctx: EventContext, horizon: bool = False) -> None:
        if self.state != "active":
            return
        self.on_end(ctx)
        self.state = "done"
        ctx.record(self.id, "end", horizon=horizon)
