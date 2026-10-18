"""The bridge `network_change` transform for a city policy run.

1. Build the bridge variant of the plan's network (sim/bridge/network.py), with any closures /
   lane / speed edits of the same transform in the same patch.
2. Closures are handled exactly as Track A's netedit does (endpoints on removed edges move to the
   nearest open edge of the zone; routes through removed edges are re-routed).
3. Re-route candidates (A-obh-005): vehicles of the allowed classes whose baseline route uses an
   edge inside the `reroute.window` polygon, or whose origin-destination line crosses the creek.
   They get a one-shot route on the baseline's congested times (TA-014); `run_policy` then runs the
   matched control that re-routes the same vehicles on the base network (TA-018), so the report
   compares bridge vs no bridge under the same routing treatment.
"""

from __future__ import annotations

import json
from typing import Any

from sim.bridge.geo import creek_polygon, crosses, edge_points, edges_in, window_polygon
from sim.bridge.geo import repo_rel as rel
from sim.bridge.network import build_bridge_net
from sim.bridge.schema import BridgeNetworkChange, bridge_config
from sim.policies.edges import load_edges
from sim.policies.netedit import remap_endpoints
from sim.policies.transforms import Plan


def candidates(plan: Plan, t: BridgeNetworkChange, cfg: dict[str, Any]) -> dict[str, set[str]]:
    """Vehicles that may switch to the bridge, by reason (computed on the base network)."""
    from sim.policies.routes import routes_using
    from sim.population.export_trips import export_config

    vclass = {k: v["vClass"] for k, v in export_config()["vtypes"].items() if isinstance(v, dict)}
    v = plan.vehicles
    allowed = v["vtype"].astype(str).map(vclass).isin(cfg["reroute"]["vclasses"]).to_numpy()
    ids = set(v.loc[allowed, "veh_id"].astype(str))
    out: dict[str, set[str]] = {"window": set(), "desire": set()}
    edges = plan.edges()
    if t.reroute.window and plan.base_routes is not None:
        w_edges = edges_in(edges, window_polygon(t.reroute.window))
        out["window"] = routes_using(plan.base_routes, w_edges, ids)
    if t.reroute.desire_crossing:
        sel = v[allowed]
        o_lon, o_lat = edge_points(edges, sel["o_edge"])
        d_lon, d_lat = edge_points(edges, sel["d_edge"])
        hit = crosses(o_lon, o_lat, d_lon, d_lat, creek_polygon())
        out["desire"] = set(sel.loc[hit, "veh_id"].astype(str))
    return out


def bridge_network_change(plan: Plan, t: BridgeNetworkChange, policy_id: str) -> dict[str, Any]:
    from sim.policies.routes import routes_using

    cfg = bridge_config()
    base_net = plan.net
    base_edges = plan.edges()
    cand = candidates(plan, t, cfg)
    variant, info, _ = build_bridge_net(base_net, t, plan.work, cfg)
    missing: set[str] = set()
    if info["closed_edges"]:
        missing = set(base_edges["edge_id"]) - set(load_edges(variant)["edge_id"])
    plan.set_net(variant)
    plan.net_info = info
    moved = remap_endpoints(plan, missing)
    affected: set[str] = set()
    if plan.base_routes is not None and missing:
        affected = routes_using(plan.base_routes, missing)
    chosen = cand["window"] | cand["desire"]
    plan.force_reroute |= affected | chosen
    out: dict[str, Any] = {
        "variant_network": rel(variant),
        "bridges": info["bridges"],
        "span_m": info["span_m"],
        "edges_new": len(info["new_edges"]),
        "edges_closed": len(info["closed_edges"]),
        "endpoints_moved": moved,
        "vehicles_rerouted_closure": len(affected),
        "candidates_window": len(cand["window"]),
        "candidates_desire_crossing": len(cand["desire"]),
        "vehicles_rerouted_bridge": len(chosen),
    }
    effects = json.dumps({**out, "network": info}, indent=2, ensure_ascii=False, default=str)
    (plan.work / "bridge_effects.json").write_text(effects)
    return out


def apply(plan: Plan, t: Any, policy_id: str) -> dict[str, Any]:
    """Track A's dispatcher, plus `network_change` transforms that carry bridges."""
    from sim.policies import transforms as T

    if isinstance(t, BridgeNetworkChange) and t.bridges:
        eff = {"type": t.type, **bridge_network_change(plan, t, policy_id)}
        plan.effects.append(eff)
        return eff
    return T.apply(plan, t, policy_id)
