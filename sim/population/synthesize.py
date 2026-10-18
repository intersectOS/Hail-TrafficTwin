"""Synthetic population of Jeddah: households and persons with primary locations.

Per zone, residents are split by nationality and household type (Saudi family, non-Saudi family,
non-Saudi shared housing), grouped into households of sampled size, and given age group, sex,
status (worker / student / homemaker / other), work sector, car availability, a home edge and a
primary location (workplace, school or university zone and edge). All behavioural numbers come
from `sim/population/config/population.yaml`.

The full population is synthesised, then households are sampled with an independent stream so a
10 % sample is a subset of the 25 % sample. Results are cached as Parquet with a population hash.

    python -m sim.population.synthesize --seed 1 --sample 0.10
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, config_hash, load_yaml
from sim.population.sampling import (
    EdgeSampler,
    categorical,
    dist_table,
    frame_hash,
    gravity_choice,
    stream,
)
from sim.population.zones import default_zone_dir, load_zones, zone_distances
from sim.schemas import WORK_SECTORS

POP_CONFIG = REPO_ROOT / "sim" / "population" / "config" / "population.yaml"
CACHE_DIR = REPO_ROOT / "data" / "population"
AGE_GROUPS = ("a0_5", "a6_17", "a18_24", "a25_59", "a60p")
HH_TYPES = ("saudi", "non_saudi_family", "non_saudi_shared")
STATUSES = ("worker", "student", "homemaker", "other")


def population_config(path: Path = POP_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


@dataclass
class Population:
    households: pd.DataFrame
    persons: pd.DataFrame
    meta: dict[str, Any]


# ---------------------------------------------------------------------------- households


def _households_for(rng: np.random.Generator, target: int, sizes: dict) -> np.ndarray:
    """Household sizes summing exactly to `target` (the last one is truncated)."""
    if target <= 0:
        return np.empty(0, dtype=np.int64)
    keys, probs = dist_table(sizes)
    mean = float(np.dot(keys, probs))
    n = int(target / mean * 1.2) + 10
    while True:
        draw = np.asarray(keys)[rng.choice(len(keys), size=n, p=probs)].astype(np.int64)
        cum = np.cumsum(draw)
        if cum[-1] >= target:
            break
        n *= 2
    k = int(np.searchsorted(cum, target))
    out = draw[: k + 1].copy()
    out[-1] -= int(cum[k] - target)
    return out[out > 0]


def make_households(zones: pd.DataFrame, cfg: dict, seed: int) -> pd.DataFrame:
    rng = stream(seed, "households")
    saudi_share = float(cfg["nationality"]["saudi_share"])
    fam_share = float(cfg["households"]["non_saudi_family_share"]["value"])
    rows = []
    for zid, pop in zip(zones["zone_id"], zones["population"], strict=True):
        pop = int(pop)
        n_saudi = int(round(pop * saudi_share))
        n_fam = int(round((pop - n_saudi) * fam_share))
        targets = {
            "saudi": n_saudi,
            "non_saudi_family": n_fam,
            "non_saudi_shared": pop - n_saudi - n_fam,
        }
        for hh_type, target in targets.items():
            sizes = _households_for(rng, target, cfg["households"][hh_type]["sizes"])
            if len(sizes):
                rows.append(
                    pd.DataFrame(
                        {
                            "zone_id": np.int32(zid),
                            "hh_type": hh_type,
                            "size": sizes.astype("int16"),
                        }
                    )
                )
    hh = pd.concat(rows, ignore_index=True)
    hh.insert(0, "hh_id", np.arange(len(hh), dtype=np.int64))
    hh["hh_type"] = pd.Categorical(hh["hh_type"], categories=HH_TYPES)
    return hh


# ---------------------------------------------------------------------------- persons


def _expand(hh: pd.DataFrame) -> pd.DataFrame:
    idx = np.repeat(np.arange(len(hh)), hh["size"].to_numpy())
    p = pd.DataFrame(
        {
            "hh_id": hh["hh_id"].to_numpy()[idx],
            "zone_id": hh["zone_id"].to_numpy()[idx],
            "hh_type": hh["hh_type"].to_numpy()[idx],
            "hh_size": hh["size"].to_numpy()[idx],
        }
    )
    starts = np.concatenate([[0], np.cumsum(hh["size"].to_numpy())[:-1]])
    p["rank"] = (np.arange(len(p)) - np.repeat(starts, hh["size"].to_numpy())).astype("int16")
    return p


def assign_age_sex(p: pd.DataFrame, cfg: dict, seed: int) -> pd.DataFrame:
    """Heads and spouses first, dependents from the residual of the census age targets."""
    rng = stream(seed, "age_sex")
    n = len(p)
    age = np.full(n, -1, dtype=np.int8)
    male = np.zeros(n, dtype=bool)
    hh_type = p["hh_type"].astype(str).to_numpy()
    rank = p["rank"].to_numpy()
    size = p["hh_size"].to_numpy()
    heads = cfg["heads"]
    a2559, a60 = AGE_GROUPS.index("a25_59"), AGE_GROUPS.index("a60p")

    # shared housing: adults only, mostly male
    shared = hh_type == "non_saudi_shared"
    tgt = cfg["age_shares"]["non_saudi"]
    adult_p = np.array([0, 0, tgt["a18_24"], tgt["a25_59"], tgt["a60p"]], dtype=float)
    age[shared] = rng.choice(5, size=int(shared.sum()), p=adult_p / adult_p.sum())
    male[shared] = rng.random(int(shared.sum())) < cfg["sex"]["shared_household_male_share"]

    for nat, types in (("saudi", ("saudi",)), ("non_saudi", ("non_saudi_family",))):
        fam = np.isin(hh_type, types)
        head = fam & (rank == 0)
        spouse = fam & (rank == 1)
        dep = fam & (rank >= 2)
        p60 = heads["saudi_head_60p" if nat == "saudi" else "non_saudi_head_60p"]
        head_age = np.where(rng.random(n) < p60, a60, a2559).astype(np.int8)
        age[head] = head_age[head]
        # spouse shares the head's age group (head age broadcast through the household id)
        hh_ids = p["hh_id"].to_numpy()
        head_age_by_hh = pd.Series(age[head], index=hh_ids[head])
        age[spouse] = head_age_by_hh.reindex(hh_ids[spouse]).to_numpy()
        single = head & (size == 1)
        female_single = single & (rng.random(n) < heads["saudi_single_head_female"])
        male[head] = True
        male[female_single] = False
        male[spouse] = False
        # dependents fill the residual age distribution of this nationality
        target = cfg["age_shares"][nat]
        nat_mask = fam | (shared if nat == "non_saudi" else np.zeros(n, dtype=bool))
        total = int(nat_mask.sum())
        want = np.array([target[a] for a in AGE_GROUPS]) * total
        have = np.bincount(age[nat_mask & (age >= 0)], minlength=5)
        resid = np.maximum(want - have, 0.0)
        if resid.sum() <= 0:
            resid = np.array([1, 1, 1, 0, 0], dtype=float)
        age[dep] = rng.choice(5, size=int(dep.sum()), p=resid / resid.sum())
        male[dep] = rng.random(int(dep.sum())) < 0.5
    p["age_group"] = pd.Categorical.from_codes(age, categories=AGE_GROUPS)
    p["male"] = male
    p["saudi"] = hh_type == "saudi"
    return p


def assign_status(p: pd.DataFrame, cfg: dict, seed: int) -> pd.DataFrame:
    rng = stream(seed, "status")
    st = cfg["status"]
    n = len(p)
    probs = np.zeros((n, 4))
    age = p["age_group"].astype(str).to_numpy()
    nat = np.where(p["saudi"], "saudi", "non_saudi")
    sex = np.where(p["male"], "male", "female")
    for ag in AGE_GROUPS:
        block = st[ag]
        m = age == ag
        if "worker" in block:
            keys = {"": block}
        elif "saudi" in block:
            keys = {k: block[k] for k in ("saudi", "non_saudi")}
        else:
            keys = {k: v for k, v in block.items()}
        for key, vals in keys.items():
            if key == "":
                sel = m
            elif key in ("saudi", "non_saudi"):
                sel = m & (nat == key)
            else:
                k_nat, k_sex = key.rsplit("_", 1)
                sel = m & (nat == k_nat) & (sex == k_sex)
            w, s, h = vals["worker"], vals["student"], vals["homemaker"]
            probs[sel] = [w, s, h, max(0.0, 1.0 - w - s - h)]
    code = categorical(rng, probs)
    p["status"] = pd.Categorical.from_codes(code.astype(np.int8), categories=STATUSES)
    # sector for workers
    rng = stream(seed, "sector")
    sector = np.full(n, -1, dtype=np.int8)
    for nat_key in ("saudi", "non_saudi"):
        sel = (code == 0) & (nat == nat_key)
        shares = cfg["sectors"][nat_key]
        pr = np.array([shares[s] for s in WORK_SECTORS], dtype=float)
        sector[sel] = rng.choice(len(WORK_SECTORS), size=int(sel.sum()), p=pr / pr.sum())
    p["sector"] = pd.Categorical.from_codes(sector, categories=WORK_SECTORS)
    # students: school (6-17) or university (18+)
    p["school_level"] = pd.Categorical(
        np.where(code == 1, np.where(age == "a6_17", "school", "university"), None),
        categories=["school", "university"],
    )
    return p


def assign_cars(hh: pd.DataFrame, p: pd.DataFrame, cfg: dict, seed: int) -> None:
    rng = stream(seed, "cars")
    c = cfg["cars"]
    hh_type = hh["hh_type"].astype(str).to_numpy()
    has = rng.random(len(hh)) < np.array([c["household_has_car"][t] for t in hh_type])
    cars = np.zeros(len(hh), dtype=np.int8)
    for t in HH_TYPES:
        sel = has & (hh_type == t)
        keys, probs = dist_table(c["cars_if_any"][t])
        cars[sel] = np.asarray(keys)[rng.choice(len(keys), size=int(sel.sum()), p=probs)]
    hh["cars"] = cars
    hd = cfg["household_driver"]["saudi_with_car"]
    hh["household_driver"] = (hh_type == "saudi") & (cars > 0) & (rng.random(len(hh)) < hd)
    # licences for adults
    adult = p["age_group"].astype(str).isin(["a18_24", "a25_59", "a60p"]).to_numpy()
    nat = np.where(p["saudi"], "saudi", "non_saudi")
    sex = np.where(p["male"], "male", "female")
    lic_p = np.array([c["licence"][f"{a}_{b}"] for a, b in zip(nat, sex, strict=True)])
    licence = adult & (rng.random(len(p)) < lic_p)
    p["licence"] = licence
    # car access as driver: licensed and a car is free (cars shared among licensed members)
    hh_cars = pd.Series(cars, index=hh["hh_id"]).reindex(p["hh_id"]).to_numpy()
    n_lic = p.groupby("hh_id")["licence"].transform("sum").to_numpy()
    share = np.where(n_lic > 0, np.minimum(1.0, hh_cars / np.maximum(n_lic, 1)), 0.0)
    p["car_driver"] = licence & (rng.random(len(p)) < share)
    p["hh_car"] = hh_cars > 0
    p["hh_driver"] = (
        pd.Series(hh["household_driver"].to_numpy(), index=hh["hh_id"])
        .reindex(p["hh_id"])
        .to_numpy()
    )


def assign_locations(
    hh: pd.DataFrame,
    p: pd.DataFrame,
    zones: pd.DataFrame,
    zone_edges: pd.DataFrame,
    cfg: dict,
    seed: int,
) -> None:
    """Home edge per household; primary zone and edge for workers and students."""
    lc = cfg["location_choice"]
    dist_km = zone_distances(zones, float(lc["detour_factor"])) / 1000.0
    home_sampler = EdgeSampler(zone_edges, "home_w")
    act_sampler = EdgeSampler(zone_edges, "act_w")
    rng = stream(seed, "home_edge")
    hh["home_edge"] = home_sampler.sample(rng, hh["zone_id"].to_numpy())
    p["home_edge"] = (
        pd.Series(hh["home_edge"].to_numpy(), index=hh["hh_id"]).reindex(p["hh_id"]).to_numpy()
    )
    n = len(p)
    pzone = np.full(n, -1, dtype=np.int32)
    status = p["status"].astype(str).to_numpy()
    sector = p["sector"].astype(str).to_numpy()
    level = p["school_level"].astype(str).to_numpy()
    home_zone = p["zone_id"].to_numpy()
    rng = stream(seed, "primary_zone")
    purposes = [(s, (status == "worker") & (sector == s)) for s in WORK_SECTORS]
    purposes += [("school", level == "school"), ("university", level == "university")]
    for purpose, sel in purposes:
        if not sel.any():
            continue
        att = zones[f"att_{purpose}"].to_numpy(dtype=float)
        beta = float(lc["beta_per_km"][purpose])
        pzone[sel] = gravity_choice(rng, home_zone[sel], att, dist_km, beta)
    p["primary_zone"] = pzone
    rng = stream(seed, "primary_edge")
    edge = np.full(n, None, dtype=object)
    has = pzone >= 0
    edge[has] = act_sampler.sample(rng, pzone[has])
    p["primary_edge"] = edge
    p["primary_km"] = np.where(has, dist_km[home_zone, np.maximum(pzone, 0)], np.nan)


# ---------------------------------------------------------------------------- driver


def synthesize(
    seed: int,
    sample: float,
    zone_dir: Path | None = None,
    cfg: dict[str, Any] | None = None,
) -> Population:
    cfg = cfg or population_config()
    zones, zone_edges, zmeta = load_zones(zone_dir or default_zone_dir())
    hh = make_households(zones, cfg, seed)
    p = _expand(hh)
    p = assign_age_sex(p, cfg, seed)
    p = assign_status(p, cfg, seed)
    assign_cars(hh, p, cfg, seed)
    assign_locations(hh, p, zones, zone_edges, cfg, seed)
    p.insert(0, "person_id", np.arange(len(p), dtype=np.int64))
    full = len(p)
    if sample < 1.0:
        u = stream(seed, "sample").random(len(hh))
        keep = hh["hh_id"].to_numpy()[u < sample]
        hh = hh[hh["hh_id"].isin(keep)].reset_index(drop=True)
        p = p[p["hh_id"].isin(keep)].reset_index(drop=True)
    for col in ("home_edge", "primary_edge"):
        p[col] = p[col].astype("string")
    hh["home_edge"] = hh["home_edge"].astype("string")
    meta = {
        "label": SYNTHETIC_LABEL,
        "seed": seed,
        "sample": sample,
        "full_population": full,
        "persons": len(p),
        "households": len(hh),
        "zones_hash": zmeta["zones_hash"],
        "config_hash": config_hash(cfg),
        "population_hash": frame_hash(hh, p),
    }
    return Population(hh, p, meta)


def cache_dir_for(seed: int, sample: float, zone_dir: Path | None = None) -> Path:
    zmeta = json.loads(((zone_dir or default_zone_dir()) / "zones.json").read_text())
    key = config_hash({"cfg": population_config(), "zones": zmeta["zones_hash"]})[:10]
    return CACHE_DIR / f"pop-{key}-s{seed}-f{sample:g}"


def load_or_synthesize(
    seed: int, sample: float, zone_dir: Path | None = None, force: bool = False
) -> Population:
    """Cached population (Parquet) keyed by config, zones, seed and sample."""
    out = cache_dir_for(seed, sample, zone_dir)
    meta_path = out / "population.json"
    if meta_path.exists() and not force:
        return Population(
            pd.read_parquet(out / "households.parquet"),
            pd.read_parquet(out / "persons.parquet"),
            json.loads(meta_path.read_text()),
        )
    pop = synthesize(seed, sample, zone_dir)
    out.mkdir(parents=True, exist_ok=True)
    pop.households.to_parquet(out / "households.parquet", index=False)
    pop.persons.to_parquet(out / "persons.parquet", index=False)
    pop.meta["dir"] = str(out.relative_to(REPO_ROOT)) if out.is_relative_to(REPO_ROOT) else str(out)
    meta_path.write_text(json.dumps(pop.meta, indent=2))
    return pop


def summary(pop: Population) -> dict[str, Any]:
    p, hh = pop.persons, pop.households
    workers = p[p["status"] == "worker"]
    return {
        "persons": len(p),
        "households": len(hh),
        "mean_household_size": {
            t: round(float(hh.loc[hh["hh_type"] == t, "size"].mean()), 2) for t in HH_TYPES
        },
        "saudi_share": round(float(p["saudi"].mean()), 3),
        "age_shares": {
            nat: {
                k: round(v, 3)
                for k, v in p[p["saudi"] == (nat == "saudi")]["age_group"]
                .value_counts(normalize=True)
                .sort_index()
                .items()
            }
            for nat in ("saudi", "non_saudi")
        },
        "status_shares": {
            k: round(v, 3) for k, v in p["status"].value_counts(normalize=True).sort_index().items()
        },
        "sector_shares": {
            k: round(v, 3)
            for k, v in workers["sector"].value_counts(normalize=True).sort_index().items()
        },
        "cars_per_1000": round(1000 * float(hh["cars"].sum()) / max(len(p), 1), 1),
        "car_driver_share_adults": round(
            float(p.loc[p["age_group"].astype(str) != "a0_5", "car_driver"].mean()), 3
        ),
        "mean_commute_km": round(float(workers["primary_km"].mean()), 2),
        "mean_school_km": round(
            float(p.loc[p["school_level"] == "school", "primary_km"].mean()), 2
        ),
    }


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    seed: int = typer.Option(1),
    sample: float = typer.Option(0.10, help="household sample fraction (0.10, 0.25, 1.0)"),
    zone_dir: Path | None = typer.Option(None),
    force: bool = typer.Option(False, help="ignore the cache"),
) -> None:
    t0 = time.perf_counter()
    pop = load_or_synthesize(seed, sample, zone_dir, force)
    typer.echo(json.dumps({**pop.meta, "summary": summary(pop)}, indent=2))
    typer.echo(f"{time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    app()
