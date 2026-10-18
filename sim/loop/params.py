"""Resolved Loop parameters: transform fields, else the defaults in sim/loop/config/loop.yaml."""

from __future__ import annotations

from typing import Any

from sim.loop.schema import LoopPrivate, LoopShuttle, loop_config


def capacity_figures(capacity: str, occupancy: float, cfg: dict[str, Any]) -> dict[str, float]:
    """Tunnel headway (s per vehicle) and station-pair capacity (passengers/h) of a scenario.

    measured: 1,355 pax/h per station pair (Vegas, July 2021) -> headway 3600 x occupancy / 1355.
    engineering: headway_s (1-2 s) -> 3600 / headway x occupancy pax/h per tunnel direction."""
    cap = cfg["capacity"]
    if capacity == "measured":
        pph = float(cap["measured"]["pax_per_hour_per_pair"])
        headway = 3600.0 * occupancy / pph
    elif capacity == "engineering":
        headway = float(cap["engineering"]["headway_s"])
        pph = 3600.0 / headway * occupancy
    else:
        raise ValueError(f"unknown capacity scenario {capacity!r}")
    return {"headway_s": round(headway, 3), "pair_capacity_pph": round(pph, 1)}


def resolve_params(
    t: LoopShuttle | LoopPrivate, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = cfg or loop_config()
    occ = float(t.occupancy or cfg["shuttle"]["occupancy"])
    capacity = t.capacity or cfg["capacity"]["default"]
    p: dict[str, Any] = {
        "speed_kmh": float(t.speed_kmh or cfg["tunnel"]["default_speed_kmh"]),
        "capacity": capacity,
        "occupancy": occ,
        **capacity_figures(capacity, occ, cfg),
        "wait_min": float(cfg["wait"][f"{capacity}_min"]),
    }
    if isinstance(t, LoopShuttle):
        acc, sh = cfg["access"], cfg["shift"]
        p |= {
            "mode": "shuttle",
            "alpha": float(sh["alpha"] if t.alpha is None else t.alpha),
            "radius_o_m": float(t.radius_o_m or acc["radius_m"]),
            "radius_d_m": float(t.radius_d_m or acc["radius_m"]),
            "dwell_s": float(cfg["station"]["dwell_s"] if t.dwell_s is None else t.dwell_s),
            "empty_reposition_factor": float(
                cfg["shuttle"]["empty_reposition_factor"]
                if t.empty_reposition_factor is None
                else t.empty_reposition_factor
            ),
            "max_pool_wait_s": float(cfg["shuttle"]["max_pool_wait_s"]),
            "shift_modes": list(sh["modes"]),
            "competitive_only": bool(
                sh["competitive_only"] if t.competitive_only is None else t.competitive_only
            ),
            "min_trip_km": float(acc["min_trip_km"] if t.min_trip_km is None else t.min_trip_km),
            "walk_speed_kmh": float(acc["walk_speed_kmh"]),
            "detour_factor": float(acc["detour_factor"]),
        }
        if t.mode_choice:
            p["mode_choice"] = t.mode_choice
    else:
        pr = cfg["private"]
        p |= {
            "mode": "private",
            "toll_sar": float(pr["toll_sar"] if t.toll_sar is None else t.toll_sar),
            "value_of_time_sar_h": float(t.value_of_time_sar_h or pr["value_of_time_sar_h"]),
            "reroute_radius_m": float(t.reroute_radius_m or pr["reroute_radius_m"]),
            "eligible_share": float(
                pr["eligible_share"] if t.eligible_share is None else t.eligible_share
            ),
            "min_trip_km": float(
                cfg["access"]["min_trip_km"] if t.min_trip_km is None else t.min_trip_km
            ),
        }
        p["toll_penalty_s"] = round(p["toll_sar"] / p["value_of_time_sar_h"] * 3600.0, 1)
    return p
