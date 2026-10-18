"""Track H: car-vs-Loop mode choice (sim/loop/mode_choice.py). Unit tests on synthetic legs
(monotonicity, tour sum, capacity cap and queue, determinism, alpha equivalence) and one
demo-window end-to-end run through `loop_shuttle` (SUMO, seconds)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sim.common import REPO_ROOT
from sim.loop.mode_choice import (
    CONFIG,
    choose,
    coefficients,
    load_mode_choice,
    pair_table,
    queue_minutes,
)
from sim.loop.params import resolve_params
from sim.loop.schema import loop_config, loop_transform
from tests.test_loop_run import lenv, run  # noqa: F401  (module fixture + helper)

MC = load_mode_choice(CONFIG)


def params(service: str = "measured") -> dict:
    from sim.loop.mode_choice import service_params

    return service_params(service, MC, loop_config())


def legs(
    n: int = 200,
    car_min: float = 45.0,
    legs_per_tour: int = 1,
    hour: int = 7,
    os_: int = 0,
    ds: int = 2,
    mode: str = "car",
    spread_s: float = 3000.0,
) -> pd.DataFrame:
    """n synthetic legs, all on line X between stations os_ and ds, arriving within one hour."""
    i = np.arange(n)
    return pd.DataFrame({
        "tour_id": i // legs_per_tour, "leg": i % legs_per_tour, "person_id": i // legs_per_tour,
        "car_mode": mode, "line": "X", "os": os_, "ds": ds,
        "depart": hour * 3600.0 + (i * spread_s / max(n, 1)),
        "walk_s": 600.0, "t_station": hour * 3600.0 + 300.0 + (i * spread_s / max(n, 1)),
        "ride_m": 6000.0, "portal_s": 27.0, "car_s": car_min * 60.0, "car_km": 8.0,
    })  # fmt: skip


def draws(lg: pd.DataFrame, seed: int = 0) -> pd.Series:
    t = np.unique(lg["tour_id"].to_numpy())
    return pd.Series(np.random.default_rng(seed).random(len(t)), index=t)


def p_mean(lg: pd.DataFrame, c: dict, p: dict, sample: float = 1.0) -> float:
    _, scored, _ = choose(lg, draws(lg), c, p, MC, sample)
    return float(scored["p_loop"].mean())


def test_config_registered_and_sourced() -> None:
    text = CONFIG.read_text()
    ids = set(re.findall(r"A-loop-0\d\d", text))
    # Track H rows (A-loop-021..) plus the Track D rows it refers to (A-loop-001..020)
    reg = "".join((REPO_ROOT / "docs" / f).read_text()
                  for f in ("assumptions-trackH.md", "assumptions-trackD.md"))  # fmt: skip
    own = (REPO_ROOT / "docs" / "assumptions-trackH.md").read_text()
    assert all(f"| A-loop-0{n} |" in own for n in range(21, 31))
    assert ids and all(f"| {i} |" in reg for i in ids), ids - set(re.findall(r"A-loop-0\d\d", reg))
    for block in ("coefficients", "car", "queue", "sweep"):
        assert any(k.endswith(("source", "assumption")) for k in MC[block]), block
    assert set(MC["services"]) >= {"measured", "vendor"}


def test_monotone_in_each_attribute() -> None:
    p = params()
    c = coefficients(MC)
    base = p_mean(legs(), c, p)
    assert p_mean(legs(car_min=80.0), c, p) > base > p_mean(legs(car_min=20.0), c, p)
    assert p_mean(legs(), coefficients(MC, fare_sar=20), p) < base
    assert p_mean(legs(), coefficients(MC, fare_sar=0), p) > base
    assert p_mean(legs(), coefficients(MC, asc_loop_min=20), p) < base
    assert p_mean(legs(), coefficients(MC, wait_mult=2.5), p) < base
    assert p_mean(legs(), c, {**p, "wait_min": 2.0}) > base
    far = legs().assign(walk_s=1500.0)
    assert p_mean(far, c, p) < base
    # a faster tunnel helps; steeper beta makes an unattractive Loop less attractive still
    assert p_mean(legs(), c, params("vendor")) > base
    assert p_mean(legs(), coefficients(MC, beta_ivt_per_min=-0.05), p) < base


def test_tour_sums_legs() -> None:
    p, c = params(), coefficients(MC)
    one = legs(n=100, legs_per_tour=1)
    two = legs(n=100, legs_per_tour=2)
    _, s1, _ = choose(one, draws(one), c, p, MC, 1.0)
    _, s2, _ = choose(two, draws(two), c, p, MC, 1.0)
    dv1 = np.log(s1["p_loop"].iloc[0] / (1 - s1["p_loop"].iloc[0]))
    dv2 = np.log(s2["p_loop"].iloc[0] / (1 - s2["p_loop"].iloc[0]))
    assert dv2 == pytest.approx(2 * dv1)
    # every leg of a tour shares one decision
    assert s2.groupby("tour_id")["admitted"].nunique().max() == 1


def test_capacity_cap_and_queue() -> None:
    p = params()
    c = coefficients(MC, asc_loop_min=-200)  # P ~ 1: everyone wants the Loop
    lg = legs(n=400, car_min=120.0)
    sample = 0.1  # 400 sampled riders = 4,000 riders/h on one pair
    adm, scored, info = choose(lg, draws(lg), c, p, MC, sample)
    seg_cap = 3600.0 / p["headway_s"] * MC["queue"]["segment_riders_per_vehicle"]
    cap = min(p["pair_capacity_pph"], seg_cap)  # the pair spans segments 0-1: segment binds
    assert info["chosen_tours"] > cap * sample
    assert len(adm) == int(np.floor(cap * sample + 1e-9))
    assert info["riders_capped_per_day"] > 0
    assert info["peak_segment_riders_pph"] <= seg_cap + 1e-6
    # riders above capacity do not shift, and the earliest arrivals are the ones admitted
    first = scored.loc[scored["admitted"], "t_station"].max()
    assert (scored.loc[scored["chosen"] & ~scored["admitted"], "t_station"] >= first).all()
    assert info["max_queue_min"] > 0
    assert queue_minutes(np.array([3000.0]), 1000.0, 60.0)[0] == pytest.approx(60.0)
    assert queue_minutes(np.array([1500.0]), 1000.0, 60.0)[0] == pytest.approx(15.0)
    assert queue_minutes(np.array([500.0]), 1000.0, 60.0)[0] == 0.0
    # the queue lowers expected demand on an over-subscribed pair (softer central coefficients)
    c2 = coefficients(MC, asc_loop_min=-60)
    mc_noq = {**MC, "queue": {**MC["queue"], "iterations": 0}}
    _, _, i_q = choose(lg, draws(lg), c2, p, MC, sample)
    _, _, i_0 = choose(lg, draws(lg), c2, p, mc_noq, sample)
    assert i_q["expected_riders_per_day"] < i_0["expected_riders_per_day"]
    t = pair_table(scored, p, sample)
    assert (t["admitted"] <= t["eligible"]).all() and t["shift_share"].between(0, 1).all()


def test_two_leg_tour_needs_room_on_both_legs() -> None:
    p = params()
    c = coefficients(MC, asc_loop_min=-200)
    out = legs(n=300, car_min=120.0, hour=7)
    back = legs(n=300, car_min=120.0, hour=17, os_=2, ds=0)
    lg = pd.concat([out, back]).reset_index(drop=True)
    lg["leg"] = np.r_[np.zeros(300), np.ones(300)].astype(int)
    adm, scored, _ = choose(lg, draws(lg), c, p, MC, 0.1)
    assert scored.groupby("tour_id")["admitted"].nunique().max() == 1
    assert len(adm) <= int(
        np.floor(
            min(
                p["pair_capacity_pph"],
                3600.0 / p["headway_s"] * MC["queue"]["segment_riders_per_vehicle"],
            )
            * 0.1
        )
    )


def test_deterministic_and_alpha_equivalent() -> None:
    p = params()
    lg = legs(n=300)
    u = draws(lg, seed=3)
    a1, s1, i1 = choose(lg, u, coefficients(MC), p, MC, 1.0)
    a2, s2, i2 = choose(lg, u, coefficients(MC), p, MC, 1.0)
    assert np.array_equal(a1, a2) and i1 == i2
    pd.testing.assert_frame_equal(s1, s2)
    # beta 0 -> P = 0.5 for every tour: exactly the alpha-0.5 path's tours (same hashed draw)
    adm, _, _ = choose(lg, u, coefficients(MC, beta_ivt_per_min=0.0), p, MC, 1.0)
    assert np.array_equal(adm, np.sort(u.index[u.to_numpy() < 0.5].to_numpy()))


def test_missing_car_time_never_shifts() -> None:
    lg = legs(n=50)
    lg.loc[lg.index[:10], "car_s"] = np.nan
    _, s, info = choose(lg, draws(lg), coefficients(MC), params(), MC, 1.0)
    assert not s.loc[s["car_s"].isna(), "admitted"].any()
    assert info["legs_without_car_time"] == 10


def test_resolve_params_and_bad_config(tmp_path: Path) -> None:
    from sim.loop.schema import LoopShuttle

    t = LoopShuttle.model_validate(
        {
            "type": "loop_shuttle",
            "assumption": "test",
            "mode_choice": str(CONFIG),
            "alignments": [
                {
                    "id": "X",
                    "stations": [
                        {"name": "a", "lon": 0, "lat": 0},
                        {"name": "b", "lon": 0, "lat": 0.1},
                    ],
                }
            ],
        }
    )
    assert resolve_params(t)["mode_choice"] == str(CONFIG)
    assert "mode_choice" not in resolve_params(t.model_copy(update={"mode_choice": None}))
    bad = tmp_path / "bad.yaml"
    bad.write_text(CONFIG.read_text().replace("beta_ivt_per_min: -0.025", "beta_ivt_per_min: 0.1"))
    with pytest.raises(ValueError, match="beta_ivt_per_min"):
        load_mode_choice(bad)


def test_demo_end_to_end_deterministic(lenv: dict, tmp_path: Path) -> None:  # noqa: F811
    from sim.loop.evaluate import make_policy, mode_choice_params
    from sim.loop.schema import load_loop_policy

    t = loop_transform(load_loop_policy("loop_demo"))
    prm, suffix = mode_choice_params(CONFIG, "vendor", None, None)
    prm |= {"radius_o_m": t.radius_o_m, "radius_d_m": t.radius_d_m, "min_trip_km": t.min_trip_km}
    al = [{"id": a.id, "name": a.name, "stations": [s.model_dump() for s in a.stations]}
          for a in t.alignments]  # fmt: skip
    pol = make_policy(f"loop_demo{suffix}", "Loop demo, mode choice", al, "shuttle", prm)
    outs = []
    for k in range(2):
        m = run(lenv, pol, tmp_path / f"runs{k}")
        out = tmp_path / f"runs{k}" / m["run_id"]
        rep = json.loads((out / "loop_report.json").read_text())
        mc = rep["mode_choice"]
        assert mc and mc["config_hash"] == suffix.split("_")[-1]
        pax = pd.read_parquet(out / "loop_pax.parquet")
        assert len(pax) == round(mc["riders_per_day"] * 1.0) == rep["passengers_per_day"]
        assert (out / "loop_mode_choice_pairs.csv").exists()
        scored = pd.read_parquet(out / "loop_mode_choice_legs.parquet")
        assert set(pax["tour_id"]) == set(scored.loc[scored["admitted"], "tour_id"])
        outs.append(pax.sort_values(["tour_id", "leg"]).reset_index(drop=True))
    pd.testing.assert_frame_equal(outs[0], outs[1])


def test_alpha_policy_hash_unchanged() -> None:
    """An alpha-path policy serialises (and hashes) as before Track H: no mode_choice key."""
    from sim.common import config_hash
    from sim.loop.schema import load_loop_policy

    pol = load_loop_policy("loop_demo")
    dump = pol.model_dump()
    assert "mode_choice" not in json.dumps(dump)
    assert config_hash(dump) == config_hash(json.loads(pol.model_dump_json()))
    # Track D's recommended run recorded this policy_hash (runs/loop_recommended/meta.json)
    assert config_hash(load_loop_policy("loop_recommended").model_dump()) == "c11f0bfaf610771b"
    t = loop_transform(pol).model_copy(update={"mode_choice": str(CONFIG)})
    assert t.model_dump()["mode_choice"] == str(CONFIG)
