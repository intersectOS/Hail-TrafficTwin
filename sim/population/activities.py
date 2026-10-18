"""Daily activity chains -> person trips for one day type.

For each person: the main tour of their segment (work by sector, school, university) with
optional split shift and errand on the way home; secondary tours (shopping, leisure, personal) by
status, chained after the person is home; mosque trips keyed to the computed adhan times of the
simulated date; plus airport ground trips (and the Makkah gate share). Start times, durations and
rates come from `sim/daytypes/<daytype>.yaml`; destination choice and planning speed from
`sim/population/config/activities.yaml`.

Output: one row per person trip (`trips.parquet`) with origin/destination zone and edge,
departure time (s after midnight, wrapped into the day), purpose, tour id and mode group.

    python -m sim.population.activities --daytype weekday --seed 1 --sample 0.10
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, load_yaml
from sim.daytypes.prayer import prayer_times
from sim.population.sampling import (
    EdgeSampler,
    frame_hash,
    gravity_choice,
    mixture_times,
    stream,
    truncated_normal,
)
from sim.population.synthesize import Population, load_or_synthesize
from sim.population.zones import default_zone_dir, load_zones, zone_distances
from sim.schemas import WORK_SECTORS, DayType, DurationDist, TimeDist, load_daytype

ACT_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "activities.yaml"
DAY = 86400.0
PURPOSES = (
    "work",
    "school",
    "university",
    "home",
    "stop",
    "shopping",
    "leisure",
    "personal",
    "mosque",
    "airport",
    "makkah",
)
TRIP_COLUMNS = [
    "person_id",
    "hh_id",
    "tour_id",
    "leg",
    "purpose",
    "segment",
    "mode_group",
    "o_zone",
    "d_zone",
    "o_edge",
    "d_edge",
    "depart",
]


def activities_config(path: Path = ACT_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


class Context:
    """Zones, distances, samplers and config shared by the generators."""

    def __init__(self, pop: Population, day: DayType, seed: int, zone_dir: Path | None) -> None:
        self.pop = pop
        self.day = day
        self.seed = seed
        self.cfg = activities_config()
        pcfg = load_yaml(REPO_ROOT / "sim" / "population" / "config" / "population.yaml")
        self.zones, self.zone_edges, _ = load_zones(zone_dir or default_zone_dir())
        detour = float(pcfg["location_choice"]["detour_factor"])
        self.dist_km = zone_distances(self.zones, detour) / 1000.0
        self.act_edges = EdgeSampler(self.zone_edges, "act_w")
        self.home_edges = EdgeSampler(self.zone_edges, "home_w")
        tt = self.cfg["travel_time"]
        self.speed_kmh = float(tt["speed_kmh"])
        self.min_tt = float(tt["min_min"]) * 60.0
        self.tours = 0
        self.parts: list[pd.DataFrame] = []

    def tt(self, o: np.ndarray, d: np.ndarray) -> np.ndarray:
        """Planning travel time (s) between zones."""
        return np.maximum(self.dist_km[o, d] / self.speed_kmh * 3600.0, self.min_tt)

    def new_tours(self, n: int) -> np.ndarray:
        ids = np.arange(self.tours, self.tours + n, dtype=np.int64)
        self.tours += n
        return ids

    def att(self, purpose: str) -> np.ndarray:
        return self.zones[f"att_{purpose}"].to_numpy(dtype=float)

    def add(self, **cols: Any) -> None:
        n = len(cols["depart"])
        if n == 0:
            return
        frame = {c: cols.get(c) for c in TRIP_COLUMNS}
        for key, value in frame.items():
            if value is None:
                raise KeyError(f"trip column {key} missing")
            if np.ndim(value) == 0:
                frame[key] = np.repeat(value, n)
        self.parts.append(pd.DataFrame(frame))


def sample_time(rng: np.random.Generator, n: int, dist: TimeDist) -> np.ndarray:
    return mixture_times(rng, n, dist.as_components(), dist.lo_s, dist.hi_s)


def sample_duration(rng: np.random.Generator, n: int, dist: DurationDist) -> np.ndarray:
    mean = np.full(n, dist.mean_min * 60.0)
    sd = np.full(n, dist.sd_min * 60.0)
    return truncated_normal(rng, mean, sd, dist.lo_min * 60.0, dist.hi_min * 60.0)


# ---------------------------------------------------------------------------- main tours


def main_tours(ctx: Context, persons: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Work / school / university tours. Returns per-person (busy_from, home_again) in seconds."""
    n = len(persons)
    busy_from = np.full(n, np.inf)
    home_again = np.zeros(n)
    status = persons["status"].astype(str).to_numpy()
    sector = persons["sector"].astype(str).to_numpy()
    level = persons["school_level"].astype(str).to_numpy()
    labour = (persons["hh_type"].astype(str) == "non_saudi_shared").to_numpy()
    for segment, tour in ctx.day.main_tours.items():
        if segment in WORK_SECTORS:
            members = (status == "worker") & (sector == segment)
            purpose = "work"
        else:
            members = level == segment
            purpose = segment
        rng = stream(ctx.seed, f"main:{ctx.day.id}:{segment}")
        idx = np.flatnonzero(members)
        idx = idx[rng.random(len(idx)) < tour.participation.value]
        idx = idx[persons["primary_zone"].to_numpy()[idx] >= 0]
        if len(idx) == 0:
            continue
        p = persons.iloc[idx]
        hz = p["zone_id"].to_numpy()
        pz = p["primary_zone"].to_numpy()
        he = p["home_edge"].to_numpy(dtype=object)
        pe = p["primary_edge"].to_numpy(dtype=object)
        tt = ctx.tt(hz, pz)
        start = sample_time(rng, len(idx), tour.start)
        dur = sample_duration(rng, len(idx), tour.duration)
        end = start + dur
        ea = ctx.cfg["early_arrival"]
        buffer = rng.uniform(float(ea["lo_min"]) * 60.0, float(ea["hi_min"]) * 60.0, len(idx))
        if segment == "school":
            group = np.full(len(idx), "pupil", dtype=object)
        else:
            group = np.where(labour[idx], "labour", "adult").astype(object)
        tours = ctx.new_tours(len(idx))
        common = {"person_id": p["person_id"].to_numpy(), "hh_id": p["hh_id"].to_numpy()}
        common |= {"tour_id": tours, "segment": segment, "mode_group": group}
        ctx.add(
            **common,
            leg=0,
            purpose=purpose,
            o_zone=hz,
            d_zone=pz,
            o_edge=he,
            d_edge=pe,
            depart=start - tt - buffer,
        )
        split = np.zeros(len(idx), dtype=bool)
        if tour.split_shift is not None:
            ss = tour.split_shift
            split = rng.random(len(idx)) < ss.probability
            k = int(split.sum())
            b0 = sample_time(rng, k, ss.break_start)
            b0 = np.clip(b0, start[split] + 3600.0, np.maximum(end[split] - 3600.0, start[split]))
            blen = sample_duration(rng, k, ss.break_min)
            sub = {key: (v[split] if isinstance(v, np.ndarray) else v) for key, v in common.items()}
            ctx.add(
                **sub,
                leg=1,
                purpose="home",
                o_zone=pz[split],
                d_zone=hz[split],
                o_edge=pe[split],
                d_edge=he[split],
                depart=b0,
            )
            ctx.add(
                **sub,
                leg=2,
                purpose=purpose,
                o_zone=hz[split],
                d_zone=pz[split],
                o_edge=he[split],
                d_edge=pe[split],
                depart=b0 + blen - tt[split],
            )
            end[split] += blen
        stop = np.zeros(len(idx), dtype=bool)
        if tour.stop_on_return is not None:
            stop = rng.random(len(idx)) < tour.stop_on_return.value
        home_at = end + tt
        # direct return
        direct = ~stop
        sub = {key: (v[direct] if isinstance(v, np.ndarray) else v) for key, v in common.items()}
        ctx.add(
            **sub,
            leg=3,
            purpose="home",
            o_zone=pz[direct],
            d_zone=hz[direct],
            o_edge=pe[direct],
            d_edge=he[direct],
            depart=end[direct],
        )
        # errand on the way home
        if stop.any():
            sc = ctx.cfg["stop_on_return"]
            beta = float(ctx.cfg["destination_beta_per_km"]["stop"])
            att = ctx.att(sc["purpose"])
            sz = gravity_choice(rng, pz[stop], att, ctx.dist_km, beta)
            se = ctx.act_edges.sample(rng, sz)
            sdur = sample_duration(
                rng, int(stop.sum()), DurationDist(**sc["duration"], assumption="A-act-003")
            )
            t1 = ctx.tt(pz[stop], sz)
            sub = {key: (v[stop] if isinstance(v, np.ndarray) else v) for key, v in common.items()}
            ctx.add(
                **sub,
                leg=3,
                purpose="stop",
                o_zone=pz[stop],
                d_zone=sz,
                o_edge=pe[stop],
                d_edge=se,
                depart=end[stop],
            )
            leave = end[stop] + t1 + sdur
            ctx.add(
                **sub,
                leg=4,
                purpose="home",
                o_zone=sz,
                d_zone=hz[stop],
                o_edge=se,
                d_edge=he[stop],
                depart=leave,
            )
            home_at[stop] = leave + ctx.tt(sz, hz[stop])
        busy_from[idx] = np.minimum(busy_from[idx], start - tt - buffer)
        home_again[idx] = np.maximum(home_again[idx], home_at)
    return busy_from, home_again


# ---------------------------------------------------------------------------- secondary tours


def secondary_tours(ctx: Context, persons: pd.DataFrame, home_again: np.ndarray) -> None:
    gap = float(ctx.cfg["min_tour_gap_min"]) * 60.0
    min_age = ctx.cfg["secondary_min_age_group"]
    ages = list(persons["age_group"].cat.categories)
    age_code = persons["age_group"].cat.codes.to_numpy()
    eligible = age_code >= ages.index(min_age)
    minor = age_code < ages.index("a18_24")
    status = persons["status"].astype(str).to_numpy()
    busy_until = home_again.copy()
    hz_all = persons["zone_id"].to_numpy()
    he_all = persons["home_edge"].to_numpy(dtype=object)
    for group, tours in ctx.day.secondary_tours.items():
        for purpose, spec in tours.items():
            rng = stream(ctx.seed, f"secondary:{ctx.day.id}:{group}:{purpose}")
            members = np.flatnonzero(eligible & (status == group))
            rate = spec.rate.value
            count = np.floor(rate).astype(int) + (rng.random(len(members)) < rate % 1.0)
            idx = np.repeat(members, count)
            if len(idx) == 0:
                continue
            start = sample_time(rng, len(idx), spec.start)
            dur = sample_duration(rng, len(idx), spec.duration)
            hz = hz_all[idx]
            beta = float(ctx.cfg["destination_beta_per_km"][purpose])
            dz = gravity_choice(rng, hz, ctx.att(purpose), ctx.dist_km, beta)
            de = ctx.act_edges.sample(rng, dz)
            tt = ctx.tt(hz, dz)
            # chain after the person is home again; drop tours pushed far past the window
            order = np.argsort(idx, kind="stable")
            dep = start - tt
            dep_s = dep[order]
            idx_s = idx[order]
            earliest = busy_until[idx_s] + gap
            dep_s = np.maximum(dep_s, earliest)
            # several tours of the same purpose for one person: keep them sequential
            dup = np.r_[False, idx_s[1:] == idx_s[:-1]]
            for j in np.flatnonzero(dup):
                prev_end = dep_s[j - 1] + tt[order][j - 1] + dur[order][j - 1] + tt[order][j - 1]
                dep_s[j] = max(dep_s[j], prev_end + gap)
            dep = np.empty_like(dep)
            dep[order] = dep_s
            ok = dep <= spec.start.hi_s + 3600.0
            idx, dep, dur, dz, de, tt, hz = (a[ok] for a in (idx, dep, dur, dz, de, tt, hz))
            back = dep + tt + dur
            np.maximum.at(busy_until, idx, back + tt)
            group_col = np.where(minor[idx], "child", "adult").astype(object)
            tid = ctx.new_tours(len(idx))
            common = {
                "person_id": persons["person_id"].to_numpy()[idx],
                "hh_id": persons["hh_id"].to_numpy()[idx],
                "tour_id": tid,
                "segment": group,
                "mode_group": group_col,
            }
            ctx.add(
                **common,
                leg=0,
                purpose=purpose,
                o_zone=hz,
                d_zone=dz,
                o_edge=he_all[idx],
                d_edge=de,
                depart=dep,
            )
            ctx.add(
                **common,
                leg=1,
                purpose="home",
                o_zone=dz,
                d_zone=hz,
                o_edge=de,
                d_edge=he_all[idx],
                depart=back,
            )


# ---------------------------------------------------------------------------- mosque trips


def mosque_trips(
    ctx: Context, persons: pd.DataFrame, busy_from: np.ndarray, home_again: np.ndarray
) -> None:
    times = prayer_times(ctx.day.date)
    adult = persons["age_group"].astype(str).isin(["a18_24", "a25_59", "a60p"]).to_numpy()
    male = persons["male"].to_numpy()
    hz_all = persons["zone_id"].to_numpy()
    he_all = persons["home_edge"].to_numpy(dtype=object)
    for name, pr in ctx.day.prayers.items():
        rng = stream(ctx.seed, f"mosque:{ctx.day.id}:{name}")
        share = np.where(male, pr.share_adult_males, pr.share_adult_females)
        go = adult & (rng.random(len(persons)) < share)
        depart = times[name] + pr.depart_offset_min * 60.0
        at_main = (busy_from <= depart) & (home_again >= depart)
        idx = np.flatnonzero(go & ~at_main)
        if len(idx) == 0:
            continue
        hz = hz_all[idx]
        beta = float(ctx.cfg["destination_beta_per_km"]["mosque"])
        if pr.distance == "district":
            beta *= 0.3
        dz = gravity_choice(rng, hz, ctx.att("mosque"), ctx.dist_km, beta)
        de = ctx.act_edges.sample(rng, dz)
        tt = ctx.tt(hz, dz)
        dep = depart + rng.uniform(-300.0, 300.0, len(idx))
        common = {
            "person_id": persons["person_id"].to_numpy()[idx],
            "hh_id": persons["hh_id"].to_numpy()[idx],
            "tour_id": ctx.new_tours(len(idx)),
            "segment": name,
            "mode_group": "mosque",
        }
        ctx.add(
            **common,
            leg=0,
            purpose="mosque",
            o_zone=hz,
            d_zone=dz,
            o_edge=he_all[idx],
            d_edge=de,
            depart=dep,
        )
        ctx.add(
            **common,
            leg=1,
            purpose="home",
            o_zone=dz,
            d_zone=hz,
            o_edge=de,
            d_edge=he_all[idx],
            depart=dep + tt + pr.duration_min * 60.0,
        )


# ---------------------------------------------------------------------------- airport


def airport_trips(ctx: Context, sample: float) -> None:
    ap = ctx.day.airport
    rng = stream(ctx.seed, f"airport:{ctx.day.id}")
    n = int(round(ap.trips_per_day * sample))
    zones = ctx.zones
    airport_zone = int(zones["poi_airport"].to_numpy().argmax())
    if n == 0 or zones["poi_airport"].max() <= 0 or not ctx.act_edges.has(airport_zone):
        return
    prof = np.asarray(ap.hourly_profile, dtype=float)
    hour = rng.choice(24, size=n, p=prof / prof.sum())
    dep = hour * 3600.0 + rng.uniform(0, 3600.0, n)
    pop_w = zones["population"].to_numpy(dtype=float)
    city_z = rng.choice(len(zones), size=n, p=pop_w / pop_w.sum())
    city_e = ctx.home_edges.sample(rng, city_z)
    ap_z = np.full(n, airport_zone)
    ap_e = ctx.act_edges.sample(rng, ap_z)
    to_airport = rng.random(n) < 0.5
    makkah = rng.random(n) < ap.to_makkah_share
    gate = ctx.cfg["gates"]["makkah"]
    ze = ctx.zone_edges.set_index("edge_id")["zone_id"]
    if gate["out_edge"] in ze.index and gate["in_edge"] in ze.index:
        city_e = city_e.astype(object)
        city_e[makkah & to_airport] = gate["in_edge"]
        city_e[makkah & ~to_airport] = gate["out_edge"]
        city_z = city_z.copy()
        city_z[makkah & to_airport] = int(ze[gate["in_edge"]])
        city_z[makkah & ~to_airport] = int(ze[gate["out_edge"]])
    else:
        makkah[:] = False
    o_z = np.where(to_airport, city_z, ap_z)
    d_z = np.where(to_airport, ap_z, city_z)
    o_e = np.where(to_airport, city_e, ap_e)
    d_e = np.where(to_airport, ap_e, city_e)
    purpose = np.where(to_airport, "airport", np.where(makkah, "makkah", "home")).astype(object)
    ctx.add(
        person_id=np.int64(-1),
        hh_id=np.int64(-1),
        tour_id=ctx.new_tours(n),
        leg=0,
        purpose=purpose,
        segment="airport",
        mode_group="airport",
        o_zone=o_z,
        d_zone=d_z,
        o_edge=o_e,
        d_edge=d_e,
        depart=dep,
    )


# ---------------------------------------------------------------------------- driver


def generate(
    pop: Population, day: DayType, seed: int, sample: float, zone_dir: Path | None = None
) -> pd.DataFrame:
    ctx = Context(pop, day, seed, zone_dir)
    persons = pop.persons.reset_index(drop=True)
    busy_from, home_again = main_tours(ctx, persons)
    secondary_tours(ctx, persons, home_again)
    mosque_trips(ctx, persons, busy_from, home_again)
    airport_trips(ctx, sample)
    trips = pd.concat(ctx.parts, ignore_index=True)
    if ctx.cfg.get("wrap_after_midnight", True):
        trips["depart"] = np.mod(trips["depart"].to_numpy(), DAY)
    trips["depart"] = trips["depart"].round(1)
    o, d = trips["o_zone"].to_numpy(), trips["d_zone"].to_numpy()
    trips["dist_km"] = ctx.dist_km[o, d].round(3)
    for col in ("purpose", "segment", "mode_group"):
        trips[col] = trips[col].astype("category")
    for col in ("o_edge", "d_edge"):
        trips[col] = trips[col].astype("string")
    trips = trips.sort_values(["person_id", "tour_id", "leg"], kind="stable").reset_index(drop=True)
    return trips


def trips_cache_dir(pop: Population, daytype: str) -> Path:
    key = config_hash({"act": activities_config(), "day": load_daytype(daytype).model_dump()})
    return REPO_ROOT / pop.meta["dir"] / f"trips-{daytype}-{key[:10]}"


def load_or_generate(
    seed: int, sample: float, daytype: str, zone_dir: Path | None = None, force: bool = False
) -> tuple[Population, pd.DataFrame, dict[str, Any]]:
    pop = load_or_synthesize(seed, sample, zone_dir)
    out = trips_cache_dir(pop, daytype)
    meta_path = out / "trips.json"
    if meta_path.exists() and not force:
        return pop, pd.read_parquet(out / "trips.parquet"), json.loads(meta_path.read_text())
    day = load_daytype(daytype)
    trips = generate(pop, day, seed, sample, zone_dir)
    out.mkdir(parents=True, exist_ok=True)
    trips.to_parquet(out / "trips.parquet", index=False)
    meta = {
        "label": SYNTHETIC_LABEL,
        "daytype": daytype,
        "date": day.date,
        "seed": seed,
        "sample": sample,
        "population_hash": pop.meta["population_hash"],
        "person_trips": len(trips),
        "trips_hash": frame_hash(trips),
        "prayer_times": prayer_times(day.date),
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    return pop, trips, meta


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    daytype: str = typer.Option("weekday"),
    seed: int = typer.Option(1),
    sample: float = typer.Option(0.10),
    force: bool = typer.Option(False),
) -> None:
    t0 = time.perf_counter()
    pop, trips, meta = load_or_generate(seed, sample, daytype, force=force)
    persons = len(pop.persons)
    typer.echo(json.dumps(meta, indent=2))
    typer.echo(
        f"{len(trips):,} person trips for {persons:,} persons "
        f"({len(trips[trips.person_id >= 0]) / persons:.2f} per person); "
        f"{time.perf_counter() - t0:.1f} s"
    )
    typer.echo(trips.groupby("purpose", observed=True).size().to_string())


if __name__ == "__main__":
    app()
