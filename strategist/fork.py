"""Shared SUMO command line and the fork protocol (load a saved state, re-apply events).

Measured on SUMO 1.28 (tahlia and demo windows): `saveState` keeps vehicles, their routes
(including TraCI reroutes), vTypes, RNG states (with --save-state.rng) and the traffic-light
program and phase, but NOT lane permission changes made through TraCI (`lane.setAllowed`) nor
lane speed changes (`lane.setMaxSpeed`). So after `--load-state` every event that is active at T
is dispatched again with ctx.t = T (accident `on_start` closes the lanes and slows the opposite
carriageway again) and the closure is asserted. Events that ended before T are marked done
without dispatch; events that start after T run normally.

Events that cannot be re-applied idempotently are refused when active at T: rain and flood
(weather multipliers would compound on vType values stored in the state), motorcades and other
emergency trips (their vehicles already exist in the state).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sim.common import REPO_ROOT
from sim.events.base import Event, EventContext
from sim.events.registry import build_events
from sim.runner import assert_tier_options, flatten

REAPPLY_SUPPORTED = ("accident",)


def rel_arg(p: str | Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def sumo_args(spec: dict[str, Any], extra: list[str] | None = None) -> list[str]:
    """Same net, demand, additionals and model options for warm-up and every fork."""
    adds = [*spec["extra_additionals"], spec["vtypes_add"], *spec.get("run_additionals", [])]
    args = [
        "-n", rel_arg(spec["net"]),
        "-r", rel_arg(spec["demand"]),
        "--additional-files", ",".join(rel_arg(a) for a in adds),
        "--seed", str(spec["seed"]),
        *flatten(spec["sumo_common"]),
        *flatten(spec["tier_options"]),
        *(extra or []),
    ]  # fmt: skip
    assert_tier_options("B", args, [Path(a) for a in adds], spec["micro_cfg"])
    return args


def is_active(plan: dict[str, Any], t: float) -> bool:
    end = plan.get("end")
    return float(plan["start"]) <= t and (end is None or t < float(end))


def prepare_events(plans: list[dict[str, Any]], t: float) -> list[Event]:
    """Runtime events for a fork at time t; ended ones are marked done, unsupported refused."""
    events = build_events(plans)
    for ev in events:
        p = ev.plan
        if p.get("end") is not None and float(p["end"]) <= t:
            ev.state = "done"
        elif is_active(p, t) and p["type"] not in REAPPLY_SUPPORTED:
            raise NotImplementedError(
                f"event {ev.id} ({p['type']}) is active at the fork time {t}: re-applying it "
                f"after loadState is not supported (supported: {REAPPLY_SUPPORTED})"
            )
    return events


def reapply(ctx: EventContext, events: list[Event]) -> list[str]:
    """Dispatch events at ctx.t (= T) and assert that every lane they close is closed.

    Returns the lanes verified closed."""
    for ev in events:
        ev.dispatch(ctx)
    closed: list[str] = []
    for ev in events:
        if ev.state == "active" and ev.plan["type"] == "accident":
            for lane in ev.plan["closed_lanes"]:
                if ctx.conn.lane.getAllowed(lane):
                    raise AssertionError(f"lane {lane} not closed after loadState + re-apply")
                closed.append(lane)
    ctx.record("strategist", "events_reapplied", t=ctx.t, closed_lanes=closed)
    return closed
