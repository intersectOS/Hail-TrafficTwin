"""Fixed mode shares by person group and car availability (v1; logit is P2).

One mode per tour (both legs share it). Rules: walking only under `walk_max_km` (with a short-trip
boost), bus only where both ends are within the bus catchment of a stop. Vehicle trips: each tour
puts a vehicle on the road with probability `vehicle_per_trip` (1/occupancy for shared vehicles);
escort tours add the driver's empty legs (with a configured probability).

    python -m sim.population.modes --daytype weekday --seed 1 --sample 0.10
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, load_yaml
from sim.population.sampling import categorical, stream
from sim.population.synthesize import Population
from sim.population.zones import default_zone_dir, load_zones

MODES_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "modes.yaml"
AVAIL = ("driver", "hh_car", "no_car")


def modes_config(path: Path = MODES_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


def mode_names(cfg: dict[str, Any]) -> list[str]:
    return [m for m in cfg["modes"] if m not in ("source", "assumption")]


def availability(persons: pd.DataFrame) -> pd.Series:
    """driver / hh_car / no_car per person_id."""
    avail = np.where(
        persons["car_driver"], "driver", np.where(persons["hh_car"], "hh_car", "no_car")
    )
    return pd.Series(avail, index=persons["person_id"].to_numpy())


def assign_modes(
    trips: pd.DataFrame,
    pop: Population,
    seed: int,
    daytype: str,
    cfg: dict[str, Any] | None = None,
    zone_dir: Path | None = None,
) -> pd.DataFrame:
    """Add a `mode` column (per tour) to the person trips."""
    cfg = cfg or modes_config()
    names = mode_names(cfg)
    rules = cfg["rules"]
    _, zone_edges, _ = load_zones(zone_dir or default_zone_dir())
    near_bus = set(zone_edges.loc[zone_edges["near_bus_stop"], "edge_id"])

    tours = trips.groupby("tour_id", sort=True).agg(
        person_id=("person_id", "first"),
        group=("mode_group", "first"),
        dist_km=("dist_km", "max"),
    )
    first_legs = trips.drop_duplicates("tour_id").set_index("tour_id").loc[tours.index]
    bus_ok = (
        first_legs["o_edge"].isin(near_bus).to_numpy()
        & first_legs["d_edge"].isin(near_bus).to_numpy()
    )
    avail = availability(pop.persons)
    tour_avail = avail.reindex(tours["person_id"].to_numpy()).fillna("driver").to_numpy()
    group = tours["group"].astype(str).to_numpy()
    probs = np.zeros((len(tours), len(names)))
    for g in np.unique(group):
        table = cfg["shares"][g]
        for a in AVAIL:
            sel = (group == g) & (tour_avail == a)
            if sel.any():
                probs[sel] = [float(table[a].get(m, 0.0)) for m in names]
    # rules: walking only for short trips (with a boost), bus only near stops
    walk = names.index("walk")
    short = tours["dist_km"].to_numpy() <= float(rules["walk_max_km"])
    fb_map = {a: names.index(m) for a, m in rules["fallback"].items()}
    fallback = np.array([fb_map[a] for a in tour_avail])
    rows = np.arange(len(tours))

    def move(col: int, allowed: np.ndarray) -> None:
        moved = np.where(allowed, 0.0, probs[:, col])
        probs[:, col] -= moved
        np.add.at(probs, (rows, fallback), moved)

    move(walk, short)
    boost = short & (probs[:, walk] > 0) & np.isin(group, ["adult", "child", "mosque"])
    probs[boost, walk] += float(rules["walk_short_boost"])
    if rules.get("bus_requires_stops", True):
        move(names.index("bus"), bus_ok)
    rng = stream(seed, f"modes:{daytype}")
    code = categorical(rng, probs)
    tour_mode = pd.Series(np.asarray(names)[code], index=tours.index)
    out = trips.copy()
    out["mode"] = pd.Categorical(tour_mode.reindex(out["tour_id"]).to_numpy(), categories=names)
    return out


def vehicle_trips(
    trips: pd.DataFrame,
    seed: int,
    daytype: str,
    speed_kmh: float,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Person trips -> vehicle trips (vtype, depart, from/to edge), with escort empty legs."""
    cfg = cfg or modes_config()
    spec = {m: cfg["modes"][m] for m in mode_names(cfg)}
    vpt = trips["mode"].map({m: float(s["vehicle_per_trip"]) for m, s in spec.items()})
    vpt = vpt.astype(float).to_numpy()
    rng = stream(seed, f"vehicles:{daytype}")
    tour_ids = trips["tour_id"].to_numpy()
    uniq, inv = np.unique(tour_ids, return_inverse=True)
    u = rng.random(len(uniq))[inv]  # one draw per tour: both legs share the vehicle
    keep = u < vpt
    v = trips.loc[keep].copy()
    v["vtype"] = v["mode"].map({m: s.get("vtype", "") for m, s in spec.items()}).astype(str)
    v["empty"] = False
    esc_modes = [m for m, s in spec.items() if s.get("return_empty")]
    esc = v[v["mode"].isin(esc_modes)]
    # the empty leg happens only when the driver is not travelling on (e.g. a parent continuing to
    # work, whose commute is already a trip of its own)
    p_empty = esc["mode"].map({m: float(spec[m]["return_empty"]) for m in esc_modes})
    esc = esc[stream(seed, f"escort:{daytype}").random(len(esc)) < p_empty.to_numpy(dtype=float)]
    if len(esc):
        tt = np.maximum(esc["dist_km"].to_numpy() / speed_kmh * 3600.0, 240.0)
        from_home = esc["leg"].to_numpy() == 0
        e = esc.copy()
        e["o_edge"], e["d_edge"] = esc["d_edge"].to_numpy(), esc["o_edge"].to_numpy()
        e["o_zone"], e["d_zone"] = esc["d_zone"].to_numpy(), esc["o_zone"].to_numpy()
        # outbound (from home): return empty after drop-off; inbound: drive out empty before
        e["depart"] = np.where(from_home, esc["depart"] + tt + 300.0, esc["depart"] - tt - 300.0)
        e["depart"] = np.mod(e["depart"].to_numpy(), 86400.0)
        e["empty"] = True
        e["purpose"] = "escort"
        v = pd.concat([v, e], ignore_index=True)
    v = v[v["o_edge"] != v["d_edge"]]
    v = v.sort_values(["depart", "person_id", "tour_id", "leg", "empty"], kind="stable")
    v = v.reset_index(drop=True)
    pid = v["person_id"].to_numpy()
    prefix = np.where(pid < 0, "a", np.where(v["empty"].to_numpy(), "e", "p"))
    v["veh_id"] = [
        f"{p}{abs(int(a))}_{int(t)}_{int(leg)}"
        for p, a, t, leg in zip(prefix, pid, v["tour_id"], v["leg"], strict=True)
    ]
    return v


def mode_summary(trips: pd.DataFrame, persons: int) -> dict[str, Any]:
    shares = trips["mode"].value_counts(normalize=True).sort_index()
    return {
        "person_trips": len(trips),
        "mode_shares": {k: round(float(x), 4) for k, x in shares.items()},
        "person_trips_per_person": round(
            float((trips["person_id"] >= 0).sum()) / max(persons, 1), 3
        ),
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    daytype: str = typer.Option("weekday"),
    seed: int = typer.Option(1),
    sample: float = typer.Option(0.10),
) -> None:
    from sim.population.activities import activities_config, load_or_generate

    pop, trips, _ = load_or_generate(seed, sample, daytype)
    trips = assign_modes(trips, pop, seed, daytype)
    speed = float(activities_config()["travel_time"]["speed_kmh"])
    veh = vehicle_trips(trips, seed, daytype, speed)
    out = mode_summary(trips, len(pop.persons))
    out["vehicle_trips"] = len(veh)
    out["vehicle_trips_per_person"] = round(len(veh) / len(pop.persons), 3)
    out["vehicle_trips_full_population"] = int(round(len(veh) / sample))
    out["vtypes"] = veh["vtype"].value_counts().to_dict()
    typer.echo(json.dumps(out, indent=2))


if __name__ == "__main__":
    app()
