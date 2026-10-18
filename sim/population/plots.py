"""Validation plots for a run: departure histogram, trip length distribution, trips per person.

Written to `runs/<id>/plots/`; sanity ranges are documented in docs/population.md.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sim.common import SYNTHETIC_LABEL  # noqa: E402


def _finish(fig: plt.Figure, path: Path, title: str) -> None:
    fig.suptitle(f"{title}\n{SYNTHETIC_LABEL}", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def validation_plots(out: Path, trips: pd.DataFrame, sample: float) -> list[Path]:
    """`trips` = tripinfo joined with vehicles (simulated vehicle trips)."""
    pdir = Path(out) / "plots"
    pdir.mkdir(parents=True, exist_ok=True)
    f = 1.0 / sample
    paths = []

    veh = pd.read_parquet(Path(out) / "vehicles.parquet")
    fig, ax = plt.subplots(figsize=(8, 4))
    bins = np.arange(0, 24.25, 0.25)
    ax.hist(veh["depart"] / 3600.0, bins=bins, weights=np.full(len(veh), f * 4), color="#4c72b0")
    ax.set_xlabel("departure hour")
    ax.set_ylabel("vehicle trips per hour (full city)")
    ax.set_xticks(range(0, 25, 2))
    p = pdir / "departures.png"
    _finish(fig, p, "Vehicle departures by time of day (15-min bins)")
    paths.append(p)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    km = trips["route_m"].dropna() / 1000.0
    axes[0].hist(km.clip(upper=60), bins=60, color="#55a868")
    axes[0].set_xlabel("simulated route length (km, clipped at 60)")
    axes[0].set_ylabel("vehicle trips (sampled)")
    axes[0].axvline(km.mean(), color="k", ls="--", lw=1, label=f"mean {km.mean():.1f} km")
    axes[0].legend()
    mins = trips["duration"].dropna() / 60.0
    axes[1].hist(mins.clip(upper=90), bins=60, color="#c44e52")
    axes[1].set_xlabel("trip duration (min, clipped at 90)")
    axes[1].axvline(mins.mean(), color="k", ls="--", lw=1, label=f"mean {mins.mean():.1f} min")
    axes[1].legend()
    p = pdir / "trip_length.png"
    _finish(fig, p, "Simulated vehicle trip length and duration")
    paths.append(p)

    person_trips = Path(out) / "person_trips_per_person.parquet"
    if person_trips.exists():
        tp = pd.read_parquet(person_trips)
        fig, ax = plt.subplots(figsize=(8, 4))
        width = 0.4
        x = tp["trips"].to_numpy()
        ax.bar(x - width / 2, tp["person_share"], width, label="person trips", color="#8172b2")
        ax.bar(x + width / 2, tp["vehicle_share"], width, label="vehicle trips", color="#ccb974")
        ax.set_xlabel("trips per person per day")
        ax.set_ylabel("share of persons")
        ax.legend()
        p = pdir / "trips_per_person.png"
        _finish(fig, p, "Trips per person (all residents incl. children)")
        paths.append(p)
    return paths


def trips_per_person_table(
    person_ids: pd.Series, vehicle_person_ids: pd.Series, persons: int, max_trips: int = 10
) -> pd.DataFrame:
    """Share of persons by number of person trips and of vehicle trips (as driver/passenger)."""
    pt = person_ids[person_ids >= 0].value_counts()
    vt = vehicle_person_ids[vehicle_person_ids >= 0].value_counts()
    rows = []
    for k in range(max_trips + 1):
        cond_p = (pt.clip(upper=max_trips) == k).sum() if k else persons - len(pt)
        cond_v = (vt.clip(upper=max_trips) == k).sum() if k else persons - len(vt)
        rows.append(
            {"trips": k, "person_share": cond_p / persons, "vehicle_share": cond_v / persons}
        )
    return pd.DataFrame(rows)
