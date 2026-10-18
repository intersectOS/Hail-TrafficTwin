"""Evaluate candidates in parallel what-if forks of the saved window state (PROJECT.md 9.9 step 2).

Each candidate runs in its own spawned process with its own SUMO, started with the same net,
demand, additionals, options and seed plus `--load-state <snapshot>`; events active at T are
re-applied (strategist.fork), the ambulance is inserted at T on the candidate's route and the
candidate's actions are stepped until T + horizon (A-strat-016). Measured per run (light
outputs, no FCD): ambulance travel time (tripinfo definition: arrival - actual departure),
time per route edge, background vehicle-hours in the window (running + waiting to be inserted,
excluding the ambulance) over the horizon, background arrivals, teleports, the most-halted edges
on the route, signals preempted, rescue-lane edges and junctions held.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import traci.constants as tc

from sim.common import sumo_bin
from sim.events.base import EVENT_VEHICLE_PREFIX, EventContext
from sim.scenarios.simulate import start_sumo
from strategist import config as C
from strategist.controllers import Ambulance, Preemption, RescueLane, SideEntryHold
from strategist.fork import prepare_events, reapply, rel_arg, sumo_args

SECONDS_PER_HOUR = 3600.0


def run_candidate(spec: dict[str, Any]) -> dict[str, Any]:
    """spec: base snapshot spec + state, t, horizon_s, plans, candidate, trip, run_dir,
    outputs (bool: also write tripinfo/statistics for an applied option)."""
    cand = spec["candidate"]
    out = Path(spec["run_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t_start = float(spec["t"])
    t_end = t_start + float(spec["horizon_s"])
    extra = [
        "--load-state", rel_arg(spec["state"]),
        "--end", str(t_end),
        "--log", rel_arg(out / "sumo.log"),
    ]  # fmt: skip
    if spec.get("outputs"):
        extra += [
            "--tripinfo-output", rel_arg(out / "tripinfo.xml"),
            "--statistic-output", rel_arg(out / "stats.xml"),
        ]  # fmt: skip
    args = sumo_args(spec, extra)
    t0 = time.perf_counter()
    log = out / "sumo.stdout.log"
    log.unlink(missing_ok=True)
    conn = start_sumo([sumo_bin("sumo"), *args], log, label=f"{cand['id']}-{time.time_ns()}")
    try:
        t_loaded = float(conn.simulation.getTime())
        if abs(t_loaded - t_start) > 1e-6:
            raise AssertionError(f"state loaded at t={t_loaded}, expected {t_start}")
        ctx = EventContext(
            conn=conn, tier="B", t=t_loaded, distributions=frozenset(spec["distributions"])
        )
        events = prepare_events(spec["plans"], t_loaded)
        closed = reapply(ctx, events)
        result = _step_loop(conn, ctx, events, spec, t_end)
        result["closed_lanes_verified"] = closed
    finally:
        conn.close()
    result.update(
        {
            "candidate_id": cand["id"],
            "run_dir": str(out),
            "wall_s": round(time.perf_counter() - t0, 2),
            "event_log": ctx.log,
        }
    )
    return result


def _step_loop(
    conn: Any, ctx: EventContext, events: list[Any], spec: dict[str, Any], t_end: float
) -> dict[str, Any]:
    cand, trip = spec["candidate"], spec["trip"]
    route = cand["route"]
    cum = cand["positions"]
    vid = f"{EVENT_VEHICLE_PREFIX}{trip['id']}.0"
    rid = f"{EVENT_VEHICLE_PREFIX}{trip['id']}.route"
    conn.route.add(rid, route)
    conn.vehicle.add(
        vid, rid, typeID=trip["vtype"], depart=f"{ctx.t:.1f}", departLane="best", departSpeed="max"
    )
    ctx.record("strategist", "dispatch", vehicle=vid, candidate=cand["id"], route_edges=len(route))
    amb = Ambulance(vid)
    pre = Preemption(cand["signals_plan"], cum)
    rescue = RescueLane(cand["rescue_plan"], cum)
    hold = SideEntryHold(cand["holds_plan"], ctx.t)
    controllers = [
        c
        for c, plan in ((pre, "signals_plan"), (rescue, "rescue_plan"), (hold, "holds_plan"))
        if cand[plan]
    ]
    for e in dict.fromkeys(route):
        conn.edge.subscribe(e, [tc.LAST_STEP_VEHICLE_HALTING_NUMBER])
    conn.simulation.subscribe(
        [
            tc.VAR_DEPARTED_VEHICLES_IDS,
            tc.VAR_ARRIVED_VEHICLES_IDS,
            tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER,
        ]
    )
    veh_s = 0.0
    bg_arrived = 0
    teleports = 0
    halted_max: dict[str, tuple[int, float]] = {}
    depart_t = arrival_t = None
    edge_entry: dict[int, float] = {}
    step = float(conn.simulation.getDeltaT())
    while ctx.t < t_end:
        conn.simulationStep()
        ctx.t = conn.simulation.getTime()
        res = conn.simulation.getSubscriptionResults()
        ctx.departed = tuple(res.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
        ctx.arrived = tuple(res.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
        teleports += int(res.get(tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER, 0))
        if vid in ctx.departed:
            amb.present = True
            depart_t = float(conn.vehicle.getDeparture(vid))
            conn.vehicle.subscribe(
                vid, [tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION, tc.VAR_ROUTE_INDEX, tc.VAR_LANE_INDEX]
            )
        if vid in ctx.arrived:
            amb.present, amb.gone = False, True
            # tripinfo `arrival` is the time at the start of the step in which the vehicle
            # left (SUMO 1.28, checked against tripinfo); getTime() is already one step later
            arrival_t = ctx.t - step
        bg_arrived += len(ctx.arrived) - (1 if vid in ctx.arrived else 0)
        if amb.present:
            r = conn.vehicle.getSubscriptionResults(vid)
            amb.route_index = int(r[tc.VAR_ROUTE_INDEX])
            amb.lane_index = int(r[tc.VAR_LANE_INDEX])
            road = r[tc.VAR_ROAD_ID]
            amb.pos_m = (
                cum[amb.route_index + 1]
                if road.startswith(":")
                else cum[amb.route_index] + float(r[tc.VAR_LANEPOSITION])
            )
            edge_entry.setdefault(amb.route_index, ctx.t)
        for e, r in conn.edge.getAllSubscriptionResults().items():
            h = r[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
            if h > halted_max.get(e, (0, 0.0))[0]:
                halted_max[e] = (h, ctx.t)
        running = conn.vehicle.getIDCount() - (1 if amb.present else 0)
        waiting = conn.simulation.getPendingVehicles()
        pending = len(waiting) - (1 if vid in waiting else 0)
        veh_s += (running + pending) * step
        ctx.closures.on_step()
        for ev in events:
            ev.dispatch(ctx)
        for c in controllers:
            c.step(ctx, amb)
    for c in controllers:
        c.finish(ctx)
    arrived = arrival_t is not None
    tt = (arrival_t - depart_t) if arrived and depart_t is not None else None
    ff = cand["ff_s"]
    # time per route edge (entry to entry; last edge to the step after arrival)
    edge_times = {}
    idxs = sorted(edge_entry)
    for a, b in zip(idxs, [*idxs[1:], None], strict=True):
        end = (
            edge_entry[b]
            if b is not None
            else (arrival_t + step if arrival_t is not None else None)
        )
        if end is not None:
            edge_times[route[a]] = edge_times.get(route[a], 0.0) + end - edge_entry[a]
    top_n = int(C.model("top_halted_edges"))
    top_halted = sorted(
        ({"edge": e, "halted": h, "t": t} for e, (h, t) in halted_max.items() if h > 0),
        key=lambda x: (-x["halted"], x["edge"]),
    )[:top_n]
    out = {
        "arrived": arrived,
        "depart_t": depart_t,
        "arrival_t": arrival_t,
        "travel_time_s": tt,
        "free_flow_s": ff,
        "ratio_to_free_flow": round(tt / ff, 3) if tt and ff else None,
        "background_veh_h": round(veh_s / SECONDS_PER_HOUR, 4),
        "background_arrived": bg_arrived,
        "teleports": teleports,
        "route_halted_max": top_halted,
        "ambulance_edge_s": edge_times,
        "horizon_end_t": ctx.t,
        "signals_preempted": 0,
        "preempt_activations": 0,
        "preempt_held_s": 0.0,
        "preempted": [],
        "rescue_lane_edges": 0,
        "junctions_held": 0,
        "hold_s_total": 0.0,
    }
    for c in controllers:
        out.update(c.summary())
    return out


def evaluate(specs: list[dict[str, Any]], parallel: bool = True) -> list[dict[str, Any]]:
    if not parallel or len(specs) == 1:
        return [run_candidate(s) for s in specs]
    workers = min(int(C.model("max_workers")), len(specs))
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        return list(ex.map(run_candidate, specs))
