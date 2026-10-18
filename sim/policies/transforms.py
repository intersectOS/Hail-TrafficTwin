"""Policy transforms (PROJECT.md section 7): applied to the population's plans and the network
before a Tier A run, never through TraCI.

A `Plan` holds the matching baseline's person trips (with modes) and vehicle trips. Transforms
edit them at the tour level, so a vehicle whose trip is unchanged keeps its identity (`veh_id`,
departure, origin and destination) and later keeps its baseline route; everything else is
re-routed (sim/policies/run.py). Random draws use streams keyed by the seed and the transform
type, not by the policy, so a sweep over `share` selects nested sets of people.

    remote_work      drop the work tour of hybrid workers at home today; induced non-work tours
    staggered_hours  shift the main tours of one segment, institutions grouped by district
    daytype          handled by the runner: the run starts from that day type's baseline
    pt_line          bus line via ptlines2flows.py + fixed car-to-bus shift in the catchment
    road_pricing     cordon: suppressed / re-timed crossing trips + routing penalty on the cordon
    network_change   closures, lanes, speeds, new links (netconvert) and signal plans
    ridehail_share   car-driver tours to ride-hail, with empty legs to each pickup
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sim.policies.edges import load_edges, utm_xy
from sim.population.sampling import gravity_choice, stream
from sim.population.synthesize import Population
from sim.schemas import (
    DayTypeChange,
    NetworkChange,
    PtLine,
    RemoteWork,
    RidehailShare,
    RoadPricing,
    StaggeredHours,
    hhmm_to_s,
    load_daytype,
)

DAY = 86400.0
SORT_KEYS = ["depart", "person_id", "tour_id", "leg", "empty"]


@dataclass
class Penalty:
    """Extra routing cost (s) on edges during [begin, end) (road pricing)."""

    edges: list[str]
    begin: float
    end: float
    seconds: float


@dataclass
class Plan:
    daytype: str
    seed: int
    sample: float
    sim_end: float
    pop: Population
    trips: pd.DataFrame
    vehicles: pd.DataFrame
    net: Path
    work: Path
    zone_dir: Path | None = None
    base_routes: Path | None = None
    additional: list[Path] = field(default_factory=list)
    extra_routes: list[Path] = field(default_factory=list)
    penalties: list[Penalty] = field(default_factory=list)
    force_reroute: set[str] = field(default_factory=set)
    effects: list[dict[str, Any]] = field(default_factory=list)
    net_info: dict[str, Any] | None = None
    _edges: pd.DataFrame | None = None

    def edges(self) -> pd.DataFrame:
        if self._edges is None:
            self._edges = load_edges(self.net)
        return self._edges

    def set_net(self, net: Path) -> None:
        self.net = net
        self._edges = None

    def next_tour_ids(self, n: int) -> np.ndarray:
        start = int(self.trips["tour_id"].max()) + 1 if len(self.trips) else 0
        return np.arange(start, start + n, dtype=np.int64)

    # ------------------------------------------------------------------ tour-level edits

    def remove_tours(self, tours: Any) -> dict[str, int]:
        tours = pd.Index(np.unique(np.asarray(tours, dtype=np.int64)))
        t_drop = self.trips["tour_id"].isin(tours)
        v_drop = self.vehicles["tour_id"].isin(tours)
        self.trips = self.trips.loc[~t_drop].reset_index(drop=True)
        self.vehicles = self.vehicles.loc[~v_drop].reset_index(drop=True)
        return {
            "tours_removed": len(tours),
            "person_trips_removed": int(t_drop.sum()),
            "vehicles_removed": int(v_drop.sum()),
        }

    def retime_tours(self, delta: pd.Series) -> dict[str, int]:
        """Add `delta` seconds (indexed by tour_id) to every leg of those tours (wraps at 24 h)."""
        for name in ("trips", "vehicles"):
            df = getattr(self, name)
            d = df["tour_id"].map(delta)
            hit = d.notna().to_numpy()
            dep = df["depart"].to_numpy(dtype=float).copy()
            dep[hit] = np.round(np.mod(dep[hit] + d.to_numpy(dtype=float)[hit], DAY), 1)
            df["depart"] = dep
        hit_v = self.vehicles["tour_id"].isin(delta.index)
        return {"tours_retimed": len(delta), "vehicles_retimed": int(hit_v.sum())}

    def add_tours(self, new_trips: pd.DataFrame, key: str) -> dict[str, int]:
        """Append new person trips: modes and vehicles drawn with streams keyed by `key`."""
        from sim.population.activities import activities_config
        from sim.population.modes import assign_modes, vehicle_trips

        if new_trips.empty:
            return {"tours_added": 0, "person_trips_added": 0, "vehicles_added": 0}
        stream_key = f"{self.daytype}:policy:{key}"
        with_modes = assign_modes(
            new_trips, self.pop, self.seed, stream_key, zone_dir=self.zone_dir
        )
        speed = float(activities_config()["travel_time"]["speed_kmh"])
        veh = vehicle_trips(with_modes, self.seed, stream_key, speed)
        self.trips = concat_trips(self.trips, with_modes)
        self.vehicles = concat_trips(self.vehicles, veh)
        return {
            "tours_added": int(new_trips["tour_id"].nunique()),
            "person_trips_added": len(new_trips),
            "vehicles_added": len(veh),
        }

    def set_mode(self, tours: Any, mode: str, key: str) -> dict[str, int]:
        """Give every leg of `tours` a new mode and re-derive their vehicles."""
        from sim.population.activities import activities_config
        from sim.population.modes import vehicle_trips

        tours = pd.Index(np.unique(np.asarray(tours, dtype=np.int64)))
        hit = self.trips["tour_id"].isin(tours)
        self.trips.loc[hit, "mode"] = mode
        v_drop = self.vehicles["tour_id"].isin(tours)
        before = int(v_drop.sum())
        self.vehicles = self.vehicles.loc[~v_drop].reset_index(drop=True)
        speed = float(activities_config()["travel_time"]["speed_kmh"])
        sub = self.trips.loc[hit]
        veh = vehicle_trips(sub, self.seed, f"{self.daytype}:policy:{key}", speed)
        self.vehicles = concat_trips(self.vehicles, veh)
        return {"tours_changed": len(tours), "vehicles_before": before, "vehicles_after": len(veh)}

    def finalize(self) -> pd.DataFrame:
        """Vehicles departing inside the simulated day, sorted like the baseline export."""
        v = self.vehicles
        v = v[(v["depart"] >= 0) & (v["depart"] < self.sim_end)]
        v = v.sort_values(SORT_KEYS, kind="stable").reset_index(drop=True)
        if not v["veh_id"].is_unique:
            raise ValueError("duplicate vehicle ids after transforms")
        self.vehicles = v
        return v


def concat_trips(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Concatenate trip/vehicle frames keeping the categorical mode column usable."""
    cats = a["mode"].cat.categories if isinstance(a["mode"].dtype, pd.CategoricalDtype) else None
    out = pd.concat([a, b[[c for c in a.columns if c in b.columns]]], ignore_index=True)
    if cats is not None:
        out["mode"] = pd.Categorical(out["mode"].astype(str), categories=cats)
    for col in ("purpose", "segment", "mode_group"):
        if col in out:
            out[col] = out[col].astype(str).astype("category")
    return out


def person_draws(plan: Plan, name: str, person_ids: np.ndarray) -> np.ndarray:
    """One uniform draw per person of the sample, independent of transform order and policy."""
    ids = np.sort(plan.pop.persons["person_id"].to_numpy())
    u = stream(plan.seed, f"policy:{name}").random(len(ids))
    return u[np.searchsorted(ids, np.asarray(person_ids))]


def tour_draws(plan: Plan, name: str, tours: np.ndarray) -> np.ndarray:
    """One uniform draw per tour id, hashed so the draw does not depend on the other tours."""
    tours = np.asarray(tours, dtype=np.uint64)
    seed = np.uint64(stream(plan.seed, f"policy:{name}").integers(1, 2**62))
    x = (tours * np.uint64(0x9E3779B97F4A7C15) + seed) & np.uint64(2**64 - 1)
    x ^= x >> np.uint64(31)
    x = (x * np.uint64(0xBF58476D1CE4E5B9)) & np.uint64(2**64 - 1)
    x ^= x >> np.uint64(27)
    return (x >> np.uint64(11)).astype(np.float64) / float(2**53)


# ---------------------------------------------------------------------------- remote work


def remote_work(plan: Plan, t: RemoteWork) -> dict[str, Any]:
    trips = plan.trips
    main = trips[trips["segment"].astype(str).isin(t.eligible_sectors) & (trips["person_id"] >= 0)]
    tours = main.groupby("tour_id", sort=True).agg(
        person_id=("person_id", "first"), sector=("segment", "first")
    )
    tours["sector"] = tours["sector"].astype(str)
    # a hybrid worker (share) is at home on a given weekday with probability days_per_week / 5
    p_home = tours["sector"].map(lambda s: t.share_for(s) * t.days_per_week / 5.0).to_numpy()
    u = person_draws(plan, "remote_work:select", tours["person_id"].to_numpy())
    home = tours[u < p_home]
    out: dict[str, Any] = {"eligible_workers_with_tour": len(tours), "remote_today": len(home)}
    out |= plan.remove_tours(home.index)
    v = person_draws(plan, "remote_work:induced", home["person_id"].to_numpy())
    who = np.unique(home["person_id"].to_numpy()[v < t.induced_trip_probability])
    new = induced_tours(plan, who, t.induced_purposes)
    added = plan.add_tours(new, "remote_work")
    out |= {f"induced_{k}": n for k, n in added.items()}
    return out


def induced_tours(plan: Plan, person_ids: np.ndarray, purposes: dict[str, float]) -> pd.DataFrame:
    """One daytime non-work tour per person (remote workers' errands), timed like homemakers'."""
    from sim.population.activities import (
        TRIP_COLUMNS,
        Context,
        sample_duration,
        sample_time,
    )

    if len(person_ids) == 0:
        return pd.DataFrame()
    day = load_daytype(plan.daytype)
    ctx = Context(plan.pop, day, plan.seed, plan.zone_dir)
    persons = plan.pop.persons.set_index("person_id").loc[person_ids]
    rng = stream(plan.seed, "policy:remote_work:induced_tours")
    names = sorted(purposes)
    w = np.array([purposes[n] for n in names], dtype=float)
    choice = rng.choice(len(names), size=len(person_ids), p=w / w.sum())
    tour_ids = plan.next_tour_ids(len(person_ids))
    for k, name in enumerate(names):
        sel = np.flatnonzero(choice == k)
        spec = day.secondary_tours.get("homemaker", {}).get(name) or day.secondary_tours.get(
            "worker", {}
        ).get(name)
        if spec is None or len(sel) == 0:
            continue
        start = sample_time(rng, len(sel), spec.start)
        dur = sample_duration(rng, len(sel), spec.duration)
        hz = persons["zone_id"].to_numpy()[sel]
        he = persons["home_edge"].to_numpy(dtype=object)[sel]
        beta = float(ctx.cfg["destination_beta_per_km"][name])
        dz = gravity_choice(rng, hz, ctx.att(name), ctx.dist_km, beta)
        de = ctx.act_edges.sample(rng, dz)
        tt = ctx.tt(hz, dz)
        dep = start - tt
        common = {
            "person_id": persons.index.to_numpy()[sel],
            "hh_id": persons["hh_id"].to_numpy()[sel],
            "tour_id": tour_ids[sel],
            "segment": "remote_work",
            "mode_group": "adult",
        }
        ctx.add(**common, leg=0, purpose=name, o_zone=hz, d_zone=dz, o_edge=he, d_edge=de,
                depart=dep)  # fmt: skip
        ctx.add(**common, leg=1, purpose="home", o_zone=dz, d_zone=hz, o_edge=de, d_edge=he,
                depart=dep + tt + dur)  # fmt: skip
    if not ctx.parts:
        return pd.DataFrame()
    out = pd.concat(ctx.parts, ignore_index=True)[TRIP_COLUMNS]
    out["depart"] = np.round(np.mod(out["depart"].to_numpy(dtype=float), DAY), 1)
    out["dist_km"] = ctx.dist_km[out["o_zone"].to_numpy(), out["d_zone"].to_numpy()].round(3)
    for col in ("o_edge", "d_edge"):
        out[col] = out[col].astype("string")
    return out.sort_values(["person_id", "tour_id", "leg"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------- staggered hours


def staggered_hours(plan: Plan, t: StaggeredHours) -> dict[str, Any]:
    trips = plan.trips
    seg = trips[(trips["segment"].astype(str) == t.segment) & (trips["person_id"] >= 0)]
    tours = seg.groupby("tour_id", sort=True)["person_id"].first()
    # the population has no school or employer ids: institutions are grouped by the district of
    # the school / workplace, so siblings' escort runs and colleagues shift together (TA-017)
    primary = plan.pop.persons.set_index("person_id")["primary_zone"]
    inst = primary.reindex(tours.to_numpy()).astype(str).to_numpy()
    uniq = np.unique(inst)
    rng = stream(plan.seed, f"policy:staggered_hours:{t.segment}")
    shifted = rng.random(len(uniq)) < t.share
    extra = rng.normal(0.0, t.spread_minutes * 60.0, len(uniq)) if t.spread_minutes > 0 else 0.0
    offset = t.offset_minutes * 60.0 + extra * np.ones(len(uniq))
    pos = np.searchsorted(uniq, inst)
    hit = shifted[pos]
    delta = pd.Series(offset[pos][hit], index=tours.index[hit])
    out: dict[str, Any] = {
        "segment": t.segment,
        "institutions": len(uniq),
        "institutions_shifted": int(shifted.sum()),
        "mean_shift_min": round(float(delta.mean() / 60.0), 1) if len(delta) else 0.0,
    }
    out |= plan.retime_tours(delta)
    return out


# ---------------------------------------------------------------------------- public transport


def pt_line(plan: Plan, t: PtLine) -> dict[str, Any]:
    from sim.policies.ptline import build_line

    line = build_line(plan, t)
    edges = plan.edges().set_index("edge_id")
    trips = plan.trips
    first = trips.drop_duplicates("tour_id")
    h0, h1 = hhmm_to_s(t.hours[0]), hhmm_to_s(t.hours[1])
    cand = first[
        first["mode"].astype(str).isin(t.shift_modes)
        & first["depart"].between(h0, h1, inclusive="left")
        & first["o_edge"].isin(edges.index)
        & first["d_edge"].isin(edges.index)
    ]
    sx, sy = utm_xy(line["stop_lon"], line["stop_lat"])

    def nearest_stop(edge_ids: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        ex, ey = utm_xy(
            edges.loc[edge_ids, "lon"].to_numpy(), edges.loc[edge_ids, "lat"].to_numpy()
        )
        d = np.hypot(ex[:, None] - sx[None, :], ey[:, None] - sy[None, :])
        return d.min(axis=1), line["stop_group"][d.argmin(axis=1)]

    do, so = nearest_stop(cand["o_edge"])
    dd, sd = nearest_stop(cand["d_edge"])
    inside = (do <= t.catchment_m) & (dd <= t.catchment_m) & (so != sd)
    eligible = cand[inside]
    u = tour_draws(plan, f"pt_line:{t.line_id}", eligible["tour_id"].to_numpy())
    shift = eligible.loc[u < t.shift_share, "tour_id"]
    out: dict[str, Any] = {
        "line": t.line_id,
        "stops": int(len(line["stop_lon"])),
        "directions": line["directions"],
        "bus_departures": line["departures"],
        "tours_in_catchment": len(eligible),
        "tours_shifted": len(shift),
    }
    out |= {f"shift_{k}": v for k, v in plan.set_mode(shift, "bus", f"pt_line:{t.line_id}").items()}
    return out


# ---------------------------------------------------------------------------- road pricing


def road_pricing(plan: Plan, t: RoadPricing) -> dict[str, Any]:
    from shapely import contains_xy
    from shapely.geometry import Polygon

    from sim.policies.routes import routes_using

    poly = Polygon(t.polygon)
    e = plan.edges()
    in0 = contains_xy(poly, e["lon0"].to_numpy(), e["lat0"].to_numpy())
    in1 = contains_xy(poly, e["lon1"].to_numpy(), e["lat1"].to_numpy())
    charged_edges = e["edge_id"].to_numpy()[(~in0 & in1) | ((in0 & ~in1) & (t.direction == "both"))]
    inside_edge = dict(zip(e["edge_id"], contains_xy(poly, e["lon"], e["lat"]), strict=True))
    h0, h1 = hhmm_to_s(t.hours[0]), hhmm_to_s(t.hours[1])
    v = plan.vehicles
    in_hours = v["depart"].between(h0, h1, inclusive="left").to_numpy()
    crossing = np.zeros(len(v), dtype=bool)
    # vehicles with a baseline route: does it use a charged (cordon-crossing) edge?
    if plan.base_routes is not None:
        users = routes_using(plan.base_routes, set(charged_edges), set(v.loc[in_hours, "veh_id"]))
        crossing |= v["veh_id"].isin(users).to_numpy()
    # new vehicles without a route: origin and destination on different sides
    o_in = v["o_edge"].map(inside_edge).fillna(False).to_numpy(dtype=bool)
    d_in = v["d_edge"].map(inside_edge).fillna(False).to_numpy(dtype=bool)
    od_cross = (~o_in & d_in) | ((o_in & ~d_in) & (t.direction == "both"))
    if plan.base_routes is None:
        crossing |= od_cross
    charged = in_hours & crossing
    charged_tours = np.unique(v.loc[charged, "tour_id"].to_numpy())
    charged_ids = set(v.loc[charged, "veh_id"])
    # demand response: constant-elasticity on the generalised trip cost
    suppressed_share = 1.0 - (1.0 + t.charge_sar / t.base_trip_cost_sar) ** t.elasticity
    u = tour_draws(plan, "road_pricing:suppress", charged_tours)
    w = tour_draws(plan, "road_pricing:retime", charged_tours)
    suppressed = charged_tours[u < suppressed_share]
    retimed = suppressed[w[u < suppressed_share] < t.retime_share]
    dropped = np.setdiff1d(suppressed, retimed)
    out: dict[str, Any] = {
        "charged_edges": len(charged_edges),
        "charged_vehicles": int(charged.sum()),
        "charged_tours": len(charged_tours),
        "suppressed_share": round(float(suppressed_share), 4),
        "tours_retimed_out_of_hours": len(retimed),
    }
    # re-timed: the charged legs move just outside the charging hours (nearer edge, +0-30 min)
    if len(retimed):
        legs = v[charged & v["tour_id"].isin(retimed).to_numpy()]
        rng = stream(plan.seed, "policy:road_pricing:retime_minutes")
        jitter = rng.uniform(0.0, 1800.0, len(legs))
        dep = legs["depart"].to_numpy()
        new = np.where(dep - h0 < h1 - dep, h0 - 60.0 - jitter, h1 + jitter)
        idx = legs.index
        plan.vehicles.loc[idx, "depart"] = np.round(np.mod(new, DAY), 1)
        out["vehicles_retimed"] = len(legs)
    out |= {f"dropped_{k}": n for k, n in plan.remove_tours(dropped).items()}
    # the rest pay and are re-routed with the charge as a time penalty on cordon edges
    remaining = np.setdiff1d(charged_tours, suppressed)
    v = plan.vehicles
    stay = v[v["veh_id"].isin(charged_ids) & v["tour_id"].isin(remaining)]
    plan.force_reroute |= set(stay["veh_id"])
    seconds = t.charge_sar / t.value_of_time_sar_h * 3600.0
    plan.penalties.append(Penalty(list(map(str, charged_edges)), h0, h1, seconds))
    out |= {"vehicles_rerouted_with_penalty": len(stay), "penalty_s": round(seconds, 1)}
    return out


# ---------------------------------------------------------------------------- network change


def network_change(plan: Plan, t: NetworkChange, policy_id: str) -> dict[str, Any]:
    from sim.policies.netedit import apply_network_change

    return apply_network_change(plan, t, policy_id)


# ---------------------------------------------------------------------------- ride-hail


def ridehail_share(plan: Plan, t: RidehailShare) -> dict[str, Any]:
    trips = plan.trips
    first = trips.drop_duplicates("tour_id")
    car = first[(first["mode"].astype(str) == "car") & (first["person_id"] >= 0)]
    u = tour_draws(plan, "ridehail_share:convert", car["tour_id"].to_numpy())
    conv = car.loc[u < t.convert_share, "tour_id"].to_numpy()
    out: dict[str, Any] = {"car_tours": len(car), "tours_converted": len(conv)}
    out |= {f"convert_{k}": n for k, n in plan.set_mode(conv, "ridehail", "ridehail").items()}
    if t.deadhead_factor <= 0 or len(conv) == 0:
        return out
    # empty leg to each pickup: from a zone about deadhead_factor x the trip distance away
    from sim.population.activities import Context

    ctx = Context(plan.pop, load_daytype(plan.daytype), plan.seed, plan.zone_dir)
    v = plan.vehicles
    rides = v[v["tour_id"].isin(conv) & ~v["empty"].astype(bool)]
    rng = stream(plan.seed, "policy:ridehail_share:deadhead")
    target = rides["dist_km"].to_numpy(dtype=float) * t.deadhead_factor
    oz = rides["o_zone"].to_numpy()
    dist = ctx.dist_km[oz]  # rows: origin zone, cols: candidate zones
    noise = rng.uniform(0.8, 1.2, (len(rides), 1))
    fz = np.abs(dist - target[:, None] * noise).argmin(axis=1)
    fz = np.array([z if ctx.act_edges.has(int(z)) else o for z, o in zip(fz, oz, strict=True)])
    fe = ctx.act_edges.sample(rng, fz)
    tt = np.maximum(ctx.dist_km[fz, oz] / ctx.speed_kmh * 3600.0, 120.0)
    e = rides.copy()
    e["d_edge"], e["d_zone"] = rides["o_edge"].to_numpy(), oz
    e["o_edge"], e["o_zone"] = fe, fz
    e["depart"] = np.round(np.mod(rides["depart"].to_numpy() - tt, DAY), 1)
    e["dist_km"] = ctx.dist_km[fz, oz].round(3)
    e["empty"] = True
    e["purpose"] = "deadhead"
    e["veh_id"] = ["d" + vid[1:] for vid in rides["veh_id"]]
    e = e[e["o_edge"] != e["d_edge"]]
    plan.vehicles = concat_trips(plan.vehicles, e)
    out["deadhead_vehicles_added"] = len(e)
    return out


# ---------------------------------------------------------------------------- dispatch


def apply(plan: Plan, t: Any, policy_id: str) -> dict[str, Any]:
    if isinstance(t, RemoteWork):
        eff = remote_work(plan, t)
    elif isinstance(t, StaggeredHours):
        eff = staggered_hours(plan, t)
    elif isinstance(t, PtLine):
        eff = pt_line(plan, t)
    elif isinstance(t, RoadPricing):
        eff = road_pricing(plan, t)
    elif isinstance(t, NetworkChange):
        eff = network_change(plan, t, policy_id)
    elif isinstance(t, RidehailShare):
        eff = ridehail_share(plan, t)
    elif isinstance(t, DayTypeChange):
        eff = {"daytype": t.daytype, "note": "run starts from this day type's baseline"}
    else:  # pragma: no cover - the schema rejects unknown types
        raise TypeError(f"unknown transform {type(t).__name__}")
    eff = {"type": t.type, **eff}
    plan.effects.append(eff)
    return eff
