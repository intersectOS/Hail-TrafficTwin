"""Candidate strategies for an emergency trip (PROJECT.md 9.9 step 1).

Routes: Yen's k-shortest loopless paths for vClass emergency on the edge graph with the lanes
closed at T removed, edge cost = the ambulance's free-flow time x the congestion ratio measured
at T (mean edgeData travel time over the last A-strat-001 seconds / free-flow time at the speed
limit, capped by A-strat-002). Diversity: a path is kept only if at most A-strat-005 of its length
is shared with every route kept before it, and its cost is within A-strat-006 x the best.

Per route r: (a) route only, (b) + signal preemption, (c) + preemption + rescue-lane proxy.
Plus one approval-required option: preemption + a short hold of the side entries upstream of
the most-halted edge, on the candidate route with the most halted vehicles at T. Plus the
no-strategy run: the default fastest route (sim.events.emergency.resolve), no interventions.
Variant (a) of a route identical to the default route is the no-strategy run itself and is not
duplicated.
"""

from __future__ import annotations

import math
import string
from typing import Any

from sim.events.netindex import NetIndex
from strategist import config as C
from strategist.graph import EdgeGraph, overlap
from strategist.situation import Situation

NO_STRATEGY_ID = "no_strategy"


def ambulance_speed(sit: Situation) -> tuple[float, float]:
    vt = sit.lib.types[sit.trip["vtype"]]
    sf = float(vt.params["speedFactor"].value) if "speedFactor" in vt.params else 1.0
    vmax = float(vt.params["maxSpeed"].value) if "maxSpeed" in vt.params else math.inf
    return sf, vmax


def edge_costs(sit: Situation, graph: EdgeGraph, edge_tt: dict[str, Any]) -> dict[str, float]:
    """Ambulance cost per edge (s) from the travel times measured before T."""
    sf, vmax = ambulance_speed(sit)
    cap = float(C.value("snapshot", "congestion_ratio_max"))
    mean = edge_tt["mean_over_window"]
    out: dict[str, float] = {}
    for eid in graph.succ:
        e = sit.idx.edge(eid)
        length, limit = e.getLength(), e.getSpeed()
        ff_amb = length / min(limit * sf, vmax) if limit > 0 else math.inf
        ratio = 1.0
        m = mean.get(eid)
        if m and m["sampledSeconds"] > 0 and length > 0 and limit > 0:
            ratio = min(cap, max(1.0, m["traveltime"] / (length / limit)))
        out[eid] = ff_amb * ratio
    return out


def k_routes(
    sit: Situation, graph: EdgeGraph, cost: dict[str, float]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    k = int(C.value("candidates", "k_routes"))
    max_paths = int(C.value("candidates", "yen_max_paths"))
    max_ov = float(C.value("candidates", "max_overlap"))
    max_ratio = float(C.value("candidates", "max_cost_ratio"))
    src, dst = sit.trip["route"][0], sit.trip["route"][-1]
    chosen: list[dict[str, Any]] = []
    examined = 0
    best = None
    for path, c in graph.yen(src, dst, cost):
        examined += 1
        best = c if best is None else best
        if c > max_ratio * best:
            break
        if all(overlap(path, r["edges"], graph.length) <= max_ov for r in chosen):
            chosen.append({"edges": path, "cost_s": round(c, 2)})
            if len(chosen) == k:
                break
        if examined >= max_paths:
            break
    sf, vmax = ambulance_speed(sit)
    for i, r in enumerate(chosen):
        r["rank"] = i + 1
        r["name"] = f"Route {string.ascii_uppercase[i]}"
        r["length_m"] = round(sum(graph.length[e] for e in r["edges"]), 1)
        r["ff_s"] = round(sum(sit.idx.free_flow_times(r["edges"], sf, vmax)), 2)
        r["is_default"] = r["edges"] == sit.trip["route"]
        r["overlap_with_default"] = round(overlap(r["edges"], sit.trip["route"], graph.length), 3)
    stats = {"paths_examined": examined, "routes_found": len(chosen), "k": k}
    return chosen, stats


def route_positions(idx: NetIndex, route: list[str]) -> list[float]:
    """cum[i] = distance from the start of the route to the start of route[i] (internal
    junction lanes not counted); cum[len] = route length."""
    cum = [0.0]
    for e in route:
        cum.append(cum[-1] + idx.edge(e).getLength())
    return cum


def signal_groups(idx: NetIndex, route: list[str]) -> list[dict[str, Any]]:
    """Traffic-light passages of a route: consecutive crossings of the same TLS are one group
    (a joined cluster), with the link indices the route uses."""
    crossings = []
    for i, (a, b) in enumerate(zip(route, route[1:], strict=False)):
        conns = idx.edge(a).getConnections(idx.edge(b))
        by_tls: dict[str, set[int]] = {}
        for c in conns:
            if c.getTLSID():
                by_tls.setdefault(c.getTLSID(), set()).add(int(c.getTLLinkIndex()))
        for tls, links in by_tls.items():
            crossings.append({"tls": tls, "links": links, "idx": i})
    groups: list[dict[str, Any]] = []
    for c in crossings:
        g = groups[-1] if groups else None
        if g and g["tls"] == c["tls"] and c["idx"] - g["last_idx"] <= 1:
            g["links"] |= c["links"]
            g["last_idx"] = c["idx"]
        else:
            groups.append(
                {
                    "tls": c["tls"],
                    "links": set(c["links"]),
                    "first_idx": c["idx"],
                    "last_idx": c["idx"],
                }
            )
    for g in groups:
        g["links"] = sorted(g["links"])
        g["junction"] = idx.edge(route[g["first_idx"]]).getToNode().getID()
    return groups


def rescue_lanes(
    idx: NetIndex, route: list[str], closed: set[str], vclass: str
) -> list[dict[str, Any]]:
    """Per route edge with >= A-strat-011 open lanes: the leftmost open lane that continues the
    route (0 = rightmost in SUMO) is reserved, provided every movement into and out of the edge
    still has another open lane (otherwise the reservation blocks the traffic ahead of the
    ambulance: measured on the demo window, where reserving the only target lane of an
    upstream edge left the ambulance stuck in the resulting queue)."""
    min_open = int(C.value("rescue_lane", "min_open_lanes"))
    out = []
    for i, eid in enumerate(route):
        e = idx.edge(eid)
        open_lanes = {
            ln.getIndex() for ln in e.getLanes() if ln.allows(vclass) and ln.getID() not in closed
        }
        if len(open_lanes) < min_open:
            continue
        if i + 1 < len(route):
            conns = e.getConnections(idx.edge(route[i + 1]))
            cont = {c.getFromLane().getIndex() for c in conns} & open_lanes
        else:
            cont = set(open_lanes)
        if not cont:
            continue
        lane = max(cont)
        others = open_lanes - {lane}
        ok_in = all(
            {c.getToLane().getIndex() for c in conns_in} & others
            for inc, conns_in in e.getIncoming().items()
            if inc.getFunction() != "internal"
            and any(c.getFromLane().getID() not in closed for c in conns_in)
        )
        ok_out = all(
            {c.getFromLane().getIndex() for c in conns_out} & others
            for conns_out in e.getOutgoing().values()
        )
        if ok_in and ok_out:
            out.append({"idx": i, "edge": eid, "lane_index": lane, "lane": f"{eid}_{lane}"})
    return out


def side_entries(idx: NetIndex, route: list[str], bottleneck_idx: int) -> list[dict[str, Any]]:
    """Route junctions within A-strat-013 upstream of the end of the bottleneck edge, with the
    internal lanes of every movement entering the route from another edge."""
    upstream = float(C.value("closure", "upstream_m"))
    cum = route_positions(idx, route)
    end_b = cum[bottleneck_idx + 1]
    holds = []
    for i in range(1, bottleneck_idx + 1):
        if end_b - cum[i] > upstream:
            continue
        via = idx.junction_movements(route[i - 1], route[i], "entering_only")
        if via:
            node = idx.edge(route[i]).getFromNode().getID()
            holds.append({"idx": i, "junction": node, "edge": route[i], "via_lanes": via})
    return holds


def _route_halted(route: list[str], halted: dict[str, int]) -> tuple[int, str | None, int]:
    """(total halted on the route, most-halted edge, its count) at T."""
    total = sum(halted.get(e, 0) for e in route)
    worst = max(route, key=lambda e: halted.get(e, 0))
    n = halted.get(worst, 0)
    return total, (worst if n else None), n


def build_candidates(
    sit: Situation, snapshot: dict[str, Any], edge_tt: dict[str, Any]
) -> dict[str, Any]:
    vclass = sit.lib.types[sit.trip["vtype"]].vClass
    closed = sit.closed_lanes_at(sit.t_dispatch)
    graph = EdgeGraph(sit.idx, vclass, closed)
    cost = edge_costs(sit, graph, edge_tt)
    routes, stats = k_routes(sit, graph, cost)
    halted = snapshot["measured_at_t"]["halted_by_edge"]
    default = sit.trip["route"]
    sf, vmax = ambulance_speed(sit)

    def route_info(edges: list[str]) -> dict[str, Any]:
        total, worst, n = _route_halted(edges, halted)
        return {
            "signals": signal_groups(sit.idx, edges),
            "rescue": rescue_lanes(sit.idx, edges, closed, vclass),
            "positions": route_positions(sit.idx, edges),
            "halted_at_t": total,
            "worst_edge_at_t": worst,
            "worst_edge_halted_at_t": n,
            "cost_s": round(graph.path_cost(edges, cost), 2) if graph.is_path(edges) else None,
            "ff_s": round(sum(sit.idx.free_flow_times(edges, sf, vmax)), 2),
            "edge_ff_s": dict(zip(edges, sit.idx.free_flow_times(edges, sf, vmax), strict=True)),
            "length_m": round(sum(sit.idx.edge(e).getLength() for e in edges), 1),
        }

    cands: list[dict[str, Any]] = [
        {
            "id": NO_STRATEGY_ID,
            "label": "No strategy (default route, no interventions)",
            "route_name": "default route",
            "route_rank": 0,
            "route": default,
            "actions": [],
            **route_info(default),
        }
    ]
    for r in routes:
        info = route_info(r["edges"])
        name = r["name"]
        reroute = [] if r["is_default"] else [{"type": "reroute", "route": name}]
        signals = info["signals"]
        variants = []
        if not r["is_default"]:
            variants.append((f"{name} only", reroute))
        if signals:
            pre = {"type": "preempt", "signals": len({g["tls"] for g in signals})}
            variants.append((f"{name} + signal preemption", [*reroute, pre]))
            if info["rescue"]:
                rl = {"type": "rescue_lane", "edges": len(info["rescue"])}
                variants.append((f"{name} + preemption + rescue lane", [*reroute, pre, rl]))
        elif info["rescue"]:
            rl = {"type": "rescue_lane", "edges": len(info["rescue"])}
            variants.append((f"{name} + rescue lane", [*reroute, rl]))
        for label, actions in variants:
            kinds = "+".join(a["type"] for a in actions) or "route"
            cands.append(
                {
                    "id": f"{name.split()[-1]}:{kinds}",
                    "label": label,
                    "route_name": name,
                    "route_rank": r["rank"],
                    "route": r["edges"],
                    "actions": actions,
                    **info,
                }
            )
    # approval-required closure option on the most congested candidate route
    if routes:
        r = max(routes, key=lambda x: (_route_halted(x["edges"], halted)[0], -x["rank"]))
        total, worst, _ = _route_halted(r["edges"], halted)
        if worst is not None:
            info = route_info(r["edges"])
            holds = side_entries(sit.idx, r["edges"], r["edges"].index(worst))
            if holds:
                name = r["name"]
                actions = [] if r["is_default"] else [{"type": "reroute", "route": name}]
                if info["signals"]:
                    actions.append(
                        {"type": "preempt", "signals": len({g["tls"] for g in info["signals"]})}
                    )
                actions.append({"type": "closure", "junctions": len(holds), "bottleneck": worst})
                cands.append(
                    {
                        "id": f"{name.split()[-1]}:" + "+".join(a["type"] for a in actions),
                        "label": f"{name} + side-entry hold upstream of the bottleneck"
                        + (" + preemption" if info["signals"] else ""),
                        "route_name": name,
                        "route_rank": r["rank"],
                        "route": r["edges"],
                        "actions": actions,
                        "holds": holds,
                        **info,
                    }
                )
    for c in cands:
        types = {a["type"] for a in c["actions"]}
        if "preempt" not in types:
            c["signals_plan"] = []
        else:
            c["signals_plan"] = c["signals"]
        c["rescue_plan"] = c["rescue"] if "rescue_lane" in types else []
        c["holds_plan"] = c.get("holds", []) if "closure" in types else []
    return {
        "candidates": cands,
        "routes": routes,
        "route_stats": stats,
        "closed_lanes_at_t": sorted(closed),
        "default_route_cost_s": round(graph.path_cost(default, cost), 2)
        if graph.is_path(default)
        else None,
    }
