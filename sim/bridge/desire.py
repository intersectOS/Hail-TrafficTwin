"""Desire lines and detours across Sharm Obhur from a Tier A baseline (no simulation).

    python -m sim.bridge.desire detour --baseline runs/baseline-weekday-f0.1-s1-<...>
    python -m sim.bridge.desire access --net data/jeddah/jeddah.m2.net.xml

Crossing trips: vehicles whose straight origin-destination line crosses the inner creek polygon
(sim/bridge/geo.py). For each, today's route is the free-flow shortest path on the base network
and the bridge route the free-flow shortest path through a crossing (Dijkstra on the passenger edge
graph, turn restrictions ignored; A-obh-030), so `saved_km` = today - the best bridge route,
floored at 0 (distance metric; minutes from the time metric). The baseline's assigned routes are
longer than shortest paths (its meso run is congested); their mean is reported, not used.

Writes `sim/bridge/results/desire_lines.csv` (district pairs), `detour_summary.json` and
`docs/img/obhur-desire.png`. All results: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from sim.bridge.geo import creek_polygon, crosses, edge_points
from sim.bridge.geo import repo_rel as rel
from sim.bridge.network import base_facts, snap_landings
from sim.bridge.schema import bridge_config, bridge_transform, load_bridge_policy
from sim.common import REPO_ROOT, SYNTHETIC_LABEL
from sim.policies.routes import iter_route_elements

RESULTS = REPO_ROOT / "sim" / "bridge" / "results"
IMG = REPO_ROOT / "docs" / "img" / "obhur-desire.png"
POLICIES = ("obhur_bridge_b1", "obhur_bridge_b2")  # B3 = the better of the two per trip
PEAKS = {"am_peak": (6 * 3600, 9 * 3600), "pm_peak": (16 * 3600, 19 * 3600)}


class Graph:
    """Directed node graph of the passenger edges (CSR arrays): distance (m), free-flow time (s).

    Pure-Python Dijkstra (heapq): the project has no scipy, and the analysis needs only a few
    single-source runs from the landing junctions plus a few hundred for the exact sample."""

    def __init__(self, edges: pd.DataFrame) -> None:
        e = edges[edges["passenger"]][["from_node", "to_node", "length", "speed"]]
        nodes = pd.Index(pd.unique(np.r_[e["from_node"].to_numpy(), e["to_node"].to_numpy()]))
        self.index = nodes
        df = (
            pd.DataFrame(
                {
                    "u": nodes.get_indexer(e["from_node"]),
                    "w": nodes.get_indexer(e["to_node"]),
                    "d": e["length"].to_numpy(dtype=float),
                    "t": (e["length"] / e["speed"]).to_numpy(dtype=float),
                }
            )
            .groupby(["u", "w"], as_index=False)
            .min()
        )
        self.n = len(nodes)
        self.fwd = self._csr(df["u"], df["w"], df)
        self.rev = self._csr(df["w"], df["u"], df)
        self._cache: dict[tuple[bool, str], tuple[list, list, list]] = {}

    def _csr(self, a: pd.Series, b: pd.Series, df: pd.DataFrame) -> dict[str, np.ndarray]:
        order = np.argsort(a.to_numpy(), kind="stable")
        ptr = np.zeros(self.n + 1, dtype=np.int64)
        np.add.at(ptr, a.to_numpy() + 1, 1)
        return {
            "ptr": np.cumsum(ptr),
            "nbr": b.to_numpy()[order],
            "dist": df["d"].to_numpy()[order],
            "time": df["t"].to_numpy()[order],
        }

    def ix(self, ids: Any) -> np.ndarray:
        return self.index.get_indexer(pd.Index(ids))

    def _lists(self, reverse: bool, metric: str) -> tuple[list, list, list]:
        key = (reverse, metric)
        if key not in self._cache:
            g = self.rev if reverse else self.fwd
            self._cache[key] = (g["ptr"].tolist(), g["nbr"].tolist(), g[metric].tolist())
        return self._cache[key]

    def sssp(
        self, src: int, metric: str = "dist", reverse: bool = False, targets: Any = None
    ) -> np.ndarray:
        """Distances from `src`; with `targets` the search stops once all of them are settled
        (other entries are then upper bounds or inf)."""
        ptr, nbr, w = self._lists(reverse, metric)
        left = set(int(t) for t in targets) if targets is not None else None
        dist = [float("inf")] * self.n
        dist[src] = 0.0
        heap = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            if left is not None:
                left.discard(u)
                if not left:
                    break
            for k in range(ptr[u], ptr[u + 1]):
                nd = d + w[k]
                v = nbr[k]
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return np.asarray(dist)

    def from_nodes(self, nodes: list[str], metric: str = "dist", reverse: bool = False):  # noqa: ANN201
        return np.vstack([self.sssp(int(i), metric, reverse) for i in self.ix(nodes)])


def bridge_routes(
    g: Graph,
    snaps: pd.DataFrame,
    info: dict[str, Any],
    b: str,
    o_ix: np.ndarray,
    d_ix: np.ndarray,
    metric: str,
) -> np.ndarray:
    """Shortest o -> d through crossing `b` in either direction (inf where none)."""
    s = snaps[snaps["bridge"] == b]
    span = float(info["span_m"][b])
    speed = info["speeds"][b]
    best = np.full(len(o_ix), np.inf)
    for frm, to in (("S", "N"), ("N", "S")):
        a, z = s[s["side"] == frm], s[s["side"] == to]
        to_a = g.from_nodes(a["node"].tolist(), metric, reverse=True)  # rows: junctions in a
        from_z = g.from_nodes(z["node"].tolist(), metric)
        for i, ra in enumerate(a.itertuples()):
            for j, rz in enumerate(z.itertuples()):
                if metric == "dist":
                    mid = ra.approach_m + span + rz.approach_m
                else:
                    mid = ra.approach_m / speed[1] + span / speed[0] + rz.approach_m / speed[1]
                best = np.minimum(best, to_a[i, o_ix] + mid + from_z[j, d_ix])
    return best


def route_stats(routes: Path, ids: set[str], edges: pd.DataFrame) -> pd.DataFrame:
    """Length (m) and free-flow time (s) of each vehicle's assigned baseline route."""
    e = edges.set_index("edge_id")
    length, tff = e["length"].to_dict(), (e["length"] / e["speed"]).to_dict()
    rows = []
    for tag, _, elem in iter_route_elements(routes):
        if tag != "vehicle" or elem.get("id") not in ids:
            continue
        r = elem.find("route")
        es = r.get("edges", "").split() if r is not None else []
        rows.append(
            (elem.get("id"), sum(length.get(x, 0.0) for x in es), sum(tff.get(x, 0.0) for x in es))
        )
    return pd.DataFrame(rows, columns=["veh_id", "route_m_assigned", "route_ff_s"])


def analyse(baseline: Path, policies: tuple[str, ...] = POLICIES) -> dict[str, Any]:
    from sim.bridge.network import edge_table
    from sim.loop.site import desire_lines
    from sim.population.export_trips import export_config

    meta = json.loads((baseline / "meta.json").read_text())
    f = 1.0 / float(meta["sample"])
    net = Path(meta["network"])
    net = net if net.is_absolute() else REPO_ROOT / net
    cfg = bridge_config()
    edges, nodes, scc, offset = base_facts(net, cfg)
    v = pd.read_parquet(baseline / "vehicles.parquet")
    ti = pd.read_parquet(
        baseline / "tripinfo.parquet", columns=["veh_id", "route_m", "duration", "time_loss"]
    )
    vclass = {k: x["vClass"] for k, x in export_config()["vtypes"].items() if isinstance(x, dict)}
    car = v["vtype"].astype(str).map(vclass).isin(cfg["reroute"]["vclasses"]).to_numpy()
    o_lon, o_lat = edge_points(edges, v["o_edge"])
    d_lon, d_lat = edge_points(edges, v["d_edge"])
    cross = crosses(o_lon, o_lat, d_lon, d_lat, creek_polygon()) & car
    c = v[cross].merge(ti, on="veh_id", how="left").reset_index(drop=True)
    c = c.merge(
        route_stats(baseline / "routes.rou.xml.gz", set(c["veh_id"]), edges),
        on="veh_id",
        how="left",
    )
    e = edges.set_index("edge_id")
    c["o_node"] = e.loc[c["o_edge"].astype(str), "to_node"].to_numpy()
    c["d_node"] = e.loc[c["d_edge"].astype(str), "from_node"].to_numpy()
    # half of the first and last edge are driven on average; the assigned route counts them whole
    ends = 0.5 * (
        e.loc[c["o_edge"].astype(str), "length"].to_numpy()
        + e.loc[c["d_edge"].astype(str), "length"].to_numpy()
    )
    g = Graph(edges)
    o_ix, d_ix = g.ix(c["o_node"]), g.ix(c["d_node"])
    crossings = {}
    for pid in policies:
        t = bridge_transform(load_bridge_policy(pid))
        assert t is not None
        snaps = snap_landings(t.bridges, edges, nodes, scc, offset, cfg)
        new = edge_table(t, snaps)
        for b in t.bridges:
            span = new[(new["bridge"] == b.id) & (new["kind"] == "span")]["length_m"].iloc[0]
            info = {
                "span_m": {b.id: span},
                "speeds": {b.id: (b.speed_kmh / 3.6, b.approach_speed_kmh / 3.6)},
            }
            km = bridge_routes(g, snaps, info, b.id, o_ix, d_ix, "dist") + 2 * ends
            ff = bridge_routes(g, snaps, info, b.id, o_ix, d_ix, "time")
            c[f"via_{b.id}_km"] = km / 1000.0
            c[f"via_{b.id}_ff_s"] = ff
            crossings[b.id] = {"name": b.name, "span_m": float(span)}
    ids = sorted(crossings)
    # today = the free-flow shortest path on the base network (distance and time metrics), from
    # one Dijkstra per distinct origin junction; the assigned baseline route is kept for reference
    today_m = np.full(len(c), np.inf)
    today_s = np.full(len(c), np.inf)
    order = pd.Series(np.arange(len(c))).groupby(o_ix).agg(list)
    for o, rows in order.items():
        if o < 0:
            continue
        rows = np.asarray(rows)
        tgt = d_ix[rows]
        ok = tgt >= 0
        today_m[rows[ok]] = g.sssp(int(o), "dist", targets=tgt[ok])[tgt[ok]]
        today_s[rows[ok]] = g.sssp(int(o), "time", targets=tgt[ok])[tgt[ok]]
    c["today_km"] = (today_m + 2 * ends) / 1000.0
    c["today_ff_s"] = today_s
    c["assigned_km"] = c["route_m_assigned"] / 1000.0
    c = c[np.isfinite(c["today_km"])].reset_index(drop=True)
    for b in ids:
        c[f"saved_{b}_km"] = (c["today_km"] - c[f"via_{b}_km"]).clip(lower=0).fillna(0)
        c[f"saved_{b}_ff_min"] = ((c["today_ff_s"] - c[f"via_{b}_ff_s"]) / 60).clip(lower=0)
    c["saved_b3_km"] = c[[f"saved_{b}_km" for b in ids]].max(axis=1)
    c["saved_b3_ff_min"] = c[[f"saved_{b}_ff_min" for b in ids]].max(axis=1)
    first, last = c[f"saved_{ids[0]}_km"], c[f"saved_{ids[-1]}_km"]
    c["best_bridge"] = np.where(first >= last, ids[0], ids[-1])
    routing = {
        "assigned_km_mean": round(float(c["assigned_km"].mean()), 2),
        "shortest_km_mean": round(float(c["today_km"].mean()), 2),
        "note": "the baseline's assigned routes avoid its congestion (meso, 50 % teleports, "
        "TA-011), so they are longer than free-flow shortest paths; savings are counted "
        "against the shortest path, the conservative choice",
    }

    def summary(mask: np.ndarray) -> dict[str, Any]:
        s = c[mask]
        out = {
            "trips_per_day": int(round(len(s) * f)),
            "today_km_mean": round(float(s["today_km"].mean()), 2),
            "assigned_km_mean": round(float(s["assigned_km"].mean()), 2),
            "baseline_time_loss_min_mean": round(float(s["time_loss"].mean() / 60), 1),
            "baseline_duration_min_mean": round(float(s["duration"].mean() / 60), 1),
        }
        for b in [*ids, "b3"]:
            sav = s[f"saved_{b}_km"]
            ff = s[f"saved_{b}_ff_min"]
            users = sav > 0.5
            out[b] = {
                "trips_saving_per_day": int(round(int(users.sum()) * f)),
                "saved_km_mean_all": round(float(sav.mean()), 2),
                "saved_km_mean_users": round(float(sav[users].mean()), 2) if users.any() else 0.0,
                "saved_ff_min_mean_users": round(float(ff[users].mean()), 1)
                if users.any()
                else 0.0,
                "vkt_saved_per_day": int(round(float(sav.sum()) * f)),
            }
        return out

    dep = c["depart"].to_numpy()
    all_cars = int(car.sum())
    res: dict[str, Any] = {
        "label": SYNTHETIC_LABEL,
        "baseline": baseline.name,
        "network": rel(net),
        "sample": float(meta["sample"]),
        "creek": cfg["creek"],
        "crossings": crossings,
        "car_vehicles_per_day": int(round(all_cars * f)),
        "crossing": summary(np.ones(len(c), dtype=bool)),
        **{k: summary((dep >= h0) & (dep < h1)) for k, (h0, h1) in PEAKS.items()},
        "routing": routing,
        "method": "free-flow shortest path today vs free-flow shortest path through each "
        "crossing (distance for km, time for minutes); saving counted when > 0.5 km; B3 = the "
        "better of B1 and B2 per trip",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "detour_summary.json").write_text(json.dumps(res, indent=2))
    c["delay_s"] = c["time_loss"]
    lines = desire_lines(c, meta, 25)
    pair = c.assign(
        za=np.minimum(c["o_zone"], c["d_zone"]), zb=np.maximum(c["o_zone"], c["d_zone"])
    )
    agg = (
        pair.groupby(["za", "zb"])
        .agg(
            today_km=("today_km", "mean"),
            saved_b1_km=("saved_b1_km", "mean"),
            saved_b2_km=("saved_b2_km", "mean"),
            saved_b3_km=("saved_b3_km", "mean"),
        )
        .reset_index()
    )
    from sim.population.zones import default_zone_dir, load_zones

    zones, _, _ = load_zones(default_zone_dir())
    z = zones.set_index("zone_id")["name_en"]
    agg["name_a"], agg["name_b"] = z.loc[agg["za"]].to_numpy(), z.loc[agg["zb"]].to_numpy()
    lines = lines.merge(agg.drop(columns=["za", "zb"]), on=["name_a", "name_b"], how="left")
    lines = lines.sort_values("trips", ascending=False).reset_index(drop=True)
    lines.round(2).to_csv(RESULTS / "desire_lines.csv", index=False)
    plot(lines, net, policies)
    return res


def plot(lines: pd.DataFrame, net: Path, policies: tuple[str, ...]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from sim.bridge.network import is_city

    del net, is_city
    poly = creek_polygon()
    fig, ax = plt.subplots(figsize=(8, 10))
    xs, ys = poly.exterior.xy
    ax.fill(xs, ys, color="#9ecae1", zorder=1, label="Sharm Obhur (OSM coastline)")
    top = lines.head(15)
    wmax = float(top["trips"].max()) if len(top) else 1.0
    for r in top.itertuples():
        ax.plot(
            [r.lon_a, r.lon_b],
            [r.lat_a, r.lat_b],
            color="#7a5cc4",
            alpha=0.55,
            lw=1 + 7 * r.trips / wmax,
            zorder=2,
        )
    for r in top.itertuples():
        for lon, lat, name in ((r.lon_a, r.lat_a, r.name_a), (r.lon_b, r.lat_b, r.name_b)):
            ax.plot(lon, lat, "o", color="#333", ms=3, zorder=3)
            ax.annotate(name, (lon, lat), fontsize=6, xytext=(3, 3), textcoords="offset points")
    colors = {"b1": "#d62728", "b2": "#ff7f0e"}
    for pid in policies:
        t = bridge_transform(load_bridge_policy(pid))
        assert t is not None
        for b in t.bridges:
            (x0, y0), (x1, y1) = b.south.abutment, b.north.abutment
            ax.plot(
                [x0, x1],
                [y0, y1],
                color=colors.get(b.id, "k"),
                lw=4,
                zorder=4,
                label=f"{b.id.upper()} {b.name.split('(')[0].strip()}",
            )
    ax.set_xlim(39.02, 39.26)
    ax.set_ylim(21.50, 21.84)
    ax.set_aspect(1 / np.cos(np.radians(21.74)))
    ax.set_title(
        "Desire lines crossing Sharm Obhur, weekday (top 15 district pairs)\n"
        f"line width = vehicle trips/day; {SYNTHETIC_LABEL}",
        fontsize=9,
    )
    ax.legend(fontsize=7, loc="lower left")
    ax.tick_params(labelsize=7)
    IMG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG, dpi=110, bbox_inches="tight")
    plt.close(fig)


def landing_access(net: Path, radius_m: float = 1500.0, min_m: float = 200.0) -> pd.DataFrame:
    """How well each landing junction is reached from its own bank today: network distance to and
    from every main-SCC junction 0.2-1.5 km away on the same bank (straight line not over the
    creek), divided by the straight-line distance (circuity). A high circuity means the local
    streets do not connect to the landing (divided arterials, missing links): a real bridge would
    need an interchange and local links that the network does not have."""
    cfg = bridge_config()
    edges, nodes, scc, offset = base_facts(net, cfg)
    g = Graph(edges)
    sc = edges[edges["edge_id"].isin(scc)]
    n = nodes[nodes["node_id"].isin(set(sc["from_node"]) & set(sc["to_node"]))].reset_index()
    nx, ny = n["x"].to_numpy() - offset[0], n["y"].to_numpy() - offset[1]
    rows = []
    for pid in POLICIES:
        t = bridge_transform(load_bridge_policy(pid))
        assert t is not None
        snaps = snap_landings(t.bridges, edges, nodes, scc, offset, cfg)
        for (b, side), grp in snaps.groupby(["bridge", "side"]):
            x0, y0 = grp["node_x"].iloc[0] - offset[0], grp["node_y"].iloc[0] - offset[1]
            crow = np.hypot(nx - x0, ny - y0)
            # same bank: the straight line to the landing does not cross the creek
            e_ll = edges.set_index("from_node")[["lon0", "lat0"]]
            e_ll = e_ll[~e_ll.index.duplicated()]
            ll = e_ll.reindex(n["node_id"])
            j0 = e_ll.reindex([grp["node"].iloc[0]]).to_numpy()[0]
            lon_j, lat_j = np.full(len(n), j0[0]), np.full(len(n), j0[1])
            lon_n, lat_n = ll["lon0"].to_numpy(), ll["lat0"].to_numpy()
            same = ~crosses(lon_n, lat_n, lon_j, lat_j, creek_polygon())
            sel = (crow > min_m) & (crow < radius_m) & same & ll["lon0"].notna().to_numpy()
            ix = g.ix(n.loc[sel, "node_id"])
            js = [int(i) for i in g.ix(grp["node"].tolist())]
            to = np.min([g.sssp(j, reverse=True)[ix] for j in js], axis=0)
            fr = np.min([g.sssp(j)[ix] for j in js], axis=0)
            c = crow[sel]
            rows.append({
                "bridge": b, "side": side, "landing": grp["landing"].iloc[0],
                "junctions": int(sel.sum()), "crow_km_median": round(float(np.median(c)) / 1e3, 2),
                "to_landing_km_median": round(float(np.median(to)) / 1e3, 2),
                "from_landing_km_median": round(float(np.median(fr)) / 1e3, 2),
                "circuity_to": round(float(np.median(to / c)), 1),
                "circuity_from": round(float(np.median(fr / c)), 1),
            })  # fmt: skip
    df = pd.DataFrame(rows).drop_duplicates(["bridge", "side"]).reset_index(drop=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "landing_access.csv", index=False)
    return df


app = typer.Typer(add_completion=False, help=__doc__)


@app.command("access")
def access_cmd(
    net: Path = typer.Option(..., help="plain base network, e.g. the baseline's"),
) -> None:
    """Landing accessibility table (sim/bridge/results/landing_access.csv)."""
    typer.echo(landing_access(net).to_string(index=False))


@app.command("detour")
def main(
    baseline: Path = typer.Option(..., help="Tier A baseline run directory"),
) -> None:
    res = analyse(baseline, POLICIES)
    typer.echo(json.dumps(res, indent=2))


if __name__ == "__main__":
    app()
