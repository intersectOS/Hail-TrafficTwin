"""Route-file helpers for incremental policy runs (TA-014).

- `routes_using`: which vehicles of a (large, gzipped) route file use any of a set of edges.
- `write_weights`: duarouter weight file (meandata `traveltime`) from a baseline run's
  edgedata.parquet, aggregated per interval, plus policy penalties (road pricing).
- `reroute`: one-shot duarouter on those weights for the vehicles that need a new route.
- `merge_routes`: stream the baseline routes (keeping only reused vehicles) and the new routes
  into one file sorted by departure; baseline vehicles go first at equal departure times, so a
  policy that changes nothing reproduces the baseline route file and simulation.
"""

from __future__ import annotations

import gzip
import heapq
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from sim.common import SYNTHETIC_LABEL, sumo_bin
from sim.policies.edges import open_xml


def iter_route_elements(path: Path) -> Iterator[tuple[str, float, ET.Element]]:
    """Top-level children of a <routes> file as (tag, depart, element); depart -1 if none."""
    depth = 0
    with open_xml(path) as fh:
        for event, elem in ET.iterparse(fh, events=("start", "end")):
            if event == "start":
                depth += 1
                continue
            depth -= 1
            if depth == 1:
                dep = elem.get("depart")
                yield elem.tag, float(dep) if dep is not None else -1.0, elem
                elem.clear()


def routes_using(path: Path, edges: set[str], veh_ids: set[str] | None = None) -> set[str]:
    """Ids of vehicles (optionally only among `veh_ids`) whose route uses any of `edges`."""
    found: set[str] = set()
    if not edges:
        return found
    for tag, _, elem in iter_route_elements(path):
        if tag != "vehicle":
            continue
        vid = elem.get("id", "")
        if veh_ids is not None and vid not in veh_ids:
            continue
        route = elem.find("route")
        if route is not None and not edges.isdisjoint(route.get("edges", "").split()):
            found.add(vid)
    return found


def route_ids(path: Path) -> set[str]:
    return {e.get("id", "") for tag, _, e in iter_route_elements(path) if tag == "vehicle"}


# ---------------------------------------------------------------------------- weights


def congested_weights(
    edgedata: Path, edges: pd.DataFrame, interval: float, min_ratio: float
) -> pd.DataFrame:
    """Per (interval, edge): travel time from a run's edgedata, kept where above free flow."""
    tbl = pq.read_table(
        edgedata, columns=["begin", "edge_id", "sampledSeconds", "traveltime"],
        read_dictionary=["edge_id"],
    )  # fmt: skip
    df = tbl.to_pandas()
    df = df[df["traveltime"].notna() & (df["sampledSeconds"] > 0)]
    k = np.floor(df["begin"].to_numpy(dtype=float) / interval).astype(np.int64)
    w = df["sampledSeconds"].to_numpy(dtype=float)
    g = pd.DataFrame({"k": k, "edge_id": df["edge_id"].astype(str).to_numpy(),
                      "wt": w * df["traveltime"].to_numpy(dtype=float), "w": w})  # fmt: skip
    agg = g.groupby(["k", "edge_id"], sort=True)[["wt", "w"]].sum()
    agg["traveltime"] = agg["wt"] / agg["w"]
    agg = agg.reset_index()[["k", "edge_id", "traveltime"]]
    ff = edges.set_index("edge_id")
    free = (ff["length"] / ff["speed"].clip(lower=0.1)).reindex(agg["edge_id"]).to_numpy()
    keep = np.isfinite(free) & (agg["traveltime"].to_numpy() > free * min_ratio)
    out = agg[keep].copy()
    out["free"] = free[keep]
    return out


def write_weights(
    path: Path,
    congested: pd.DataFrame,
    edges: pd.DataFrame,
    interval: float,
    end: float,
    penalties: list[Any] | None = None,
) -> int:
    """Write a meandata weight file; penalties add seconds on their edges during their hours."""
    w = congested[congested["edge_id"].isin(set(edges["edge_id"]))][["k", "edge_id", "traveltime"]]
    rows = [w]
    ff = edges.set_index("edge_id")
    for pen in penalties or []:
        ids = [e for e in pen.edges if e in ff.index]
        k0, k1 = int(pen.begin // interval), int(np.ceil(pen.end / interval))
        for k in range(k0, k1):
            base = w[(w["k"] == k) & w["edge_id"].isin(ids)].set_index("edge_id")["traveltime"]
            free = (ff.loc[ids, "length"] / ff.loc[ids, "speed"].clip(lower=0.1)).astype(float)
            tt = base.reindex(ids).fillna(free) + pen.seconds
            rows.append(pd.DataFrame({"k": k, "edge_id": ids, "traveltime": tt.to_numpy()}))
    allw = pd.concat(rows, ignore_index=True)
    # a penalty row replaces the congested row of the same (interval, edge)
    allw = allw.drop_duplicates(["k", "edge_id"], keep="last").sort_values(["k", "edge_id"])
    n_int = int(np.ceil(end / interval))
    with gzip.open(path, "wt") as fh:
        fh.write(f"<!-- {SYNTHETIC_LABEL}; policy routing weights -->\n<meandata>\n")
        groups = dict(tuple(allw.groupby("k")))
        for k in range(n_int):
            fh.write(f'    <interval begin="{k * interval:.1f}" end="{(k + 1) * interval:.1f}">\n')
            part = groups.get(k)
            if part is not None:
                for eid, tt in zip(part["edge_id"], part["traveltime"], strict=True):
                    fh.write(f'        <edge id="{eid}" traveltime="{tt:.2f}"/>\n')
            fh.write("    </interval>\n")
        fh.write("</meandata>\n")
    return len(allw)


# ---------------------------------------------------------------------------- routing


def reroute_command(
    net: Path,
    trips: Path,
    weights: Path,
    out: Path,
    vtypes_out: Path,
    seed: int,
    end: float,
    cfg: dict[str, Any],
) -> list[str]:
    return [
        sumo_bin("duarouter"),
        "-n", str(net),
        "-r", str(trips),
        "--weight-files", str(weights),
        "--weights.expand", "true",
        "--routing-algorithm", str(cfg["routing_algorithm"]),
        "--routing-threads", str(cfg["routing_threads"]),
        "--seed", str(seed),
        "--begin", "0",
        "--end", f"{end:.0f}",
        "-o", str(out),
        "--vtype-output", str(vtypes_out),
        "--ignore-errors", "true",
        "--no-step-log", "true",
        "--aggregate-warnings", "5",
    ]  # fmt: skip


# ---------------------------------------------------------------------------- merging


def _serialise(elem: ET.Element) -> str:
    elem.tail = None
    return "    " + ET.tostring(elem, encoding="unicode").replace("\n", "\n    ").rstrip() + "\n"


def merge_routes(
    base: Path,
    new: Path | None,
    keep: set[str],
    out: Path,
    vtype_lines: list[str],
    retype: dict[str, str] | None = None,
) -> dict[str, int]:
    """Baseline vehicles in `keep` + all vehicles of `new`, one file sorted by departure.
    `retype` gives reused vehicles a new vType (same vehicle class, e.g. car -> ride-hail)."""
    retype = retype or {}

    Item = tuple[float, int, int, str]

    def stream(path: Path, rank: int, only: set[str] | None) -> Iterator[Item]:
        n = 0
        for tag, dep, elem in iter_route_elements(path):
            if tag != "vehicle":
                continue
            if only is not None and elem.get("id") not in only:
                continue
            n += 1
            if rank == 0 and elem.get("id") in retype:
                elem.set("type", retype[elem.get("id", "")])
            yield dep, rank, n, _serialise(elem)

    counts = {"reused": 0, "rerouted": 0}
    streams = [stream(base, 0, keep)]
    if new is not None and new.exists():
        streams.append(stream(new, 1, None))
    with gzip.open(out, "wt") as fh:
        fh.write(f"<!-- {SYNTHETIC_LABEL}; policy routes -->\n<routes>\n")
        fh.write("\n".join(vtype_lines) + "\n")
        for _, rank, _, text in heapq.merge(*streams):
            counts["rerouted" if rank else "reused"] += 1
            fh.write(text)
        fh.write("</routes>\n")
    return counts
