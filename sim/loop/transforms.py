"""Loop transforms on Track A's `Plan` (sim/policies/transforms.py), applied before the run.

loop_shuttle
    1. Builds the Loop network (shuttle class only) and snaps every leg of the plan to the nearest
       station of each line. A tour shifts only if all its legs are car / ride-hail trips whose
       origin is within R_o and destination within R_d of two different stations of the same line
       and at least `min_trip_km` apart.
    2. A share alpha of the eligible tours (hashed draw per tour, so alpha sweeps select nested
       sets) becomes mode `loop`: their car vehicles are removed.
    3. Shuttle vehicles replace them: passengers reach the station after an access walk and fill
       shuttles of `occupancy` in arrival order per station pair (a shuttle leaves with its last
       passenger, 30 s loading stop on the down ramp); empty repositioning trips go back with
       probability `empty_reposition_factor`. Shuttles run as an extra route file in the city run.
    4. Quality flags: share of shifted passengers above the station-pair capacity (per hour),
       tunnel-segment utilisation (shuttles per hour vs 3600 / headway).

loop_private
    Builds the Loop network open to passenger cars, adds the toll as a routing penalty on the down
    ramps (toll / value of time) and re-routes one-shot every passenger car whose ends are within
    `reroute_radius_m` of two different stations (TA-014 incremental routing). Track A's matched
    control (TA-018) then re-routes the same cars on the base network.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from sim.common import SYNTHETIC_LABEL
from sim.loop.network import build_loop_net, meso_types_file, shuttle_route
from sim.loop.params import resolve_params
from sim.loop.schema import LoopPrivate, LoopShuttle, loop_config
from sim.policies.edges import utm_xy
from sim.policies.transforms import Penalty, Plan, tour_draws
from sim.population.sampling import stream

DAY = 86400.0
LOOP_MODE = "loop"
SHUTTLE_VTYPE = "loop_shuttle"
SHUTTLE_PREFIX = "loop_"


# ---------------------------------------------------------------------------- snapping


def edge_xy(edges: pd.DataFrame, ids: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    pos = edges.set_index("edge_id")[["lon", "lat"]]
    ll = pos.reindex(ids.astype(str).to_numpy())
    return utm_xy(ll["lon"].to_numpy(), ll["lat"].to_numpy())


def nearest_station(
    x: np.ndarray, y: np.ndarray, sx: np.ndarray, sy: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Index of and distance to the nearest station (NaN coordinates -> inf distance)."""
    best = np.full(len(x), np.inf)
    idx = np.full(len(x), -1, dtype=np.int64)
    for k in range(len(sx)):
        d = np.hypot(x - sx[k], y - sy[k])
        better = d < best
        best[better], idx[better] = d[better], k
    return idx, best


def snap_legs(
    stations: pd.DataFrame,
    ox: np.ndarray,
    oy: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
    r_o: float,
    r_d: float,
    min_km: float,
) -> pd.DataFrame:
    """Per leg and line: origin/destination station and whether the leg can use that line."""
    out = []
    crow = np.hypot(dx - ox, dy - oy) / 1000.0
    for li, (line, g) in enumerate(stations.groupby("line", sort=False)):
        g = g.sort_values("k")
        sx, sy = g["x"].to_numpy(), g["y"].to_numpy()
        so, do = nearest_station(ox, oy, sx, sy)
        sd, dd = nearest_station(dx, dy, sx, sy)
        ok = (do <= r_o) & (dd <= r_d) & (so != sd) & (crow >= min_km)
        out.append(pd.DataFrame({"line_rank": li, "line": line, "os": so, "ds": sd,
                                 "access_m": do, "egress_m": dd, "ok": ok}))  # fmt: skip
    return pd.concat(out, keys=range(len(out)), names=["li", "row"]).reset_index()


def choose_line(snaps: pd.DataFrame, tour_ids: np.ndarray) -> pd.DataFrame:
    """First line on which every leg of the tour is eligible; one row per leg (else empty)."""
    s = snaps.copy()
    s["tour_id"] = tour_ids[s["row"].to_numpy()]
    all_ok = s.groupby(["tour_id", "li"])["ok"].transform("all")
    s = s[all_ok]
    if s.empty:
        return s
    first = s.groupby("tour_id")["li"].transform("min")
    s = s[s["li"] == first]
    assert s["row"].nunique() == len(s), "a leg got two lines"
    return s


# ---------------------------------------------------------------------------- shuttle mode


def pool(t: np.ndarray, seats: int, max_wait: float) -> list[tuple[float, int]]:
    """Dispatch in arrival order: a shuttle leaves when full (with its last passenger) or when its
    first passenger has waited `max_wait`. Returns (departure, passengers) per shuttle."""
    out = []
    i = 0
    while i < len(t):
        t0 = t[i]
        j = i + 1
        while j < len(t) and j - i < seats and t[j] - t0 <= max_wait:
            j += 1
        k = j - i
        out.append((float(t[j - 1] if k == seats else t0 + max_wait), k))
        i = j
    return out


def shuttles(
    pax: pd.DataFrame,
    seg_len: dict[tuple[str, int], float],
    p: dict[str, Any],
    seed: int,
) -> pd.DataFrame:
    """Shuttle trips from passenger arrival times at stations (loaded + empty repositioning)."""
    seats = max(int(round(p["occupancy"])), 1)
    max_wait = float(p["max_pool_wait_s"])
    rows = []
    for (line, os_, ds), g in pax.groupby(["line", "os", "ds"], sort=True):
        dispatch = pool(np.sort(g["t_station"].to_numpy()), seats, max_wait)
        for n, (d, k) in enumerate(dispatch):
            rows.append((line, int(os_), int(ds), d, k, False, n))
    df = pd.DataFrame(rows, columns=["line", "os", "ds", "depart", "pax", "empty", "n"])
    if df.empty:
        return df
    # empty repositioning back to the origin station after arrival
    ride = np.array([
        sum(seg_len[(r.line, min(k, k + (1 if r.ds > r.os else -1)))]
            for k in range(r.os, r.ds, 1 if r.ds > r.os else -1))
        for r in df.itertuples()
    ])  # fmt: skip
    df["ride_m"] = ride
    u = stream(seed, "policy:loop_shuttle:empty").random(len(df))
    back = df[u < p["empty_reposition_factor"]].copy()
    back["os"], back["ds"] = df.loc[back.index, "ds"], df.loc[back.index, "os"]
    back["depart"] = back["depart"] + p["dwell_s"] + back["ride_m"] / (p["speed_kmh"] / 3.6)
    back["pax"], back["empty"] = 0, True
    out = pd.concat([df, back], ignore_index=True)
    out["depart"] = np.round(np.mod(out["depart"].to_numpy(), DAY), 1)
    out["veh_id"] = [
        f"{SHUTTLE_PREFIX}{r.line}_{r.os}_{r.ds}_{r.n}{'e' if r.empty else ''}"
        for r in out.itertuples()
    ]
    return out.sort_values(["depart", "veh_id"], kind="stable").reset_index(drop=True)


def write_shuttle_routes(path: Any, sh: pd.DataFrame, p: dict[str, Any], scale: float,
                         cfg: dict[str, Any]) -> None:  # fmt: skip
    s = cfg["shuttle"]
    lines = [
        f"<!-- {SYNTHETIC_LABEL}; Loop shuttles, capacity scale {scale:g} -->",
        "<routes>",
        f'    <vType id="{SHUTTLE_VTYPE}" vClass="{cfg["shuttle_vclass"]}" '
        f'length="{float(s["length_m"]) * scale:.2f}" minGap="{float(s["min_gap_m"]) * scale:.2f}" '
        f'maxSpeed="{float(s["max_speed_kmh"]) / 3.6:.2f}" emissionClass="Zero" color="1,0,0"/>',
    ]  # fmt: skip
    for r in sh.itertuples():
        edges = " ".join(shuttle_route(r.line, r.os, r.ds))
        stop = (
            ""
            if r.empty
            else (f'\n        <stop edge="{edges.split()[0]}" duration="{p["dwell_s"]:.0f}"/>')
        )
        lines.append(f'    <vehicle id="{r.veh_id}" type="{SHUTTLE_VTYPE}" depart="{r.depart:.1f}">'
                     f'\n        <route edges="{edges}"/>{stop}\n    </vehicle>')  # fmt: skip
    lines.append("</routes>")
    path.write_text("\n".join(lines) + "\n")


def capacity_flags(
    pax: pd.DataFrame, sh: pd.DataFrame, p: dict[str, Any], sample: float
) -> dict[str, Any]:
    """Passengers above the station-pair capacity (per hour) and tunnel segment utilisation."""
    f = 1.0 / sample
    if pax.empty:
        return {"pair_exceedance_share": 0.0, "segment_peak_utilisation": 0.0,
                "segment_exceedance_share": 0.0, "peak_pair_pph": 0.0}  # fmt: skip
    hour = np.floor(pax["t_station"].to_numpy() / 3600.0).astype(int) % 24
    n = pax.assign(hour=hour).groupby(["line", "os", "ds", "hour"]).size() * f
    excess = (n - p["pair_capacity_pph"]).clip(lower=0.0)
    # tunnel segment loads: every shuttle occupies each segment it passes, per hour and direction
    seg_rows = []
    for r in sh.itertuples():
        step = 1 if r.ds > r.os else -1
        h = int(r.depart // 3600) % 24
        seg_rows += [(r.line, k, step, h) for k in range(r.os, r.ds, step)]
    seg = pd.DataFrame(seg_rows, columns=["line", "k", "dir", "hour"])
    vph = seg.groupby(["line", "k", "dir", "hour"]).size() * f
    cap_vph = 3600.0 / p["headway_s"]
    util = vph / cap_vph
    over = seg.merge(util.rename("u").reset_index(), on=["line", "k", "dir", "hour"])["u"] > 1.0
    return {
        "pair_exceedance_share": round(float(excess.sum() / n.sum()), 4),
        "peak_pair_pph": round(float(n.max()), 1),
        "segment_peak_utilisation": round(float(util.max()), 3) if len(util) else 0.0,
        "segment_exceedance_share": round(float(over.mean()), 4) if len(over) else 0.0,
    }


def keep_competitive(
    plan: Plan,
    cand: pd.DataFrame,
    legs: pd.DataFrame,
    stations: pd.DataFrame,
    seg_len: dict[tuple[str, int], float],
    p: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep tours whose every leg is faster by Loop (walk + wait + dwell + ride) than the same
    leg by car in the starting baseline (simulated duration + departure delay)."""
    tun = cfg["tunnel"]
    ramp_s = 2 * float(tun["ramp_length_m"]) / (float(tun["ramp_speed_kmh"]) / 3.6)
    st = stations.set_index(["line", "k"])["connect_m"]
    ride_m = np.array([
        sum(seg_len[(ln, min(k, k + (1 if d > o else -1)))]
            for k in range(o, d, 1 if d > o else -1))
        for ln, o, d in zip(legs["line"], legs["os"], legs["ds"], strict=True)
    ])  # fmt: skip
    ramp_m = float(tun["ramp_length_m"])
    extra_ramp = np.array([
        max(st[(ln, o)] - ramp_m, 0) + max(st[(ln, d)] - ramp_m, 0)
        for ln, o, d in zip(legs["line"], legs["os"], legs["ds"], strict=True)
    ]) / (float(tun["ramp_speed_kmh"]) / 3.6)  # fmt: skip
    walk = p["walk_speed_kmh"] / 3.6 / p["detour_factor"]
    loop_s = ((legs["access_m"].to_numpy() + legs["egress_m"].to_numpy()) / walk
              + p["wait_min"] * 60.0 + p["dwell_s"] + ramp_s + extra_ramp
              + ride_m / (p["speed_kmh"] / 3.6))  # fmt: skip
    rows = cand.loc[legs["row"].to_numpy(), ["tour_id", "leg", "person_id"]]
    v = plan.vehicles[["veh_id", "tour_id", "leg", "person_id"]]
    ti = pd.read_parquet(plan.base_routes.parent / "tripinfo.parquet",  # type: ignore[union-attr]
                         columns=["veh_id", "duration", "depart_delay"])  # fmt: skip
    ti["car_s"] = ti["duration"] + ti["depart_delay"]
    car = (
        rows.merge(v, on=["tour_id", "leg", "person_id"], how="left")
        .merge(ti[["veh_id", "car_s"]], on="veh_id", how="left")["car_s"]
        .to_numpy()
    )
    fast = np.isfinite(car) & (loop_s < car)
    ok_tour = pd.Series(fast).groupby(legs["tour_id"].to_numpy()).transform("all").to_numpy()
    kept = legs[ok_tour]
    info = {
        "legs_tested": len(legs),
        "legs_faster_by_loop": int(fast.sum()),
        "tours_before": int(legs["tour_id"].nunique()),
        "tours_after": int(kept["tour_id"].nunique()),
        "mean_loop_estimate_min": round(float(loop_s.mean() / 60.0), 1),
        "mean_car_min": round(float(np.nanmean(car) / 60.0), 1),
    }
    return kept, info


def loop_shuttle(plan: Plan, t: LoopShuttle) -> dict[str, Any]:
    from sim.population.baseline import baseline_config, scale_options

    cfg = loop_config()
    p = resolve_params(t, cfg)
    base_edges = plan.edges()
    net, stations, info = build_loop_net(plan.net, t.alignments, "shuttle", p["speed_kmh"],
                                         plan.work, base_edges, cfg)  # fmt: skip
    trips = plan.trips
    # every leg of a tour must be a shift-mode trip
    is_mode = trips["mode"].astype(str).isin(p["shift_modes"]).to_numpy()
    mode_ok = pd.Series(is_mode).groupby(trips["tour_id"].to_numpy()).transform("all").to_numpy()
    cand = trips[mode_ok].reset_index()
    ox, oy = edge_xy(base_edges, cand["o_edge"])
    dx, dy = edge_xy(base_edges, cand["d_edge"])
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
    competitive = None
    if p["competitive_only"] and len(legs):
        legs, competitive = keep_competitive(plan, cand, legs, stations, seg_len, p, cfg)
    elig_tours = np.unique(legs["tour_id"].to_numpy()) if len(legs) else np.array([], np.int64)
    mode_choice = None
    if p.get("mode_choice"):
        # Track H: logit on generalised time + capacity cap instead of the fixed share alpha
        from sim.loop.mode_choice import shuttle_choice

        shifted, mode_choice = shuttle_choice(plan, cand, legs, stations, seg_len, p, cfg,
                                              elig_tours)  # fmt: skip
    else:
        u = tour_draws(plan, "loop_shuttle:shift", elig_tours)
        shifted = elig_tours[u < p["alpha"]]
    legs = legs[legs["tour_id"].isin(shifted)]
    rows = cand.loc[legs["row"].to_numpy()]
    walk = p["walk_speed_kmh"] / 3.6
    access_s = legs["access_m"].to_numpy() * p["detour_factor"] / walk
    pax = pd.DataFrame({
        "tour_id": rows["tour_id"].to_numpy(), "person_id": rows["person_id"].to_numpy(),
        "leg": rows["leg"].to_numpy(), "depart": rows["depart"].to_numpy(dtype=float),
        "line": legs["line"].to_numpy(), "os": legs["os"].to_numpy(), "ds": legs["ds"].to_numpy(),
        "access_m": legs["access_m"].to_numpy().round(1),
        "egress_m": legs["egress_m"].to_numpy().round(1),
        "t_station": np.mod(rows["depart"].to_numpy(dtype=float) + access_s, DAY),
    })  # fmt: skip
    # baseline vehicles of the shifted tours (for the rider-time comparison after the run)
    v = plan.vehicles
    removed = v[v["tour_id"].isin(shifted)][["veh_id", "tour_id", "leg", "person_id"]]
    pax = pax.merge(removed.rename(columns={"veh_id": "base_veh_id"}),
                    on=["tour_id", "leg", "person_id"], how="left")  # fmt: skip
    if LOOP_MODE not in plan.trips["mode"].cat.categories:
        plan.trips["mode"] = plan.trips["mode"].cat.add_categories([LOOP_MODE])
    changed = plan.set_mode(shifted, LOOP_MODE, "loop_shuttle")
    plan.set_net(net)
    plan.net_info = info
    sh = shuttles(pax, seg_len, p, plan.seed)
    scale, _ = scale_options(plan.sample, baseline_config())
    routes = plan.work / "loop_shuttles.rou.xml"
    write_shuttle_routes(routes, sh, p, scale, cfg)
    plan.extra_routes.append(routes)
    plan.additional.append(meso_types_file(plan.work / "loop_meso.add.xml", p["headway_s"],
                                           plan.sample))  # fmt: skip
    flags = capacity_flags(pax, sh, p, plan.sample)
    pax.to_parquet(plan.work / "loop_pax.parquet", index=False)
    sh.to_parquet(plan.work / "loop_shuttles.parquet", index=False)
    stations.to_parquet(plan.work / "loop_stations.parquet", index=False)
    f = 1.0 / plan.sample
    out: dict[str, Any] = {
        "params": p,
        "network": info,
        "eligible_tours": len(elig_tours),
        "competitive_filter": competitive,
        **({"mode_choice": mode_choice} if mode_choice else {}),
        "tours_shifted": len(shifted),
        "person_trips_shifted": len(pax),
        "passengers_per_day": int(round(len(pax) * f)),
        "car_vehicles_removed": changed["vehicles_before"],
        "shuttles_loaded": int((~sh["empty"]).sum()) if len(sh) else 0,
        "shuttles_empty": int(sh["empty"].sum()) if len(sh) else 0,
        **flags,
    }
    (plan.work / "loop_effects.json").write_text(json.dumps(out, indent=2, default=str))
    return out


# ---------------------------------------------------------------------------- private mode


def loop_private(plan: Plan, t: LoopPrivate) -> dict[str, Any]:
    from sim.population.export_trips import export_config

    cfg = loop_config()
    p = resolve_params(t, cfg)
    base_edges = plan.edges()
    net, stations, info = build_loop_net(plan.net, t.alignments, "private", p["speed_kmh"],
                                         plan.work, base_edges, cfg)  # fmt: skip
    vclass = {k: v["vClass"] for k, v in export_config()["vtypes"].items() if isinstance(v, dict)}
    v = plan.vehicles
    cars = v[v["vtype"].astype(str).map(vclass) == "passenger"].reset_index(drop=True)
    ox, oy = edge_xy(base_edges, cars["o_edge"])
    dx, dy = edge_xy(base_edges, cars["d_edge"])
    r = p["reroute_radius_m"]
    snaps = snap_legs(stations, ox, oy, dx, dy, r, r, p["min_trip_km"])
    ok_rows = np.unique(snaps.loc[snaps["ok"], "row"].to_numpy())
    near = cars.loc[ok_rows]
    u = tour_draws(plan, "loop_private:eligible", near["tour_id"].to_numpy())
    chosen = near[u < p["eligible_share"]]
    plan.force_reroute |= set(chosen["veh_id"])
    downs = [f"loop_{s.line}_D{s.k}" for s in stations.itertuples()]
    if p["toll_penalty_s"] > 0:
        plan.penalties.append(Penalty(downs, 0.0, 2 * DAY, p["toll_penalty_s"]))
    plan.set_net(net)
    plan.net_info = info
    plan.additional.append(meso_types_file(plan.work / "loop_meso.add.xml", p["headway_s"],
                                           plan.sample))  # fmt: skip
    stations.to_parquet(plan.work / "loop_stations.parquet", index=False)
    out: dict[str, Any] = {
        "params": p,
        "network": info,
        "cars_near_stations": len(near),
        "cars_rerouted": len(chosen),
    }
    (plan.work / "loop_effects.json").write_text(json.dumps(out, indent=2, default=str))
    return out


# ---------------------------------------------------------------------------- dispatch


def apply(plan: Plan, t: Any, policy_id: str) -> dict[str, Any]:
    """Track A's dispatcher plus the two Loop transforms."""
    from sim.policies import transforms as T

    if isinstance(t, LoopShuttle):
        eff = loop_shuttle(plan, t)
    elif isinstance(t, LoopPrivate):
        eff = loop_private(plan, t)
    else:
        return T.apply(plan, t, policy_id)
    eff = {"type": t.type, **eff}
    plan.effects.append(eff)
    return eff
