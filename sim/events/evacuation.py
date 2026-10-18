"""Evacuation (M7): mass departures from a zone polygon to exit points, phased release, optional
contraflow and an evacuation signal plan; clearance metrics (time to 50 / 90 / 100 % out) and
bottleneck edges. Tier B (microscopic) only. Synthetic demand, uncalibrated; scenarios fictional.

    python -m sim.events.evacuation run --scenario evac_obhur --seed 1
    python -m sim.events.evacuation validate sim/scenarios/evac_*.yaml
    python -m sim.events.evacuation net --scenario evac_flood_balad      # build the contraflow net
    python -m sim.events.evacuation register [--check]

Main process (sumolib): `analyse` finds the zone's origin edges (passenger edges whose midpoint
lies in the polygon, weighted by lane length, A-evac-005), the exits (`auto`: window fringe edges
by capacity, A-evac-007..010) and one reverse free-flow shortest-path tree per exit; samples the
evacuee origins (seeded) and the contraflow corridors (A-evac-016..021). `resolve` turns a spec and
its strategy fields (phasing, exit assignment, contraflow set, signal plan) into a JSON plan with
every evacuee's route and departure time. Worker (TraCI): `EvacuationEvent` inserts the evacuees
when the order is given, re-plans their routes (A-evac-004), switches contraflow and the signal
plan, and measures arrivals and halted vehicles on the evacuation routes.

Contraflow (decision B-D-027, documented in docs/evacuation.md): SUMO cannot reverse a lane at run
time, so the window net is edited once per scenario (`net`): every corridor edge gets the reversed
inbound lanes as extra lanes on its median side, with explicit lane connections along the corridor
(netconvert keeps the loaded connections, so new lanes would otherwise be unreachable), and the
signal programs are Webster-retimed on the edited net (sim.link.retime_tls). The extra lanes are
closed to everyone in every run of the scenario (reference, no strategy, all candidates) until a
contraflow is switched on, which opens them and closes the inbound carriageway (emergency
vehicles only, A-evac-020) after the setup time (A-evac-015): the lane-direction trick. The city
net and the window net are not touched; the edited net is
`data/windows/<w>/<w>.evac-<hash>.net.xml`.

The scenario schema and event registry (sim/scenarios/schema.py, sim/events/registry.py) still
reject evacuation (M5 files, not owned by M7): this module validates the event with its own model
and registers its event classes in the worker processes it starts (B-D-026).
"""

from __future__ import annotations

import heapq
import json
import math
import multiprocessing as mp
import random
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path
from typing import Any, Literal

import traci.constants as tc
import typer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from traci._trafficlight import Logic, Phase
from traci.exceptions import TraCIException

from sim.common import (
    REPO_ROOT,
    SYNTHETIC_LABEL,
    config_hash,
    content_hash,
    load_yaml,
    rel,
    sumo_bin,
    sumo_env,
    sumo_version,
)
from sim.events.base import EVENT_VEHICLE_PREFIX, Event, EventContext, lane_edge
from sim.events.netindex import NetIndex, _heading
from sim.scenarios.schema import Evacuation, Scenario, SimTime
from sim.vtypes.schema import Param, params_in

SETTINGS_FILE = REPO_ROOT / "sim" / "scenarios" / "evac_settings.yaml"
SCENARIO_DIR = REPO_ROOT / "sim" / "scenarios"
RUNS_DIR = REPO_ROOT / "runs"
DOC = REPO_ROOT / "docs" / "evacuation.md"
EVAC_TYPE = "evacuation"
PASSENGER = "passenger"


# --- settings -----------------------------------------------------------------------------------
@cache
def _tree() -> dict[str, Any]:
    return load_yaml(SETTINGS_FILE)


def param(section: str, key: str) -> Param:
    return Param.model_validate(_tree()[section][key])


def value(section: str, key: str) -> Any:
    return param(section, key).value


def model(key: str) -> Any:
    return _tree()["model"][key]


def registered() -> list[tuple[str, Param]]:
    tree = {k: v for k, v in _tree().items() if k != "model"}
    return [(path, Param.model_validate(raw)) for path, raw in params_in(tree)]


def event_ids() -> list[str]:
    """Register ids the evacuation event depends on (everything except the strategy weights)."""
    return [p.id for path, p in registered() if not path.startswith("strategy.")]


# --- spec ---------------------------------------------------------------------------------------
Phasing = Literal["simultaneous", "near_first", "far_first"]
Assignment = Literal["nearest", "balanced"]
SignalPlan = Literal["default", "evacuation"]


class EvacSpec(BaseModel):
    """The evacuation event of a scenario file (strict; the M5 schema accepts it loosely)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["evacuation"]
    id: str
    start: SimTime
    zone: list[tuple[float, float]] = Field(min_length=3)  # [lon, lat] polygon
    vehicles: int = Field(ge=1, le=20000)
    release_s: float | None = Field(default=None, gt=0)
    exits: Literal["auto"] | list[str] = "auto"
    exit_count: int | None = Field(default=None, ge=1, le=20)
    phasing: Phasing = "simultaneous"
    exit_assignment: Assignment | None = None
    contraflow: list[str] = Field(default_factory=list)  # exit edge ids, or ["all"]
    signal_plan: SignalPlan = "default"
    source: str | None = None
    assumption: str | None = None
    notes: str | None = None

    @field_validator("zone")
    @classmethod
    def _lonlat(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for lon, lat in v:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"zone point ({lon}, {lat}) is not lon/lat")
        return v

    @model_validator(mode="after")
    def _provenance(self) -> EvacSpec:
        if (self.release_s is not None or self.exit_count is not None) and not (
            self.source or self.assumption
        ):
            raise ValueError(
                "evacuation: overriding release_s / exit_count needs `source:` or `assumption:`"
            )
        return self


def evac_specs(scen: Scenario) -> list[EvacSpec]:
    return [
        EvacSpec.model_validate(e.model_dump(mode="json", exclude_none=True))
        for e in scen.events
        if isinstance(e, Evacuation)
    ]


def without_evacuation(scen: Scenario) -> Scenario:
    return scen.model_copy(
        update={"events": [e for e in scen.events if not isinstance(e, Evacuation)]}
    )


def load(ref: str | Path) -> tuple[Scenario, EvacSpec]:
    path = Path(ref)
    if not path.exists():
        path = SCENARIO_DIR / f"{ref}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"scenario {ref!r} not found (looked for {rel(path)})")
    scen = Scenario.model_validate(load_yaml(path))
    specs = evac_specs(scen)
    if len(specs) != 1:
        raise ValueError(f"{rel(path)}: expected exactly one evacuation event, got {len(specs)}")
    if not scen.fictional:
        raise ValueError(f"{rel(path)}: public evacuation scenarios must be fictional (PROJECT 11)")
    return scen, specs[0]


# --- network analysis (main process) ------------------------------------------------------------
def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_area(poly: list[tuple[float, float]]) -> float:
    return abs(
        sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True))
        / 2
    )


def _mid(edge: Any) -> tuple[float, float]:
    shape = edge.getShape()
    return (
        shape[len(shape) // 2]
        if len(shape) % 2
        else (
            (shape[len(shape) // 2 - 1][0] + shape[len(shape) // 2][0]) / 2,
            (shape[len(shape) // 2 - 1][1] + shape[len(shape) // 2][1]) / 2,
        )
    )


def free_flow_s(edge: Any) -> float:
    return edge.getLength() / max(edge.getSpeed(), 0.1)


class EvacNet:
    """Static analysis of a window net for one zone (sumolib)."""

    def __init__(self, idx: NetIndex, zone_lonlat: list[tuple[float, float]]) -> None:
        self.idx = idx
        self.net = idx.net
        self.zone = [idx.lonlat_to_xy(lon, lat) for lon, lat in zone_lonlat]
        self.edges = {eid: e for eid, e in idx.edges.items() if e.allows(PASSENGER)}
        self._pred: dict[str, list[str]] | None = None

    def origins(self) -> list[tuple[str, float]]:
        """(edge, weight = lane length) for passenger edges whose midpoint is in the zone."""
        out = []
        for eid, e in sorted(self.edges.items()):
            x, y = _mid(e)
            if point_in_polygon(x, y, self.zone):
                lanes = sum(1 for ln in e.getLanes() if ln.allows(PASSENGER))
                out.append((eid, round(e.getLength() * lanes, 3)))
        return out

    def zone_distance(self, x: float, y: float) -> float:
        if point_in_polygon(x, y, self.zone):
            return 0.0
        best = math.inf
        for (x1, y1), (x2, y2) in zip(self.zone, self.zone[1:] + self.zone[:1], strict=True):
            dx, dy = x2 - x1, y2 - y1
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / ((dx * dx + dy * dy) or 1)))
            best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
        return best

    def auto_exits(self, count: int) -> list[str]:
        """Window fringe edges (no passenger successor) by capacity, far enough from the zone
        and apart from each other (A-evac-007..010)."""
        min_cap = float(value("exits", "min_capacity"))
        min_dist = float(value("exits", "min_distance_m"))
        spacing = float(value("exits", "min_spacing_m"))
        cands = []
        for eid, e in self.edges.items():
            if e.getAllowedOutgoing(PASSENGER):
                continue
            lanes = sum(1 for ln in e.getLanes() if ln.allows(PASSENGER))
            cap = lanes * e.getSpeed()
            end = e.getShape()[-1]
            if cap >= min_cap and self.zone_distance(*end) >= min_dist:
                cands.append((-cap, eid, end))
        chosen: list[tuple[str, tuple[float, float]]] = []
        for _, eid, end in sorted(cands):
            if all(math.dist(end, p) >= spacing for _, p in chosen):
                chosen.append((eid, end))
            if len(chosen) == count:
                break
        return [eid for eid, _ in chosen]

    @property
    def pred(self) -> dict[str, list[str]]:
        if self._pred is None:
            pred: dict[str, list[str]] = {eid: [] for eid in self.edges}
            for eid, e in self.edges.items():
                for o in e.getAllowedOutgoing(PASSENGER):
                    if o.getID() in pred:
                        pred[o.getID()].append(eid)
            self._pred = pred
        return self._pred

    def tree(self, exit_edge: str) -> tuple[dict[str, float], dict[str, str]]:
        """Reverse Dijkstra: free-flow seconds from the start of each edge to the end of the
        exit edge, and the next edge on that path."""
        dist = {exit_edge: free_flow_s(self.edges[exit_edge])}
        nxt: dict[str, str] = {}
        heap = [(dist[exit_edge], exit_edge)]
        while heap:
            d, eid = heapq.heappop(heap)
            if d > dist.get(eid, math.inf):
                continue
            for p in self.pred[eid]:
                nd = d + free_flow_s(self.edges[p])
                if nd < dist.get(p, math.inf) - 1e-9 or (
                    abs(nd - dist.get(p, math.inf)) <= 1e-9 and eid < nxt.get(p, eid)
                ):
                    dist[p] = nd
                    nxt[p] = eid
                    heapq.heappush(heap, (nd, p))
        return dist, nxt

    @staticmethod
    def path(origin: str, exit_edge: str, nxt: dict[str, str]) -> list[str]:
        out = [origin]
        while out[-1] != exit_edge:
            out.append(nxt[out[-1]])
        return out

    # contraflow --------------------------------------------------------------------------------
    def partners(self, eid: str) -> list[str]:
        """Inbound carriageway of a corridor edge: the reverse edge between the same nodes, else
        the nearest anti-parallel edge (heading differs by > A-evac-036) within A-evac-037
        of the edge's start, middle and end, of an allowed road type and with the same name when
        both are named."""
        e = self.edges[eid]
        types = set(str(value("contraflow", "road_types")).split("|"))
        a, b = e.getFromNode(), e.getToNode()
        same = sorted(
            o.getID()
            for o in b.getOutgoing()
            if o.getToNode() == a and o.getID() in self.edges and o.getType() in types
        )
        if same:
            return same
        h = _heading(e)
        r = float(value("contraflow", "partner_search_m"))
        anti = float(value("contraflow", "antiparallel_deg"))
        found: set[str] = set()
        shape = e.getShape()
        for x, y in (shape[0], _mid(e), shape[-1]):
            best: tuple[float, str] | None = None
            for o, d in self.net.getNeighboringEdges(x, y, r=r, includeJunctions=False):
                oid = o.getID()
                if oid == eid or oid not in self.edges or o.getType() not in types:
                    continue
                if e.getName() and o.getName() and o.getName() != e.getName():
                    continue
                if abs((_heading(o) - h + 180) % 360 - 180) > anti and (
                    best is None or d < best[0]
                ):
                    best = (d, oid)
            if best:
                found.add(best[1])
        return sorted(found)

    def corridor(self, route: list[str], taken: set[str]) -> dict[str, Any] | None:
        """The trailing part of a route (towards its exit) that can be reversed (edges in `taken`,
        i.e. zone origin edges and other corridors, are excluded): contiguous edges
        of an allowed road type (A-evac-019) up to A-evac-016, skipping at most two fringe stubs
        at the exit. The inbound carriageway = partners found along it; it must run beside at
        least A-evac-038 of the corridor length. Every corridor edge gets the same number
        of reversed lanes: the inbound lane count (length-weighted mode), capped (A-evac-018)."""
        types = set(str(value("contraflow", "road_types")).split("|"))
        max_len = float(value("contraflow", "max_length_m"))
        max_add = int(value("contraflow", "max_added_lanes"))
        picked: list[tuple[str, list[str]]] = []
        length = 0.0
        skipped = 0
        for eid in reversed(route):
            e = self.edges[eid]
            if e.getType() not in types or eid in taken:
                if picked or skipped >= 2:
                    break
                skipped += 1  # fringe ramp stubs at the exit end
                continue
            if length + e.getLength() > max_len:
                break
            picked.append((eid, [p for p in self.partners(eid) if p not in taken]))
            length += e.getLength()
        if not picked or length < float(value("contraflow", "min_length_m")):
            return None
        covered = sum(self.edges[eid].getLength() for eid, parts in picked if parts)
        if covered < float(value("contraflow", "partner_coverage")) * length:
            return None
        lanes: Counter = Counter()
        for eid, parts in picked:
            for p in parts:
                lanes[self.edges[p].getLaneNumber()] += self.edges[eid].getLength()
        add = min(max_add, min(lanes, key=lambda n: (-lanes[n], n)))
        partners = sorted({p for _, parts in picked for p in parts})
        edges = [
            {"edge": eid, "base_lanes": self.edges[eid].getLaneNumber(), "added": add,
             "partners": parts}
            for eid, parts in picked
        ]  # fmt: skip
        edges.reverse()
        first = route.index(edges[0]["edge"])
        last = route.index(edges[-1]["edge"])
        lane_km = sum(self.edges[c["edge"]].getLength() * c["added"] for c in edges) / 1000
        return {
            "exit": route[-1],
            "edges": edges,
            "pred": route[first - 1] if first > 0 else None,
            "succ": route[last + 1] if last + 1 < len(route) else None,
            "length_m": round(length, 1),
            "lane_km": round(lane_km, 3),
            "name": self.edges[edges[0]["edge"]].getName() or edges[0]["edge"],
            "inbound_edges": partners,
            "partner_coverage": round(covered / length, 3),
        }


def analyse(spec: EvacSpec, idx: NetIndex, seed: int) -> dict[str, Any]:
    """Strategy-independent part of the plan: origins, exits, trees, sampled evacuees, corridors.

    Common random numbers: every strategy of a scenario uses the same evacuees (origin edges and
    order), so their clearance times differ only by the strategy."""
    en = EvacNet(idx, spec.zone)
    origins = en.origins()
    if not origins:
        raise ValueError(f"evacuation {spec.id}: no passenger edge inside the zone polygon")
    ids: list[str] = []
    if spec.exits == "auto":
        if spec.exit_count is None:
            ids.append(param("exits", "count").id)
        count = int(spec.exit_count or value("exits", "count"))
        exits = en.auto_exits(count)
        ids += [param("exits", k).id for k in ("min_capacity", "min_distance_m", "min_spacing_m")]
    else:
        exits = list(spec.exits)
        for x in exits:
            idx.edge(x)
    if not exits:
        raise ValueError(f"evacuation {spec.id}: no exit edge found")
    trees = {x: en.tree(x) for x in exits}
    reach = {o: {x: trees[x][0][o] for x in exits if o in trees[x][0]} for o, _ in origins}
    usable = [(o, w) for o, w in origins if reach[o]]
    if not usable:
        raise ValueError(f"evacuation {spec.id}: no zone edge reaches an exit")
    rng = random.Random(f"evac:{seed}:{spec.id}")
    sampled = rng.choices([o for o, _ in usable], weights=[w for _, w in usable], k=spec.vehicles)
    nearest = [min(reach[o], key=lambda x: (reach[o][x], x)) for o in sampled]
    lanes = {x: sum(1 for ln in en.edges[x].getLanes() if ln.allows(PASSENGER)) for x in exits}
    balanced = _assign(
        {
            "reach": reach,
            "sampled": sampled,
            "exits": [{"edge": x, "lanes": lanes[x]} for x in exits],
        },
        "balanced",
    )
    # corridors for the exits most used without guidance, then with balanced guidance
    counts = Counter({x: 0 for x in exits})
    route_counts: dict[str, Counter] = {x: Counter() for x in exits}
    for o, x in [*zip(sampled, nearest, strict=True), *zip(sampled, balanced, strict=True)]:
        counts[x] += 1
        route_counts[x][o] += 1
    counts = Counter({x: n for x, n in counts.items() if n})
    corridors: list[dict[str, Any]] = []
    # zone edges are never reversed nor closed: evacuees start on them (corridors end at the zone)
    taken: set[str] = {o for o, _ in origins}
    for x, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(corridors) >= int(value("contraflow", "max_corridors")):
            break
        top_origin = min(route_counts[x], key=lambda o: (-route_counts[x][o], o))
        c = en.corridor(EvacNet.path(top_origin, x, trees[x][1]), taken)
        if c:
            c["id"] = f"cf{len(corridors) + 1}"
            corridors.append(c)
            taken |= {ce["edge"] for ce in c["edges"]} | {
                p for ce in c["edges"] for p in ce["partners"]
            }
    exit_info = []
    for x in exits:
        e = en.edges[x]
        lon, lat = idx.net.convertXY2LonLat(*e.getShape()[-1])
        exit_info.append(
            {
                "edge": x,
                "name": e.getName(),
                "type": e.getType(),
                "lanes": sum(1 for ln in e.getLanes() if ln.allows(PASSENGER)),
                "speed_ms": round(e.getSpeed(), 2),
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "nearest_assigned": Counter(nearest).get(x, 0),
                "balanced_assigned": Counter(balanced).get(x, 0),
            }
        )
    return {
        "zone_area_km2": round(polygon_area(en.zone) / 1e6, 3),
        "origin_edges": len(origins),
        "origin_edges_reaching_exit": len(usable),
        "exits": exit_info,
        "sampled": sampled,
        "reach": {o: reach[o] for o in sorted(set(sampled))},
        "trees": {x: trees[x][1] for x in exits},
        "corridors": corridors,
        "assumption_ids": ids,
    }


# --- contraflow network edit --------------------------------------------------------------------
def corridor_patch(corridors: list[dict[str, Any]]) -> tuple[str, str]:
    """(edge patch, connection file) adding the reversed lanes and their lane connections."""
    edg = ["<edges>"]
    con = ["<connections>"]
    pairs: list[tuple[str, int, str, int]] = []
    for c in corridors:
        ces = c["edges"]
        for ce in ces:
            edg.append(f'    <edge id="{ce["edge"]}" numLanes="{ce["base_lanes"] + ce["added"]}"/>')
        first = ces[0]
        if c["pred"]:
            pairs += [
                (c["pred"], -1, first["edge"], first["base_lanes"] + j)
                for j in range(first["added"])
            ]
        for a, b in zip(ces, ces[1:], strict=False):
            for j in range(b["added"]):
                pairs.append(
                    (
                        a["edge"],
                        a["base_lanes"] + min(j, a["added"] - 1),
                        b["edge"],
                        b["base_lanes"] + j,
                    )
                )
            for j in range(b["added"], a["added"]):
                pairs.append(
                    (a["edge"], a["base_lanes"] + j, b["edge"], b["base_lanes"] + b["added"] - 1)
                )
        last = ces[-1]
        if c["succ"]:
            pairs += [
                (last["edge"], last["base_lanes"] + j, c["succ"], -1) for j in range(last["added"])
            ]
    for f, fl, t, tl in dict.fromkeys(pairs):
        con.append(f'    <connection from="{f}" to="{t}" fromLane="{fl}" toLane="{tl}"/>')
    return "\n".join([*edg, "</edges>"]) + "\n", "\n".join([*con, "</connections>"]) + "\n"


def _resolve_lane(net: NetIndex, edge: str, lane: int) -> int:
    return net.edge(edge).getLaneNumber() - 1 if lane < 0 else lane


def evac_net_paths(window: str, key: str, base: Path | None = None) -> dict[str, Path]:
    base = base or REPO_ROOT / "data" / "windows" / window
    stem = f"{window}.evac-{key}"
    return {
        "net": base / f"{stem}.net.xml",
        "tls": base / f"{stem}.tls.add.xml",
        "edg": base / f"{stem}.edg.xml",
        "con": base / f"{stem}.con.xml",
        "meta": base / f"{stem}.json",
    }


def build_evac_net(
    window: str,
    net: Path,
    routes: Path,
    extra_adds: list[Path],
    corridors: list[dict[str, Any]],
    idx: NetIndex,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Window net + reversible lanes (cached by window net hash and corridor set)."""
    if not corridors:
        return {"net": net, "additionals": extra_adds, "key": None, "built": False}
    edg, con_tmpl = corridor_patch(corridors)
    # resolve the -1 placeholders (leftmost lane of a corridor's neighbour edge) on the window net
    lines = []
    for line in con_tmpl.splitlines():
        if "<connection " in line:
            el = ET.fromstring(line.strip())
            fl = _resolve_lane(idx, el.get("from", ""), int(el.get("fromLane", "0")))
            tl = _resolve_lane(idx, el.get("to", ""), int(el.get("toLane", "0")))
            line = (
                f'    <connection from="{el.get("from")}" to="{el.get("to")}" '
                f'fromLane="{fl}" toLane="{tl}"/>'
            )
        lines.append(line)
    con = "\n".join(lines) + "\n"
    key = config_hash({"net": content_hash(net), "edg": edg, "con": con})[:10]
    p = evac_net_paths(window, key, out_dir)
    if p["net"].exists() and p["meta"].exists():
        meta = json.loads(p["meta"].read_text())
        adds = [p["tls"]] if meta.get("tls") else []
        return {"net": p["net"], "additionals": adds, "key": key, "built": False, "meta": meta}
    p["net"].parent.mkdir(parents=True, exist_ok=True)
    p["edg"].write_text(edg)
    p["con"].write_text(con)
    log = REPO_ROOT / "logs" / f"evac-net-{window}-{key}.log"
    log.parent.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    with log.open("w") as fh:
        subprocess.run(
            [
                sumo_bin("netconvert"), "-s", str(net), "-e", str(p["edg"]), "-x", str(p["con"]),
                "-o", str(p["net"]),
            ],
            check=True, stdout=fh, stderr=subprocess.STDOUT, env=sumo_env(), cwd=REPO_ROOT,
        )  # fmt: skip
    tls_meta = None
    if extra_adds:  # the window has retimed programs: retime again on the edited net
        from sim.link import retime_tls

        tls_meta = retime_tls(p["net"], routes, p["tls"], log=log)
    meta = {
        "label": SYNTHETIC_LABEL,
        "window": window,
        "window_net": rel(net),
        "window_net_hash": content_hash(net),
        "corridors": [c["id"] for c in corridors],
        "netconvert_s": round(time.perf_counter() - t0, 1),
        "tls": tls_meta,
        "net_hash": content_hash(p["net"]),
        "log": rel(log),
    }
    p["meta"].write_text(json.dumps(meta, indent=2, default=str))
    adds = [p["tls"]] if tls_meta else []
    return {"net": p["net"], "additionals": adds, "key": key, "built": True, "meta": meta}


# --- plan ---------------------------------------------------------------------------------------
def _assign(ana: dict[str, Any], mode: str) -> list[str]:
    reach = ana["reach"]
    if mode == "nearest":
        return [min(reach[o], key=lambda x: (reach[o][x], x)) for o in ana["sampled"]]
    sat = float(value("exits", "sat_flow_vps_lane"))
    detour = float(value("assignment", "balanced_max_detour"))
    lanes = {x["edge"]: x["lanes"] for x in ana["exits"]}
    load: Counter = Counter()
    out = []
    for o in ana["sampled"]:
        best = min(reach[o].values())
        options = [x for x, t in reach[o].items() if t <= detour * best]
        x = min(options, key=lambda x: (reach[o][x] + load[x] / (sat * lanes[x]), x))
        load[x] += 1
        out.append(x)
    return out


def _release(
    spec: EvacSpec, ana: dict[str, Any], exits: list[str], release_s: float, seed: int
) -> tuple[list[float], list[int]]:
    """Departure time (absolute) and band of each evacuee."""
    n = len(exits)
    k = int(value("phasing", "sectors"))
    ff = [ana["reach"][o][x] for o, x in zip(ana["sampled"], exits, strict=True)]
    order = sorted(range(n), key=lambda i: (ff[i], i))
    band = [0] * n
    for r, i in enumerate(order):
        band[i] = min(k - 1, r * k // n)
    rng = random.Random(f"release:{seed}:{spec.id}")
    t0 = float(spec.start)
    times = [0.0] * n
    if spec.phasing == "simultaneous":
        groups = [(list(range(n)), t0, t0 + release_s)]
    else:
        seq = list(range(k)) if spec.phasing == "near_first" else list(reversed(range(k)))
        step = release_s / k
        groups = [
            ([i for i in range(n) if band[i] == b], t0 + pos * step, t0 + (pos + 1) * step)
            for pos, b in enumerate(seq)
        ]
    for members, a, b in groups:
        members = sorted(members)
        rng.shuffle(members)
        m = len(members)
        for j, i in enumerate(members):
            times[i] = float(math.floor(a + (j + rng.random()) * (b - a) / m))
    return times, band


def resolve(
    spec: EvacSpec,
    ana: dict[str, Any],
    seed: int,
    begin: float,
    vtypes: dict[str, float],
    tls_nodes: dict[str, str],
    run_end: float,
) -> dict[str, Any]:
    """JSON plan for the worker. `vtypes`: evacuee type shares (passenger-class members of the
    scenario mix, A-evac-034). `tls_nodes`: edge id -> TLS controlling movements out of it."""
    overridden = set()
    if spec.release_s is not None:
        overridden.add(param("event", "release_s").id)
    if spec.exit_count is not None or spec.exits != "auto":
        overridden.add(param("exits", "count").id)
    if spec.exits != "auto":
        overridden |= {param("exits", k).id for k in ("min_capacity", "min_distance_m",
                                                      "min_spacing_m")}  # fmt: skip
    ids = [i for i in [*ana["assumption_ids"], *event_ids()] if i not in overridden]
    release_s = float(spec.release_s or value("event", "release_s"))
    mode = spec.exit_assignment or str(value("assignment", "default"))
    exits = _assign(ana, mode)
    times, band = _release(spec, ana, exits, release_s, seed)
    routes: dict[str, list[str]] = {}
    route_of: dict[tuple[str, str], str] = {}
    vehicles = []
    prefix = f"{EVENT_VEHICLE_PREFIX}{spec.id}."
    trng = random.Random(f"vtype:{seed}:{spec.id}")
    names = sorted(vtypes)
    types = trng.choices(names, weights=[vtypes[n] for n in names], k=len(exits))
    for i, (o, x) in enumerate(zip(ana["sampled"], exits, strict=True)):
        if (o, x) not in route_of:
            rid = f"{prefix}r{len(route_of)}"
            route_of[(o, x)] = rid
            routes[rid] = EvacNet.path(o, x, ana["trees"][x])
        vehicles.append([f"{prefix}{i}", route_of[(o, x)], times[i], band[i], x, types[i]])
    if "all" in spec.contraflow:
        active = [c["id"] for c in ana["corridors"]]
    else:
        by_exit = {c["exit"]: c["id"] for c in ana["corridors"]}
        missing = [x for x in spec.contraflow if x not in by_exit]
        if missing:
            raise ValueError(
                f"evacuation {spec.id}: no contraflow corridor towards exit(s) {missing}; "
                f"corridors exist towards {sorted(by_exit)}"
            )
        active = [by_exit[x] for x in spec.contraflow]
    moves = sorted(
        {(a, b) for r in routes.values() for a, b in zip(r, r[1:], strict=False) if a in tls_nodes}
    )
    watch = sorted({e for r in routes.values() for e in r})
    return {
        "type": EVAC_TYPE,
        "id": spec.id,
        "start": float(begin),  # dormant contraflow lanes are closed from the run's begin
        "end": None,
        "order_t": float(spec.start),
        "run_end": float(run_end),
        "release_s": release_s,
        "phasing": spec.phasing,
        "exit_assignment": mode,
        "signal_plan": spec.signal_plan,
        "contraflow": active,
        "corridors": ana["corridors"],
        "setup_s": float(value("contraflow", "setup_s")),
        "inbound_allowed": [str(value("contraflow", "inbound_allowed"))]
        if value("contraflow", "inbound_allowed") != "none"
        else [],
        "reroute_period_s": float(value("event", "reroute_period_s")),
        "signals": {
            "green_factor": float(value("signals", "green_factor")),
            "other_factor": float(value("signals", "other_factor")),
            "min_green_s": float(value("signals", "min_green_s")),
            "max_green_s": float(value("signals", "max_green_s")),
        },
        "vtypes": vtypes,
        "routes": routes,
        "vehicles": vehicles,
        "moves": [list(m) for m in moves],
        "watch_edges": watch,
        "sample_s": float(model("bottleneck_sample_s")),
        "exits": ana["exits"],
        "assigned": dict(sorted(Counter(exits).items())),
        "bands": dict(sorted(Counter(band).items())),
        "zone": spec.zone,
        "zone_area_km2": ana["zone_area_km2"],
        "reference": False,
        "assumption_ids": list(dict.fromkeys(ids)),
    }


def evacuee_types(mix: dict[str, float], lib: Any) -> dict[str, float]:
    """Evacuees are private cars: the passenger-class members of the mix, renormalised
    (A-evac-034); trucks and buses may not enter car-park service roads."""
    cars = {n: s for n, s in mix.items() if s > 0 and lib.types[n].vClass == PASSENGER}
    if not cars:
        raise ValueError("the scenario's vType mix has no passenger-class type for evacuees")
    total = sum(cars.values())
    return {n: round(s / total, 6) for n, s in sorted(cars.items())}


def reference_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Same net state without the evacuation: dormant lanes closed, nothing else."""
    return {
        **plan,
        "vehicles": [],
        "routes": {},
        "contraflow": [],
        "signal_plan": "default",
        "moves": [],
        "watch_edges": [],
        "reference": True,
    }


def tls_nodes(idx: NetIndex) -> dict[str, str]:
    """Edge id -> id of the traffic light controlling movements out of it."""
    out: dict[str, str] = {}
    for t in idx.net.getTrafficLights():
        for in_lane, _out_lane, _link in t.getConnections():
            out.setdefault(in_lane.getEdge().getID(), t.getID())
    return dict(sorted(out.items()))


# --- runtime (worker) ---------------------------------------------------------------------------
HALT = tc.LAST_STEP_VEHICLE_HALTING_NUMBER


class EvacuationEvent(Event):
    """Inserts evacuees at the order time, applies the strategy, measures clearance."""

    def __init__(self, plan: dict[str, Any]) -> None:
        super().__init__(plan)
        self.order_t = float(plan["order_t"])
        self.ids = {v[0] for v in plan["vehicles"]}
        self.ordered = False
        self.arrivals: dict[str, float] = {}
        self.departs: dict[str, float] = {}
        self.running: set[str] = set()
        self.next_reroute = math.inf
        self.next_sample = math.inf
        self.halted_vs: Counter = Counter()
        self.halted_max: dict[str, tuple[int, float]] = {}
        self.cf_on = False
        self.cf_lanes_opened = 0
        self.cf_lanes_closed = 0
        self.signals: dict[str, str] = {}  # tls -> original program id
        self.restore_t: float | None = None
        self.restored = False
        self.reroutes = 0
        self.reroute_errors = 0
        self.add_errors = 0
        self.max_backlog = 0

    # contraflow lanes: dormant owner per corridor
    def _dormant_owner(self, cid: str) -> str:
        return f"{model('dormant_owner')}.{self.id}.{cid}"

    def _cf_owner(self, cid: str) -> str:
        return f"evac.cf.{self.id}.{cid}"

    def on_start(self, ctx: EventContext) -> None:
        for c in self.plan["corridors"]:
            lanes = [
                f"{ce['edge']}_{ce['base_lanes'] + j}"
                for ce in c["edges"]
                for j in range(ce["added"])
            ]
            ctx.closures.restrict(self._dormant_owner(c["id"]), lanes, [])
        ctx.record(
            self.id, "dormant_lanes_closed", corridors=[c["id"] for c in self.plan["corridors"]]
        )

    def _order(self, ctx: EventContext) -> None:
        conn = ctx.conn
        p = self.plan
        for rid, edges in p["routes"].items():
            conn.route.add(rid, edges)
        for vid, rid, depart, _band, _x, vtype in p["vehicles"]:
            try:
                conn.vehicle.add(
                    vid, rid, typeID=vtype, depart=f"{max(depart, ctx.t):.1f}",
                    departLane="best", departPos="random", departSpeed="0",
                )  # fmt: skip
            except TraCIException:
                self.add_errors += 1
        if p["signal_plan"] == "evacuation" and p["moves"]:
            self._signal_plan(ctx)
        self.next_reroute = ctx.t + p["reroute_period_s"]
        self.next_sample = ctx.t
        ctx.record(
            self.id,
            "order",
            vehicles=len(p["vehicles"]),
            phasing=p["phasing"],
            exit_assignment=p["exit_assignment"],
            contraflow=p["contraflow"],
            signal_plan=p["signal_plan"],
            signals_retimed=sorted(self.signals),
        )

    def _signal_plan(self, ctx: EventContext) -> None:
        conn = ctx.conn
        s = self.plan["signals"]
        moves = {tuple(m) for m in self.plan["moves"]}
        for tls in conn.trafficlight.getIDList():
            links = conn.trafficlight.getControlledLinks(tls)
            evac = {
                i
                for i, ls in enumerate(links)
                for (a, b, _via) in ls
                if (lane_edge(a), lane_edge(b)) in moves
            }
            if not evac:
                continue
            prog = conn.trafficlight.getProgram(tls)
            logic = next(
                lg for lg in conn.trafficlight.getAllProgramLogics(tls) if lg.programID == prog
            )
            phases = []
            for ph in logic.phases:
                st = ph.state
                if "y" in st.lower() or not any(c in "Gg" for c in st):
                    dur = ph.duration
                elif any(st[i] in "Gg" for i in evac if i < len(st)):
                    dur = min(s["max_green_s"], max(ph.duration, ph.duration * s["green_factor"]))
                else:
                    dur = max(s["min_green_s"], min(ph.duration, ph.duration * s["other_factor"]))
                phases.append(Phase(float(dur), st))
            new = Logic(f"evac_{self.id}", 0, 0, phases)
            conn.trafficlight.setProgramLogic(tls, new)
            conn.trafficlight.setProgram(tls, f"evac_{self.id}")
            self.signals[tls] = prog

    def _contraflow(self, ctx: EventContext, on: bool) -> None:
        by_id = {c["id"]: c for c in self.plan["corridors"]}
        for cid in self.plan["contraflow"]:
            c = by_id[cid]
            dormant = [
                f"{ce['edge']}_{ce['base_lanes'] + j}"
                for ce in c["edges"]
                for j in range(ce["added"])
            ]
            inbound = sorted(
                {f"{p}_{k}" for p in c["inbound_edges"]
                 for k in range(ctx.conn.edge.getLaneNumber(p))}
            )  # fmt: skip
            if on:
                ctx.closures.release(self._dormant_owner(cid))
                ctx.closures.restrict(
                    self._cf_owner(cid), inbound, self.plan["inbound_allowed"], reroute=True
                )
                self.cf_lanes_opened += len(dormant)
                self.cf_lanes_closed += len(inbound)
            else:
                ctx.closures.release(self._cf_owner(cid))
                ctx.closures.restrict(self._dormant_owner(cid), dormant, [])
        if on:
            for vid in self.running:  # use the new lanes at once
                self._reroute(ctx, vid)
        ctx.record(
            self.id, "contraflow_on" if on else "contraflow_off", corridors=self.plan["contraflow"]
        )

    def _reroute(self, ctx: EventContext, vid: str) -> None:
        try:
            ctx.conn.vehicle.rerouteTraveltime(vid)
            self.reroutes += 1
        except TraCIException:
            self.reroute_errors += 1

    def on_step(self, ctx: EventContext) -> None:
        p = self.plan
        if p["reference"]:
            return
        if not self.ordered:
            if ctx.t < self.order_t:
                return
            self.ordered = True
            self._order(ctx)
        for vid in ctx.departed:
            if vid in self.ids:
                self.departs[vid] = ctx.t
                self.running.add(vid)
                self._reroute(ctx, vid)
        for vid in ctx.arrived:
            if vid in self.ids:
                self.arrivals[vid] = ctx.t
                self.running.discard(vid)
        if p["contraflow"] and not self.cf_on and ctx.t >= self.order_t + p["setup_s"]:
            self.cf_on = True
            self._contraflow(ctx, True)
        if ctx.t >= self.next_reroute:
            for vid in sorted(self.running):
                self._reroute(ctx, vid)
            self.next_reroute = ctx.t + p["reroute_period_s"]
        if ctx.t >= self.next_sample:
            self._sample(ctx)
            self.next_sample = ctx.t + p["sample_s"]
        if len(self.arrivals) == len(self.ids) and self.restore_t is None:
            # signals return to their program at once; reversed lanes need the staging time again
            self.restore_t = ctx.t + (p["setup_s"] if self.cf_on else 0.0)
            ctx.record(self.id, "cleared", out=len(self.arrivals))

    def _sample(self, ctx: EventContext) -> None:
        res = ctx.conn.edge.getAllSubscriptionResults()
        dt = self.plan["sample_s"]
        for e in self.plan["watch_edges"]:
            h = res.get(e, {}).get(HALT, 0)
            if h:
                self.halted_vs[e] += h * dt
                if h > self.halted_max.get(e, (0, 0.0))[0]:
                    self.halted_max[e] = (int(h), ctx.t)
        pending = len(self.ids) - len(self.departs)
        due = sum(1 for v in self.plan["vehicles"] if v[2] <= ctx.t and v[0] not in self.departs)
        self.max_backlog = max(self.max_backlog, min(pending, due))

    def finished(self, ctx: EventContext) -> bool:
        if self.plan["reference"]:
            return False
        return self.restore_t is not None and ctx.t >= self.restore_t

    def on_end(self, ctx: EventContext) -> None:
        if not self.restored and ctx.t < self.plan["run_end"]:
            for tls, prog in self.signals.items():
                ctx.conn.trafficlight.setProgram(tls, prog)
            if self.cf_on:
                self._contraflow(ctx, False)
            self.restored = True
        self.summary.update(
            {
                "order_t": self.order_t,
                "vehicles": len(self.ids),
                "departed": len(self.departs),
                "arrived": len(self.arrivals),
                "arrival_times": sorted(self.arrivals.values()),
                "depart_times": sorted(self.departs.values()),
                "halted_vs": dict(self.halted_vs),
                "halted_max": {e: list(v) for e, v in self.halted_max.items()},
                "contraflow_on": self.cf_on,
                "contraflow_lanes_opened": self.cf_lanes_opened,
                "contraflow_lanes_closed": self.cf_lanes_closed,
                "signals_retimed": sorted(self.signals),
                "restored_at": ctx.t if self.restored else None,
                "reroutes": self.reroutes,
                "reroute_errors": self.reroute_errors,
                "add_errors": self.add_errors,
                "max_insertion_backlog": self.max_backlog,
            }
        )


def register_event_classes() -> None:
    """Make build_events() know the evacuation event (in this process)."""
    from sim.events import registry

    registry.EVENT_CLASSES[EVAC_TYPE] = EvacuationEvent


# --- metrics ------------------------------------------------------------------------------------
def clearance(summary: dict[str, Any], run_end: float) -> dict[str, Any]:
    """Time after the order until 50 / 90 / 100 % of the evacuees have left through an exit."""
    n = summary["vehicles"]
    t0 = summary["order_t"]
    arr = sorted(summary["arrival_times"])
    out: dict[str, Any] = {"vehicles": n, "out": len(arr), "out_share": round(len(arr) / n, 4)}
    for q in (50, 90, 100):
        k = math.ceil(n * q / 100)
        out[f"t{q}_s"] = round(arr[k - 1] - t0, 1) if len(arr) >= k else None
    out["horizon_s"] = round(run_end - t0, 1)
    deps = summary["depart_times"]
    out["last_departure_s"] = round(max(deps) - t0, 1) if deps else None
    out["max_insertion_backlog"] = summary["max_insertion_backlog"]
    return out


def effective(c: dict[str, Any], key: str) -> float:
    v = c[key]
    return (
        float(v)
        if v is not None
        else float(value("clearance", "not_cleared_factor")) * c["horizon_s"]
    )


def bottlenecks(
    summary: dict[str, Any],
    idx: NetIndex,
    routes: dict[str, list[str]],
    vehicles: list[list[Any]],
    top: int | None = None,
) -> list[dict[str, Any]]:
    top = top or int(model("top_bottlenecks"))
    use: Counter = Counter()
    for v in vehicles:
        for e in routes[v[1]]:
            use[e] += 1
    n = max(len(vehicles), 1)
    rows = []
    for e, vs in sorted(summary["halted_vs"].items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        edge = idx.edge(e)
        lon, lat = idx.net.convertXY2LonLat(*_mid(edge))
        hmax = summary["halted_max"].get(e, [0, 0])
        rows.append(
            {
                "edge": e,
                "name": edge.getName(),
                "type": edge.getType(),
                "lanes": edge.getLaneNumber(),
                "halted_veh_h": round(vs / 3600, 2),
                "max_halted_veh": hmax[0],
                "max_at_s": hmax[1],
                "planned_evacuee_share": round(use[e] / n, 3),
                "lon": round(lon, 5),
                "lat": round(lat, 5),
            }
        )
    return rows


def background_delay(tripinfo: Path) -> dict[str, float]:
    """Background (non-event) vehicle-hours of time loss + insertion delay from tripinfo
    (with --tripinfo-output.write-unfinished, so vehicles still running count up to the end)."""
    loss = dep = 0.0
    n = 0
    if tripinfo.exists():
        for _, el in ET.iterparse(tripinfo, events=("end",)):
            if el.tag == "tripinfo":
                if not str(el.get("id")).startswith(EVENT_VEHICLE_PREFIX):
                    loss += float(el.get("timeLoss", 0))
                    dep += float(el.get("departDelay", 0) or 0)
                    n += 1
                el.clear()
    return {
        "vehicles": n,
        "time_loss_veh_h": round(loss / 3600, 3),
        "depart_delay_veh_h": round(dep / 3600, 3),
        "delay_veh_h": round((loss + dep) / 3600, 3),
    }


# --- light simulation (no FCD) ------------------------------------------------------------------
def simulate(spec: dict[str, Any]) -> dict[str, Any]:
    """One window run with light outputs (tripinfo incl. unfinished, statistics, log). Same SUMO
    arguments and event dispatch order as sim.scenarios.simulate.run_window_sim, so the dynamics
    are identical; per-edge halting numbers are subscribed for the bottleneck measure."""
    from sim.events.registry import build_events
    from sim.runner import assert_tier_options, flatten
    from sim.scenarios.simulate import _rel, start_sumo

    register_event_classes()
    out = Path(spec["run_dir"])
    out.mkdir(parents=True, exist_ok=True)
    log = out / "sumo.stdout.log"
    log.unlink(missing_ok=True)
    begin, end = float(spec["begin"]), float(spec["end"])
    adds = [*spec.get("extra_additionals", []), spec["vtypes_add"]]
    args = [
        "-n", _rel(spec["net"]),
        "-r", _rel(spec["demand"]),
        "--additional-files", ",".join(_rel(a) for a in adds),
        "--begin", str(begin),
        "--end", str(end),
        "--seed", str(spec["seed"]),
        "--tripinfo-output", _rel(out / "tripinfo.xml"),
        "--statistic-output", _rel(out / "stats.xml"),
        "--log", _rel(out / "sumo.log"),
        *flatten(spec["sumo_common"]),
        *flatten(spec["tier_options"]),
    ]  # fmt: skip
    assert_tier_options(
        "B", args, list(map(Path, spec.get("extra_additionals", []))), spec["micro_cfg"]
    )
    t0 = time.perf_counter()
    conn = start_sumo([sumo_bin("sumo"), *args], log, label=f"{out.name}-{time.time_ns()}")
    ctx = EventContext(conn=conn, tier="B", t=begin, distributions=frozenset(spec["distributions"]))
    events = build_events(spec["plans"])
    for e in conn.edge.getIDList():
        if not e.startswith(":"):
            conn.edge.subscribe(e, [HALT])
    conn.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS])
    try:
        for ev in events:
            ev.dispatch(ctx)
        while ctx.t < end:
            conn.simulationStep()
            ctx.t = conn.simulation.getTime()
            res = conn.simulation.getSubscriptionResults()
            ctx.departed = tuple(res.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
            ctx.arrived = tuple(res.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
            ctx.closures.on_step()
            for ev in events:
                ev.dispatch(ctx)
        for ev in events:
            ev.close(ctx, horizon=True)
    finally:
        conn.close()
    return _collect(out, ctx, events, time.perf_counter() - t0)


def _collect(out: Path, ctx: EventContext, events: list[Event], wall: float) -> dict[str, Any]:
    from sim.scenarios.outputs import teleports_from_log

    tel = teleports_from_log(out / "sumo.log")
    return {
        "run_dir": str(out),
        "event_summaries": {ev.id: ev.summary for ev in events},
        "event_log": ctx.log,
        "background": background_delay(out / "tripinfo.xml"),
        "teleports": len(tel),
        "teleports_evacuees": sum(1 for x in tel if x["vehicle"].startswith(EVENT_VEHICLE_PREFIX)),
        "reroutes": {"rerouted": ctx.closures.rerouted, "failed": ctx.closures.reroute_failures},
        "sim_wall_s": round(wall, 2),
    }


def full_sim(spec: dict[str, Any]) -> dict[str, Any]:
    """M5 window run (FCD, queues, KPIs) with the evacuation event registered in this worker."""
    from sim.scenarios.simulate import run_window_sim

    register_event_classes()
    res = run_window_sim(spec)
    res["background"] = background_delay(Path(spec["run_dir"]) / "tripinfo.xml")
    tel = res.get("teleport_events", [])
    res["teleports"] = len(tel)
    res["teleports_evacuees"] = sum(1 for x in tel if x["vehicle"].startswith(EVENT_VEHICLE_PREFIX))
    return res


def execute(
    fn: Any, specs: list[dict[str, Any]], workers: int | None = None
) -> list[dict[str, Any]]:
    if len(specs) == 1 or workers == 1:
        return [fn(s) for s in specs]
    n = min(len(specs), workers or len(specs))
    with ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn")) as ex:
        return list(ex.map(fn, specs))


# --- situation: everything a run of the scenario needs ------------------------------------------
class Situation(BaseModel):
    """Inputs shared by the reference, the evacuation runs and every strategist candidate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario: Scenario
    spec: EvacSpec
    window: str
    seed: int
    begin: float
    end: float
    window_net: Path
    net: Path
    demand_src: Path
    additionals: list[Path]
    evac_net: dict[str, Any]
    analysis: dict[str, Any]
    other_plans: list[dict[str, Any]]
    other_ids: list[str]
    tls_nodes: dict[str, str]
    vtypes: dict[str, float]
    run_cfg: dict[str, Any]
    lib: Any
    mix: dict[str, float]

    def plan(self, **strategy: Any) -> dict[str, Any]:
        spec = self.spec.model_copy(update=strategy)
        return resolve(
            spec, self.analysis, self.seed, self.begin, self.vtypes, self.tls_nodes, self.end
        )

    def strategy(self) -> dict[str, Any]:
        s = self.spec
        return {
            "phasing": s.phasing,
            "exit_assignment": s.exit_assignment or str(value("assignment", "default")),
            "contraflow": list(s.contraflow),
            "signal_plan": s.signal_plan,
        }


def situation(ref: str | Path, window: str | None = None, seed: int = 1,
              end: float | None = None) -> Situation:  # fmt: skip
    from sim.events.registry import resolve_events
    from sim.runner import runner_config
    from sim.scenarios.run import window_inputs
    from sim.vtypes.loader import load_library, resolve_mix

    scen, spec = load(ref)
    w = window or scen.window
    net, demand_src, extra_adds = window_inputs(w)
    idx0 = NetIndex(net)
    ana = analyse(spec, idx0, seed)
    evac = build_evac_net(w, net, demand_src, extra_adds, ana["corridors"], idx0)
    idx = NetIndex(evac["net"]) if evac["net"] != net else idx0
    lib = load_library()
    mix = resolve_mix(scen.vtype_mix, lib)
    others, other_ids = resolve_events(without_evacuation(scen), idx, lib)
    return Situation(
        scenario=scen,
        spec=spec,
        window=w,
        seed=seed,
        begin=float(scen.begin),
        end=float(end if end is not None else scen.end),
        window_net=net,
        net=evac["net"],
        demand_src=demand_src,
        additionals=list(evac["additionals"]),
        evac_net={
            k: (rel(v) if isinstance(v, Path) else v) for k, v in evac.items() if k != "additionals"
        },  # fmt: skip
        analysis=ana,
        other_plans=others,
        other_ids=other_ids,
        tls_nodes=tls_nodes(idx),
        vtypes=evacuee_types(mix, lib),
        run_cfg=runner_config(),
        lib=lib,
        mix=mix,
    )


def prepare_inputs(sit: Situation, out: Path) -> dict[str, Any]:
    """vTypes and mixed demand in `out`; returns the spec fields shared by all runs."""
    from sim.vtypes.loader import apply_mix, write_vtypes_additional

    out.mkdir(parents=True, exist_ok=True)
    vt = write_vtypes_additional(out / "vtypes.add.xml", sit.mix, "B", sit.lib)
    demand = out / "demand.rou.xml"
    counts = apply_mix(sit.demand_src, demand, sit.lib.distribution_id)
    settings = load_yaml(SCENARIO_DIR / "run.yaml")
    cfg = sit.run_cfg
    return {
        "net": str(sit.net),
        "demand": str(demand),
        "vtypes_add": str(vt),
        "begin": sit.begin,
        "end": sit.end,
        "seed": sit.seed,
        "sumo_common": cfg["sumo_common"],
        "tier_options": cfg["tier_B"]["options"]
        + settings["sumo_options"]
        + ["--tripinfo-output.write-unfinished"],
        "extra_additionals": [str(p) for p in sit.additionals],
        "micro_cfg": cfg,
        "edgedata_freq": cfg["smoke"]["edgedata_freq_s"],
        "distributions": [sit.lib.distribution_id],
        "demand_counts": counts,
    }


def ordered_plans(sit: Situation, evac_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Scenario order: the evacuation plan takes the place of the evacuation event."""
    out: list[dict[str, Any]] = []
    others = iter(sit.other_plans)
    for e in sit.scenario.events:
        out.append(evac_plan if isinstance(e, Evacuation) else next(others))
    return out


def light_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """The plan without per-vehicle data (for reports)."""
    drop = {"routes", "vehicles", "moves", "watch_edges"}
    return {k: v for k, v in plan.items() if k not in drop}


def summarize_run(sit: Situation, plan: dict[str, Any], res: dict[str, Any],
                  idx: NetIndex) -> dict[str, Any]:  # fmt: skip
    summ = res["event_summaries"][plan["id"]]
    return {
        "clearance": clearance(summ, sit.end),
        "bottlenecks": bottlenecks(summ, idx, plan["routes"], plan["vehicles"]),
        "background": res["background"],
        "teleports": res["teleports"],
        "teleports_evacuees": res.get("teleports_evacuees"),
        "contraflow_lanes_opened": summ["contraflow_lanes_opened"],
        "contraflow_lanes_closed": summ["contraflow_lanes_closed"],
        "signals_retimed": summ["signals_retimed"],
        "reroutes": summ["reroutes"],
        "add_errors": summ["add_errors"],
        "sim_wall_s": res["sim_wall_s"],
    }


# --- run (demo command) -------------------------------------------------------------------------
def run(ref: str | Path, window: str | None = None, seed: int = 1, fcd: bool = True,
        runs_dir: Path = RUNS_DIR, end: float | None = None, quiet: bool = False,
        parallel: bool = True) -> dict[str, Any]:  # fmt: skip
    """Reference (scenario without the evacuation) and the evacuation as written, in parallel."""
    from sim.scenarios import kpis as K

    t_all = time.perf_counter()
    sit = situation(ref, window, seed, end)
    plan = sit.plan()
    ref_plan = reference_plan(plan)
    key = config_hash(
        {
            "scenario": sit.scenario.model_dump(mode="json"),
            "window": sit.window,
            "seed": seed,
            "end": sit.end,
            "net": content_hash(sit.net),
            "settings": _tree(),
            "fcd": fcd,
        }
    )
    run_id = f"{sit.scenario.id}-{sit.window}-s{seed}-{key[:8]}"
    out = runs_dir / run_id
    if out.exists():
        shutil.rmtree(out)
    common = prepare_inputs(sit, out)
    counts = common.pop("demand_counts")
    specs = [
        {**common, "run_dir": str(out / "reference"), "plans": ordered_plans(sit, ref_plan)},
        {**common, "run_dir": str(out / "evacuation"), "plans": ordered_plans(sit, plan)},
    ]
    fn = full_sim if fcd else simulate
    ref_res, evac_res = execute(fn, specs, workers=None if parallel else 1)
    idx = NetIndex(sit.net)
    evac = summarize_run(sit, plan, evac_res, idx)
    report: dict[str, Any] = {
        "scenario": sit.scenario.id,
        "title": sit.scenario.label,
        "label": SYNTHETIC_LABEL,
        "fictional": sit.scenario.fictional,
        "window": sit.window,
        "daytype": sit.scenario.daytype,
        "seed": seed,
        "begin": sit.begin,
        "end": sit.end,
        "reference_definition": "same demand, vType mix, seed, network (incl. closed contraflow "
        "lanes) and other events; no evacuation",
        "evacuation": {
            **light_plan(plan),
            "corridors": [
                {k: v for k, v in c.items() if k != "edges"} | {"edges": len(c["edges"])}
                for c in plan["corridors"]
            ],
            "persons": round(len(plan["vehicles"]) * float(value("event", "occupancy"))),
            "origin_edges": sit.analysis["origin_edges"],
        },
        "result": evac,
        "background_added_veh_h": round(
            evac_res["background"]["delay_veh_h"] - ref_res["background"]["delay_veh_h"], 3
        ),
        "reference": {
            "background": ref_res["background"],
            "teleports": ref_res["teleports"]
            if "teleports" in ref_res
            else len(ref_res.get("teleport_events", [])),
        },
        "evac_net": sit.evac_net,
        "event_log": evac_res["event_log"],
        "other_events": [light_plan(p) for p in sit.other_plans],
        "assumption_ids": list(dict.fromkeys([*plan["assumption_ids"], *sit.other_ids])),
    }
    if fcd:
        report["window_kpis"] = {
            "reference": K.window_kpis(ref_res),
            "evacuation": K.window_kpis(evac_res),
        }
        report["result"]["teleports"] = len(evac_res.get("teleport_events", []))
        report["result"]["teleports_evacuees"] = sum(
            1 for x in evac_res.get("teleport_events", [])
            if x["vehicle"].startswith(EVENT_VEHICLE_PREFIX)
        )  # fmt: skip
        report["reference"]["teleports"] = len(ref_res.get("teleport_events", []))
    meta = {
        "run_id": run_id,
        "label": SYNTHETIC_LABEL,
        "kind": "evacuation",
        "scenario": sit.scenario.id,
        "fictional": sit.scenario.fictional,
        "tier": "B",
        "mode": sit.run_cfg["tier_B"]["mode"],
        "window": sit.window,
        "seed": seed,
        "config_hash": key,
        "network": rel(sit.net),
        "network_hash": content_hash(sit.net),
        "window_network": rel(sit.window_net),
        "additionals": {rel(p): content_hash(p) for p in sit.additionals},
        "demand_source": rel(sit.demand_src),
        "population_hash": content_hash(Path(common["demand"])),
        "demand_counts": counts,
        "vtype_mix": sit.mix,
        "sumo_version": sumo_version(),
        "fcd": fcd,
        "wall_s": {
            "reference_sim": ref_res["sim_wall_s"],
            "evacuation_sim": evac_res["sim_wall_s"],
            "total": round(time.perf_counter() - t_all, 2),
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (out / "evacuation_report.json").write_text(json.dumps(report, indent=2, default=str))
    md = render_md(report, meta)
    (out / "evacuation_report.md").write_text(md)
    stable = runs_dir / (sit.scenario.id if sit.window == sit.scenario.window
                         else f"{sit.scenario.id}-{sit.window}")  # fmt: skip
    stable.mkdir(parents=True, exist_ok=True)
    for name in ("meta.json", "evacuation_report.json", "evacuation_report.md"):
        shutil.copy2(out / name, stable / name)
    (stable / "RUN_DIR").write_text(rel(out) + "\n")
    if not quiet:
        print(md)
    return {"out": out, "stable": stable, "report": report, "meta": meta}


def _f(v: Any, unit: str = " s") -> str:
    if v is None:
        return "not reached"
    return f"{v:,.0f}{unit}" if isinstance(v, int | float) else str(v)


def render_md(r: dict[str, Any], meta: dict[str, Any]) -> str:
    ev = r["evacuation"]
    c = r["result"]["clearance"]
    lines = [
        f"# Evacuation report: {r['scenario']} ({r['window']} window)",
        "",
        f"**{r['label']}.** Fictional scenario (PROJECT.md section 11). Seed {r['seed']}, "
        f"SUMO {meta['sumo_version']}, run `{meta['run_id']}`.",
        "",
        f"{r['title']}",
        "",
        "## Evacuation",
        "",
        f"- Order at {ev['order_t']:.0f} s; {len(ev['assigned']) and sum(ev['assigned'].values())} "
        f"vehicles (~{ev['persons']:,} persons at A-evac-001) from {ev['origin_edges']} zone edges "
        f"({ev['zone_area_km2']} km2); release over {ev['release_s']:.0f} s, phasing "
        f"`{ev['phasing']}`, exit assignment `{ev['exit_assignment']}`, signal plan "
        f"`{ev['signal_plan']}`, contraflow {ev['contraflow'] or 'none'}.",
        "- Exits: "
        + "; ".join(
            f"`{x['edge']}` {x['name'] or '(unnamed)'} ({x['lanes']} lanes): "
            f"{ev['assigned'].get(x['edge'], 0)} assigned"
            for x in ev["exits"]
        ),
        "- Contraflow corridors available: "
        + (
            "; ".join(
                f"{k['id']} towards `{k['exit']}` ({k['name']}, {k['length_m']:.0f} m, "
                f"{k['lane_km']} lane-km)"
                for k in ev["corridors"]
            )
            or "none"
        ),  # fmt: skip
        "",
        "## Clearance (time after the order)",
        "",
        "| 50 % out | 90 % out | 100 % out | out by run end | last departure "
        "| max insertion backlog |",
        "|---|---|---|---|---|---|",
        f"| {_f(c['t50_s'])} | {_f(c['t90_s'])} | {_f(c['t100_s'])} | {c['out']} / "
        f"{c['vehicles']} | {_f(c['last_departure_s'])} | {c['max_insertion_backlog']} |",
        "",
        "## Bottleneck edges (halted vehicle-hours on evacuation routes)",
        "",
        "| edge | name | type | lanes | halted veh-h | max halted | at s | planned evacuee share |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in r["result"]["bottlenecks"]:
        lines.append(
            f"| `{b['edge']}` | {b['name'] or ''} | {b['type']} | {b['lanes']} | "
            f"{b['halted_veh_h']} | {b['max_halted_veh']} | {b['max_at_s']:.0f} | "
            f"{b['planned_evacuee_share']} |"
        )
    bg = r["result"]["background"]
    rb = r["reference"]["background"]
    lines += [
        "",
        "## Background traffic",
        "",
        f"- Delay (time loss + insertion delay, unfinished trips included): reference "
        f"{rb['delay_veh_h']} veh-h, with evacuation {bg['delay_veh_h']} veh-h "
        f"({r['background_added_veh_h']:+.2f}).",
        f"- Teleports: reference {r['reference']['teleports']}, evacuation "
        f"{r['result']['teleports']} (evacuees {r['result']['teleports_evacuees']}).",
    ]
    if "window_kpis" in r:
        kr, ke = r["window_kpis"]["reference"], r["window_kpis"]["evacuation"]
        lines += [
            "",
            "## Window KPIs (M5 definitions, background vehicles)",
            "",
            "| KPI | reference | evacuation |",
            "|---|---|---|",
        ]
        for k in ("mean_travel_time_s", "mean_delay_s", "mean_speed_kmh", "vht", "halted_max_veh",
                  "queue_max_m", "teleports"):  # fmt: skip
            lines.append(f"| {k} | {kr.get(k)} | {ke.get(k)} |")
    if r["other_events"]:
        lines += [
            "",
            "Other events: " + ", ".join(f"{p['type']} `{p['id']}`" for p in r["other_events"]),
        ]
    lines += [
        "",
        f"Wall time: reference {meta['wall_s']['reference_sim']} s, evacuation "
        f"{meta['wall_s']['evacuation_sim']} s, total {meta['wall_s']['total']} s.",
        "",
        "Assumptions: " + ", ".join(r["assumption_ids"]),
        "",
    ]
    return "\n".join(lines)


# --- register block in docs/evacuation.md -------------------------------------------------------
BEGIN = (
    "<!-- BEGIN M7 assumptions: generated by `python -m sim.events.evacuation register`, "
    "do not edit -->"
)
END_MARK = "<!-- END M7 assumptions -->"
HEAD = (
    "| id | parameter | value | unit | range | source or assumption | status | used in |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _cell(text: object) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def register_block() -> str:
    rows = []
    for path, p in sorted(registered(), key=lambda kv: int(kv[1].id.rsplit("-", 1)[1])):
        text = p.source or ""
        if p.assumption:
            text = f"{text}; {p.assumption}" if text else p.assumption
        rows.append(
            f"| {p.id} | {_cell(path)} | {_cell(p.value)} | {_cell(p.unit)} | "
            f"{_cell(p.range_text())} | {_cell(text)} | {p.status} | {rel(SETTINGS_FILE)} |"
        )
    return f"{BEGIN}\n{HEAD}" + "\n".join(rows) + f"\n{END_MARK}"


def render_register(text: str) -> str:
    if BEGIN in text and END_MARK in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END_MARK, 1)
        return pre + register_block() + post
    return text.rstrip("\n") + "\n\n" + register_block() + "\n"


def register_current(doc: Path = DOC) -> bool:
    return doc.exists() and render_register(doc.read_text()) == doc.read_text()


# --- CLI ----------------------------------------------------------------------------------------
app = typer.Typer(add_completion=False, help=__doc__)


@app.command("run")
def run_cmd(
    scenario: str = typer.Option(..., "--scenario"),
    window: str | None = typer.Option(None, "--window"),
    seed: int = typer.Option(1, "--seed"),
    fcd: bool = typer.Option(True, "--fcd/--no-fcd", help="M5 outputs incl. FCD Parquet"),
    end: float | None = typer.Option(None, "--end", help="override the scenario end (s)"),
) -> None:
    res = run(scenario, window, seed, fcd=fcd, end=end, quiet=True)
    typer.echo((res["out"] / "evacuation_report.md").read_text())


@app.command("validate")
def validate_cmd(paths: list[Path]) -> None:
    bad = 0
    for p in paths:
        try:
            scen, spec = load(p)
            typer.echo(f"OK   {rel(p)}: {scen.id} ({spec.vehicles} vehicles, window {scen.window})")
        except Exception as exc:  # noqa: BLE001 - report every file
            bad += 1
            typer.echo(f"FAIL {rel(p)}: {exc}")
    raise typer.Exit(code=1 if bad else 0)


@app.command("net")
def net_cmd(
    scenario: str = typer.Option(..., "--scenario"),
    window: str | None = typer.Option(None, "--window"),
    seed: int = typer.Option(1, "--seed"),
) -> None:
    sit = situation(scenario, window, seed)
    typer.echo(json.dumps({"evac_net": sit.evac_net, "corridors": sit.analysis["corridors"]},
                          indent=2, default=str))  # fmt: skip


@app.command("register")
def register_cmd(check: bool = typer.Option(False, "--check")) -> None:
    if check:
        if not register_current():
            typer.echo("docs/evacuation.md M7 assumptions are out of date: "
                       "python -m sim.events.evacuation register")  # fmt: skip
            raise typer.Exit(code=1)
        typer.echo(f"current: {len(registered())} M7 assumptions in docs/evacuation.md")
        return
    DOC.write_text(render_register(DOC.read_text() if DOC.exists() else "# Evacuation (M7)\n"))
    typer.echo(f"wrote {len(registered())} M7 assumptions to docs/evacuation.md")


if __name__ == "__main__":
    app()
