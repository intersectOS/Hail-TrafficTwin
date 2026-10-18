"""Loop siting: desire lines, top-delay corridors and 6-8 candidate alignments from a baseline.

    python -m sim.loop.site                       # newest 10 % weekday baseline in runs/
    python -m sim.loop.site --baseline runs/<baseline run>

1. Desire lines: district-to-district vehicle trips x baseline delay per trip (city-equivalent
   delay hours, both directions summed). Top corridors: edges grouped by street name, ranked by
   the day's time loss (edgedata).
2. Station sites: trip ends of car / ride-hail trips weighted by the trip's baseline delay on a
   750 m grid; a site's score is the delay of trip ends within the access radius; peaks at least
   1.5 km apart (top 45). The named anchors (KAIA, Al Balad, Tahlia/Al Andalus, KAU) are added as
   sites but get no bonus: they are tested, not assumed.
3. Alignments: every pair of sites 6-25 tunnel-km apart, 4-8 stations at 1.5-3 km spacing along
   the straight line, intermediate stations snapped to the best site within 700 m. Score =
   delay of trips whose origin and destination are within R of two different stations (>= 2 km
   apart), the trips a shuttle line could take over.
4. Selection: best captured delay per tunnel-km first, at most one shared station and no parallel
   duplicate; an anchor not covered by a data-driven pick gets its best alignment as a test
   candidate. Writes sim/loop/candidates.yaml, sim/loop/results/{desire_lines,corridors,sites}.csv
   and docs/img/loop-candidates.png.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer
import yaml

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, rel
from sim.loop.schema import loop_config
from sim.policies.edges import load_edges, utm_xy

LOOP_DIR = Path(__file__).resolve().parent
CANDIDATES = LOOP_DIR / "candidates.yaml"
RESULTS = LOOP_DIR / "results"
MAP = REPO_ROOT / "docs" / "img" / "loop-candidates.png"
DISTRICTS = REPO_ROOT / "data" / "jeddah" / "districts.geojson"


def latest_baseline(runs: Path, daytype: str = "weekday", sample: float = 0.1) -> Path:
    found = sorted(Path(runs).glob(f"baseline-{daytype}-f{sample:g}-s1-*/meta.json"),
                   key=lambda p: p.stat().st_mtime)  # fmt: skip
    if not found:
        raise FileNotFoundError(f"no {daytype} baseline with sample {sample:g} in {runs}")
    return found[-1].parent


def from_utm(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:32637", "EPSG:4326", always_xy=True)
    lon, lat = tf.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return np.asarray(lon), np.asarray(lat)


# ---------------------------------------------------------------------------- inputs


def load_trips(base: Path, cfg: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Baseline vehicle trips with delay (s) and UTM coordinates of both ends."""
    meta = json.loads((base / "meta.json").read_text())
    veh = pd.read_parquet(base / "vehicles.parquet",
                          columns=["veh_id", "o_edge", "d_edge", "o_zone", "d_zone", "mode",
                                   "empty", "depart"])  # fmt: skip
    ti = pd.read_parquet(base / "tripinfo.parquet",
                         columns=["veh_id", "time_loss", "depart_delay"])  # fmt: skip
    v = veh.merge(ti, on="veh_id", how="inner")
    v["delay_s"] = v["time_loss"] + v["depart_delay"]
    net = Path(meta["network"])
    net = net if net.is_absolute() else REPO_ROOT / net
    edges = load_edges(net).set_index("edge_id")[["lon", "lat"]]
    for end in ("o", "d"):
        ll = edges.reindex(v[f"{end}_edge"].astype(str).to_numpy())
        v[f"{end}x"], v[f"{end}y"] = utm_xy(ll["lon"].to_numpy(), ll["lat"].to_numpy())
    v = v[np.isfinite(v[["ox", "oy", "dx", "dy"]].to_numpy()).all(axis=1)]
    v["shift"] = v["mode"].astype(str).isin(cfg["shift"]["modes"]) & ~v["empty"].astype(bool)
    return v.reset_index(drop=True), meta


def districts(path: Path = DISTRICTS) -> pd.DataFrame:
    from shapely.geometry import shape

    g = json.loads(Path(path).read_text())
    rows = []
    for f in g["features"]:
        geom = shape(f["geometry"])
        c = geom.representative_point()
        rows.append({"name_en": f["properties"].get("name_en") or f["properties"].get("name_ar"),
                     "geom": geom, "lon": c.x, "lat": c.y})  # fmt: skip
    return pd.DataFrame(rows)


def district_of(lon: np.ndarray, lat: np.ndarray, dist: pd.DataFrame) -> list[str]:
    from shapely import contains_xy

    names = np.array([""] * len(lon), dtype=object)
    for r in dist.itertuples():
        hit = contains_xy(r.geom, lon, lat) & (names == "")
        names[hit] = r.name_en
    return [str(n) if n else "outside districts" for n in names]


# ---------------------------------------------------------------------------- desire lines


def desire_lines(
    v: pd.DataFrame, meta: dict[str, Any], top: int, zone_dir: Path | None = None
) -> pd.DataFrame:
    from sim.population.zones import default_zone_dir, load_zones

    zones, _, _ = load_zones(zone_dir or default_zone_dir())
    f = 1.0 / float(meta["sample"])
    t = v[(v["o_zone"] >= 0) & (v["d_zone"] >= 0) & (v["o_zone"] != v["d_zone"])]
    a = np.minimum(t["o_zone"], t["d_zone"])
    b = np.maximum(t["o_zone"], t["d_zone"])
    g = t.groupby([a.rename("za"), b.rename("zb")]).agg(trips=("veh_id", "size"),
                                                       delay_s=("delay_s", "sum"))  # fmt: skip
    g = g.reset_index()
    g["trips"] = g["trips"] * f
    g["delay_h"] = g["delay_s"] / 3600.0 * f
    g["delay_min_per_trip"] = g["delay_s"] / 60.0 / (g["trips"] / f)
    z = zones.set_index("zone_id")
    for end, col in (("a", "za"), ("b", "zb")):
        g[f"name_{end}"] = z.loc[g[col], "name_en"].to_numpy()
        g[f"lon_{end}"] = z.loc[g[col], "lon"].to_numpy()
        g[f"lat_{end}"] = z.loc[g[col], "lat"].to_numpy()
    xa, ya = utm_xy(g["lon_a"], g["lat_a"])
    xb, yb = utm_xy(g["lon_b"], g["lat_b"])
    g["km"] = np.hypot(xb - xa, yb - ya) / 1000.0
    g = g.sort_values("delay_h", ascending=False).head(top).reset_index(drop=True)
    cols = ["name_a", "name_b", "km", "trips", "delay_h", "delay_min_per_trip",
            "lon_a", "lat_a", "lon_b", "lat_b"]  # fmt: skip
    return g[cols].round(4)


def corridors(base: Path, meta: dict[str, Any], top: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Street names with the largest daily time loss, and their edges (for the map)."""
    import pyarrow.parquet as pq

    f = 1.0 / float(meta["sample"])
    ed = pq.read_table(base / "edgedata.parquet", columns=["edge_id", "timeLoss"],
                       read_dictionary=["edge_id"]).to_pandas()  # fmt: skip
    loss = ed.groupby("edge_id", observed=True)["timeLoss"].sum() / 3600.0 * f
    net = Path(meta["network"])
    edges = load_edges(net if net.is_absolute() else REPO_ROOT / net).set_index("edge_id")
    e = edges.reindex(loss.index.astype(str))
    e["loss_h"] = loss.to_numpy()
    e["street"] = e["name"].where(e["name"].fillna("") != "", e.index.to_series())
    by = e.groupby("street")["loss_h"].sum().sort_values(ascending=False).head(top)
    table = by.rename("time_loss_veh_h").reset_index()
    table["edges"] = [int((e["street"] == s).sum()) for s in table["street"]]
    geo = e[e["street"].isin(set(by.index))][["street", "lon0", "lat0", "lon1", "lat1", "loss_h"]]
    return table.round(1), geo


# ---------------------------------------------------------------------------- sites


def station_sites(v: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    s = cfg["siting"]
    t = v[v["shift"]]
    x = np.concatenate([t["ox"].to_numpy(), t["dx"].to_numpy()])
    y = np.concatenate([t["oy"].to_numpy(), t["dy"].to_numpy()])
    w = np.concatenate([t["delay_s"].to_numpy(), t["delay_s"].to_numpy()]) / 3600.0
    cell = float(s["site_grid_m"])
    gx, gy = np.floor(x / cell).astype(np.int64), np.floor(y / cell).astype(np.int64)
    cells = pd.DataFrame({"gx": gx, "gy": gy, "w": w, "x": x * w, "y": y * w})
    agg = cells.groupby(["gx", "gy"]).sum().reset_index()
    agg["cx"], agg["cy"] = agg["x"] / agg["w"], agg["y"] / agg["w"]  # delay-weighted centroid
    r = float(cfg["access"]["radius_m"])
    cx, cy, cw = agg["cx"].to_numpy(), agg["cy"].to_numpy(), agg["w"].to_numpy()
    score = np.zeros(len(agg))
    for i in range(0, len(agg), 2000):
        d = np.hypot(cx[i : i + 2000, None] - cx[None, :], cy[i : i + 2000, None] - cy[None, :])
        score[i : i + 2000] = (cw[None, :] * (d <= r)).sum(axis=1)
    order = np.argsort(-score)
    picked: list[int] = []
    sep = float(s["site_min_separation_m"])
    for i in order:
        if all(np.hypot(cx[i] - cx[j], cy[i] - cy[j]) >= sep for j in picked):
            picked.append(int(i))
        if len(picked) >= int(s["max_sites"]):
            break
    sites = pd.DataFrame({"x": cx[picked], "y": cy[picked], "score_h": score[picked]})
    sites["anchor"] = ""
    ax, ay = utm_xy([a["lon"] for a in s["anchors"]], [a["lat"] for a in s["anchors"]])
    anchors = pd.DataFrame({"x": ax, "y": ay, "anchor": [a["name"] for a in s["anchors"]]})
    for i, a in anchors.iterrows():
        d = np.hypot(cx - a.x, cy - a.y)
        anchors.at[i, "score_h"] = float(cw[d <= r].sum())
    sites = pd.concat([sites, anchors], ignore_index=True)
    sites["lon"], sites["lat"] = from_utm(sites["x"], sites["y"])
    sites["site_id"] = [f"s{i}" for i in range(len(sites))]
    return sites


# ---------------------------------------------------------------------------- alignments


class Scorer:
    """Captured delay of an ordered station list: trips with both ends near different stations."""

    def __init__(self, v: pd.DataFrame, cfg: dict[str, Any], sample: float) -> None:
        t = v[v["shift"]]
        self.ox, self.oy = t["ox"].to_numpy(), t["oy"].to_numpy()
        self.dx, self.dy = t["dx"].to_numpy(), t["dy"].to_numpy()
        self.w = t["delay_s"].to_numpy() / 3600.0
        self.crow = np.hypot(self.dx - self.ox, self.dy - self.oy)
        self.r = float(cfg["access"]["radius_m"])
        self.min_m = float(cfg["access"]["min_trip_km"]) * 1000.0
        self.f = 1.0 / sample
        # prefilter: trips longer than the minimum (the only ones that can ever be captured)
        keep = self.crow >= self.min_m
        self.ox, self.oy, self.dx, self.dy = (
            self.ox[keep],
            self.oy[keep],
            self.dx[keep],
            self.dy[keep],
        )
        self.w = self.w[keep]

    def score(self, sx: np.ndarray, sy: np.ndarray) -> tuple[float, float]:
        from sim.loop.transforms import nearest_station

        lo = (min(sx) - self.r, max(sx) + self.r, min(sy) - self.r, max(sy) + self.r)
        box = (
            (self.ox >= lo[0])
            & (self.ox <= lo[1])
            & (self.oy >= lo[2])
            & (self.oy <= lo[3])
            & (self.dx >= lo[0])
            & (self.dx <= lo[1])
            & (self.dy >= lo[2])
            & (self.dy <= lo[3])
        )
        so, do = nearest_station(self.ox[box], self.oy[box], sx, sy)
        sd, dd = nearest_station(self.dx[box], self.dy[box], sx, sy)
        ok = (do <= self.r) & (dd <= self.r) & (so != sd)
        return float(self.w[box][ok].sum() * self.f), float(ok.sum() * self.f)


def place_stations(a: pd.Series, b: pd.Series, sites: pd.DataFrame, cfg: dict[str, Any]
                   ) -> tuple[np.ndarray, np.ndarray, list[int]] | None:  # fmt: skip
    """Stations from site a to site b: equal spacing, intermediates snapped to good sites."""
    s = cfg["siting"]
    lo_sp, hi_sp = (float(v) for v in s["station_spacing_m"])
    n_lo, n_hi = (int(v) for v in s["stations"])
    km_lo, km_hi = (float(v) for v in s["length_km"])
    cf = float(cfg["tunnel"]["curvature_factor"])
    L = float(np.hypot(b.x - a.x, b.y - a.y))
    if not (km_lo * 1000.0 <= L * cf <= km_hi * 1000.0):
        return None
    target = (lo_sp + hi_sp) / 2.0
    n = int(np.clip(round(L / target) + 1, n_lo, n_hi))
    if not (lo_sp <= L / (n - 1) <= hi_sp):
        n = int(np.clip(np.ceil(L / hi_sp) + 1, n_lo, n_hi))
        if not (lo_sp <= L / (n - 1) <= hi_sp):
            return None
    fr = np.linspace(0.0, 1.0, n)
    sx, sy = a.x + fr * (b.x - a.x), a.y + fr * (b.y - a.y)
    ids = [int(a.name)] + [-1] * (n - 2) + [int(b.name)]
    snap = float(s["snap_m"])
    px, py, ps = sites["x"].to_numpy(), sites["y"].to_numpy(), sites["score_h"].to_numpy()
    for k in range(1, n - 1):
        d = np.hypot(px - sx[k], py - sy[k])
        near = np.flatnonzero((d <= snap) & (sites["anchor"].to_numpy() == ""))
        near = [j for j in near if j not in ids]
        if not near:
            continue
        j = max(near, key=lambda i: ps[i])
        nx, ny = sx.copy(), sy.copy()
        nx[k], ny[k] = px[j], py[j]
        sp = np.hypot(np.diff(nx), np.diff(ny))
        tol = float(s["spacing_tolerance"])
        if (sp >= lo_sp * (1 - tol)).all() and (sp <= hi_sp * (1 + tol)).all():
            sx, sy, ids[k] = nx, ny, int(j)
    return sx, sy, ids


def generate(sites: pd.DataFrame, scorer: Scorer, cfg: dict[str, Any]) -> pd.DataFrame:
    cf = float(cfg["tunnel"]["curvature_factor"])
    rows = []
    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            placed = place_stations(sites.iloc[i], sites.iloc[j], sites, cfg)
            if placed is None:
                continue
            sx, sy, ids = placed
            delay_h, trips = scorer.score(sx, sy)
            km = float(np.hypot(np.diff(sx), np.diff(sy)).sum()) * cf / 1000.0
            rows.append({"a": i, "b": j, "sx": sx, "sy": sy, "site_ids": ids, "km": km,
                         "captured_delay_h": delay_h, "captured_trips": trips,
                         "delay_h_per_km": delay_h / km})  # fmt: skip
    return pd.DataFrame(rows)


def overlaps(c: pd.Series, chosen: list[pd.Series], cfg: dict[str, Any]) -> bool:
    s = cfg["siting"]
    lim = float(s["overlap_m"])
    for o in chosen:
        d = np.hypot(c.sx[:, None] - o.sx[None, :], c.sy[:, None] - o.sy[None, :])
        shared = int((d.min(axis=1) <= lim).sum())
        if shared > int(s["max_shared_stations"]):
            return True
        # parallel duplicate: most stations within 2 x overlap of the other line's stations
        if (d.min(axis=1) <= float(s["parallel_factor"]) * lim).mean() > float(s["parallel_share"]):
            return True
    return False


def select(cands: pd.DataFrame, sites: pd.DataFrame, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    s = cfg["siting"]
    n_max = int(s["n_candidates"])
    ranked = cands.sort_values("delay_h_per_km", ascending=False)
    # only alignments that capture a meaningful amount (top half by captured delay)
    floor = ranked["captured_delay_h"].quantile(float(s["capture_floor_quantile"]))
    chosen: list[pd.Series] = []
    for _, c in ranked[ranked["captured_delay_h"] >= floor].iterrows():
        if not overlaps(c, chosen, cfg):
            chosen.append(pd.concat([c, pd.Series({"origin": "data"})]))
        if len(chosen) >= n_max:
            break
    anchors = sites[sites["anchor"] != ""]
    lim = float(s["overlap_m"])
    tests = []
    for idx, an in anchors.iterrows():
        covered = any(np.hypot(c.sx - an.x, c.sy - an.y).min() <= lim for c in chosen)
        if covered:
            continue
        mine = ranked[(ranked["a"] == idx) | (ranked["b"] == idx)]
        mine = mine[[not overlaps(c, tests, cfg) for _, c in mine.iterrows()]]
        if len(mine):
            tests.append(
                pd.concat([mine.iloc[0], pd.Series({"origin": f"anchor test: {an.anchor}"})])
            )
    keep = max(n_max - len(tests), 4)
    final = chosen[:keep] + tests
    return [c.to_dict() for c in final[: max(n_max, keep + len(tests))]]


def name_stations(sx: np.ndarray, sy: np.ndarray, ids: list[int], sites: pd.DataFrame,
                  dist: pd.DataFrame) -> list[dict[str, Any]]:  # fmt: skip
    lon, lat = from_utm(sx, sy)
    names = district_of(lon, lat, dist)
    out = []
    for k in range(len(sx)):
        sid = ids[k]
        label = sites.at[sid, "anchor"] if sid >= 0 and sites.at[sid, "anchor"] else names[k]
        out.append({"name": str(label), "lon": round(float(lon[k]), 5),
                    "lat": round(float(lat[k]), 5)})  # fmt: skip
    return out


# ---------------------------------------------------------------------------- map


def draw_map(path: Path, dist: pd.DataFrame, lines: pd.DataFrame, corr: pd.DataFrame,
             cands: list[dict[str, Any]], sites: pd.DataFrame, title: str) -> None:  # fmt: skip
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 13), dpi=110)
    for r in dist.itertuples():
        geoms = getattr(r.geom, "geoms", [r.geom])
        for gm in geoms:
            xs, ys = gm.exterior.xy
            ax.plot(xs, ys, color="#b8b8b8", lw=0.5, zorder=1)
    wmax = lines["delay_h"].max() if len(lines) else 1.0
    for r in lines.itertuples():
        ax.plot([r.lon_a, r.lon_b], [r.lat_a, r.lat_b], color="#7a5cc4",
                lw=0.5 + 5.0 * r.delay_h / wmax, alpha=0.35, zorder=2)  # fmt: skip
    lmax = corr["loss_h"].max() if len(corr) else 1.0
    for r in corr.itertuples():
        ax.plot([r.lon0, r.lon1], [r.lat0, r.lat1], color="#d9822b",
                lw=0.8 + 2.5 * min(r.loss_h / lmax * 20, 1.0), alpha=0.8, zorder=3)  # fmt: skip
    data_sites = sites[sites["anchor"] == ""]
    ax.scatter(data_sites["lon"], data_sites["lat"], s=10, color="#555555", zorder=4,
               label="delay hot spots (station sites)")  # fmt: skip
    an = sites[sites["anchor"] != ""]
    ax.scatter(an["lon"], an["lat"], s=140, marker="*", color="#111111", zorder=6,
               label="anchors (tested)")  # fmt: skip
    colors = plt.get_cmap("tab10")
    for i, c in enumerate(cands):
        lon = [s["lon"] for s in c["stations"]]
        lat = [s["lat"] for s in c["stations"]]
        ax.plot(
            lon,
            lat,
            "-o",
            color=colors(i % 10),
            lw=2.6,
            ms=5,
            zorder=5,
            label=f"{c['id']} {c['tunnel_km']:.1f} km, {len(lon)} st. ({c['origin']})",
        )
        ax.annotate(c["id"], (lon[0], lat[0]), xytext=(4, 4), textcoords="offset points",
                    fontsize=10, weight="bold", color=colors(i % 10), zorder=7)  # fmt: skip
    ax.plot([], [], color="#7a5cc4", lw=3, alpha=0.5, label="desire lines (delay hours)")
    ax.plot([], [], color="#d9822b", lw=2, label="top-delay corridors (edgedata)")
    ax.set_aspect(1.0 / np.cos(np.radians(21.55)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title, fontsize=11)
    ax.legend(loc="lower left", fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------------------- CLI


def run_site(base: Path, out: Path = CANDIDATES, img: Path = MAP, results: Path = RESULTS,
             cfg: dict[str, Any] | None = None, districts_path: Path = DISTRICTS,
             zone_dir: Path | None = None) -> list[dict[str, Any]]:  # fmt: skip
    cfg = cfg or loop_config()
    s = cfg["siting"]
    v, meta = load_trips(base, cfg)
    sample = float(meta["sample"])
    dist = districts(districts_path)
    lines = desire_lines(v, meta, int(s["top_desire_lines"]), zone_dir)
    corr_table, corr_geo = corridors(base, meta, int(s["top_corridors"]))
    sites = station_sites(v, cfg)
    scorer = Scorer(v, cfg, sample)
    cands = generate(sites, scorer, cfg)
    picked = select(cands, sites, cfg)
    result = []
    for i, c in enumerate(picked):
        stations = name_stations(c["sx"], c["sy"], c["site_ids"], sites, dist)
        result.append({
            "id": f"C{i + 1}",
            "name": f"{stations[0]['name']} - {stations[-1]['name']}",
            "origin": c["origin"],
            "tunnel_km": round(float(c["km"]), 2),
            "captured_delay_h": round(float(c["captured_delay_h"]), 1),
            "captured_trips": round(float(c["captured_trips"])),
            "delay_h_per_km": round(float(c["delay_h_per_km"]), 1),
            "stations": stations,
        })  # fmt: skip
    results.mkdir(parents=True, exist_ok=True)
    lines.to_csv(results / "desire_lines.csv", index=False)
    corr_table.to_csv(results / "corridors.csv", index=False)
    sites.drop(columns=["x", "y"]).round(5).to_csv(results / "sites.csv", index=False)
    cands.drop(columns=["sx", "sy", "site_ids"]).round(2).to_csv(results / "alignments_all.csv",
                                                                  index=False)  # fmt: skip
    doc = {
        "kind": "loop_candidates",
        "label": SYNTHETIC_LABEL,
        "baseline": base.name,
        "generated_by": "python -m sim.loop.site",
        "access_radius_m": float(cfg["access"]["radius_m"]),
        "alignments_scored": len(cands),
        "candidates": result,
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    title = (f"Loop candidate alignments, Jeddah ({SYNTHETIC_LABEL})\n"
             f"baseline {base.name}; desire lines = vehicle trips x baseline delay")  # fmt: skip
    draw_map(img, dist, lines, corr_geo, result, sites, title)
    return result


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    baseline: Path | None = typer.Option(None, help="baseline run dir (default: newest 10 %)"),
    out: Path = typer.Option(CANDIDATES),
    img: Path = typer.Option(MAP),
) -> None:
    base = baseline or latest_baseline(REPO_ROOT / "runs")
    res = run_site(base, out, img)
    for c in res:
        typer.echo(
            f"{c['id']}: {c['name']} | {c['tunnel_km']} km, {len(c['stations'])} stations, "
            f"captured {c['captured_delay_h']:,.0f} delay-h/day ({c['origin']})"
        )
    typer.echo(f"wrote {rel(out)}, {rel(img)}")


if __name__ == "__main__":
    app()
