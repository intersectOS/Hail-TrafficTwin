"""Read producer Parquet in the contract schema (docs/contracts/run-outputs.md §4, §5, §12).

Producers write `edgedata.parquet` / `fcd.parquet` with SUMO attribute names (`begin`, `id` or
`edge_id`, `speed`, `sampledSeconds`, ... ; `time`, `id`, `type`, `angle`, ...). The API never
rewrites those files (other modules read them); it reads them through a DuckDB SELECT that renames
columns and fills what is missing, so no copy of a 100 MB city table is made.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

SECONDS_PER_HOUR = 3600  # unit conversion

# contract column -> source columns accepted, in order of preference
EDGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "bin_begin_s": ("bin_begin_s", "begin", "interval_begin"),
    "bin_end_s": ("bin_end_s", "end", "interval_end"),
    "edge_id": ("edge_id", "id", "edge"),
    "speed_ms": ("speed_ms", "speed"),
    "speed_rel": ("speed_rel", "speedRelative"),
    "density_veh_km": ("density_veh_km", "density"),
    "occupancy_pct": ("occupancy_pct", "occupancy"),
    "flow_veh_h": ("flow_veh_h", "flow"),
    "entered": ("entered",),
    "left": ("left",),
    "sampled_s": ("sampled_s", "sampledSeconds"),
    "traveltime_s": ("traveltime_s", "traveltime"),
    "time_loss_s": ("time_loss_s", "timeLoss"),
    "waiting_s": ("waiting_s", "waitingTime"),
}
EDGE_INT = ("bin_begin_s", "bin_end_s")
EDGE_REQUIRED = ("bin_begin_s", "bin_end_s", "edge_id")

# Only geo FCD (lon/lat) is accepted: x/y in metres would draw in the wrong place.
FCD_COLUMNS: dict[str, tuple[str, ...]] = {
    "time_s": ("time_s", "time"),
    "vehicle_id": ("vehicle_id", "id"),
    "vtype": ("vtype", "type"),
    "lon": ("lon",),
    "lat": ("lat",),
    "speed_ms": ("speed_ms", "speed"),
    "angle_deg": ("angle_deg", "angle"),
}
FCD_REQUIRED = ("time_s", "vehicle_id", "lon", "lat")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _pick(names: set[str], candidates: tuple[str, ...]) -> str | None:
    return next((c for c in candidates if c in names), None)


def columns(path: Path) -> set[str]:
    return set(pq.read_schema(path).names)


def is_contract_edgedata(path: Path) -> bool:
    return {"bin_begin_s", "edge_id", "speed_ms", "sampled_s"} <= columns(path)


def is_contract_fcd(path: Path) -> bool:
    return set(FCD_COLUMNS) <= columns(path)


def edge_select(path: Path) -> str:
    """SELECT with every contract §4 column (DOUBLE, NULL when absent) over a Parquet file.

    `flow_veh_h` falls back to entered * 3600 / bin width (as in api.ingest); `speed_rel` stays
    NULL when absent (api.bins derives it from the network speed limit)."""
    names = columns(path)
    src = {col: _pick(names, cands) for col, cands in EDGE_COLUMNS.items()}
    missing = [c for c in EDGE_REQUIRED if src[c] is None]
    if missing:
        raise ValueError(f"{path}: no column for {missing} (have {sorted(names)})")
    parts = []
    for col, s in src.items():
        if col == "edge_id":
            expr = f"CAST({_q(str(s))} AS VARCHAR)"
        elif col in EDGE_INT:
            expr = f"CAST(round({_q(str(s))}) AS INTEGER)"
        elif s is not None:
            expr = f"CAST({_q(s)} AS DOUBLE)"
        elif col == "flow_veh_h" and src["entered"]:
            width = f"NULLIF({_q(str(src['bin_end_s']))} - {_q(str(src['bin_begin_s']))}, 0)"
            expr = f"CAST({_q(src['entered'])} AS DOUBLE) * {SECONDS_PER_HOUR} / {width}"
        else:
            expr = "CAST(NULL AS DOUBLE)"
        parts.append(f"{expr} AS {col}")
    return f"SELECT {', '.join(parts)} FROM read_parquet({sql_path(path)})"


def fcd_select(path: Path) -> str:
    """SELECT with the contract §5 columns over a producer FCD Parquet file."""
    names = columns(path)
    src = {col: _pick(names, cands) for col, cands in FCD_COLUMNS.items()}
    missing = [c for c in FCD_REQUIRED if src[c] is None]
    if missing:
        raise ValueError(f"{path}: no column for {missing} (have {sorted(names)})")
    parts = []
    for col, s in src.items():
        if col in ("vehicle_id", "vtype"):
            expr = f"CAST({_q(s)} AS VARCHAR)" if s else "''"
        elif col in ("lon", "lat"):
            expr = f"CAST({_q(str(s))} AS DOUBLE)"
        else:
            expr = f"CAST({_q(s)} AS FLOAT)" if s else "CAST('NaN' AS FLOAT)"
        parts.append(f"{expr} AS {col}")
    return f"SELECT {', '.join(parts)} FROM read_parquet({sql_path(path)})"
