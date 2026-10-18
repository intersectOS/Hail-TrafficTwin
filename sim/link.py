"""Tier link: Tier B windows with service roads, Tier A exit times, cutRoutes and the flow check.

    python -m sim.link window --name tahlia                       # cut + service-road graft
    python -m sim.link tier-a --routes runs/source-smoke-A/routes.rou.xml   # meso exit-time run
    python -m sim.link cut --window tahlia --tier-a runs/tierA-exit-<hash>/ [--time-shift 0]
    python -m sim.link check --window tahlia --tier-a runs/tierA-exit-<hash>/ --seed 1

Window edge ids equal Tier A ids (the window is cut from the city net); service / living-street
roads from OSM are grafted by splitting the city edges they attach to. A split edge keeps its id on
the first part and continues as `<id>.s1`, `<id>.s2`, ...; `<w>.edgemap.json` maps each split city
edge to its window edge sequence so cut Tier A routes are rewritten exactly (B-D-001..003).
All results: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sumolib
import typer
from sumolib import geomhelper

from sim.common import (
    REPO_ROOT,
    config_hash,
    content_hash,
    file_hash,
    load_yaml,
    python_tool_cmd,
    run_cmd,
    sumo_bin,
    sumo_home,
    sumo_version,
)
from sim.common import rel as _resolved_rel
from sim.network.build_window import boundary_arg, cut_window, load_window
from sim.network.netinfo import net_stats

LINK_CONFIG = REPO_ROOT / "sim" / "config" / "link.yaml"
RUNS_DIR = REPO_ROOT / "runs"
LOGS_DIR = REPO_ROOT / "logs"
TLS_TYPES = ("traffic_light", "traffic_light_unregulated", "traffic_light_right_on_red")
SERVICE_PREFIX = "svc_"
SPLIT_NODE_PREFIX = "svcj_"


def rel(path: Path) -> str:
    """Repo-relative path, also for paths under symlinked dirs (data/jeddah -> main checkout).

    sim.common.rel resolves symlinks first, which turns data/jeddah/... into an absolute path
    outside this checkout; compare the unresolved absolute path before falling back to it.
    """
    absolute = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        return str(absolute.relative_to(REPO_ROOT))
    except ValueError:
        return _resolved_rel(path)


def link_config() -> dict[str, Any]:
    return load_yaml(LINK_CONFIG)


def expand(path: str) -> str:
    return path.replace("${SUMO_HOME}", str(sumo_home()))


def flat(options: list[Any]) -> list[str]:
    from sim.runner import flatten

    return flatten(options)


def window_dir(cfg: dict[str, Any]) -> Path:
    return REPO_ROOT / cfg.get("out_dir", f"data/windows/{cfg['name']}")


def geh(model: float, count: float) -> float:
    """GEH statistic for hourly flows (veh/h); 0 when both are 0."""
    total = model + count
    if total <= 0:
        return 0.0
    return math.sqrt(2.0 * (model - count) ** 2 / total)


# ------------------------------------------------------------------------------------------------
# window build: cut + service-road graft
# ------------------------------------------------------------------------------------------------


@dataclass
class Attach:
    """Where a service-road node joins the city network."""

    node: str  # node id in the grafted net (city junction or new split node)
    x: float
    y: float


@dataclass
class GraftReport:
    service_edges_candidate: int = 0
    service_edges_grafted: int = 0
    service_edges_dropped_unattached: int = 0
    service_edges_dropped_access: int = 0
    service_edges_dropped_loop: int = 0
    attach_nodes: int = 0
    attach_at_junction: int = 0
    attach_unsnapped: int = 0
    split_nodes: int = 0
    split_edges: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def osm_way_tags(osm_file: Path, keys: set[str]) -> dict[str, dict[str, str]]:
    """Way id -> selected tags, streamed from an OSM XML (.osm or .osm.gz) file."""
    opener = gzip.open if str(osm_file).endswith(".gz") else open
    tags: dict[str, dict[str, str]] = {}
    with opener(osm_file, "rb") as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "way":
                found = {t.get("k", ""): t.get("v", "") for t in elem.iter("tag")}
                sel = {k: v for k, v in found.items() if k in keys}
                if sel:
                    tags[elem.get("id", "")] = sel
                elem.clear()
            elif elem.tag in ("node", "relation"):
                elem.clear()
    return tags


def edge_orig_ids(net: Path) -> dict[str, list[str]]:
    """Edge id -> OSM way ids (lane param origId), streamed."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for event, elem in ET.iterparse(net, events=("start", "end")):
        if event == "start" and elem.tag == "edge":
            current = elem.get("id") if elem.get("function") != "internal" else None
        elif event == "end" and elem.tag == "param" and current and current not in out:
            if elem.get("key") == "origId":
                out[current] = (elem.get("value") or "").split()
        elif event == "end" and elem.tag == "edge":
            current = None
            elem.clear()
    return out


def write_type_overlay(graft: dict[str, Any], path: Path) -> None:
    root = ET.Element("types")
    for tid, attrs in sorted(graft.get("type_overrides", {}).items()):
        ET.SubElement(root, "type", id=tid, **{k: str(v) for k, v in attrs.items()})
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def osm_extract(cfg: dict[str, Any], pbf: Path, out: Path, log: Path | None) -> None:
    if "bbox" in cfg:
        bbox = cfg["bbox"]
    else:
        lons = [p[0] for p in cfg["polygon"]]
        lats = [p[1] for p in cfg["polygon"]]
        bbox = [min(lons), min(lats), max(lons), max(lats)]
    cmd = ["osmium", "extract", "-b", ",".join(str(v) for v in bbox), "-s", "complete_ways"]
    run_cmd([*cmd, str(pbf), "-o", str(out), "--overwrite"], log=log)


def _heading(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def _turn(in_shape: list[tuple[float, float]], out_shape: list[tuple[float, float]]) -> float:
    """Signed turn angle (deg, + = left) from the end of in_shape to the start of out_shape."""
    h_in = _heading(in_shape[-2], in_shape[-1])
    h_out = _heading(out_shape[0], out_shape[1])
    return (h_out - h_in + 180.0) % 360.0 - 180.0


def _reverse_edge(edge: sumolib.net.edge.Edge) -> sumolib.net.edge.Edge | None:
    cands = [e for e in edge.getToNode().getOutgoing() if e.getToNode() == edge.getFromNode()]
    if not cands:
        return None
    eid = edge.getID()
    want = eid[1:] if eid.startswith("-") else f"-{eid}"
    for e in cands:
        if e.getID() == want:
            return e
    return sorted(cands, key=lambda e: e.getID())[0]


def _passenger_lanes(edge: sumolib.net.edge.Edge) -> list[int]:
    return [ln.getIndex() for ln in edge.getLanes() if ln.allows("passenger")]


def graft_service_roads(
    cut_net: Path,
    osm_file: Path,
    cfg: dict[str, Any],
    out_net: Path,
    work: Path,
    link_cfg: dict[str, Any],
    log: Path | None = None,
) -> tuple[dict[str, list[str]], GraftReport]:
    """Graft OSM service roads onto a cut window net. Returns (edgemap, report)."""
    graft = link_cfg["graft"]
    work.mkdir(parents=True, exist_ok=True)
    report = GraftReport()
    tol = float(graft["snap_tolerance_m"])
    jsnap = float(graft["junction_snap_m"])
    service_types = set(graft["service_types"])

    # (b) window OSM import with service roads
    overlay = work / "service.typ.xml"
    write_type_overlay(graft, overlay)
    osm_net = work / "osm_window.net.xml"
    type_files = [expand(t) for t in graft["osm_type_files"]] + [str(overlay)]
    run_cmd(
        [
            sumo_bin("netconvert"),
            "--osm-files",
            str(osm_file),
            "--type-files",
            ",".join(type_files),
            "--keep-edges.in-geo-boundary",
            boundary_arg(cfg),
            *flat(graft["osm_netconvert_options"]),
            "--no-warnings",
            "-o",
            str(osm_net),
        ],
        log=log,
    )
    wnet = sumolib.net.readNet(str(osm_net))
    cnet = sumolib.net.readNet(str(cut_net))
    keys = set(graft["access_keys"])
    way_tags = osm_way_tags(osm_file, keys)
    orig = edge_orig_ids(osm_net)
    excluded = set(graft["exclude_access"])

    service: list[sumolib.net.edge.Edge] = []
    for e in sorted(wnet.getEdges(), key=lambda e: e.getID()):
        if e.getType() not in service_types or not _passenger_lanes(e):
            continue
        ways = orig.get(e.getID()) or [e.getID().lstrip("-").split("#")[0]]
        if any(way_tags.get(w, {}).get(k) in excluded for w in ways for k in keys):
            report.service_edges_dropped_access += 1
            continue
        service.append(e)
    report.service_edges_candidate = len(service) + report.service_edges_dropped_access
    service_ids = {e.getID() for e in service}

    def to_cut(x: float, y: float) -> tuple[float, float]:
        lon, lat = wnet.convertXY2LonLat(x, y)
        return cnet.convertLonLat2XY(lon, lat)

    snodes: dict[str, sumolib.net.node.Node] = {}
    for e in service:
        snodes[e.getFromNode().getID()] = e.getFromNode()
        snodes[e.getToNode().getID()] = e.getToNode()

    # (c) snap attachment nodes to the nearest passenger city edge
    snaps: dict[str, tuple[str, float, tuple[float, float]]] = {}  # wnode -> (edge, pos, point)
    attach: dict[str, Attach] = {}
    for nid in sorted(snodes):
        node = snodes[nid]
        incident = node.getIncoming() + node.getOutgoing()
        if all(e.getID() in service_ids for e in incident):
            continue  # internal service node or dead end
        x, y = to_cut(*node.getCoord())
        near = [
            (d, e.getID(), e)
            for e, d in cnet.getNeighboringEdges(x, y, tol)
            if e.getFunction() != "internal" and _passenger_lanes(e)
        ]
        if not near:
            report.attach_unsnapped += 1
            continue
        _, _, edge = min(near, key=lambda t: (t[0], t[1]))
        raw = edge.getRawShape()
        length = geomhelper.polyLength(raw)
        pos, _ = geomhelper.polygonOffsetAndDistanceToPoint((x, y), raw)
        ends = [(pos, edge.getFromNode()), (length - pos, edge.getToNode())]
        jnode = None
        for dist, cand in sorted(ends, key=lambda t: t[0]):
            if dist <= jsnap and cand.getType() not in TLS_TYPES:
                jnode = cand
                break
        if jnode is not None:
            jx, jy = jnode.getCoord()
            attach[nid] = Attach(jnode.getID(), jx, jy)
            report.attach_at_junction += 1
            continue
        if length < 2 * jsnap:
            report.attach_unsnapped += 1
            continue
        pos = min(max(pos, jsnap), length - jsnap)
        snaps[nid] = (edge.getID(), pos, geomhelper.positionAtShapeOffset(raw, pos))

    # group split points per road (an edge and its reverse) and merge close ones
    groups: dict[str, list[tuple[float, str, tuple[float, float]]]] = defaultdict(list)
    for nid, (eid, _, point) in snaps.items():
        edge = cnet.getEdge(eid)
        rev = _reverse_edge(edge)
        canon = min(eid, rev.getID()) if rev is not None else eid
        cedge = cnet.getEdge(canon)
        cpos, _ = geomhelper.polygonOffsetAndDistanceToPoint(point, cedge.getRawShape())
        groups[canon].append((cpos, nid, point))
    splits: dict[str, list[tuple[float, str]]] = defaultdict(list)  # edge -> [(pos, node id)]
    counter = 0
    for canon in sorted(groups):
        cedge = cnet.getEdge(canon)
        rev = _reverse_edge(cedge)
        last_pos: float | None = None
        last_attach: Attach | None = None
        for cpos, nid, point in sorted(groups[canon]):
            if last_pos is not None and last_attach is not None and cpos - last_pos < jsnap:
                attach[nid] = last_attach
                continue
            counter += 1
            node_id = f"{SPLIT_NODE_PREFIX}{counter}"
            att = Attach(node_id, point[0], point[1])
            ok = True
            pieces: list[tuple[str, float]] = []
            for edge in [cedge] + ([rev] if rev is not None else []):
                raw = edge.getRawShape()
                length = geomhelper.polyLength(raw)
                epos, _ = geomhelper.polygonOffsetAndDistanceToPoint(point, raw)
                if not jsnap <= epos <= length - jsnap:
                    ok = False
                pieces.append((edge.getID(), epos))
            if not ok:
                counter -= 1
                report.attach_unsnapped += 1
                continue
            for eid, epos in pieces:
                splits[eid].append((epos, node_id))
            attach[nid] = att
            last_pos, last_attach = cpos, att
    # drop splits on one edge closer than jsnap to the previous one (cannot form a valid part)
    edgemap: dict[str, list[str]] = {}
    split_root = ET.Element("edges")
    for eid in sorted(splits):
        items = sorted(splits[eid])
        el = ET.SubElement(split_root, "edge", id=eid)
        seq = [eid]
        for k, (epos, node_id) in enumerate(items, start=1):
            ET.SubElement(
                el,
                "split",
                pos=f"{epos:.2f}",
                id=node_id,
                idBefore=seq[-1],
                idAfter=f"{eid}.s{k}",
            )
            seq.append(f"{eid}.s{k}")
        edgemap[eid] = seq
    report.split_nodes = counter
    report.split_edges = len(edgemap)

    split_net = work / "split.net.xml"
    if edgemap:
        split_file = work / "splits.edg.xml"
        ET.indent(split_root)
        ET.ElementTree(split_root).write(split_file, encoding="UTF-8", xml_declaration=True)
        run_cmd(
            [
                sumo_bin("netconvert"),
                "--sumo-net-file",
                str(cut_net),
                "--edge-files",
                str(split_file),
                "--output.street-names",
                "--output.original-names",
                "--no-warnings",
                "-o",
                str(split_net),
            ],
            log=log,
        )
    else:
        shutil.copyfile(cut_net, split_net)

    # service subgraph after mapping; keep components with at least one attachment
    def mapped(nid: str) -> str:
        return attach[nid].node if nid in attach else f"{SERVICE_PREFIX}{nid}"

    adj: dict[str, set[str]] = defaultdict(set)
    kept: list[sumolib.net.edge.Edge] = []
    for e in service:
        a, b = mapped(e.getFromNode().getID()), mapped(e.getToNode().getID())
        if a == b:
            report.service_edges_dropped_loop += 1
            continue
        kept.append(e)
        adj[a].add(b)
        adj[b].add(a)
    attach_ids = {att.node for att in attach.values()}
    good: set[str] = set()
    seen: set[str] = set()
    for start in sorted(adj):
        if start in seen:
            continue
        comp = {start}
        queue = deque([start])
        while queue:
            n = queue.popleft()
            for m in adj[n]:
                if m not in comp:
                    comp.add(m)
                    queue.append(m)
        seen |= comp
        if comp & attach_ids:
            good |= comp
    graft_edges = [
        e
        for e in kept
        if mapped(e.getFromNode().getID()) in good and mapped(e.getToNode().getID()) in good
    ]
    report.service_edges_dropped_unattached = len(kept) - len(graft_edges)
    report.service_edges_grafted = len(graft_edges)
    report.attach_nodes = len({mapped(n) for n in attach} & good)

    # plain roundtrip of the split net + service nodes / edges / connections
    plain = work / "plain"
    plain.mkdir(exist_ok=True)
    prefix = plain / "p"
    run_cmd(
        [
            sumo_bin("netconvert"),
            "--sumo-net-file",
            str(split_net),
            "--plain-output-prefix",
            str(prefix),
            "--no-warnings",
        ],
        log=log,
    )
    snet = sumolib.net.readNet(str(split_net))
    nod_root = ET.Element("nodes")
    node_xy: dict[str, tuple[float, float]] = {}
    for nid in sorted(snodes):
        m = mapped(nid)
        if m not in good:
            continue
        if nid in attach:
            if snet.hasNode(m):
                node_xy[m] = snet.getNode(m).getCoord()
            continue
        x, y = to_cut(*snodes[nid].getCoord())
        node_xy[m] = (x, y)
        ET.SubElement(nod_root, "node", id=m, x=f"{x:.2f}", y=f"{y:.2f}", type="priority")
    edg_root = ET.Element("edges")
    out_by_node: dict[str, list[tuple[str, list[tuple[float, float]]]]] = defaultdict(list)
    for e in graft_edges:
        a, b = mapped(e.getFromNode().getID()), mapped(e.getToNode().getID())
        shape = [to_cut(*p) for p in e.getRawShape()]
        shape[0], shape[-1] = node_xy[a], node_xy[b]
        lane0 = e.getLanes()[0]
        attrs = {
            "id": f"{SERVICE_PREFIX}{e.getID()}",
            "from": a,
            "to": b,
            "type": e.getType(),
            "numLanes": str(e.getLaneNumber()),
            "speed": f"{max(ln.getSpeed() for ln in e.getLanes()):.2f}",
            "allow": " ".join(sorted(lane0.getPermissions())),
            "shape": " ".join(f"{x:.2f},{y:.2f}" for x, y in shape),
        }
        if e.getName():
            attrs["name"] = e.getName()
        ET.SubElement(edg_root, "edge", **attrs)
        out_by_node[a].append((attrs["id"], shape))
    con_root = ET.Element("connections")
    for node_id in sorted(attach_ids & good):
        if not snet.hasNode(node_id):
            continue
        for inc in sorted(snet.getNode(node_id).getIncoming(), key=lambda e: e.getID()):
            lanes = _passenger_lanes(inc)
            if not lanes or inc.getFunction() == "internal":
                continue
            in_shape = inc.getRawShape()
            for sid, sshape in out_by_node.get(node_id, []):
                turn = _turn(in_shape, sshape)
                if abs(turn) > 160.0:
                    continue  # no U-turn into the service road
                lane = max(lanes) if turn > 30.0 else min(lanes)
                ET.SubElement(
                    con_root,
                    "connection",
                    **{"from": inc.getID(), "to": sid, "fromLane": str(lane), "toLane": "0"},
                )
    files = {}
    outputs = (("svc.nod.xml", nod_root), ("svc.edg.xml", edg_root), ("svc.con.xml", con_root))
    for name, root in outputs:
        ET.indent(root)
        files[name] = work / name
        ET.ElementTree(root).write(files[name], encoding="UTF-8", xml_declaration=True)
    type_list = [expand(graft["osm_type_files"][0]), str(overlay)]
    if Path(f"{prefix}.typ.xml").exists():
        type_list.append(f"{prefix}.typ.xml")
    cmd = [
        sumo_bin("netconvert"),
        "--node-files",
        f"{prefix}.nod.xml,{files['svc.nod.xml']}",
        "--edge-files",
        f"{prefix}.edg.xml,{files['svc.edg.xml']}",
        "--connection-files",
        f"{prefix}.con.xml,{files['svc.con.xml']}",
        "--type-files",
        ",".join(type_list),
        *flat(graft["graft_netconvert_options"]),
        "--no-warnings",
        "-o",
        str(out_net),
    ]
    if Path(f"{prefix}.tll.xml").exists():
        cmd[cmd.index("--type-files") : cmd.index("--type-files")] = [
            "--tllogic-files",
            f"{prefix}.tll.xml",
        ]
    run_cmd(cmd, log=log)
    return edgemap, report


def validate_window(
    net: Path, cut_net: Path, edgemap: dict[str, list[str]], log: Path | None = None
) -> dict[str, Any]:
    """SUMO load check, service-edge reachability, edgemap and connection preservation."""
    sumo_log = net.with_suffix(".load.log")
    sumo_log.unlink(missing_ok=True)
    run_cmd(
        [sumo_bin("sumo"), "-n", str(net), "--end", "1", "--no-step-log", "--log", str(sumo_log)],
        log=log,
    )
    load_errors = [ln for ln in sumo_log.read_text().splitlines() if ln.startswith("Error")]
    wnet = sumolib.net.readNet(str(net))
    cnet = sumolib.net.readNet(str(cut_net))

    def succ(e: sumolib.net.edge.Edge) -> list[sumolib.net.edge.Edge]:
        return [
            to
            for to, conns in e.getOutgoing().items()
            if any(
                c.getFromLane().allows("passenger") and c.getToLane().allows("passenger")
                for c in conns
            )
        ]

    edges = [e for e in wnet.getEdges() if e.getFunction() != "internal"]
    fwd: dict[str, list[str]] = {e.getID(): [t.getID() for t in succ(e)] for e in edges}
    bwd: dict[str, list[str]] = defaultdict(list)
    for a, outs in fwd.items():
        for b in outs:
            bwd[b].append(a)
    main = {e.getID() for e in edges if not e.getID().startswith(SERVICE_PREFIX)}
    svc = {e.getID() for e in edges if e.getID().startswith(SERVICE_PREFIX)}

    def reach(graph: dict[str, list[str]]) -> set[str]:
        seen = set(main)
        queue = deque(main)
        while queue:
            for n in graph.get(queue.popleft(), []):
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        return seen

    from_main, to_main = reach(fwd) & svc, reach(bwd) & svc
    broken = [
        city
        for city, seq in edgemap.items()
        if any(b not in fwd.get(a, []) for a, b in zip(seq, seq[1:], strict=False))
        or any(not wnet.hasEdge(x) for x in seq)
    ]
    # untouched city edges: same edge-level connections as in the cut net
    touched_nodes = {
        n.getID()
        for n in wnet.getNodes()
        if any(e.getID().startswith(SERVICE_PREFIX) for e in n.getIncoming() + n.getOutgoing())
    }
    changed = 0
    compared = 0
    for e in cnet.getEdges():
        eid = e.getID()
        if eid in edgemap or e.getToNode().getID() in touched_nodes or not wnet.hasEdge(eid):
            continue
        compared += 1
        before = {t.getID() for t in e.getOutgoing()}
        after = {t.getID() for t in wnet.getEdge(eid).getOutgoing()}
        # successors that were split keep their first part id, so sets compare directly
        if before != after:
            changed += 1
    missing = sorted({e.getID() for e in cnet.getEdges()} - {e.getID() for e in edges})
    return {
        "sumo_load_ok": not load_errors,
        "sumo_load_errors": load_errors[:10],
        "service_edges": len(svc),
        "service_reachable_from_main": len(from_main),
        "service_can_reach_main": len(to_main),
        "service_connected_both_ways": len(from_main & to_main),
        "edgemap_broken": broken,
        "untouched_edges_compared": compared,
        "untouched_edges_connections_changed": changed,
        "city_edges_missing": missing[:20],
        "city_edges_missing_count": len(missing),
    }


def build_link_window(
    cfg: dict[str, Any],
    city_net: Path,
    osm_source: Path,
    out_dir: Path,
    link_cfg: dict[str, Any] | None = None,
    log: Path | None = None,
) -> dict[str, Any]:
    """(a) cut, (b) OSM window import, (c) graft, (d) validate; write net, edgemap, window.json."""
    link_cfg = link_cfg or link_config()
    name = cfg["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "graft"
    t0 = time.perf_counter()
    cut_net = out_dir / f"{name}.cut.net.xml"
    cut_window(city_net, cfg, cut_net, log=log)
    t_cut = time.perf_counter() - t0
    if str(osm_source).endswith(".pbf"):
        osm_file = out_dir / f"{name}.osm.gz"
        osm_extract(cfg, osm_source, osm_file, log)
    else:
        osm_file = osm_source
    net = out_dir / f"{name}.net.xml"
    edgemap, report = graft_service_roads(cut_net, osm_file, cfg, net, work, link_cfg, log)
    validation = validate_window(net, cut_net, edgemap, log)
    (out_dir / f"{name}.edgemap.json").write_text(json.dumps(edgemap, indent=1, sort_keys=True))
    meta = {
        "window": name,
        "label": link_cfg["label"],
        "definition": cfg,
        "city_net": rel(city_net),
        "city_net_hash": content_hash(city_net),
        "cut_net": rel(cut_net),
        "cut_net_stats": net_stats(cut_net).as_dict(),
        "osm_source": rel(osm_source),
        "osm_source_hash": file_hash(osm_source),
        "osm_window_file": rel(osm_file),
        "graft_config_hash": config_hash(link_cfg["graft"]),
        "sumo_version": sumo_version(),
        "network": net_stats(net).as_dict(),
        "graft": {**report.__dict__},
        "validation": validation,
        "seconds": {"cut": round(t_cut, 1), "total": round(time.perf_counter() - t0, 1)},
    }
    (out_dir / f"{name}.window.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


# ------------------------------------------------------------------------------------------------
# Tier A exit times (B-D-002)
# ------------------------------------------------------------------------------------------------


def clean_exit_routes(vehroutes: Path, out: Path) -> dict[str, int]:
    """Make vehroute output a cutRoutes input: drop output-only attributes; truncate the -1 exit
    times of vehicles still running at the end (their tail was never driven in Tier A)."""
    counts = Counter()
    with out.open("w", encoding="UTF-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        for _, elem in ET.iterparse(vehroutes, events=("end",)):
            if elem.tag == "vType":
                fh.write("    " + ET.tostring(elem, encoding="unicode").strip() + "\n")
                elem.clear()
                continue
            if elem.tag != "vehicle":
                continue
            route = elem.find("route")
            if route is None:
                elem.clear()
                continue
            edges = route.get("edges", "").split()
            exits = route.get("exitTimes", "").split()
            counts["vehicles"] += 1
            if len(exits) != len(edges):
                counts["exit_times_length_mismatch"] += 1
            done = [i for i, t in enumerate(exits) if float(t) >= 0]
            if elem.get("arrival") is None:
                counts["unfinished"] += 1
                if not done:
                    counts["dropped_never_left_first_edge"] += 1
                    elem.clear()
                    continue
                keep = done[-1] + 1
                edges, exits = edges[:keep], exits[:keep]
            elif len(done) != len(exits):
                counts["finished_with_missing_exit_times"] += 1
            attrs = {k: v for k, v in elem.attrib.items() if k not in ("arrival", "routeLength")}
            v = ET.Element("vehicle", attrs)
            ET.SubElement(v, "route", edges=" ".join(edges), exitTimes=" ".join(exits))
            fh.write("    " + ET.tostring(v, encoding="unicode") + "\n")
            counts["written"] += 1
            elem.clear()
        fh.write("</routes>\n")
    return dict(counts)


def edgedata_additional(path: Path, entries: list[dict[str, str]]) -> None:
    root = ET.Element("additional")
    for attrs in entries:
        ET.SubElement(root, "edgeData", **attrs)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def run_tier_a(
    routes: Path,
    out: Path | None,
    seed: int,
    net: Path | None = None,
    link_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from sim.runner import assert_tier_options, parse_statistics, runner_config, summarise

    link_cfg = link_cfg or link_config()
    rcfg = runner_config()
    ta = link_cfg["tier_a"]
    net = net or (REPO_ROOT / link_cfg["city_net"])
    rhash, nhash = content_hash(routes), content_hash(net)
    run_cfg = {
        "kind": "tierA-exit",
        "seed": seed,
        "tier_a": ta,
        "sumo_common": rcfg["sumo_common"],
        "tier_options": rcfg["tier_A"]["options"],
    }
    chash = config_hash(run_cfg)
    out = out or (RUNS_DIR / f"tierA-exit-{rhash[:8]}-{chash[:8]}")
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
    log.unlink(missing_ok=True)
    additional = out / "edgedata.add.xml"
    b, e = ta["edgedata_interval"]
    edgedata_additional(
        additional,
        [
            {
                "id": "ed_bins",
                "freq": str(ta["edgedata_freq_s"]),
                "file": "edgedata.xml",
                "excludeEmpty": "true",
            },
            {
                "id": "ed_hour",
                "begin": str(b),
                "end": str(e),
                "file": "edgedata_hour.xml",
                "excludeEmpty": "true",
            },
        ],
    )
    args = [
        "-n", str(net), "-r", str(routes), "--additional-files", str(additional),
        "--begin", str(ta["begin"]), "--end", str(ta["sim_end"]), "--seed", str(seed),
        "--vehroute-output", str(out / "vehroutes.xml"),
        "--vehroute-output.exit-times", "--vehroute-output.write-unfinished",
        "--statistic-output", str(out / "stats.xml"), "--log", str(out / "sumo.log"),
        *flat(rcfg["sumo_common"]), *flat(rcfg["tier_A"]["options"]),
    ]  # fmt: skip
    assert_tier_options("A", args, [additional], rcfg)
    t0 = time.perf_counter()
    run_cmd([sumo_bin("sumo"), *args], log=log)
    wall = time.perf_counter() - t0
    clean = clean_exit_routes(out / "vehroutes.xml", out / "exit_routes.rou.xml")
    stats = parse_statistics(out / "stats.xml")
    result = summarise(stats, int(ta["sim_end"]) - int(ta["begin"]), wall)
    meta = {
        "run_id": out.name,
        "label": link_cfg["label"],
        "kind": "tierA-exit",
        "tier": "A",
        "mode": rcfg["tier_A"]["mode"],
        "seed": seed,
        "config_hash": chash,
        "network": rel(net),
        "network_hash": nhash,
        "routes": rel(routes),
        "routes_hash": rhash,
        "population_hash": rhash,
        "sumo_version": sumo_version(),
        "sim_begin": ta["begin"],
        "sim_end": ta["sim_end"],
        "edgedata_interval": ta["edgedata_interval"],
        "wall_seconds": round(wall, 2),
        "result": result,
        "teleports": result["teleports"],
        "teleport_share": result["teleport_share"],
        "teleport_ok": result["teleport_share"] < rcfg["smoke"]["teleport_share_max"],
        "exit_routes": {"file": "exit_routes.rou.xml", **clean},
        "sumo_statistics": stats,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


# ------------------------------------------------------------------------------------------------
# cut (cutRoutes.py on the city-cut net, then edgemap rewrite)
# ------------------------------------------------------------------------------------------------


def _depart(elem: ET.Element) -> float:
    return float(elem.get("depart", elem.get("begin", "0")))


def rewrite_routes(
    cut_routes: Path, edgemap: dict[str, list[str]], out: Path, time_shift: float, header: str
) -> dict[str, int]:
    """Map split city edges to window edge sequences, shift and sort by depart."""
    vtypes: list[ET.Element] = []
    vehicles: list[tuple[float, int, ET.Element]] = []
    rewritten = 0
    for idx, (_, elem) in enumerate(ET.iterparse(cut_routes, events=("end",))):
        if elem.tag == "vType":
            vtypes.append(elem)
        elif elem.tag in ("vehicle", "trip", "flow"):
            for route in elem.iter("route"):
                edges = route.get("edges", "").split()
                new = [w for c in edges for w in edgemap.get(c, [c])]
                if len(new) != len(edges):
                    rewritten += 1
                route.set("edges", " ".join(new))
                route.attrib.pop("exitTimes", None)
            if time_shift:
                key = "depart" if elem.tag != "flow" else "begin"
                elem.set(key, f"{float(elem.get(key, '0')) + time_shift:.2f}")
            vehicles.append((_depart(elem), idx, elem))
    vehicles.sort(key=lambda t: (t[0], t[1]))
    with out.open("w", encoding="UTF-8") as fh:
        fh.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- {header} -->\n<routes>\n')
        for vt in vtypes:
            fh.write("    " + ET.tostring(vt, encoding="unicode").strip() + "\n")
        for _, _, v in vehicles:
            ET.indent(v, space="    ", level=1)
            fh.write("    " + ET.tostring(v, encoding="unicode").strip() + "\n")
        fh.write("</routes>\n")
    return {"vehicles": len(vehicles), "routes_rewritten": rewritten}


def cut_routes(
    cut_net: Path,
    exit_routes: Path,
    edgemap: dict[str, list[str]],
    out: Path,
    time_shift: float = 0.0,
    link_cfg: dict[str, Any] | None = None,
    log: Path | None = None,
) -> dict[str, Any]:
    link_cfg = link_cfg or link_config()
    c = link_cfg["cut"]
    raw = out.with_name(out.stem + ".cutraw.xml")
    run_cmd(
        python_tool_cmd(
            "route/cutRoutes.py",
            str(cut_net),
            str(exit_routes),
            "-o",
            str(raw),
            "--disconnected-action",
            str(c["disconnected_action"]),
            "--default.departLane",
            str(c["default_depart_lane"]),
            "--default.departSpeed",
            str(c["default_depart_speed"]),
            "--min-length",
            str(c["min_length"]),
        ),
        log=log,
    )
    header = (
        f"cut from {rel(exit_routes)} on {rel(cut_net)} with cutRoutes.py; edges rewritten via "
        f"edgemap; time_shift_s={time_shift}; {link_cfg['label']}"
    )
    counts = rewrite_routes(raw, edgemap, out, time_shift, header)
    raw.unlink(missing_ok=True)
    return {**counts, "time_shift_s": time_shift}


def retime_tls(
    net: Path,
    routes: Path,
    out: Path,
    link_cfg: dict[str, Any] | None = None,
    log: Path | None = None,
) -> dict[str, Any]:
    """Webster retiming of a window's signal programs (tools/tlsCycleAdaptation.py, A-link-009).

    Writes a Tier B additional with one new program per signal; the city net is not touched."""
    t = (link_cfg or link_config())["tls"]
    run_cmd(
        python_tool_cmd(
            "tlsCycleAdaptation.py",
            "-n", str(net), "-r", str(routes), "-o", str(out), "-b", str(t["begin"]),
            "-p", str(t["program_id"]), "-y", str(t["yellow_time_s"]), "-a", str(t["all_red_s"]),
            "-l", str(t["lost_time_s"]), "-g", str(t["min_green_s"]),
            "--min-cycle", str(t["min_cycle_s"]), "--max-cycle", str(t["max_cycle_s"]),
            "-H", str(t["saturation_headway_s"]), "--sorted",
        ),
        log=log,
    )  # fmt: skip
    programs = []
    for _, elem in ET.iterparse(out, events=("end",)):
        if elem.tag == "tlLogic":
            programs.append(
                {
                    "id": elem.get("id"),
                    "cycle_s": sum(float(ph.get("duration", 0)) for ph in elem.iter("phase")),
                }
            )
    return {"file": rel(out), "programs": programs, "config": t}


def window_tls(name: str) -> dict[str, Any]:
    """Retime the window's signals from its cut routes -> data/windows/<w>/<w>.tls.add.xml."""
    link_cfg = link_config()
    wdir = window_dir(load_window(name))
    out = wdir / f"{name}.tls.add.xml"
    log = LOGS_DIR / f"link-tls-{name}.log"
    log.unlink(missing_ok=True)
    meta = retime_tls(wdir / f"{name}.net.xml", wdir / f"{name}.rou.xml", out, link_cfg, log)
    meta["hash"] = content_hash(out)
    (wdir / f"{name}.tls.json").write_text(json.dumps(meta, indent=2))
    return meta


def cut_window_routes(name: str, tier_a: Path, time_shift: float | None = None) -> dict[str, Any]:
    link_cfg = link_config()
    cfg = load_window(name)
    wdir = window_dir(cfg)
    shift = float(link_cfg["cut"]["time_shift_s"] if time_shift is None else time_shift)
    edgemap = json.loads((wdir / f"{name}.edgemap.json").read_text())
    exit_routes = tier_a / "exit_routes.rou.xml"
    out = wdir / f"{name}.rou.xml"
    log = LOGS_DIR / f"link-cut-{name}.log"
    log.unlink(missing_ok=True)
    t0 = time.perf_counter()
    counts = cut_routes(wdir / f"{name}.cut.net.xml", exit_routes, edgemap, out, shift, link_cfg,
                        log)  # fmt: skip
    tmeta = json.loads((tier_a / "meta.json").read_text())
    meta = {
        "window": name,
        "label": link_cfg["label"],
        "tier_a_run": rel(tier_a),
        "tier_a_routes_hash": tmeta.get("routes_hash"),
        "tier_a_network_hash": tmeta.get("network_hash"),
        "routes": rel(out),
        "routes_hash": content_hash(out),
        "cut_config": link_cfg["cut"],
        "seconds": round(time.perf_counter() - t0, 1),
        **counts,
    }
    (wdir / f"{name}.cut.json").write_text(json.dumps(meta, indent=2))
    meta["tls"] = window_tls(name)
    return meta


# ------------------------------------------------------------------------------------------------
# flow check (PROJECT.md 9.3 acceptance)
# ------------------------------------------------------------------------------------------------


def edge_flows(
    edgedata: Path, begin: float, end: float, edges: set[str] | None
) -> dict[str, float]:
    """entered + departed per edge for the interval [begin, end) (edgeData `entered` excludes
    departures, so the sum counts every vehicle that started driving on the edge)."""
    flows: dict[str, float] = defaultdict(float)
    active = False
    for event, elem in ET.iterparse(edgedata, events=("start", "end")):
        if elem.tag == "interval":
            if event == "start":
                active = float(elem.get("begin", 0)) == begin and float(elem.get("end", 0)) == end
            else:
                elem.clear()
        elif event == "end" and elem.tag == "edge":
            eid = elem.get("id", "")
            if active and (edges is None or eid in edges):
                flows[eid] += float(elem.get("entered", 0)) + float(elem.get("departed", 0))
            elem.clear()
    return dict(flows)


def teleports_by_edge(sumo_log: Path) -> Counter:
    """Teleports per edge from a SUMO log (micro: lane='<lane>', meso: from edge '<edge>')."""
    pat = re.compile(r"Teleporting vehicle '[^']*';.*?(?:lane='([^']*)'|from edge '([^']*)')")
    out: Counter = Counter()
    if sumo_log.exists():
        for line in sumo_log.read_text(errors="replace").splitlines():
            m = pat.search(line)
            if m:
                edge = m.group(2) if m.group(1) is None else m.group(1).rsplit("_", 1)[0]
                out[edge] += 1
    return out


def backlog_by_edge(tripinfo: Path, delay_s: float) -> Counter:
    out: Counter = Counter()
    for _, elem in ET.iterparse(tripinfo, events=("end",)):
        if elem.tag == "tripinfo":
            if float(elem.get("departDelay", 0)) > delay_s:
                out[elem.get("departLane", "").rsplit("_", 1)[0]] += 1
            elem.clear()
    return out


def compare_flows(
    window_flows: dict[str, float],
    tier_a_flows: dict[str, float],
    edges: list[str],
    hours: float,
    chk: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for eid in edges:
        a = tier_a_flows.get(eid, 0.0) / hours
        if a < chk["min_tier_a_flow_vph"]:
            continue
        w = window_flows.get(eid, 0.0) / hours
        rows.append({"edge": eid, "tier_a_vph": a, "window_vph": w, "geh": geh(w, a)})
    n = len(rows)
    ok = sum(1 for r in rows if r["geh"] < chk["geh_max"])
    tot_a = sum(r["tier_a_vph"] for r in rows)
    tot_w = sum(r["window_vph"] for r in rows)
    ratio = tot_w / tot_a if tot_a else 0.0
    share = ok / n if n else 0.0
    gehs = sorted(r["geh"] for r in rows)

    def q(p: float) -> float:
        return round(gehs[min(len(gehs) - 1, int(p * len(gehs)))], 2) if gehs else 0.0

    return {
        "edges_compared": n,
        "edges_geh_ok": ok,
        "geh_ok_share": round(share, 4),
        "geh_quantiles": {"p50": q(0.5), "p85": q(0.85), "p95": q(0.95), "max": q(1.0)},
        "geh_bins": {
            "<1": sum(g < 1 for g in gehs),
            "1-3": sum(1 <= g < 3 for g in gehs),
            "3-5": sum(3 <= g < 5 for g in gehs),
            "5-10": sum(5 <= g < 10 for g in gehs),
            ">=10": sum(g >= 10 for g in gehs),
        },
        "total_tier_a_vph": round(tot_a, 1),
        "total_window_vph": round(tot_w, 1),
        "total_ratio": round(ratio, 4),
        "pass_geh": n > 0 and share >= chk["geh_share_min"],
        "pass_total": n > 0 and abs(ratio - 1.0) <= chk["total_ratio_tol"],
        "rows": sorted(rows, key=lambda r: -r["geh"]),
    }


def run_check(name: str, tier_a: Path, seed: int, use_tls: bool = True) -> dict[str, Any]:
    from sim.runner import (
        assert_tier_options,
        parse_statistics,
        runner_config,
        summarise,
    )

    link_cfg = link_config()
    rcfg = runner_config()
    chk = link_cfg["check"]
    cfg = load_window(name)
    wdir = window_dir(cfg)
    net, routes = wdir / f"{name}.net.xml", wdir / f"{name}.rou.xml"
    out = RUNS_DIR / (f"link-{name}" if use_tls else f"link-{name}-defaulttls")
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
    log.unlink(missing_ok=True)
    b, e = chk["interval"]
    additional = out / "edgedata.add.xml"
    edgedata_additional(
        additional,
        [
            {
                "id": "ed_bins",
                "freq": str(chk["edgedata_freq_s"]),
                "file": "edgedata.xml",
                "excludeEmpty": "true",
            },
            {
                "id": "ed_hour",
                "begin": str(b),
                "end": str(e),
                "file": "edgedata_hour.xml",
                "excludeEmpty": "true",
            },
        ],
    )
    tls_add = wdir / f"{name}.tls.add.xml"
    adds = [additional] + ([tls_add] if tls_add.exists() and use_tls else [])
    add_files = ",".join(str(x) for x in adds)
    args = [
        "-n", str(net), "-r", str(routes), "--additional-files", add_files,
        "--begin", str(b), "--end", str(chk["sim_end"]), "--seed", str(seed),
        "--tripinfo-output", str(out / "tripinfo.xml"),
        "--statistic-output", str(out / "stats.xml"), "--log", str(out / "sumo.log"),
        *flat(rcfg["sumo_common"]), *flat(rcfg["tier_B"]["options"]),
    ]  # fmt: skip
    assert_tier_options("B", args, adds, rcfg)
    t0 = time.perf_counter()
    run_cmd([sumo_bin("sumo"), *args], log=log)
    wall = time.perf_counter() - t0
    stats = parse_statistics(out / "stats.xml")
    result = summarise(stats, int(chk["sim_end"]) - int(b), wall)

    cut_net = sumolib.net.readNet(str(wdir / f"{name}.cut.net.xml"))
    cut_ids = {ed.getID() for ed in cut_net.getEdges()}
    wnet = sumolib.net.readNet(str(net))
    wids = [ed.getID() for ed in wnet.getEdges() if ed.getID() in cut_ids]
    hours = (e - b) / 3600.0
    wflows = edge_flows(out / "edgedata_hour.xml", b, e, set(wids))
    aflows = edge_flows(tier_a / "edgedata_hour.xml", b, e, set(wids))
    cmp = compare_flows(wflows, aflows, sorted(wids), hours, chk)
    edgemap = json.loads((wdir / f"{name}.edgemap.json").read_text())
    tele = teleports_by_edge(out / "sumo.log")
    backlog = backlog_by_edge(out / "tripinfo.xml", float(chk["backlog_delay_s"]))
    worst = []
    for r in cmp["rows"][:10]:
        ed = wnet.getEdge(r["edge"])
        reasons = ["window lower than Tier A" if r["window_vph"] < r["tier_a_vph"]
                   else "window higher than Tier A"]  # fmt: skip
        if not [i for i in ed.getIncoming() if i.getFunction() != "internal"]:
            reasons.append("boundary entry edge (cut routes are inserted here)")
        if backlog.get(r["edge"]):
            reasons.append(f"insertion backlog: {backlog[r['edge']]} departures delayed "
                           f"> {chk['backlog_delay_s']} s")  # fmt: skip
        if tele.get(r["edge"]):
            reasons.append(f"{tele[r['edge']]} teleports on this edge")
        if r["edge"] in edgemap:
            reasons.append("split by a service-road graft (first part compared)")
        if ed.getToNode().getType() in TLS_TYPES:
            reasons.append("signalised junction downstream (micro queues, meso penalty)")
        worst.append({**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()},
                      "lanes": ed.getLaneNumber(), "reasons": reasons})  # fmt: skip
    passed = cmp["pass_geh"] and cmp["pass_total"]
    tmeta = json.loads((tier_a / "meta.json").read_text())
    report = {
        "window": name,
        "label": link_cfg["label"],
        "seed": seed,
        "tier_a_run": rel(tier_a),
        "tier_a_mode": tmeta.get("mode"),
        "window_mode": rcfg["tier_B"]["mode"],
        "interval": [b, e],
        "tolerance": {
            k: chk[k]
            for k in ("min_tier_a_flow_vph", "geh_max", "geh_share_min", "total_ratio_tol")
        },
        "flow_definition": "edgeData entered + departed over the interval, veh/h",
        "network_hash": content_hash(net),
        "routes_hash": content_hash(routes),
        "tls_additional": rel(adds[1]) if len(adds) > 1 else None,
        "tls_additional_hash": content_hash(adds[1]) if len(adds) > 1 else None,
        "config_hash": config_hash(
            {
                "check": chk,
                "sumo_common": rcfg["sumo_common"],
                "tier_options": rcfg["tier_B"]["options"],
                "tls": link_cfg["tls"] if len(adds) > 1 else None,
            }
        ),
        "sumo_version": sumo_version(),
        "window_run": result,
        "pass": passed,
        **{k: v for k, v in cmp.items() if k != "rows"},
        "worst_edges": worst,
        "teleports_window_total": int(sum(tele.values())),
    }
    (out / "flow_comparison.json").write_text(json.dumps({**report, "rows": cmp["rows"]},
                                                         indent=2))  # fmt: skip
    (out / "meta.json").write_text(json.dumps(
        {k: report[k] for k in ("window", "label", "seed", "config_hash", "network_hash",
                                "routes_hash", "sumo_version", "pass")}
        | {"run_id": out.name, "tier": "B", "wall_seconds": round(wall, 2), "result": result},
        indent=2))  # fmt: skip
    (out / "flow_comparison.md").write_text(flow_markdown(report))
    return report


def flow_markdown(r: dict[str, Any]) -> str:
    t = r["tolerance"]
    lines = [
        f"# Flow check: window `{r['window']}` vs Tier A ({r['label']})",
        "",
        f"Tier A run `{r['tier_a_run']}` ({r['tier_a_mode']}) vs window run "
        f"({r['window_mode']}, seed {r['seed']}), "
        f"interval {r['interval'][0]}-{r['interval'][1]} s. "
        f"Flow = {r['flow_definition']}.",
        "",
        f"Tolerance: GEH < {t['geh_max']} on >= {100 * t['geh_share_min']:.0f} % of edges with "
        f"Tier A flow >= {t['min_tier_a_flow_vph']} veh/h, and total flow ratio within "
        f"{100 * t['total_ratio_tol']:.0f} %. Micro (window) and meso (Tier A) dynamics differ, so "
        "this tests the link (same vehicles, same entry times), not realism.",
        "",
        "| measure | value |",
        "|---|---|",
        f"| signal programs | {r['tls_additional'] or 'netconvert defaults (city net)'} |",
        f"| edges compared | {r['edges_compared']} |",
        f"| GEH < {t['geh_max']} | {r['edges_geh_ok']} ({100 * r['geh_ok_share']:.1f} %) |",
        f"| GEH p50 / p85 / p95 / max | {r['geh_quantiles']['p50']} / {r['geh_quantiles']['p85']} "
        f"/ {r['geh_quantiles']['p95']} / {r['geh_quantiles']['max']} |",
        f"| GEH bins | {', '.join(f'{k}: {v}' for k, v in r['geh_bins'].items())} |",
        f"| total flow Tier A / window (veh/h) | {r['total_tier_a_vph']} / {r['total_window_vph']} "
        f"(ratio {r['total_ratio']}) |",
        f"| window vehicles loaded / inserted / teleports | {r['window_run']['vehicles_loaded']} / "
        f"{r['window_run']['vehicles_inserted']} / {r['window_run']['teleports']} |",
        f"| result | **{'PASS' if r['pass'] else 'FAIL'}** "
        f"(GEH {'ok' if r['pass_geh'] else 'fail'},"
        f" total {'ok' if r['pass_total'] else 'fail'}) |",
        "",
        "## Worst 10 edges",
        "",
        "| edge | lanes | Tier A veh/h | window veh/h | GEH | reasons |",
        "|---|---|---|---|---|---|",
    ]
    for w in r["worst_edges"]:
        lines.append(
            f"| `{w['edge']}` | {w['lanes']} | {w['tier_a_vph']} | {w['window_vph']} | "
            f"{w['geh']} | {'; '.join(w['reasons'])} |"
        )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------------------

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def window(
    name: str = typer.Option(..., help="window name (sim/network/windows/<name>.yaml)"),
    city_net: Path | None = typer.Option(None, help="Tier A net (default: sim/config/link.yaml)"),
    osm: Path | None = typer.Option(None, help="OSM source: .pbf (extracted) or .osm(.gz) (as is)"),
    out_dir: Path | None = typer.Option(None, help="output dir (default: window YAML out_dir)"),
) -> None:
    """Cut the window from the city net and graft its service roads."""
    lc = link_config()
    cfg = load_window(name)
    out = out_dir or window_dir(cfg)
    log = LOGS_DIR / f"link-window-{name}.log"
    log.unlink(missing_ok=True)
    meta = build_link_window(
        cfg,
        city_net or REPO_ROOT / lc["city_net"],
        osm or REPO_ROOT / lc["city_pbf"],
        out,
        lc,
        log,
    )
    typer.echo(json.dumps({k: meta[k] for k in ("network", "graft", "validation")}, indent=1))


@app.command("tier-a")
def tier_a_cmd(
    routes: Path = typer.Option(..., help="Tier A route file"),
    out: Path | None = typer.Option(None, help="run dir (default runs/tierA-exit-<hash>)"),
    seed: int = typer.Option(1),
    net: Path | None = typer.Option(None, help="override the city network"),
) -> None:
    """Re-simulate a Tier A route set in meso with exit times and edgeData."""
    meta = run_tier_a(routes, out, seed, net)
    r = meta["result"]
    typer.echo(
        f"{meta['run_id']}: wall {meta['wall_seconds']} s, loaded {r['vehicles_loaded']}, "
        f"teleports {r['teleports']} ({100 * r['teleport_share']:.3f} %), "
        f"exit routes {meta['exit_routes']}"
    )


@app.command()
def cut(
    window_name: str = typer.Option(..., "--window", help="window name"),
    tier_a: Path = typer.Option(..., help="Tier A exit-time run dir"),
    time_shift: float | None = typer.Option(None, help="seconds added to every depart"),
) -> None:
    """cutRoutes.py with Tier A exit times, edgemap rewrite -> data/windows/<w>/<w>.rou.xml."""
    meta = cut_window_routes(window_name, tier_a, time_shift)
    typer.echo(json.dumps(meta, indent=1))


@app.command()
def tls(window_name: str = typer.Option(..., "--window", help="window name")) -> None:
    """Webster retiming of the window's signals from its cut routes (also run by `cut`)."""
    typer.echo(json.dumps(window_tls(window_name), indent=1))


@app.command()
def check(
    window_name: str = typer.Option(..., "--window", help="window name"),
    tier_a: Path = typer.Option(..., help="Tier A exit-time run dir"),
    seed: int = typer.Option(1),
    default_tls: bool = typer.Option(
        False, help="ignore <w>.tls.add.xml (netconvert default programs; for before/after)"
    ),
) -> None:
    """Run the window micro and compare its edge flows with Tier A."""
    report = run_check(window_name, tier_a, seed, use_tls=not default_tls)
    typer.echo(flow_markdown(report))
    if not report["pass"]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
