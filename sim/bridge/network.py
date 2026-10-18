"""Bridge network variants: crossings added to a base network with a netconvert patch.

    python -m sim.bridge.network data/jeddah/jeddah.m2.net.xml --policy obhur_bridge_b1
    python -m sim.bridge.network data/windows/obhur_creek/obhur_creek.net.xml \
        --policy obhur_bridge_b3

Per crossing `<b>` (ids prefixed `obh_<b>_`): nodes `S` and `N` at the two abutments (lon/lat from
the policy, projected with the network's own UTM zone and netOffset); the span `SN` / `NS` with the
crossing's lanes and speed; and per landing junction k (the policy's `connect` points snapped to
existing arterial junctions) an approach pair `S<k>i` (junction -> abutment, entered from every
passenger edge into that junction) and `S<k>o` (abutment -> junction), likewise `N<k>i` / `N<k>o`.
Edge lengths follow from the node positions (straight lines). Every other element of the base
network is read back unchanged (`-s base -n -e -t -x`); Track A's closures / lane / speed edits of
the same `network_change` go into the same edge patch.

The base network is never touched: city variants go to `data/jeddah/<stem>.bridge-<key>.net.xml.gz`,
others to the work directory. All results: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.bridge.geo import repo_rel as rel
from sim.bridge.schema import BridgeNetworkChange, Crossing, bridge_config, load_bridge_policy
from sim.common import REPO_ROOT, config_hash, run_cmd, sumo_bin
from sim.policies.edges import CACHE, load_edges, net_hash, open_xml, utm_xy
from sim.policies.netedit import CITY_NET_DIR, NETCONVERT_OPTIONS, patch_xml

SPAN_TYPE = "obh_bridge"
APPROACH_TYPE = "obh_approach"


# ---------------------------------------------------------------------------- ids


def node_id(b: str, side: str) -> str:
    return f"obh_{b}_{side}"


def span_id(b: str, frm: str) -> str:
    """Span edge leaving abutment `frm` ('S' -> SN, 'N' -> NS)."""
    return f"obh_{b}_{frm}{'N' if frm == 'S' else 'S'}"


def approach_id(b: str, side: str, k: int, inbound: bool) -> str:
    return f"obh_{b}_{side}{k}{'i' if inbound else 'o'}"


def span_ids(t: BridgeNetworkChange) -> list[str]:
    return [span_id(c.id, s) for c in t.bridges for s in ("S", "N")]


# ---------------------------------------------------------------------------- base network facts


def is_city(net: Path) -> bool:
    return net.resolve().parent == CITY_NET_DIR.resolve()


def connected_edges(net: Path, cfg: dict[str, Any]) -> set[str]:
    """Edges a bridge may join: the main passenger SCC of a city network; for any other network
    (a focus window, a test net) every SCC with at least `window_min_component_edges` edges plus
    the largest, since a window cut out of the city splits into several components (D-017)."""
    from sim.loop.network import main_scc_edges
    from sim.network.netinfo import edge_graph, strongly_connected

    if is_city(net):
        return main_scc_edges(net)
    path = CACHE / f"bridgescc-{net_hash(net)}.parquet"
    if path.exists():
        return set(pd.read_parquet(path)["edge_id"])
    comps = strongly_connected(edge_graph(net, "passenger"))
    floor = min(int(cfg["network"]["window_min_component_edges"]), len(comps[0]) if comps else 0)
    edges = sorted(e for c in comps if len(c) >= floor for e in c)
    CACHE.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"edge_id": edges}).to_parquet(path, index=False)
    return set(edges)


def base_facts(
    base: Path, cfg: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, set[str], tuple[float, float]]:
    """(edges, nodes, connected edges, netOffset) of a plain base network (cached by hash)."""
    from sim.loop.network import net_offset, node_table

    cfg = cfg or bridge_config()
    return load_edges(base), node_table(base), connected_edges(base, cfg), net_offset(base)


def snap_landings(
    crossings: list[Crossing],
    edges: pd.DataFrame,
    nodes: pd.DataFrame,
    scc: set[str],
    offset: tuple[float, float],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """One row per (crossing, side, k): the arterial junction each `connect` point snaps to.

    A candidate junction has at least one incoming and one outgoing main-component passenger edge
    of a `connect_types` class; the nearest within `max_snap_m` wins (A-obh-010, A-obh-011)."""
    nc = cfg["network"]
    art = edges[edges["type"].isin(nc["connect_types"]) & edges["passenger"]
                & edges["edge_id"].isin(scc)]  # fmt: skip
    ok = set(art["to_node"]) & set(art["from_node"])
    cand = nodes[nodes["node_id"].isin(ok)].reset_index(drop=True)
    if cand.empty:
        raise ValueError("no arterial junction in the main component to connect a bridge to")
    dx, dy = offset
    names = pd.concat([
        art[["to_node", "name"]].rename(columns={"to_node": "node"}),
        art[["from_node", "name"]].rename(columns={"from_node": "node"}),
    ])  # fmt: skip
    names = names[names["name"] != ""].groupby("node")["name"].agg(lambda s: sorted(set(s)))
    rows = []
    for c in crossings:
        for side, land in (("S", c.south), ("N", c.north)):
            ax, ay = utm_xy(np.array([land.abutment[0]]), np.array([land.abutment[1]]))
            for k, (lon, lat) in enumerate(land.connect):
                x, y = utm_xy(np.array([lon]), np.array([lat]))
                d = np.hypot(cand["x"].to_numpy() - dx - x[0], cand["y"].to_numpy() - dy - y[0])
                j = int(d.argmin())
                if d[j] > float(nc["max_snap_m"]):
                    raise ValueError(
                        f"bridge {c.id} {land.name}: no arterial junction within "
                        f"{nc['max_snap_m']} m of connect point {k} ({lon}, {lat}); nearest "
                        f"{cand.at[j, 'node_id']} at {d[j]:.0f} m"
                    )
                node = cand.at[j, "node_id"]
                rows.append({
                    "bridge": c.id, "side": side, "k": k, "landing": land.name,
                    "node": node, "node_type": cand.at[j, "type"],
                    "node_x": float(cand.at[j, "x"]), "node_y": float(cand.at[j, "y"]),
                    "snap_m": round(float(d[j]), 1),
                    "abut_x": float(ax[0]) + dx, "abut_y": float(ay[0]) + dy,
                    "approach_m": round(float(np.hypot(cand.at[j, "x"] - dx - ax[0],
                                                       cand.at[j, "y"] - dy - ay[0])), 1),
                    "street": " / ".join(names.get(node, [])),
                })  # fmt: skip
    snaps = pd.DataFrame(rows)
    dup = snaps.duplicated(["bridge", "side", "node"])
    if dup.any():
        clash = snaps.loc[dup, ["bridge", "side", "node"]].to_dict("records")
        raise ValueError(f"two connect points of one landing snap to the same junction: {clash}")
    return snaps


def edge_table(t: BridgeNetworkChange, snaps: pd.DataFrame) -> pd.DataFrame:
    """The new edges: id, from_node, to_node, kind, lanes, speed (m/s), crow length (m)."""
    rows = []
    for c in t.bridges:
        g = snaps[snaps["bridge"] == c.id]
        s = g[g["side"] == "S"].iloc[0]
        n = g[g["side"] == "N"].iloc[0]
        span_m = float(np.hypot(n.abut_x - s.abut_x, n.abut_y - s.abut_y))
        for frm, to in (("S", "N"), ("N", "S")):
            rows.append({
                "edge_id": span_id(c.id, frm), "bridge": c.id, "kind": "span",
                "from_node": node_id(c.id, frm), "to_node": node_id(c.id, to), "lanes": c.lanes,
                "speed": c.speed_kmh / 3.6, "length_m": round(span_m, 1),
            })  # fmt: skip
        for r in g.itertuples():
            ab = node_id(c.id, r.side)
            for inbound in (True, False):
                rows.append({
                    "edge_id": approach_id(c.id, r.side, r.k, inbound), "bridge": c.id,
                    "kind": "approach", "from_node": r.node if inbound else ab,
                    "to_node": ab if inbound else r.node, "lanes": c.lanes,
                    "speed": c.approach_speed_kmh / 3.6, "length_m": r.approach_m,
                })  # fmt: skip
    return pd.DataFrame(rows)


def plain_files(
    t: BridgeNetworkChange, snaps: pd.DataFrame, new: pd.DataFrame, edits_patch: str | None,
    edges: pd.DataFrame, cfg: dict[str, Any],
) -> tuple[str, str, str, str]:  # fmt: skip
    """(nodes, edges, types, connections) plain XML for netconvert.

    netconvert keeps the loaded connections of the base network's edges, so the bridge would have
    no way in: every passenger edge entering a landing junction gets lane connections to the
    approach (explicit lanes, as Track D does for its Loop ramps; edge-only connections are dropped
    for edges whose lanes were loaded): its rightmost lane to the approach's rightmost lane and its
    leftmost lane to the approach's leftmost, so the bridge can be reached turning either way."""
    nc = cfg["network"]
    nod = ["<nodes>"]
    for c in t.bridges:
        g = snaps[snaps["bridge"] == c.id]
        for side in ("S", "N"):
            r = g[g["side"] == side].iloc[0]
            nod.append(f'    <node id="{node_id(c.id, side)}" x="{r.abut_x:.2f}" '
                       f'y="{r.abut_y:.2f}" type="priority"/>')  # fmt: skip
    nod.append("</nodes>")
    edg = ["<edges>"]
    if edits_patch:
        edg += [ln for ln in edits_patch.splitlines() if ln.strip() not in ("<edges>", "</edges>")]
    names = {c.id: c.name for c in t.bridges}
    for r in new.itertuples():
        typ = SPAN_TYPE if r.kind == "span" else APPROACH_TYPE
        edg.append(
            f'    <edge id="{r.edge_id}" from="{r.from_node}" to="{r.to_node}" type="{typ}" '
            f'numLanes="{r.lanes}" speed="{r.speed:.3f}" name="{names[r.bridge]}"/>'
        )
    edg.append("</edges>")
    typ = [
        "<types>",
        f'    <type id="{SPAN_TYPE}" priority="{nc["priority"]}" allow="{nc["allow"]}" '
        'oneway="true"/>',
        f'    <type id="{APPROACH_TYPE}" priority="{nc["priority"]}" allow="{nc["allow"]}" '
        'oneway="true"/>',
        "</types>",
    ]
    closed = set()
    if edits_patch:
        closed = {ln.split('"')[1] for ln in edits_patch.splitlines() if "<delete " in ln}
    feed = edges[edges["passenger"] & ~edges["edge_id"].isin(closed)]
    con = ["<connections>"]
    for r in new[(new["kind"] == "approach") & new["edge_id"].str.endswith("i")].itertuples():
        inc = feed[feed["to_node"] == r.from_node].sort_values("edge_id")
        for eid, n_in in zip(inc["edge_id"], inc["lanes"].astype(int), strict=True):
            # rightmost lane -> rightmost approach lane, leftmost -> leftmost: right and left turns
            for f, to in sorted({(0, 0), (n_in - 1, int(r.lanes) - 1)}):
                con.append(f'    <connection from="{eid}" to="{r.edge_id}" fromLane="{f}" '
                           f'toLane="{to}"/>')  # fmt: skip
    con.append("</connections>")
    return ("\n".join(nod) + "\n", "\n".join(edg) + "\n", "\n".join(typ) + "\n",
            "\n".join(con) + "\n")  # fmt: skip


def variant_path(base: Path, key: str, work: Path) -> Path:
    stem = base.name.removesuffix(".gz").removesuffix(".net.xml")
    city = base.resolve().parent == CITY_NET_DIR.resolve()
    return (CITY_NET_DIR if city else work) / f"{stem}.bridge-{key}.net.xml.gz"


def build_bridge_net(
    base: Path, t: BridgeNetworkChange, work: Path, cfg: dict[str, Any] | None = None
) -> tuple[Path, dict[str, Any], pd.DataFrame]:
    """Build (or reuse) the variant of `base` with the crossings (and edits) of `t`."""
    cfg = cfg or bridge_config()
    edges, nodes, scc, offset = base_facts(base, cfg)
    snaps = snap_landings(t.bridges, edges, nodes, scc, offset, cfg)
    new = edge_table(t, snaps)
    edits_patch, edit_info = None, {"closed_edges": [], "changed_edges": [], "new_edges": []}
    if t.edits or t.new_edges:
        edits_patch, edit_info = patch_xml(t, edges)
    files = plain_files(t, snaps, new, edits_patch, edges, cfg)
    key = config_hash({"base": net_hash(base), "files": list(files)})[:10]
    out = variant_path(base, key, work)
    if not out.exists():
        work.mkdir(parents=True, exist_ok=True)
        stem = out.name.removesuffix(".net.xml.gz")
        paths = []
        for suffix, text in zip(("nod", "edg", "typ", "con"), files, strict=True):
            p = work / f"{stem}.{suffix}.xml"
            p.write_text(text)
            paths.append(p)
        tmp = out.with_name(out.name + ".tmp.net.xml.gz")
        cmd = [sumo_bin("netconvert"), "-s", str(base), "-n", str(paths[0]), "-e", str(paths[1]),
               "-t", str(paths[2]), "-x", str(paths[3]), "-o", str(tmp)]  # fmt: skip
        run_cmd([*cmd, *NETCONVERT_OPTIONS], log=work / "netconvert-bridge.log")
        tmp.rename(out)
    spans = new[new["kind"] == "span"].drop_duplicates("bridge").set_index("bridge")["length_m"]
    info: dict[str, Any] = {
        "base": rel(base),
        "variant": rel(out),
        "bridges": [c.id for c in t.bridges],
        "span_m": {b: float(v) for b, v in spans.items()},
        "approach_m": {b: float(g["approach_m"].sum()) for b, g in snaps.groupby("bridge")},
        "landings": snaps.drop(columns=["abut_x", "abut_y", "node_x", "node_y"]).to_dict("records"),
        "new_edges": new["edge_id"].tolist(),
        **edit_info,
    }
    return out, info, new


# ---------------------------------------------------------------------------- checks


def new_edge_links(
    variant: Path, new_ids: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:  # noqa: E501
    """(successors, predecessors) over connections that touch a new edge (streamed, gz ok)."""
    succ: dict[str, set[str]] = defaultdict(set)
    pred: dict[str, set[str]] = defaultdict(set)
    with open_xml(variant) as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "connection":
                f, t = elem.get("from", ""), elem.get("to", "")
                if (f in new_ids or t in new_ids) and not f.startswith(":"):
                    succ[f].add(t)
                    pred[t].add(f)
            if elem.tag in ("edge", "connection", "junction", "tlLogic"):
                elem.clear()
    return succ, pred


def scc_membership(variant: Path, new_ids: set[str], base_scc: set[str]) -> dict[str, bool]:
    """A new edge joins the main strongly connected component if it is reachable from a main-SCC
    edge and reaches one (the main SCC is strongly connected, so both paths close a cycle). For a
    window base `base_scc` is the union of its large components: then the test says the edge is
    entered from and leaves into them (a bridge between two components joins them).
    Searched over the new edges only, since every other connection is the base network's."""
    succ, pred = new_edge_links(variant, new_ids)

    def reach(start: str, nbrs: dict[str, set[str]]) -> bool:
        seen, todo = {start}, deque([start])
        while todo:
            e = todo.popleft()
            for n in nbrs.get(e, ()):
                if n in base_scc:
                    return True
                if n in new_ids and n not in seen:
                    seen.add(n)
                    todo.append(n)
        return False

    return {e: reach(e, succ) and reach(e, pred) for e in sorted(new_ids)}


def through_route_trips(new: pd.DataFrame, edges: pd.DataFrame, scc: set[str]) -> list[dict]:
    """Per crossing and direction: a trip from an arterial edge into the departure landing
    junction to an arterial edge out of the arrival landing junction (must use the span)."""
    trips = []
    main = edges[edges["edge_id"].isin(scc) & edges["passenger"]]
    for b, g in new.groupby("bridge"):
        for frm, to in (("S", "N"), ("N", "S")):
            src = g[(g["kind"] == "approach") & g["edge_id"].str.match(rf"obh_{b}_{frm}\d+i$")]
            dst = g[(g["kind"] == "approach") & g["edge_id"].str.match(rf"obh_{b}_{to}\d+o$")]
            j_from, j_to = src["from_node"].iloc[0], dst["to_node"].iloc[0]
            into = main[(main["to_node"] == j_from) & ~main["edge_id"].str.startswith("obh_")]
            out = main[(main["from_node"] == j_to) & ~main["edge_id"].str.startswith("obh_")]
            if into.empty or out.empty:
                continue
            trips.append({"id": f"{b}_{frm}{to}", "from": into["edge_id"].iloc[0],
                          "to": out["edge_id"].iloc[0], "span": span_id(b, frm)})  # fmt: skip
    return trips


def through_routes(variant: Path, trips: list[dict], work: Path) -> dict[str, bool]:
    """Route the check trips with duarouter (free flow) and report whether each uses its span."""
    work.mkdir(parents=True, exist_ok=True)
    tf = work / "bridge-check.trips.xml"
    lines = ["<routes>"] + [
        f'    <trip id="{t["id"]}" depart="0" from="{t["from"]}" to="{t["to"]}"/>' for t in trips
    ] + ["</routes>"]  # fmt: skip
    tf.write_text("\n".join(lines) + "\n")
    out = work / "bridge-check.rou.xml"
    run_cmd([sumo_bin("duarouter"), "-n", str(variant), "-r", str(tf), "-o", str(out),
             "--ignore-errors", "true", "--no-warnings", "true", "--no-step-log", "true"],
            log=work / "bridge-check.log")  # fmt: skip
    used: dict[str, bool] = {t["id"]: False for t in trips}
    spans = {t["id"]: t["span"] for t in trips}
    for _, elem in ET.iterparse(out, events=("end",)):
        if elem.tag == "vehicle":
            r = elem.find("route")
            if r is not None:
                used[elem.get("id", "")] = spans[elem.get("id", "")] in r.get("edges", "").split()
    return used


def check_variant(
    base: Path, variant: Path, new: pd.DataFrame, work: Path, route_check: bool = True
) -> dict[str, Any]:
    edges, _, scc, _ = base_facts(base)
    member = scc_membership(variant, set(new["edge_id"]), scc)
    out: dict[str, Any] = {
        "new_edges": len(member),
        "in_main_scc": int(sum(member.values())),
        "not_in_main_scc": [e for e, ok in member.items() if not ok],
    }
    if route_check:
        trips = through_route_trips(new, edges, scc)
        used = through_routes(variant, trips, work)
        out["through_routes"] = used
        out["through_routes_ok"] = bool(used) and all(used.values())
    out["ok"] = not out["not_in_main_scc"] and out.get("through_routes_ok", True)
    return out


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    base: Path,
    policy: str = typer.Option(..., help="bridge policy id or YAML path"),
    work: Path = typer.Option(REPO_ROOT / "runs" / "bridge-nets"),
    route_check: bool = typer.Option(True, help="duarouter through-route check"),
) -> None:
    """Build the bridge variant of `base` and check it (SCC membership, through-routes)."""
    from sim.bridge.schema import bridge_transform

    t = bridge_transform(load_bridge_policy(policy))
    if t is None:
        raise typer.BadParameter("policy has no bridges")
    path, info, new = build_bridge_net(base, t, work)
    info["check"] = check_variant(base, path, new, work, route_check)
    typer.echo(json.dumps(info, indent=2, ensure_ascii=False, default=str))
    if not info["check"]["ok"]:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
