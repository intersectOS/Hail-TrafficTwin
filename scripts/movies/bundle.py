"""Film data bundle: everything the cinema renderer draws, precomputed from real run outputs.

`build_bundle(film, ...)` writes `runs/movies/<film>/bundle/`:

- manifest.json   film, size, fps, frame count, shots (layers, HUD), data file index
- frames.json     per frame: shot, sim time, camera, sun light, clock text, KPI values, fades
- roads.bin       network geometry (starts u32[n+1], lon/lat f32 offsets from an origin, class u8)
- heat-<src>.bin  u8 [n_bins x n_edges] edge metric per 5-minute bin (255 = no data)
- trips-<src>.bin vehicle paths for TripsLayer (starts, lon/lat offsets, times, speeds, class)
- overlays.json   events, closures, evacuation zone/exits/phases/contraflow, strategist routes
- buildings.json, water.json (copied from the basemap cache)
- labels.json     street, district and landmark labels for the map area (scripts/movies/labels.py)

The manifest also carries `fictional`, `annotations` (labels, compass, scale bar, subtitles) and
`narration` (the voice-over lines with their film times, for the subtitles); overlay items carry an
English `callout` where the renderer draws a leader-line label (MOVIES_V2).

The browser only interpolates between what is stored here, so the same spec and the same runs
give the same frames. Sources are resolved through the API's run registry (TT_RUNS_DIR), read
only (TT_RUNS_READONLY=1: conversions go to the viewer cache).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq

from scripts.movies import basemap as bm
from scripts.movies.camera import FramePlan, ease, plan_frames
from scripts.movies.labels import build_labels
from scripts.movies.spec import Film, Shot, load_settings
from scripts.movies.sun import lighting, sun_for_film
from sim.common import REPO_ROOT, SYNTHETIC_LABEL

DAY_S = 86400
SPEED_SCALE = 4.0  # m/s -> u8 (0.25 m/s steps, 63.75 m/s max)
BUNDLE_VERSION = 1

# Road classes (drawing order, width and glow in the renderer)
ROAD_CLASSES = ["motorway", "primary", "secondary", "minor", "link"]
_CLASS_OF = {
    "motorway": 0,
    "trunk": 0,
    "primary": 1,
    "secondary": 2,
    "tertiary": 2,
    "motorway_link": 4,
    "trunk_link": 4,
    "primary_link": 4,
    "secondary_link": 4,
    "tertiary_link": 4,
}
VEHICLE_CLASSES = ["car", "truck", "bus", "emergency", "convoy", "evacuee"]


def runs_root() -> Path:
    return Path(os.environ.get("TT_RUNS_DIR") or REPO_ROOT / "runs")


def movies_runs_dir() -> Path:
    """Bundles and frames; TT_MOVIES_DIR overrides it (tests keep the real cache untouched)."""
    return Path(os.environ.get("TT_MOVIES_DIR") or REPO_ROOT / "runs" / "movies")


def road_class(edge_type: str) -> int:
    t = edge_type.split(".", 1)[-1]
    return _CLASS_OF.get(t, 3)


EVACUEE_PREFIX = "ev."  # sim/events/evacuation.py names evacuees ev.<event>.<n>


def vehicle_class(vtype: str, vid: str = "") -> int:
    """Display class from the vType (and the event-vehicle id prefix for evacuees)."""
    s = f"{vtype} {vid}".lower()
    for key, cls in (
        ("emergency", 3),
        ("ambulance", 3),
        ("bluelight", 3),
        ("convoy", 4),
        ("motorcade", 4),
    ):
        if key in s:
            return cls
    if vid.startswith(EVACUEE_PREFIX) or "evac" in s:
        return 5
    for key, cls in (("bus", 2), ("truck", 1)):
        if key in s:
            return cls
    return 0


def quantize(values: np.ndarray, lo: float, hi: float, levels: int) -> np.ndarray:
    """float -> u8 in [0, levels]; NaN -> 255."""
    out = np.full(values.shape, 255, dtype=np.uint8)
    ok = np.isfinite(values)
    t = np.clip((values[ok] - lo) / (hi - lo), 0.0, 1.0)
    out[ok] = np.round(t * levels).astype(np.uint8)
    return out


def flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(d, list):
        if all(not isinstance(x, (dict, list)) for x in d):
            out[prefix[:-1]] = d
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = d
    return out


FACT_RE = re.compile(r"\{([A-Za-z0-9_-]+)\.([^}:]+)(?::([^}]*))?\}")


def fill_text(text: str, facts: dict[str, dict[str, Any]]) -> str:
    """Replace {src.path} / {src.path:fmt} with run facts (missing facts raise)."""

    def sub(m: re.Match[str]) -> str:
        src, path, fmt = m.group(1), m.group(2), m.group(3)
        if src not in facts or path not in facts[src]:
            raise KeyError(f"fact {src}.{path} not available")
        v = facts[src][path]
        return format(v, fmt) if fmt else str(v)

    return FACT_RE.sub(sub, text).replace("`", "")


# ----------------------------------------------------------------------------- sources


@dataclass
class SourceData:
    sid: str
    kind: str  # run | strategist
    run: Any = None  # api.runs.Run
    rec: dict[str, Any] | None = None
    candidate: str | None = None
    background: Any = None  # api.runs.Run for strategist backgrounds
    facts: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] | None = None  # normalised scenario / evacuation report

    @property
    def network_hash(self) -> str:
        if self.run is not None:
            return str(self.run.meta["network_hash"])
        assert self.rec is not None
        return str(self.rec["snapshot"]["network_hash"])

    @property
    def fcd_run(self) -> Any:
        return self.run if self.run is not None else self.background


def _registry() -> dict[str, Any]:
    from api import runs as api_runs

    reg, aliases = api_runs.registry()
    for a, target in aliases.items():
        reg.setdefault(a, reg[target])
    return reg


def _report(run: Any) -> dict[str, Any] | None:
    from api import normalize
    from api.runs import read_json_file

    if run.role not in ("run",):
        return None
    raw = read_json_file(run.path / "scenario_report.json")
    if raw is not None:
        return normalize.scenario_report(raw, run.run_id, run.meta.get("baseline_run_id"))
    raw = read_json_file(run.path / "evacuation_report.json")
    if raw is not None:
        return normalize.evacuation_report(raw, run.run_id, run.meta.get("baseline_run_id"))
    return None


def resolve_sources(film: Film) -> dict[str, SourceData]:
    reg = _registry()
    out: dict[str, SourceData] = {}
    for sid, src in film.sources.items():
        if src.run is not None:
            if src.run not in reg:
                raise FileNotFoundError(f"source {sid}: run {src.run!r} not in {runs_root()}")
            run = reg[src.run]
            rep = _report(run)
            facts = flatten(rep.get("summary") or {}) if rep else {}
            if rep:
                facts.update(flatten(rep.get("delta") or {}, "delta."))
                facts.update(flatten(rep.get("convoy") or [], "convoy."))
            if rep and "result" in rep:
                facts.update(flatten(rep["result"], "result."))
                facts["background_added_veh_h"] = rep.get("background_added_veh_h")
            out[sid] = SourceData(sid, "run", run=run, facts=facts, report=rep)
        else:
            path = runs_root() / "strategist" / str(src.strategist) / "recommendation.json"
            rec = json.loads(path.read_text())
            cid = str(src.candidate)
            if cid not in rec["results"]:
                raise KeyError(f"source {sid}: candidate {cid!r} not in {path}")
            facts = flatten(rec["results"][cid])
            opt = next((o for o in rec["options"] if o["candidate_id"] == cid), None)
            if opt is not None:
                facts.update({k: v for k, v in opt.items() if not isinstance(v, (dict, list))})
            else:
                facts["label"] = "no strategy" if cid == "no_strategy" else cid
                facts["rank"] = "-"
            facts["no_strategy_tt_s"] = rec["no_strategy"]["travel_time_s"]
            facts["title"] = rec.get("title", "")
            bg = reg[src.background] if src.background else None
            out[sid] = SourceData(
                sid, "strategist", rec=rec, candidate=cid, background=bg, facts=facts
            )
    return out


# ----------------------------------------------------------------------------- network


@dataclass
class FilmNet:
    network_hash: str
    edge_ids: list[str]  # film edges (subset of the index, in index order)
    keep: np.ndarray  # index positions of the film edges
    position: dict[str, int]  # edge id -> film edge position
    starts: np.ndarray  # u32 [n + 1]
    coords: np.ndarray  # f64 [n_points, 2]
    classes: np.ndarray  # u8 [n]
    names: list[str]


def _edge_index(src: SourceData) -> tuple[Any, dict[str, Any]]:
    from api.edges import index_dir, load_edge_index
    from api.runs import network_for_hash, run_network
    from api.util import read_json

    h = src.network_hash
    net = run_network(src.run) if src.run is not None else network_for_hash(h)
    index = load_edge_index(net, h)
    attrs = read_json(index_dir(h) / "edges.json")
    return index, attrs


def film_network(
    sources: dict[str, SourceData],
    primary: str,
    bbox: tuple[float, float, float, float],
    major_only: bool,
) -> FilmNet:
    index, attrs = _edge_index(sources[primary])
    types = attrs["types"]
    names = attrs["names"]
    w, s, e, n = bbox
    keep = []
    for i in range(index.n_edges):
        cls = road_class(types[i])
        if major_only and cls == 3:
            continue
        pts = index.path(i)
        if len(pts) < 2:
            continue
        if pts[:, 0].max() < w or pts[:, 0].min() > e or pts[:, 1].max() < s or pts[:, 1].min() > n:
            continue
        keep.append(i)
    keep_a = np.asarray(keep, dtype=np.int64)
    lens = np.asarray([index.starts[i + 1] - index.starts[i] for i in keep], dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(lens)]).astype(np.uint32)
    coords = (
        np.concatenate([index.path(i) for i in keep]).astype(np.float64)
        if keep
        else np.zeros((0, 2))
    )
    ids = [index.edge_ids[i] for i in keep]
    return FilmNet(
        sources[primary].network_hash,
        ids,
        keep_a,
        {e: k for k, e in enumerate(ids)},
        starts,
        coords,
        np.asarray([road_class(types[i]) for i in keep], dtype=np.uint8),
        [names[i] for i in keep],
    )


def edge_paths(net: FilmNet, edges: list[str]) -> list[list[list[float]]]:
    out = []
    for e in edges:
        k = net.position.get(e)
        if k is None:
            continue
        pts = net.coords[net.starts[k] : net.starts[k + 1]]
        out.append([[round(float(x), 6), round(float(y), 6)] for x, y in pts])
    return out


# ----------------------------------------------------------------------------- heat


def _heat_ranges(shots: list[Shot], plans: list[FramePlan], sid: str) -> tuple[float, float]:
    ts = []
    for p in plans:
        lay = shots[p.shot].layers
        if sid in (lay.heat, lay.compare, *(lay.split or ())):
            ts.append(p.camera.sim_t)
    return (min(ts), max(ts)) if ts else (0.0, 0.0)


def build_heat(
    src: SourceData,
    net: FilmNet,
    metric: str,
    t_range: tuple[float, float],
    out: Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    from api.bins import bin_values, ensure_bins

    run = src.run
    info = ensure_bins(run)
    bin_s, begin, n_bins = int(info["bin_s"]), float(info["begin_s"]), int(info["n_bins"])
    first = max(0, math.floor((t_range[0] - begin) / bin_s - 0.5))
    last = min(n_bins - 1, math.floor((t_range[1] - begin) / bin_s - 0.5) + 1)
    index, _ = _edge_index(src)
    if src.network_hash == net.network_hash:
        sel = net.keep
        valid = np.ones(len(sel), dtype=bool)
    else:  # map film edges to this run's network by edge id
        pos = index.position
        sel = np.asarray([pos.get(e, -1) for e in net.edge_ids], dtype=np.int64)
        valid = sel >= 0
        sel = np.where(valid, sel, 0)
    lo, hi = settings["heat"]["ranges"][metric]
    levels = int(settings["heat"]["quantization"])
    n = len(net.edge_ids)
    with out.open("wb") as fh:
        for i in range(first, last + 1):
            vals = bin_values(run.run_id, metric, i, index.n_edges)[sel]
            vals = np.where(valid, vals, np.nan)
            fh.write(quantize(vals, lo, hi, levels).tobytes())
    return {
        "url": out.name,
        "metric": metric,
        "range": [lo, hi],
        "levels": levels,
        "bin_s": bin_s,
        "begin_s": begin + first * bin_s,
        "n_bins": last - first + 1,
        "n_edges": n,
        "matched_edges": int(valid.sum()),
    }


# ----------------------------------------------------------------------------- trips


@dataclass
class Trips:
    starts: np.ndarray  # u32 [n + 1]
    coords: np.ndarray  # f64 [p, 2]
    times: np.ndarray  # f64 [p]
    speeds: np.ndarray  # f32 [p] m/s
    classes: np.ndarray  # u8 [n]
    ids: list[str]


def _trip_range(shots: list[Shot], plans: list[FramePlan], sid: str) -> tuple[float, float]:
    ts = [
        p.camera.sim_t
        for p in plans
        if sid in (shots[p.shot].layers.trips, *(shots[p.shot].layers.split or ()))
    ]
    return (min(ts), max(ts)) if ts else (0.0, 0.0)


def read_fcd(run: Any, t0: float, t1: float, step: int) -> Trips:
    from api.ingest import ensure_fcd

    fcd = ensure_fcd(run.data_dir, run_id=run.run_id, tier="B")
    if fcd is None:
        raise FileNotFoundError(f"{run.run_id}: no FCD (trajectories)")
    table = pq.read_table(
        fcd,
        columns=["time_s", "vehicle_id", "vtype", "lon", "lat", "speed_ms"],
        filters=[("time_s", ">=", t0), ("time_s", "<=", t1)],
    )
    vid_arr = pc.cast(table["vehicle_id"], "string").to_numpy(zero_copy_only=False)
    vtype_arr = pc.cast(table["vtype"], "string").to_numpy(zero_copy_only=False)
    t = table["time_s"].to_numpy().astype(np.float64)
    lon = table["lon"].to_numpy()
    lat = table["lat"].to_numpy()
    spd = table["speed_ms"].to_numpy().astype(np.float32)
    order = np.lexsort((t, vid_arr))  # by vehicle, then time (deterministic)
    vid_arr, vtype_arr, t, lon, lat, spd = (
        vid_arr[order],
        vtype_arr[order],
        t[order],
        lon[order],
        lat[order],
        spd[order],
    )
    if len(vid_arr) == 0:
        return Trips(
            np.zeros(1, np.uint32),
            np.zeros((0, 2)),
            np.zeros(0),
            np.zeros(0),
            np.zeros(0, np.uint8),
            [],
        )
    cuts = np.flatnonzero(vid_arr[1:] != vid_arr[:-1]) + 1
    begins = np.concatenate([[0], cuts])
    ends = np.concatenate([cuts, [len(vid_arr)]])
    keep_rows = []
    starts = [0]
    classes = []
    ids = []
    for a, b in zip(begins, ends, strict=True):
        rows = np.arange(a, b, step)
        if rows[-1] != b - 1:
            rows = np.append(rows, b - 1)
        if len(rows) < 2:
            continue
        keep_rows.append(rows)
        starts.append(starts[-1] + len(rows))
        classes.append(vehicle_class(str(vtype_arr[a]), str(vid_arr[a])))
        ids.append(str(vid_arr[a]))
    rows = np.concatenate(keep_rows) if keep_rows else np.zeros(0, dtype=np.int64)
    return Trips(
        np.asarray(starts, dtype=np.uint32),
        np.column_stack([lon[rows], lat[rows]]),
        t[rows],
        spd[rows],
        np.asarray(classes, dtype=np.uint8),
        ids,
    )


def ambulance_trip(src: SourceData, net: FilmNet) -> Trips:
    """The candidate's ambulance moved along its route with the recorded per-edge times."""
    assert src.rec is not None and src.candidate is not None
    rec = src.rec
    res = rec["results"][src.candidate]
    edge_s: dict[str, float] = res["ambulance_edge_s"]
    route = route_edges(src)
    t = float(rec["snapshot"]["t_dispatch"])
    pts: list[tuple[float, float]] = []
    times: list[float] = []
    for e in route:
        k = net.position.get(e)
        if k is None:
            continue
        path = net.coords[net.starts[k] : net.starts[k + 1]]
        seg = np.hypot(*np.diff(path, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        dur = float(edge_s.get(e, 0.0))
        for j, p in enumerate(path):
            if pts and j == 0 and np.allclose(p, pts[-1]):
                continue
            frac = cum[j] / cum[-1] if cum[-1] > 0 else 1.0
            pts.append((float(p[0]), float(p[1])))
            times.append(t + dur * frac)
        t += dur
    n = len(pts)
    return Trips(
        np.asarray([0, n], dtype=np.uint32),
        np.asarray(pts, dtype=np.float64).reshape(-1, 2),
        np.asarray(times, dtype=np.float64),
        np.full(n, 12.0, dtype=np.float32),
        np.asarray([3], dtype=np.uint8),
        [f"ambulance:{src.candidate}"],
    )


def route_edges(src: SourceData) -> list[str]:
    assert src.rec is not None
    rec, cid = src.rec, src.candidate
    if cid == "no_strategy":
        name = next(r["name"] for r in rec["routes"] if r.get("is_default"))
    else:
        opt = next(o for o in rec["options"] if o["candidate_id"] == cid)
        name = opt["route_name"]
    return list(next(r for r in rec["routes"] if r["name"] == name)["edges"])


def merge_trips(a: Trips, b: Trips) -> Trips:
    off = int(a.starts[-1])
    return Trips(
        np.concatenate([a.starts[:-1], b.starts + off]).astype(np.uint32),
        np.concatenate([a.coords, b.coords]),
        np.concatenate([a.times, b.times]),
        np.concatenate([a.speeds, b.speeds]),
        np.concatenate([a.classes, b.classes]).astype(np.uint8),
        a.ids + b.ids,
    )


def write_trips(trips: Trips, origin: tuple[float, float], out: Path) -> dict[str, Any]:
    off = (trips.coords - np.asarray(origin)).astype("<f4")
    with out.open("wb") as fh:
        fh.write(trips.starts.astype("<u4").tobytes())
        fh.write(off.tobytes())
        fh.write(trips.times.astype("<f4").tobytes())
        fh.write(np.clip(np.round(trips.speeds * SPEED_SCALE), 0, 255).astype(np.uint8).tobytes())
        fh.write(trips.classes.astype(np.uint8).tobytes())
    return {
        "url": out.name,
        "n_vehicles": len(trips.ids),
        "n_points": int(trips.starts[-1]),
        "speed_scale": SPEED_SCALE,
        "t_min": float(trips.times.min()) if len(trips.times) else 0.0,
        "t_max": float(trips.times.max()) if len(trips.times) else 0.0,
        "classes": {c: int((trips.classes == i).sum()) for i, c in enumerate(VEHICLE_CLASSES)},
    }


# ----------------------------------------------------------------------------- series


def fcd_series(run: Any, kind: str, times: list[float]) -> list[float]:
    """Per-frame value of a series KPI from the run's FCD (1 s samples).

    running / halted / mean_speed_kmh: vehicles with a sample in that second; arrived: vehicles
    whose last sample is before t (left the window or finished). The evacuees_* variants count
    only event vehicles (`ev.` ids: evacuees in an evacuation run).
    """
    from api.ingest import ensure_fcd

    fcd = ensure_fcd(run.data_dir, run_id=run.run_id, tier="B")
    where = f"WHERE vehicle_id LIKE '{EVACUEE_PREFIX}%'" if kind.startswith("evacuees_") else ""
    base = kind.removeprefix("evacuees_")
    con = duckdb.connect()
    try:
        if base in ("arrived", "out"):
            last = con.execute(
                f"SELECT max(time_s) FROM read_parquet('{fcd}') {where} GROUP BY vehicle_id"
            ).fetchnumpy()
            arr = np.sort(next(iter(last.values())))
            end = arr.max() if len(arr) else 0
            return [float(np.searchsorted(arr, min(t, end), side="left")) for t in times]
        rows = con.execute(
            f"SELECT floor(time_s) AS s, count(*) AS n, "
            f"sum(CASE WHEN speed_ms < 0.1 THEN 1 ELSE 0 END) AS halted, "
            f"avg(speed_ms) AS v FROM read_parquet('{fcd}') {where} GROUP BY 1 ORDER BY 1"
        ).fetchnumpy()
    finally:
        con.close()
    secs = rows["s"].astype(np.int64)
    col = {"running": rows["n"], "halted": rows["halted"], "mean_speed_kmh": rows["v"] * 3.6}[base]
    lut = dict(zip(secs.tolist(), np.asarray(col, dtype=np.float64).tolist(), strict=True))
    return [float(lut.get(math.floor(t), 0.0)) for t in times]


def tripinfo_series(run: Any, kind: str, times: list[float]) -> list[float]:
    """Vehicles in the network (Tier A) from tripinfo depart/arrival."""
    path = run.data_dir / "tripinfo.parquet"
    tab = pq.read_table(path, columns=["depart", "arrival"])
    dep = np.sort(tab["depart"].to_numpy())
    arr = np.sort(tab["arrival"].to_numpy())
    if kind == "arrived":
        return [float(np.searchsorted(arr, t, side="right")) for t in times]
    if kind != "running":
        raise ValueError(f"series {kind!r} needs FCD (Tier B)")
    return [
        float(np.searchsorted(dep, t, side="right") - np.searchsorted(arr, t, side="right"))
        for t in times
    ]


# ----------------------------------------------------------------------------- overlays


def _is_edge_id(name: str) -> bool:
    return not name or bool(re.search(r"[#_]|^-?\d+$|Added", name))


def street_en(name: str | None, names_en: dict[str, str]) -> str:
    """English street name for a network (Arabic OSM) name, '' when unnamed."""
    if not name or _is_edge_id(name):
        return ""
    return names_en.get(name, name)


def edges_street(net: FilmNet, edges: list[str], names_en: dict[str, str]) -> str:
    """The most common English street name over the edges ('' when none is named)."""
    counts: dict[str, int] = {}
    for e in edges:
        k = net.position.get(e)
        if k is not None and (nm := street_en(net.names[k], names_en)):
            counts[nm] = counts.get(nm, 0) + 1
    return max(sorted(counts), key=lambda n: counts[n]) if counts else ""


CALLOUT_EVENT = {"accident": "Crash", "flood": "Flooding", "motorcade": "Motorcade"}


def add_callouts(
    o: dict[str, Any], src: SourceData, net: FilmNet, names_en: dict[str, str]
) -> None:
    """English callout text on overlay items the renderer labels with a leader line."""

    def on(text: str, street: str) -> str:
        return f"{text} on {street}" if street else text

    rep = src.report or {}
    edges_of = {ev["id"]: ev.get("edges") or [] for ev in rep.get("events") or []}
    edges_of.update({c["id"]: c.get("edges") or [] for c in rep.get("closures") or []})
    for ev in o["events"]:
        kind = CALLOUT_EVENT.get(ev["type"])
        if kind is None:
            continue
        if src.kind == "strategist":
            ev["callout"] = "Crash: one lane closed"
        else:
            ev["callout"] = on(kind, edges_street(net, edges_of.get(ev["id"], []), names_en))
    for c in o["closures"]:
        street = edges_street(net, edges_of.get(c["id"], []), names_en)
        flooded = "flood" in c["id"]
        c["callout"] = "Flooded sites closed" if flooded else on("Road closed", street)
    for k, ex in enumerate(o["exits"], start=1):
        eid = str(ex["id"]).removeprefix("exit:")
        street = edges_street(net, [eid], names_en)
        ex["callout"] = f"Exit {k}: {street}" if street else f"Exit {k}"
    for c in o["contraflow"]:
        name = street_en(c.get("name"), names_en)
        c["name_en"] = name
        num = str(c.get("id") or "").removeprefix("cf")
        c["callout"] = f"Contraflow: {name}" if name else f"Contraflow {num}"


def build_overlays(src: SourceData, net: FilmNet) -> dict[str, Any]:
    out: dict[str, Any] = {
        "events": [],
        "closures": [],
        "zone": None,
        "exits": [],
        "routes": [],
        "phases": [],
        "contraflow": [],
    }
    if src.kind == "strategist":
        assert src.rec is not None
        out["routes"].append(
            {
                "name": src.facts.get("route_name") or "default route",
                "paths": edge_paths(net, route_edges(src)),
            }
        )
        ev = src.rec.get("closed_lanes_at_t") or []
        edges = sorted({lane.rsplit("_", 1)[0] for lane in ev})
        if edges:
            out["events"].append(
                {
                    "id": "crash",
                    "type": "accident",
                    "begin_s": 0.0,
                    "end_s": 1e9,
                    "paths": edge_paths(net, edges),
                }
            )
        return out
    rep = src.report or {}
    for ev in rep.get("events") or []:
        geom = ev.get("geometry") or {}
        item = {
            "id": ev["id"],
            "type": ev["type"],
            "begin_s": ev.get("begin_s") or 0.0,
            "end_s": ev.get("end_s") or 1e9,
            "paths": edge_paths(net, ev.get("edges") or []),
        }
        if geom.get("type") == "Point":
            item["point"] = geom["coordinates"]
            if ev.get("producer_type") == "evacuation_exit":
                out["exits"].append(item)
                continue
        if geom.get("type") == "Polygon" and ev["type"] == "evacuation":
            out["zone"] = {"ring": geom["coordinates"][0], "begin_s": item["begin_s"]}
            continue
        out["events"].append(item)
    for c in rep.get("closures") or []:
        item = {
            "id": c["id"],
            "begin_s": c.get("begin_s") or 0.0,
            "end_s": c.get("end_s") or 1e9,
            "paths": edge_paths(net, c.get("edges") or []),
        }
        if str(c["id"]).startswith("contraflow:"):
            continue  # dormant contraflow lanes: drawn from the evacuation block below
        out["closures"].append(item)
    evac = rep.get("evacuation") or {}
    if evac:
        order = float(evac.get("order_t") or 0.0)
        active = {str(x) for x in evac.get("contraflow") or []}
        for cor in evac.get("corridors") or []:
            if "all" in active or cor.get("id") in active or cor.get("exit") in active:
                out["contraflow"].append(
                    {
                        "id": cor.get("id"),
                        "name": cor.get("name"),
                        "begin_s": order,
                        "paths": edge_paths(net, cor.get("inbound_edges") or []),
                    }
                )
        cf_on = next(
            (e["t"] for e in rep.get("event_log") or [] if e.get("action") == "contraflow_on"),
            order,
        )
        for c in out["contraflow"]:
            c["begin_s"] = float(cf_on)
        out["phases"] = evac_phases(src, evac)
    return out


def evac_phases(src: SourceData, evac: dict[str, Any]) -> list[dict[str, Any]]:
    """Release bands of a phased evacuation, from the evacuees' FCD departures.

    Each band is a convex hull of where its evacuees start, lit from the first departure in the
    band; band = position of the departure inside the release window (equal shares, A-evac-014).
    """
    from shapely.geometry import MultiPoint

    from api.ingest import ensure_fcd

    bands = evac.get("bands") or {}
    n_bands = len(bands)
    if n_bands < 2 or evac.get("phasing") == "simultaneous":
        return []
    fcd = ensure_fcd(src.run.data_dir, run_id=src.run.run_id, tier="B")
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT vehicle_id, min(time_s) AS t0, arg_min(lon, time_s) AS lon, "
            f"arg_min(lat, time_s) AS lat FROM read_parquet('{fcd}') "
            f"WHERE vehicle_id LIKE '{EVACUEE_PREFIX}%' GROUP BY 1 ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    order = float(evac["order_t"])
    width = float(evac["release_s"]) / n_bands
    groups: dict[int, list[tuple[float, float, float]]] = {b: [] for b in range(n_bands)}
    for _vid, t0, lon, lat in rows:
        b = min(n_bands - 1, max(0, int((float(t0) - order) // width)))
        groups[b].append((float(t0), float(lon), float(lat)))
    out = []
    for b, pts in groups.items():
        if len(pts) < 3:
            continue
        hull = MultiPoint([(x, y) for _, x, y in pts]).convex_hull.buffer(0.0004)
        out.append(
            {
                "band": b,
                "begin_s": round(min(p[0] for p in pts), 1),
                "end_s": round(max(p[0] for p in pts), 1),
                "vehicles": len(pts),
                "ring": [[round(x, 6), round(y, 6)] for x, y in hull.exterior.coords],
                "points": [[round(x, 6), round(y, 6), round(t, 1)] for t, x, y in sorted(pts)],
            }
        )
    return out


# ----------------------------------------------------------------------------- frames


def clock_text(film: Film, sim_t: float) -> str:
    if film.clock_t0:
        h, m = (int(x) for x in film.clock_t0.split(":"))
        local = h * 3600 + m * 60 + sim_t
    else:
        local = sim_t
    local = int(math.floor(local)) % DAY_S
    return f"{local // 3600:02d}:{(local % 3600) // 60:02d}"


def local_seconds(film: Film, sim_t: float) -> float:
    if film.clock_t0:
        h, m = (int(x) for x in film.clock_t0.split(":"))
        return h * 3600 + m * 60 + sim_t
    return sim_t


def fade_alpha(film: Film, plans: list[FramePlan], fps: int) -> list[float]:
    """Black overlay: fade in/out at film ends, short dip at shot cuts."""
    total = len(plans) / fps
    bounds = np.cumsum([s.duration_s for s in film.shots])[:-1]
    out = []
    for p in plans:
        t = p.film_t
        a = max(0.0, 1 - t / 0.6) if t < 0.6 else 0.0
        a = max(a, max(0.0, 1 - (total - t - 1 / fps) / 0.7))
        for b in bounds:
            d = abs(t - b)
            if d < 0.25:
                a = max(a, 1 - d / 0.25)
        out.append(round(min(1.0, a), 4))
    return out


def plan_json(
    film: Film,
    plans: list[FramePlan],
    fps: int,
    sources: dict[str, SourceData],
    settings: dict[str, Any],
) -> dict[str, Any]:
    # sun per frame
    light = []
    for p in plans:
        lt = lighting(
            sun_for_film(film.date, local_seconds(film, p.camera.sim_t), settings), settings
        )
        light.append(
            [
                lt["night"],
                lt["sun_intensity"],
                lt["ambient_intensity"],
                *lt["direction"],
                *lt["sun_color"],
                *lt["ambient_color"],
                lt["elevation_deg"],
                lt["azimuth_deg"],
            ]
        )
    # KPI values per frame
    kpi_vals: list[list[float | None]] = [[] for _ in plans]
    series_cache: dict[tuple[str, str], list[float]] = {}
    for s_idx, shot in enumerate(film.shots):
        frames = [p for p in plans if p.shot == s_idx]
        for kpi in shot.hud.kpis:
            if kpi.series is not None:
                src = sources[str(kpi.source)]
                key = (str(kpi.source), kpi.series)
                times = [p.camera.sim_t for p in plans]
                if key not in series_cache:
                    run = src.fcd_run
                    if run.tier == "A":
                        series_cache[key] = tripinfo_series(run, kpi.series, times)
                    else:
                        series_cache[key] = fcd_series(run, kpi.series, times)
                for p in frames:
                    kpi_vals[p.index].append(round(series_cache[key][p.index], 3))
                continue
            if kpi.fact is not None:
                facts = sources[str(kpi.source)].facts
                if kpi.fact not in facts or facts[kpi.fact] is None:
                    raise KeyError(f"KPI {kpi.label!r}: fact {kpi.source}.{kpi.fact} missing")
                target = float(facts[kpi.fact]) * kpi.scale
            else:
                target = float(kpi.value)  # type: ignore[arg-type]
            for p in frames:
                f = ease(p.shot_t / kpi.count_s, "out") if kpi.count_s > 0 else 1.0
                kpi_vals[p.index].append(round(kpi.start + (target - kpi.start) * f, 4))
    caption_alpha = []
    for p in plans:
        dur = film.shots[p.shot].duration_s
        a = min(1.0, p.shot_t / 0.6, max(0.0, (dur - p.shot_t) / 0.4))
        caption_alpha.append(round(max(0.0, a), 4))
    title = []
    for p in plans:
        tc = film.title_card_s
        a = 0.0 if tc <= 0 else (1.0 if p.film_t < tc - 0.6 else max(0.0, (tc - p.film_t) / 0.6))
        title.append(round(a, 4))
    return {
        "n": len(plans),
        "fps": fps,
        "shot": [p.shot for p in plans],
        "shot_t": [round(p.shot_t, 5) for p in plans],
        "sim_t": [round(p.camera.sim_t, 4) for p in plans],
        "camera": [
            [
                round(p.camera.lon, 7),
                round(p.camera.lat, 7),
                round(p.camera.zoom, 5),
                round(p.camera.pitch, 4),
                round(p.camera.bearing, 4),
            ]
            for p in plans
        ],
        "light": light,
        "light_fields": [
            "night",
            "sun_intensity",
            "ambient_intensity",
            "dx",
            "dy",
            "dz",
            "sun_r",
            "sun_g",
            "sun_b",
            "amb_r",
            "amb_g",
            "amb_b",
            "elevation_deg",
            "azimuth_deg",
        ],
        "clock": [clock_text(film, p.camera.sim_t) for p in plans],
        "kpi": kpi_vals,
        "caption_alpha": caption_alpha,
        "title_alpha": title,
        "fade": fade_alpha(film, plans, fps),
    }


# ----------------------------------------------------------------------------- bundle


def film_bbox(film: Film, plans: list[FramePlan], width: int, height: int) -> tuple[float, ...]:
    if film.basemap.bbox is not None:
        return film.basemap.bbox
    pts = []
    for p in plans[:: max(1, len(plans) // 60)] + plans[-1:]:
        c = p.camera
        r = bm.view_extent(c.lon, c.lat, c.zoom, width, height) * (1 + c.pitch / 45)
        pts += [(c.lon - r, c.lat - r), (c.lon + r, c.lat + r)]
    return bm.pad_bbox(pts, film.basemap.margin_deg)


def primary_source(film: Film) -> str:
    for shot in film.shots:
        lay = shot.layers
        for sid in (lay.heat, *(lay.split or ()), lay.trips, lay.route_source):
            if sid is not None:
                return sid
    return next(iter(film.sources))


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def film_labels(
    film: Film, plans: list[FramePlan], bbox: tuple[float, ...], settings: dict[str, Any]
) -> dict[str, Any]:
    """Labels for the film's map area, thinned to the street classes its cameras get close to."""
    data = json.loads(build_labels(tuple(bbox)).read_text())  # type: ignore[arg-type]
    max_zoom = max(p.camera.zoom for p in plans)
    gate = settings["labels"]["street_min_zoom"]
    data["streets"] = [s for s in data["streets"] if gate[s["cls"]] <= max_zoom + 0.3]
    data["landmarks"] = [lm for lm in data["landmarks"] if lm["min_zoom"] <= max_zoom]
    return data


def build_bundle(
    film: Film,
    fps: int,
    width: int,
    height: int,
    letterbox: bool,
    out: Path | None = None,
    narration: list[dict[str, Any]] | None = None,
    subtitles: bool = True,
) -> Path:
    """Write the bundle; `narration` = voice-over lines [{text, start_s, end_s}] (film seconds)."""
    settings = load_settings()
    out = out or movies_runs_dir() / film.film / "bundle"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    plans = plan_frames(film, fps)
    sources = resolve_sources(film)
    bbox = film_bbox(film, plans, width, height)
    primary = primary_source(film)
    net = film_network(sources, primary, bbox, film.basemap.road_classes == "major")
    origin = (round(float(net.coords[:, 0].mean()), 4), round(float(net.coords[:, 1].mean()), 4))
    # roads
    with (out / "roads.bin").open("wb") as fh:
        fh.write(net.starts.astype("<u4").tobytes())
        fh.write((net.coords - np.asarray(origin)).astype("<f4").tobytes())
        fh.write(net.classes.astype(np.uint8).tobytes())
    files: dict[str, Any] = {"heat": {}, "trips": {}, "overlays": "overlays.json"}
    # heat
    heat_ids: dict[str, str] = {}
    for shot in film.shots:
        lay = shot.layers
        for sid in (lay.heat, lay.compare, *(lay.split or ())):
            if sid is not None and sources[sid].kind == "run":
                heat_ids[sid] = lay.metric
    for sid, metric in sorted(heat_ids.items()):
        files["heat"][sid] = build_heat(
            sources[sid],
            net,
            metric,
            _heat_ranges(film.shots, plans, sid),
            out / f"heat-{sid}.bin",
            settings,
        )
    # trips
    trail = float(settings["trips"]["trail_s"]["value"])
    step = int(settings["trips"]["fcd_step"]["value"])
    trip_ids = sorted(
        {
            sid
            for s in film.shots
            for sid in (s.layers.trips, *(s.layers.split or ()))
            if sid is not None
        }
    )
    for sid in trip_ids:
        src = sources[sid]
        t0, t1 = _trip_range(film.shots, plans, sid)
        if src.kind == "strategist":
            amb = ambulance_trip(src, net)
            trips = (
                merge_trips(read_fcd(src.background, t0 - trail, t1, step), amb)
                if (src.background is not None)
                else amb
            )
        else:
            if src.run.tier != "B":
                continue
            trips = read_fcd(src.run, t0 - trail, t1, step)
        files["trips"][sid] = write_trips(trips, origin, out / f"trips-{sid}.bin")
    # labels (street names in English where OSM has them, Arabic second line)
    names_en: dict[str, str] = {}
    if film.annotations.labels:
        labels = film_labels(film, plans, bbox, settings)
        text = json.dumps(labels, ensure_ascii=False, separators=(",", ":"))
        (out / "labels.json").write_text(text)
        names_en = {s["ar"]: s["en"] for s in labels["streets"] if s.get("ar")}
    # overlays
    overlays = {sid: build_overlays(src, net) for sid, src in sorted(sources.items())}
    for sid, o in overlays.items():
        add_callouts(o, sources[sid], net, names_en)
    (out / "overlays.json").write_text(json.dumps(overlays, separators=(",", ":")))
    # basemap
    if film.basemap.buildings or film.basemap.water:
        bdir = bm.build_basemap(tuple(bbox))  # type: ignore[arg-type]
        if film.basemap.buildings:
            shutil.copyfile(bdir / "buildings.json", out / "buildings.json")
            files["buildings"] = "buildings.json"
        if film.basemap.water:
            shutil.copyfile(bdir / "water.json", out / "water.json")
            files["water"] = "water.json"
    # frames + HUD text
    frames = plan_json(film, plans, fps, sources, settings)
    (out / "frames.json").write_text(json.dumps(frames, separators=(",", ":")))
    facts = {sid: s.facts for sid, s in sources.items()}
    shots = []
    for shot in film.shots:
        d = shot.model_dump()
        for key in ("line", "stations"):  # optional layers: absent keeps older manifests identical
            if d["layers"][key] is None:
                del d["layers"][key]
        d["hud"]["caption"] = fill_text(shot.hud.caption, facts)
        d["hud"]["detail"] = fill_text(shot.hud.detail, facts)
        shots.append(d)
    manifest = {
        "version": BUNDLE_VERSION,
        "label": SYNTHETIC_LABEL,
        "film": film.film,
        "title": film.title,
        "subtitle": film.subtitle,
        "tier": film.tier,
        "fictional": film.fictional,
        "annotations": {
            "labels": "labels.json" if film.annotations.labels else None,
            "compass": film.annotations.compass,
            "scale_bar": film.annotations.scale_bar,
            "subtitles": bool(narration) and subtitles,
        },
        "narration": narration or [],
        "width": width,
        "height": height,
        "fps": fps,
        "n_frames": len(plans),
        "letterbox": settings["render"]["letterbox_aspect"] if letterbox else None,
        "bbox": list(bbox),
        "origin": list(origin),
        "roads": {
            "url": "roads.bin",
            "n_edges": len(net.edge_ids),
            "n_points": int(net.starts[-1]),
            "classes": ROAD_CLASSES,
            "network_hash": net.network_hash,
        },
        "vehicle_classes": VEHICLE_CLASSES,
        "trail_s": trail,
        "diff_half_range": settings["heat"]["diff_half_range"],
        "files": files,
        "frames": "frames.json",
        "shots": shots,
        "sources": {
            sid: {
                "kind": s.kind,
                "run_id": s.run.run_id if s.run is not None else None,
                "recommendation_id": (s.rec or {}).get("recommendation_id"),
                "candidate": s.candidate,
                "background": s.background.run_id if s.background is not None else None,
            }
            for sid, s in sorted(sources.items())
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    hashes = {p.name: sha_file(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / "hashes.json").write_text(json.dumps(hashes, indent=1))
    return out
