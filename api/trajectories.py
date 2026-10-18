"""TripsLayer JSON from fcd.parquet (Tier B only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from api import settings

COORD_DECIMALS = 6
SPEED_DECIMALS = 2
TIME_DECIMALS = 2


def trajectories(
    parquet: Path,
    run_id: str,
    begin: float | None,
    end: float | None,
    step: int,
) -> dict[str, Any]:
    filters = []
    if begin is not None:
        filters.append(("time_s", ">=", begin))
    if end is not None:
        filters.append(("time_s", "<=", end))
    table = pq.read_table(parquet, filters=filters or None)
    vid = np.asarray(pc.cast(table["vehicle_id"], pa.string()).to_numpy(zero_copy_only=False))
    vtype = np.asarray(pc.cast(table["vtype"], pa.string()).to_numpy(zero_copy_only=False))
    t = table["time_s"].to_numpy()
    lon = np.round(table["lon"].to_numpy(), COORD_DECIMALS)
    lat = np.round(table["lat"].to_numpy(), COORD_DECIMALS)
    speed = np.round(table["speed_ms"].to_numpy().astype(np.float64), SPEED_DECIMALS)
    vehicles = []
    if len(vid):
        cuts = np.flatnonzero(vid[1:] != vid[:-1]) + 1
        starts = np.concatenate([[0], cuts])
        stops = np.concatenate([cuts, [len(vid)]])
        for a, b in zip(starts, stops, strict=True):
            sel = slice(a, b, step)
            vehicles.append(
                {
                    "id": str(vid[a]),
                    "vtype": str(vtype[a]),
                    "path": np.column_stack([lon[sel], lat[sel]]).tolist(),
                    "timestamps": np.round(t[sel].astype(np.float64), TIME_DECIMALS).tolist(),
                    "speeds": speed[sel].tolist(),
                }
            )
    t_begin = float(t.min()) if len(t) else (begin or 0.0)
    t_end = float(t.max()) if len(t) else (end or 0.0)
    return {
        "label": settings.LABEL,
        "run_id": run_id,
        "begin_s": begin if begin is not None else t_begin,
        "end_s": end if end is not None else t_end,
        "step": step,
        "n_vehicles": len(vehicles),
        "vehicles": vehicles,
    }
