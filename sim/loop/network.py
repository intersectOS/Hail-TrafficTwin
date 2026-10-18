"""Loop tunnel network: one tunnel edge per direction between consecutive stations, a down ramp and
an up ramp per station joined to the surface network, written under a new name.

    python -m sim.loop.network data/jeddah/jeddah.m2.net.xml --policy loop_demo

Topology per alignment `<a>` with stations k = 0..n-1 (node and edge ids prefixed `loop_<a>_`):
`S<k>` is the tunnel node under station k; `T<k>_<k+1>` / `T<k+1>_<k>` the tunnel edges (one lane,
length = crow distance x curvature factor); `D<k>` (surface junction -> S<k>) the down ramp, where
shuttles load (30 s stop), and `U<k>` (S<k> -> surface junction) the up ramp. Shuttles pass
intermediate stations without stopping (Boring's express station bypass).

Modes: `shuttle` lets only the shuttle class (custom1) use tunnels and ramps, and adds no surface
connections into the down ramps (shuttles start on them); `private` lets passenger cars use them
and connects every incoming main-component edge at the surface junction to the down ramp.

Headways (capacity) are meso edge-type parameters in an additional file (`<type id=loop_tunnel>
<meso tauff=...>`), multiplied by 1/sample like every other headway (capacity scaling, A-sim-101).
The base network is never touched: city variants go to `data/jeddah/jeddah.loop-<key>.net.xml.gz`,
others to the run directory.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.common import REPO_ROOT, config_hash, rel, run_cmd, sumo_bin
from sim.loop.schema import Alignment, loop_config
from sim.policies.edges import CACHE, net_hash, open_xml, utm_xy
from sim.policies.netedit import CITY_NET_DIR, NETCONVERT_OPTIONS

TUNNEL_TYPE = "loop_tunnel"
RAMP_TYPE = "loop_ramp"


# ---------------------------------------------------------------------------- base network facts


def net_offset(net: Path) -> tuple[float, float]:
    """netOffset of a SUMO network (net XY = UTM 37N + offset; the projection is checked)."""
    with open_xml(net) as fh:
        head = fh.read(20000).decode("utf-8", "replace")
    pattern = r'<location[^>]*netOffset="([-\d.]+),([-\d.]+)"[^>]*projParameter="([^"]*)"'
    m = re.search(pattern, head)
    if m is None:
        raise ValueError(f"{net}: no <location> with netOffset in the header")
    if "+proj=utm" not in m.group(3) or "+zone=37" not in m.group(3):
        raise ValueError(f"{net}: expected a UTM zone 37 projection, got {m.group(3)}")
    return float(m.group(1)), float(m.group(2))


def node_table(net: Path, cache: Path | None = None) -> pd.DataFrame:
    """Junctions (id, type, x, y in net coordinates), cached by network hash."""
    cache = Path(cache or CACHE)
    path = cache / f"loopnodes-{net_hash(net)}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    rows = []
    with open_xml(net) as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == "junction":
                if elem.get("type") != "internal":
                    rows.append((elem.get("id"), elem.get("type"), float(elem.get("x", 0)),
                                 float(elem.get("y", 0))))  # fmt: skip
                elem.clear()
            elif elem.tag in ("edge", "connection", "tlLogic"):
                elem.clear()
    df = pd.DataFrame(rows, columns=["node_id", "type", "x", "y"])
    cache.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def main_scc_edges(net: Path, cache: Path | None = None) -> set[str]:
    """Edges of the largest passenger strongly connected component, cached by network hash."""
    from sim.network.netinfo import edge_graph, strongly_connected

    cache = Path(cache or CACHE)
    path = cache / f"loopscc-{net_hash(net)}.parquet"
    if path.exists():
        return set(pd.read_parquet(path)["edge_id"])
    if str(net).endswith(".gz"):
        raise ValueError("main_scc_edges needs a plain .net.xml base network")
    comps = strongly_connected(edge_graph(net, "passenger"))
    edges = sorted(comps[0]) if comps else []
    cache.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"edge_id": edges}).to_parquet(path, index=False)
    return set(edges)


# ---------------------------------------------------------------------------- stations


def station_table(
    alignments: list[Alignment],
    edges: pd.DataFrame,
    nodes: pd.DataFrame,
    scc: set[str],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """One row per station: line, k, name, lon, lat, UTM x/y, surface junction and its distance."""
    st = cfg["station"]
    main = edges[edges["type"].isin(st["connect_types"]) & edges["passenger"]
                 & edges["edge_id"].isin(scc)]  # fmt: skip
    ok = set(main["to_node"]) & set(main["from_node"])
    tls = set(nodes.loc[nodes["type"].str.contains("traffic_light", na=False), "node_id"])
    cand = nodes[nodes["node_id"].isin(ok - tls)].reset_index(drop=True)
    if cand.empty:
        raise ValueError("no surface junction with main-component edges to connect stations to")
    dx, dy = edges.attrs.get("net_offset", (0.0, 0.0))
    rows = []
    for a in alignments:
        lon = np.array([s.lon for s in a.stations])
        lat = np.array([s.lat for s in a.stations])
        x, y = utm_xy(lon, lat)
        for k, s in enumerate(a.stations):
            d = np.hypot(cand["x"].to_numpy() - dx - x[k], cand["y"].to_numpy() - dy - y[k])
            j = int(d.argmin())
            rows.append({
                "line": a.id, "k": k, "name": s.name, "lon": s.lon, "lat": s.lat,
                "x": float(x[k]), "y": float(y[k]), "node": cand.at[j, "node_id"],
                "node_x": float(cand.at[j, "x"]), "node_y": float(cand.at[j, "y"]),
                "connect_m": round(float(d[j]), 1),
                "connect_flag": bool(d[j] > float(st["max_connect_m"])),
            })  # fmt: skip
    return pd.DataFrame(rows)


def segment_lengths(stations: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Tunnel segment k -> k+1 per line: crow distance and modelled length (curvature factor)."""
    rows = []
    f = float(cfg["tunnel"]["curvature_factor"])
    for line, g in stations.groupby("line", sort=False):
        g = g.sort_values("k")
        x, y = g["x"].to_numpy(), g["y"].to_numpy()
        for k in range(len(g) - 1):
            crow = float(np.hypot(x[k + 1] - x[k], y[k + 1] - y[k]))
            rows.append({"line": line, "k": k, "crow_m": round(crow, 1),
                         "length_m": round(crow * f, 1)})  # fmt: skip
    return pd.DataFrame(rows)


def alignment_km(stations: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, float]:
    seg = segment_lengths(stations, cfg)
    return {str(k): round(v / 1000.0, 3) for k, v in seg.groupby("line")["length_m"].sum().items()}


# ---------------------------------------------------------------------------- ids and routes


def node_id(line: str, k: int) -> str:
    return f"loop_{line}_S{k}"


def tunnel_id(line: str, i: int, j: int) -> str:
    return f"loop_{line}_T{i}_{j}"


def down_id(line: str, k: int) -> str:
    return f"loop_{line}_D{k}"


def up_id(line: str, k: int) -> str:
    return f"loop_{line}_U{k}"


def shuttle_route(line: str, i: int, j: int) -> list[str]:
    """Edges from station i to station j of a line (down ramp, tunnels, up ramp)."""
    step = 1 if j > i else -1
    tunnels = [tunnel_id(line, k, k + step) for k in range(i, j, step)]
    return [down_id(line, i), *tunnels, up_id(line, j)]


# ---------------------------------------------------------------------------- build


def plain_files(
    stations: pd.DataFrame,
    edges: pd.DataFrame,
    scc: set[str],
    mode: str,
    speed_kmh: float,
    cfg: dict[str, Any],
) -> tuple[str, str, str, str]:
    """(nodes, edges, types, connections) plain XML for netconvert."""
    tun = cfg["tunnel"]
    allow = cfg["shuttle_vclass"] if mode == "shuttle" else "passenger"
    dx, dy = edges.attrs.get("net_offset", (0.0, 0.0))
    nod = ["<nodes>"]
    edg = ["<edges>"]
    seg = segment_lengths(stations, cfg).set_index(["line", "k"])["length_m"]
    for _, s in stations.iterrows():
        nod.append(f'    <node id="{node_id(s.line, s.k)}" x="{s.x + dx:.2f}" y="{s.y + dy:.2f}" '
                   'type="priority"/>')  # fmt: skip
        ramp = max(float(tun["ramp_length_m"]), float(s.connect_m))
        edg.append(
            f'    <edge id="{down_id(s.line, s.k)}" from="{s.node}" '
            f'to="{node_id(s.line, s.k)}" type="{RAMP_TYPE}" length="{ramp:.1f}"/>'
        )
        edg.append(f'    <edge id="{up_id(s.line, s.k)}" from="{node_id(s.line, s.k)}" '
                   f'to="{s.node}" type="{RAMP_TYPE}" length="{ramp:.1f}"/>')  # fmt: skip
    for (line, k), length in seg.items():
        for i, j in ((k, k + 1), (k + 1, k)):
            edg.append(
                f'    <edge id="{tunnel_id(line, i, j)}" from="{node_id(line, i)}" '
                f'to="{node_id(line, j)}" type="{TUNNEL_TYPE}" length="{length:.1f}"/>'
            )
    nod.append("</nodes>")
    edg.append("</edges>")
    typ = [
        "<types>",
        f'    <type id="{TUNNEL_TYPE}" numLanes="{int(tun["lanes"])}" '
        f'speed="{speed_kmh / 3.6:.3f}" allow="{allow}" priority="1"/>',
        f'    <type id="{RAMP_TYPE}" numLanes="1" speed="{float(tun["ramp_speed_kmh"]) / 3.6:.3f}" '
        f'allow="{allow}" priority="1"/>',
        "</types>",
    ]  # fmt: skip
    con = ["<connections>"]
    if mode == "private":
        inc = edges[edges["passenger"] & edges["edge_id"].isin(scc)]
        for _, s in stations.iterrows():
            for eid in sorted(inc.loc[inc["to_node"] == s.node, "edge_id"]):
                con.append(f'    <connection from="{eid}" to="{down_id(s.line, s.k)}" '
                           'fromLane="0" toLane="0"/>')  # fmt: skip
    con.append("</connections>")
    return ("\n".join(nod) + "\n", "\n".join(edg) + "\n", "\n".join(typ) + "\n",
            "\n".join(con) + "\n")  # fmt: skip


def variant_path(base: Path, key: str, work: Path) -> Path:
    city = base.resolve().parent == CITY_NET_DIR.resolve()
    if city:
        return CITY_NET_DIR / f"jeddah.loop-{key}.net.xml.gz"
    stem = base.name.removesuffix(".gz").removesuffix(".net.xml")
    return work / f"{stem}.loop-{key}.net.xml.gz"


def build_loop_net(
    base: Path,
    alignments: list[Alignment],
    mode: str,
    speed_kmh: float,
    work: Path,
    edges: pd.DataFrame,
    cfg: dict[str, Any] | None = None,
) -> tuple[Path, pd.DataFrame, dict[str, Any]]:
    """Build (or reuse) the Loop variant of `base`; returns (path, station table, info)."""
    cfg = cfg or loop_config()
    if mode not in ("shuttle", "private"):
        raise ValueError(f"mode must be shuttle or private, not {mode!r}")
    edges = edges.copy()
    edges.attrs["net_offset"] = net_offset(base)
    nodes = node_table(base)
    scc = main_scc_edges(base)
    stations = station_table(alignments, edges, nodes, scc, cfg)
    files = plain_files(stations, edges, scc, mode, speed_kmh, cfg)
    key = config_hash({"base": net_hash(base), "files": list(files)})[:10]
    out = variant_path(base, key, work)
    info: dict[str, Any] = {
        "base": rel(base), "variant": rel(out), "mode": mode, "speed_kmh": speed_kmh,
        "alignment_km": alignment_km(stations, cfg), "stations": len(stations),
        "connect_flags": int(stations["connect_flag"].sum()),
        "max_connect_m": float(stations["connect_m"].max()),
    }  # fmt: skip
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
        run_cmd([*cmd, *NETCONVERT_OPTIONS], log=work / "netconvert-loop.log")
        tmp.rename(out)
    return out, stations, info


def meso_types_file(path: Path, headway_s: float, sample: float) -> Path:
    """Meso edge-type headways for tunnels and ramps (capacity scaling: x 1/sample)."""
    tau = headway_s / min(sample, 1.0) if sample < 1.0 else headway_s
    body = " ".join(f'{k}="{tau:.3f}"' for k in ("tauff", "taufj", "taujf", "taujj"))
    path.write_text(
        "<additional>\n"
        f"    <!-- Loop headway {headway_s:.2f} s per vehicle, x 1/sample {sample:g} -->\n"
        f'    <type id="{TUNNEL_TYPE}"><meso {body}/></type>\n'
        f'    <type id="{RAMP_TYPE}"><meso {body}/></type>\n'
        "</additional>\n"
    )
    return path


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    base: Path,
    policy: str = typer.Option(..., help="loop policy id or YAML path"),
    mode: str | None = typer.Option(None, help="override: shuttle or private"),
    speed_kmh: float | None = typer.Option(None),
    work: Path = typer.Option(REPO_ROOT / "runs" / "loop-nets"),
) -> None:
    """Build the Loop variant network of a policy's alignments."""
    from sim.loop.params import resolve_params
    from sim.loop.schema import LoopPrivate, load_loop_policy, loop_transform
    from sim.policies.edges import load_edges

    t = loop_transform(load_loop_policy(policy))
    if t is None:
        raise typer.BadParameter("policy has no loop transform")
    p = resolve_params(t)
    m = mode or ("private" if isinstance(t, LoopPrivate) else "shuttle")
    path, st, info = build_loop_net(base, t.alignments, m, speed_kmh or p["speed_kmh"], work,
                                    load_edges(base))  # fmt: skip
    typer.echo(json.dumps(info, indent=2))
    typer.echo(st[["line", "k", "name", "node", "connect_m"]].to_string(index=False))


if __name__ == "__main__":
    app()
