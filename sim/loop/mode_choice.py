"""Car-vs-Loop mode choice: a binary logit on door-to-door generalised time (Track H).

Replaces the exogenous shift share alpha (A-loop-009) in shuttle mode. For every eligible tour
(all legs station-to-station on one line, Track D rule) and every leg:

    car   = baseline simulated time (duration + departure delay) + parking search (car driver)
            + ride-hail pickup wait x wait_mult + out-of-pocket cost / VOT
    Loop  = walk access + egress x walk_mult + (station wait + queue) x wait_mult
            + loading stop + ramps + tunnel ride + fare / VOT + ASC

in minutes; V = beta_ivt x minutes; a tour chooses on the sum over its legs (one mode per tour),
P(Loop) = 1 / (1 + exp(V_car - V_loop)). Queueing: a station pair whose expected demand in an
hour exceeds its capacity adds a deterministic queue wait, fed back by successive averages. The
tour's hashed draw is the alpha path's draw (`loop_shuttle:shift`), so a constant P = alpha selects
exactly the alpha path's tours. Riders above the pair capacity in their hour (arrival order) do
not shift; their tour stays by car. Coefficients: sim/loop/config/mode_choice.yaml (A-loop-021..).

    uv run python -m sim.loop.mode_choice sweep --source-root ../trackD     # offline, no SUMO

The offline sweep rebuilds the starting baseline's plan (no simulation) and evaluates the logit
for each candidate, service case and coefficient set; results in sim/loop/results/mode_choice.*.
"""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, load_yaml

LOOP_DIR = Path(__file__).resolve().parent
CONFIG = LOOP_DIR / "config" / "mode_choice.yaml"
RESULTS = LOOP_DIR / "results"
COEF_KEYS = ("beta_ivt_per_min", "vot_sar_h", "wait_mult", "walk_mult", "asc_loop_min", "fare_sar")


def load_mode_choice(path: str | Path = CONFIG) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = REPO_ROOT / p
    cfg = load_yaml(p)
    if cfg.get("kind") != "loop_mode_choice":
        raise ValueError(f"{p}: kind must be loop_mode_choice")
    missing = [k for k in COEF_KEYS if k not in cfg["coefficients"]]
    if missing:
        raise ValueError(f"{p}: coefficients missing {missing}")
    if float(cfg["coefficients"]["beta_ivt_per_min"]) > 0:
        raise ValueError(f"{p}: beta_ivt_per_min must be <= 0 (time is a disutility)")
    return cfg


def mc_hash(cfg: dict[str, Any]) -> str:
    keep = {k: cfg[k] for k in ("coefficients", "car", "queue")}
    return config_hash(keep)[:8]


def coefficients(cfg: dict[str, Any], **override: float) -> dict[str, float]:
    c = {k: float(cfg["coefficients"][k]) for k in COEF_KEYS}
    c.update({k: float(v) for k, v in override.items() if v is not None})
    return c


# ---------------------------------------------------------------------------- leg attributes


def ride_m(legs: pd.DataFrame, seg_len: dict[tuple[str, int], float]) -> np.ndarray:
    """Tunnel distance between the leg's stations (sum of segment lengths)."""
    return np.array([
        sum(seg_len[(ln, min(k, k + (1 if d > o else -1)))]
            for k in range(o, d, 1 if d > o else -1))
        for ln, o, d in zip(legs["line"], legs["os"], legs["ds"], strict=True)
    ], dtype=float)  # fmt: skip


def portal_s(legs: pd.DataFrame, stations: pd.DataFrame, cfg: dict[str, Any]) -> np.ndarray:
    """Ramp time at both ends (down + up ramps, plus any connection beyond the ramp length);
    the same estimate as Track D's time-competitive filter (keep_competitive)."""
    tun = cfg["tunnel"]
    v = float(tun["ramp_speed_kmh"]) / 3.6
    ramp_m = float(tun["ramp_length_m"])
    st = stations.set_index(["line", "k"])["connect_m"]
    extra = np.array([
        max(st[(ln, o)] - ramp_m, 0) + max(st[(ln, d)] - ramp_m, 0)
        for ln, o, d in zip(legs["line"], legs["os"], legs["ds"], strict=True)
    ], dtype=float)  # fmt: skip
    return 2 * ramp_m / v + extra / v


def leg_table(
    plan: Any,
    cand: pd.DataFrame,
    legs: pd.DataFrame,
    stations: pd.DataFrame,
    seg_len: dict[tuple[str, int], float],
    p: dict[str, Any],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """One row per eligible leg with the attributes the logit needs (service-independent except
    speed, which enters via `ride_m`). `cand`/`legs` as in sim.loop.transforms.loop_shuttle."""
    rows = cand.loc[legs["row"].to_numpy()]
    walk = p["walk_speed_kmh"] / 3.6
    access_s = legs["access_m"].to_numpy() * p["detour_factor"] / walk
    egress_s = legs["egress_m"].to_numpy() * p["detour_factor"] / walk
    t = pd.DataFrame({
        "tour_id": rows["tour_id"].to_numpy(), "leg": rows["leg"].to_numpy(),
        "person_id": rows["person_id"].to_numpy(), "car_mode": rows["mode"].astype(str).to_numpy(),
        "line": legs["line"].to_numpy(), "os": legs["os"].to_numpy(), "ds": legs["ds"].to_numpy(),
        "depart": rows["depart"].to_numpy(dtype=float),
        "walk_s": access_s + egress_s,
        "t_station": np.mod(rows["depart"].to_numpy(dtype=float) + access_s, 86400.0),
        "ride_m": ride_m(legs, seg_len), "portal_s": portal_s(legs, stations, cfg),
        "dist_km": rows["dist_km"].to_numpy(dtype=float),
    })  # fmt: skip
    v = plan.vehicles[["veh_id", "tour_id", "leg", "person_id"]]
    ti = pd.read_parquet(plan.base_routes.parent / "tripinfo.parquet",
                         columns=["veh_id", "duration", "depart_delay", "route_m"])  # fmt: skip
    ti["car_s"] = ti["duration"] + ti["depart_delay"]
    m = t.merge(v, on=["tour_id", "leg", "person_id"], how="left").merge(
        ti[["veh_id", "car_s", "route_m"]], on="veh_id", how="left"
    )
    m["car_km"] = (m["route_m"] / 1000.0).fillna(m["dist_km"])
    return m.drop(columns=["route_m", "dist_km"])


# ---------------------------------------------------------------------------- the logit


def car_minutes(legs: pd.DataFrame, c: dict[str, float], car: dict[str, Any]) -> np.ndarray:
    ivt = legs["car_s"].to_numpy(dtype=float) / 60.0
    km = legs["car_km"].to_numpy(dtype=float)
    rh = (legs["car_mode"] == "ridehail").to_numpy()
    fare = np.maximum(
        float(car["ridehail_base_sar"])
        + float(car["ridehail_sar_per_km"]) * km
        + float(car["ridehail_sar_per_min"]) * ivt,
        float(car["ridehail_min_sar"]),
    )
    cost = np.where(rh, fare, float(car["cost_sar_per_km"]) * km)  # fmt: skip
    access = np.where(rh, c["wait_mult"] * float(car["ridehail_pickup_min"]),
                      float(car["parking_search_min"]))  # fmt: skip
    return ivt + access + cost / c["vot_sar_h"] * 60.0


def loop_minutes(
    legs: pd.DataFrame, c: dict[str, float], p: dict[str, Any], queue_min: np.ndarray
) -> np.ndarray:
    ivt = (p["dwell_s"] + legs["portal_s"].to_numpy() + legs["ride_m"].to_numpy()
           / (p["speed_kmh"] / 3.6)) / 60.0  # fmt: skip
    walk = c["walk_mult"] * legs["walk_s"].to_numpy() / 60.0
    wait = c["wait_mult"] * (p["wait_min"] + queue_min)
    return ivt + walk + wait + c["fare_sar"] / c["vot_sar_h"] * 60.0 + c["asc_loop_min"]


def tour_prob(legs: pd.DataFrame, dv: np.ndarray) -> np.ndarray:
    """P(Loop) per leg from the tour's summed utility difference; a tour with any leg lacking a
    baseline car time gets P = 0 (it is not evaluated)."""
    tours = legs["tour_id"].to_numpy()
    s = pd.Series(dv).groupby(tours).transform("sum").to_numpy().copy()
    # pandas skips NaN in sums: a tour with any leg lacking a car time is not evaluated
    gap = pd.Series(np.isnan(dv).astype(np.int8)).groupby(tours).transform("max").to_numpy()
    s[gap > 0] = np.nan
    p = 1.0 / (1.0 + np.exp(-np.clip(s, -60.0, 60.0)))
    return np.where(np.isfinite(s), p, 0.0)


def resources(legs: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """Capacity resources each leg uses in its station-arrival hour: its station pair and every
    tunnel segment (per direction) it traverses. Returns (leg index, resource id, number of
    resources, is-pair flag per resource)."""
    hour = np.floor(legs["t_station"].to_numpy() / 3600.0).astype(np.int64) % 24
    li, keys = [], []
    for i, (ln, o, d, h) in enumerate(
        zip(legs["line"].astype(str), legs["os"], legs["ds"], hour, strict=True)
    ):
        li.append(i)
        keys.append(f"P|{ln}|{o}|{d}|{h}")
        step = 1 if d > o else -1
        for k in range(o, d, step):
            li.append(i)
            keys.append(f"S|{ln}|{min(k, k + step)}|{step}|{h}")
    rid, uniq = pd.factorize(pd.Series(keys))
    is_pair = np.asarray(uniq.str.startswith("P|"), dtype=bool)
    return np.array(li, np.int64), rid.astype(np.int64), len(uniq), is_pair


def queue_minutes(load_pph: np.ndarray, cap_pph: float, max_min: float) -> np.ndarray:
    """Deterministic queue, uniform arrivals over the hour: mean wait (D - C) / (2 C) h."""
    return np.clip((load_pph - cap_pph) / (2.0 * cap_pph), 0.0, max_min / 60.0) * 60.0


def leg_queue(prob: np.ndarray, res: tuple, cap: np.ndarray, max_min: float, sample: float
              ) -> np.ndarray:  # fmt: skip
    """Queue minutes per leg: the worst queue among the resources it uses."""
    li, rid, n, _ = res
    load = np.bincount(rid, weights=prob[li], minlength=n) / sample
    qr = queue_minutes(load, cap, max_min)
    q = np.zeros(len(prob))
    np.maximum.at(q, li, qr[rid])
    return q


def capacities(is_pair: np.ndarray, p: dict[str, Any], mc: dict[str, Any]) -> np.ndarray:
    """Riders per hour per resource: a station pair carries `pair_capacity_pph` (A-loop-006/007);
    a tunnel segment direction carries 3600 / headway shuttles x riders per shuttle movement
    (loaded shuttles run part-full and empty repositioning shares the tunnel, A-loop-030)."""
    seg = 3600.0 / float(p["headway_s"]) * float(mc["queue"]["segment_riders_per_vehicle"])
    return np.where(is_pair, float(p["pair_capacity_pph"]), seg)


def share(mask: pd.Series, sel: pd.Series) -> float | None:
    return round(float(mask[sel].mean()), 4) if sel.any() else None


def choose(
    legs: pd.DataFrame,
    u_tour: pd.Series,
    c: dict[str, float],
    p: dict[str, Any],
    mc: dict[str, Any],
    sample: float,
    res: tuple | None = None,
) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
    """Shift decision per tour. `u_tour`: the tour's uniform draw (index tour_id); `res`: the
    resources(legs) table (computed if not given). Returns the shifted (admitted) tour ids, the leg
    table with P / queue / chosen / admitted, and a summary.

    Capacity: a station pair and a tunnel segment direction each carry at most `pair_capacity_pph`
    riders per hour (one shuttle every headway_s at full occupancy, A-loop-006/007)."""
    legs = legs.reset_index(drop=True).copy()
    if legs.empty:
        return np.array([], np.int64), legs, {"eligible_tours": 0, "tours_shifted": 0}
    res = res if res is not None else resources(legs)
    li, rid, n_res, is_pair = res
    car = car_minutes(legs, c, mc["car"])
    cap = capacities(is_pair, p, mc)
    q_cfg = mc["queue"]
    max_q = float(q_cfg["max_queue_min"])
    q = np.zeros(len(legs))
    beta = c["beta_ivt_per_min"]
    for it in range(int(q_cfg["iterations"])):
        prob = tour_prob(legs, beta * (loop_minutes(legs, c, p, q) - car))
        q = q + (leg_queue(prob, res, cap, max_q, sample) - q) / (it + 1.0)
    prob = tour_prob(legs, beta * (loop_minutes(legs, c, p, q) - car))
    legs["car_gen_min"] = car
    legs["loop_gen_min"] = loop_minutes(legs, c, p, q)
    legs["queue_min"] = q
    legs["loop_time_min"] = (legs["walk_s"] + p["dwell_s"] + legs["portal_s"] + legs["ride_m"]
                             / (p["speed_kmh"] / 3.6)) / 60.0 + p["wait_min"] + q  # fmt: skip
    legs["p_loop"] = prob
    u = u_tour.reindex(legs["tour_id"].to_numpy()).to_numpy()
    legs["chosen"] = u < prob
    # capacity cap: tours in order of their first station arrival; a tour shifts only if every
    # resource of every leg still has room (capacity x sample riders in the simulated sample)
    tour_of = legs["tour_id"].to_numpy()
    chosen_leg = legs["chosen"].to_numpy()
    sel = chosen_leg[li]
    need_by_tour: dict[int, dict[int, int]] = {}
    for t, r in zip(tour_of[li[sel]], rid[sel], strict=True):
        d = need_by_tour.setdefault(int(t), {})
        d[int(r)] = d.get(int(r), 0) + 1
    order = (
        legs[chosen_leg].groupby("tour_id")["t_station"].min().reset_index()
        .sort_values(["t_station", "tour_id"], kind="stable")["tour_id"].to_numpy()
    )  # fmt: skip
    room = cap * sample + 1e-9
    used = np.zeros(n_res)
    admitted = []
    for t in order:
        need = need_by_tour[int(t)]
        if all(used[k] + m <= room[k] for k, m in need.items()):
            for k, m in need.items():
                used[k] += m
            admitted.append(int(t))
    adm = np.array(sorted(admitted), dtype=np.int64)
    legs["admitted"] = legs["tour_id"].isin(adm).to_numpy()
    f = 1.0 / sample
    adm_leg = legs["admitted"]
    rload = np.bincount(rid, weights=adm_leg.to_numpy(float)[li], minlength=n_res) * f
    info = {
        "eligible_tours": int(legs["tour_id"].nunique()),
        "eligible_legs": len(legs),
        "legs_without_car_time": int(legs["car_s"].isna().sum()),
        "expected_tours": round(float(legs.groupby("tour_id")["p_loop"].first().sum()), 2),
        "expected_riders_per_day": round(float(prob.sum() * f)),
        "chosen_tours": int(legs.loc[legs["chosen"], "tour_id"].nunique()),
        "tours_shifted": len(adm),
        "riders_per_day": round(float(adm_leg.sum() * f)),
        "riders_capped_per_day": round(float((legs["chosen"] & ~adm_leg).sum() * f)),
        "shift_share_legs": round(float(adm_leg.mean()), 4),
        "mean_p_loop": round(float(prob.mean()), 4),
        "max_queue_min": round(float(q.max()), 2),
        "peak_pair_riders_pph": round(float(rload[is_pair].max()), 1),
        "peak_segment_riders_pph": round(float(rload[~is_pair].max()), 1)
        if (~is_pair).any()
        else 0.0,
        "resources_full": int((rload >= cap - 1e-6).sum()),
        "segment_capacity_pph": round(float(cap[~is_pair][0]), 1) if (~is_pair).any() else None,
        "share_admitted_slower_gen": share(legs["loop_gen_min"] > legs["car_gen_min"], adm_leg),
        "share_admitted_slower_time": share(legs["loop_time_min"] > legs["car_s"] / 60.0, adm_leg),
        "mean_car_gen_min": round(float(np.nanmean(car)), 1),
        "mean_loop_gen_min": round(float(legs["loop_gen_min"].mean()), 1),
    }
    return adm, legs, info


def pair_table(legs: pd.DataFrame, p: dict[str, Any], sample: float) -> pd.DataFrame:
    """Shift share per station pair and hour (city-equivalent riders per hour)."""
    if legs.empty:
        return pd.DataFrame()
    f = 1.0 / sample
    hour = np.floor(legs["t_station"].to_numpy() / 3600.0).astype(np.int64) % 24
    g = legs.assign(hour=hour).groupby(["line", "os", "ds", "hour"])
    t = g.agg(
        eligible=("tour_id", "size"), expected=("p_loop", "sum"), chosen=("chosen", "sum"),
        admitted=("admitted", "sum"), queue_min=("queue_min", "mean"),
        mean_p=("p_loop", "mean"),
    ).reset_index()  # fmt: skip
    for k in ("eligible", "expected", "chosen", "admitted"):
        t[k] = (t[k] * f).round(1)
    t["capacity_pph"] = float(p["pair_capacity_pph"])
    t["shift_share"] = (t["admitted"] / t["eligible"]).round(4)
    t["label"] = SYNTHETIC_LABEL
    return t


def shuttle_choice(
    plan: Any,
    cand: pd.DataFrame,
    legs: pd.DataFrame,
    stations: pd.DataFrame,
    seg_len: dict[tuple[str, int], float],
    p: dict[str, Any],
    cfg: dict[str, Any],
    elig_tours: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Mode-choice replacement for `elig_tours[u < alpha]` inside loop_shuttle."""
    from sim.policies.transforms import tour_draws

    mc = load_mode_choice(p["mode_choice"])
    c = coefficients(mc)
    u = pd.Series(tour_draws(plan, "loop_shuttle:shift", elig_tours), index=elig_tours)
    table = leg_table(plan, cand, legs, stations, seg_len, p, cfg)
    shifted, scored, info = choose(table, u, c, p, mc, plan.sample)
    pairs = pair_table(scored, p, plan.sample)
    pairs.to_csv(plan.work / "loop_mode_choice_pairs.csv", index=False)
    scored.to_parquet(plan.work / "loop_mode_choice_legs.parquet", index=False)
    info = {"config": str(p["mode_choice"]), "config_hash": mc_hash(mc), "coefficients": c,
            **info}  # fmt: skip
    return shifted, info


# ---------------------------------------------------------------------------- offline sweep


SegLen = dict[tuple[str, int], float]


def candidate_legs(plan: Any, cand_row: dict[str, Any], p: dict[str, Any],
                   cfg: dict[str, Any]) -> tuple[pd.DataFrame, SegLen]:  # fmt: skip
    """Eligible legs of one candidate on `plan`, exactly as loop_shuttle selects them, but with
    the station table only (no netconvert). Returns (leg table, segment lengths)."""
    from sim.loop.network import main_scc_edges, net_offset, node_table, station_table
    from sim.loop.schema import Alignment
    from sim.loop.transforms import choose_line, edge_xy, snap_legs

    al = Alignment.model_validate({"id": cand_row["id"], "name": cand_row.get("name", ""),
                                   "stations": cand_row["stations"]})  # fmt: skip
    edges = plan.edges().copy()
    edges.attrs["net_offset"] = net_offset(plan.net)
    stations = station_table([al], edges, node_table(plan.net), main_scc_edges(plan.net), cfg)
    trips = plan.trips
    is_mode = trips["mode"].astype(str).isin(p["shift_modes"]).to_numpy()
    mode_ok = pd.Series(is_mode).groupby(trips["tour_id"].to_numpy()).transform("all").to_numpy()
    cand = trips[mode_ok].reset_index()
    ox, oy = edge_xy(plan.edges(), cand["o_edge"])
    dx, dy = edge_xy(plan.edges(), cand["d_edge"])
    snaps = snap_legs(stations, ox, oy, dx, dy, p["radius_o_m"], p["radius_d_m"],
                      p["min_trip_km"])  # fmt: skip
    legs = choose_line(snaps, cand["tour_id"].to_numpy())
    nxt = stations.assign(k=stations["k"] - 1)
    seg = stations.merge(nxt, on=["line", "k"], suffixes=("", "_n"))
    seg_len = {
        (r.line, int(r.k)): float(np.hypot(r.x_n - r.x, r.y_n - r.y))
        * float(cfg["tunnel"]["curvature_factor"])
        for r in seg.itertuples()
    }
    return leg_table(plan, cand, legs, stations, seg_len, p, cfg), seg_len


def service_params(service: str, mc: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    from sim.loop.params import resolve_params
    from sim.loop.schema import LoopShuttle

    s = mc["services"][service]
    t = LoopShuttle.model_validate(
        {
            "type": "loop_shuttle",
            "assumption": "sweep",
            "alignments": [
                {
                    "id": "X",
                    "stations": [
                        {"name": "a", "lon": 0, "lat": 0},
                        {"name": "b", "lon": 0, "lat": 0.1},
                    ],
                }
            ],
            "speed_kmh": s["speed_kmh"],
            "capacity": s["capacity"],
        }
    )
    return resolve_params(t, cfg)


def competitive_tours(legs: pd.DataFrame, p: dict[str, Any]) -> np.ndarray:
    """Tours whose every leg is faster by Loop than by car (Track D's keep_competitive check),
    used to confirm the offline legs reproduce the Track D runs."""
    loop_s = (legs["walk_s"] + p["wait_min"] * 60.0 + p["dwell_s"] + legs["portal_s"]
              + legs["ride_m"] / (p["speed_kmh"] / 3.6))  # fmt: skip
    car = legs["car_s"].to_numpy()
    fast = np.isfinite(car) & (loop_s.to_numpy() < car)
    ok = pd.Series(fast).groupby(legs["tour_id"].to_numpy()).transform("all").to_numpy()
    return legs.loc[ok, "tour_id"].unique()


def dispatch_check(scored: pd.DataFrame, seg_len: dict[tuple[str, int], float],
                   p: dict[str, Any], plan: Any) -> dict[str, Any]:  # fmt: skip
    """Track D's shuttle dispatch and capacity flags on the admitted riders (the quality gate the
    city run would apply; A-loop-014: segment exceedance at most 10 %)."""
    from sim.loop.transforms import capacity_flags, shuttles

    pax = scored.loc[scored["admitted"], ["line", "os", "ds", "t_station"]]
    if pax.empty:
        return {}
    sh = shuttles(pax, seg_len, p, plan.seed)
    flags = capacity_flags(pax, sh, p, plan.sample)
    flags["riders_per_shuttle_movement"] = round(len(pax) / len(sh), 3)
    return flags


def sweep(
    plan: Any,
    cands: dict[str, dict[str, Any]],
    ids: list[str],
    mc: dict[str, Any],
    cfg: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    from sim.policies.transforms import tour_draws

    sw = mc["sweep"]
    grid = list(itertools.product(sw["vot_sar_h"], sw["wait_mult"], sw["asc_loop_min"],
                                  sw["fare_sar"]))  # fmt: skip
    doc: dict[str, Any] = {"label": SYNTHETIC_LABEL, "config_hash": mc_hash(mc),
                           "baseline": plan.base_routes.parent.name, "sample": plan.sample,
                           "candidates": {}}  # fmt: skip
    rows = []
    for cid in ids:
        t0 = time.perf_counter()
        p0 = service_params("measured", mc, cfg)
        legs, seg_len = candidate_legs(plan, cands[cid], p0, cfg)
        elig = np.unique(legs["tour_id"].to_numpy())
        u = pd.Series(tour_draws(plan, "loop_shuttle:shift", elig), index=elig)
        legs = legs.reset_index(drop=True)
        res = resources(legs)
        cdoc: dict[str, Any] = {
            "eligible_tours": len(elig),
            "eligible_legs": len(legs),
            "eligible_riders_per_day": round(len(legs) / plan.sample),
        }
        for service in ("measured", "vendor"):
            p = service_params(service, mc, cfg)
            comp = competitive_tours(legs, p)
            cleg = legs[legs["tour_id"].isin(comp[u.reindex(comp).to_numpy() < 0.5])]
            central = coefficients(mc)
            _, scored, info = choose(legs, u, central, p, mc, plan.sample, res)
            info["dispatch_check"] = dispatch_check(scored, seg_len, p, plan)
            pair_table(scored, p, plan.sample).to_csv(
                out_dir / f"mode_choice_pairs_{cid}_{service}.csv", index=False
            )
            vals = []
            for vot, wm, asc, fare in grid:
                c = coefficients(mc, vot_sar_h=vot, wait_mult=wm, asc_loop_min=asc, fare_sar=fare)
                _, _, i = choose(legs, u, c, p, mc, plan.sample, res)
                vals.append(i["riders_per_day"])
                rows.append(
                    {
                        "candidate": cid,
                        "service": service,
                        "vot_sar_h": vot,
                        "wait_mult": wm,
                        "asc_loop_min": asc,
                        "fare_sar": fare,
                        **{
                            k: i[k]
                            for k in (
                                "riders_per_day",
                                "expected_riders_per_day",
                                "riders_capped_per_day",
                                "tours_shifted",
                                "shift_share_legs",
                                "max_queue_min",
                            )
                        },
                    }
                )
            v = np.array(vals, dtype=float)
            oat: dict[str, dict[str, int]] = {}
            for key, values in sw["one_at_a_time"].items():
                oat[key] = {}
                for val in values:
                    _, _, i = choose(
                        legs, u, coefficients(mc, **{key: val}), p, mc, plan.sample, res
                    )
                    oat[key][f"{val:g}"] = i["riders_per_day"]
            by_fare = {
                str(f): [int(min(r["riders_per_day"] for r in rows if r["candidate"] == cid
                                 and r["service"] == service and r["fare_sar"] == f)),
                         int(max(r["riders_per_day"] for r in rows if r["candidate"] == cid
                                 and r["service"] == service and r["fare_sar"] == f))]
                for f in sw["fare_sar"]
            }  # fmt: skip
            cdoc[service] = {
                "params": {
                    k: p[k]
                    for k in ("speed_kmh", "capacity", "headway_s", "pair_capacity_pph", "wait_min")
                },  # fmt: skip
                "central": info,
                "range_riders_per_day": [int(v.min()), int(np.percentile(v, 50)), int(v.max())],
                "range_by_fare": by_fare,
                "one_at_a_time": oat,
                "time_competitive_alpha0p5_riders_per_day": round(len(cleg) / plan.sample),
            }
        cdoc["wall_s"] = round(time.perf_counter() - t0, 1)
        doc["candidates"][cid] = cdoc
        typer.echo(
            f"{cid}: eligible {cdoc['eligible_riders_per_day']} riders/day; central "
            f"measured {cdoc['measured']['central']['riders_per_day']}, vendor "
            f"{cdoc['vendor']['central']['riders_per_day']} ({cdoc['wall_s']} s)"
        )
    pd.DataFrame(rows).assign(label=SYNTHETIC_LABEL).to_csv(out_dir / "mode_choice_sweep.csv",
                                                             index=False)  # fmt: skip
    (out_dir / "mode_choice.json").write_text(json.dumps(doc, indent=2, default=float))
    return doc


app = typer.Typer(add_completion=False, help=__doc__)


@app.command("sweep")
def sweep_cmd(
    config: Path = typer.Option(CONFIG, help="mode-choice YAML"),
    source_root: Path = typer.Option(
        REPO_ROOT,
        help="checkout holding runs/ and data/ caches of the starting baseline (read-only)",
    ),  # fmt: skip
    baseline: str = typer.Option("baseline-weekday-f0.1-s1-e5f1906a-65fac195-f124c5"),
    candidates: Path = typer.Option(LOOP_DIR / "candidates.yaml"),
    ids: str | None = typer.Option(None, help="comma-separated ids (default: config sweep list)"),
    out_dir: Path = typer.Option(RESULTS),
    work: Path = typer.Option(Path("/tmp/trackH_mode_choice")),
) -> None:
    import sim.loop.network as N
    import sim.policies.edges as E
    import sim.population.baseline as B
    import sim.population.synthesize as S
    from sim.loop.evaluate import load_candidates
    from sim.loop.schema import loop_config
    from sim.policies.run import build_plan

    root = source_root.resolve()
    S.CACHE_DIR, B.ROUTE_CACHE = (
        root / "data" / "population",
        root / "data" / "population" / "routes",
    )
    E.CACHE = N.CACHE = root / "data" / "policies"
    work.mkdir(parents=True, exist_ok=True)
    plan = build_plan(root / "runs" / baseline, root / "data" / "population" / "zones", work)
    mc = load_mode_choice(config)
    todo = [c.strip() for c in ids.split(",")] if ids else list(mc["sweep"]["candidates"])
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep(plan, load_candidates(candidates), todo, mc, loop_config(), out_dir)


@app.command("check")
def check_cmd(config: Path = typer.Option(CONFIG)) -> None:
    """Validate a mode-choice YAML and print its hash."""
    mc = load_mode_choice(config)
    typer.echo(f"{config}: ok, hash {mc_hash(mc)}, service {mc['service']}")


if __name__ == "__main__":
    app()
