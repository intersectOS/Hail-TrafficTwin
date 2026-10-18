"""Score and rank evaluated candidates (PROJECT.md 9.9 step 3).

score = w_time x ambulance travel time (s; not arrived by the horizon = A-strat-017 x horizon)
      + w_delay x background vehicle-hours added versus the no-strategy run
      + w_closure x junctions held + w_preempt x signals preempted          (lower is better)

Top N (model.top_n): distinct routes first (the best option of each route, in score order),
then filled with the next best options; the no-strategy run is the reference, never an option.
"""

from __future__ import annotations

from typing import Any

from strategist import config as C
from strategist.candidates import NO_STRATEGY_ID


def effective_tt(result: dict[str, Any], horizon_s: float) -> float:
    if result["arrived"] and result["travel_time_s"] is not None:
        return float(result["travel_time_s"])
    return float(C.value("evaluation", "not_arrived_factor")) * horizon_s


def score(
    result: dict[str, Any], baseline: dict[str, Any], weights: dict[str, float], horizon_s: float
) -> dict[str, Any]:
    added = round(result["background_veh_h"] - baseline["background_veh_h"], 4)
    terms = {
        "time": weights["w_time"] * effective_tt(result, horizon_s),
        "delay": weights["w_delay"] * added,
        "closure": weights["w_closure"] * result["junctions_held"],
        "preempt": weights["w_preempt"] * result["signals_preempted"],
    }
    return {
        "added_veh_h": added,
        "terms": {k: round(v, 4) for k, v in terms.items()},
        "score": round(sum(terms.values()), 4),
    }


def rank(
    candidates: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    weights: dict[str, float],
    horizon_s: float,
    top_n: int | None = None,
    distinct_routes: bool | None = None,
) -> dict[str, Any]:
    top_n = int(top_n if top_n is not None else C.model("top_n"))
    distinct = bool(C.model("top_routes_distinct") if distinct_routes is None else distinct_routes)
    base = results[NO_STRATEGY_ID]
    scored = []
    for c in candidates:
        s = score(results[c["id"]], base, weights, horizon_s)
        scored.append({"candidate_id": c["id"], "route_name": c["route_name"], **s})
    options = sorted(
        (s for s in scored if s["candidate_id"] != NO_STRATEGY_ID),
        key=lambda s: (
            s["score"],
            effective_tt(results[s["candidate_id"]], horizon_s),
            s["candidate_id"],
        ),
    )
    picked: list[dict[str, Any]] = []
    if distinct:
        routes: set[str] = set()
        for s in options:
            if s["route_name"] not in routes:
                picked.append(s)
                routes.add(s["route_name"])
    for s in options:
        if len(picked) >= top_n:
            break
        if s not in picked:
            picked.append(s)
    picked = sorted(picked[:top_n], key=lambda s: options.index(s))
    for i, s in enumerate(picked):
        s["rank"] = i + 1
    return {
        "scores": scored,
        "top": picked,
        "baseline": next(s for s in scored if s["candidate_id"] == NO_STRATEGY_ID),
    }
