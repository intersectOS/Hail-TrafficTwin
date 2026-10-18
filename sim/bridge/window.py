"""Tier B evaluation of the Obhur bridges on the `obhur_creek` window (microscopic, weekday peaks).

    python -m sim.bridge.window prepare --baseline runs/baseline-weekday-f0.1-s1-<...>
    python -m sim.bridge.window run --peak am --seed 1               # baseline, control, variants
    python -m sim.bridge.window report                               # tables from every run found

1. Demand (`prepare`): every vehicle of the Tier A weekday baseline whose route touches the window
   gets exit times along its route (departure + the baseline's congested 5-min edge travel times,
   capped at `max_congestion_factor` x free flow, A-obh-022), then SUMO's cutRoutes.py cuts it to
   the window (sim.link.cut_routes, edge map for the service-road graft). The baseline is a 10 %
   sample: each cut vehicle is replicated 1/sample times with seeded departure jitter (A-obh-021).
   One route file per peak holds the vehicles that enter from `warmup_s` before the peak to its end.
2. Runs (`run`), all microscopic with the same options and seed:
   - `baseline`: the cut routes as they are (the city assignment, B-D-002 style);
   - `control`: every vehicle re-routed one-shot (duarouter, A*) from its window entry edge to its
     exit edge on the window baseline's congested 15-min travel times, without a bridge;
   - one run per bridge policy: the same trips and weights on the policy's window variant
     (sim/bridge/network.py), bridge edges at free flow.
   Bridge vs control is the matched comparison (same vehicles, same routing treatment: TA-018);
   control vs baseline is the routing gain alone.
3. KPIs (`report`): per peak, seed and variant: bridge volumes, travel time and delay of the
   vehicles that depart in the peak (paired by vehicle id), VKT, approach-road delay and speed,
   distance saved per bridge user, edges relieved / worsened; the noise band is the control's
   change between seeds. Results go to `sim/bridge/results/window_*.csv` and `window_report.md`.

All results: synthetic demand, uncalibrated.
"""

from __future__ import annotations

import gzip
import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import numpy as np
import pandas as pd
import typer

from sim.bridge.geo import repo_rel as rel
from sim.bridge.schema import bridge_config, bridge_transform, load_bridge_policy
from sim.common import REPO_ROOT, SYNTHETIC_LABEL, run_cmd, sumo_bin, sumo_version
from sim.policies.edges import load_edges, utm_xy

RUNS = REPO_ROOT / "runs" / "obhur-window"
RESULTS = REPO_ROOT / "sim" / "bridge" / "results"
VARIANTS = (
    "obhur_bridge_b1", "obhur_bridge_b1_3x3", "obhur_bridge_b2", "obhur_bridge_b2_3x3",
    "obhur_bridge_b3", "obhur_bridge_b3_3x3",
)  # fmt: skip
BIN = 300.0  # Tier A edgedata interval (s)


def wcfg() -> dict[str, Any]:
    return bridge_config()["window"]


def window_dir() -> Path:
    from sim.network.build_window import load_window

    return REPO_ROOT / load_window(wcfg()["name"])["out_dir"]


def demand_dir() -> Path:
    return window_dir() / "bridge"


def hhmm(s: str) -> float:
    h, m = s.split(":")
    return int(h) * 3600.0 + int(m) * 60.0


def peak_span(peak: str) -> tuple[float, float]:
    p = wcfg()["peaks"][peak]
    return hhmm(p["begin"]), hhmm(p["end"])


# ---------------------------------------------------------------------------- 1. demand


def travel_time_table(baseline: Path, edges: pd.DataFrame, cap: float) -> np.ndarray:
    """[edge, 5-min bin] congested travel time (s): baseline edgedata, free flow where missing,
    capped at `cap` x free flow."""
    ff = (edges["length"] / edges["speed"]).to_numpy(dtype=np.float32)
    ed = pd.read_parquet(baseline / "edgedata.parquet", columns=["begin", "edge_id", "traveltime"])
    ed = ed[ed["traveltime"].notna()]
    idx = pd.Index(edges["edge_id"])
    e = idx.get_indexer(ed["edge_id"].astype(str))
    b = (ed["begin"].to_numpy() // BIN).astype(np.int64)
    nb = int(b.max()) + 2 if len(b) else 1
    tt = np.repeat(ff[:, None], nb, axis=1)
    ok = e >= 0
    tt[e[ok], b[ok]] = ed["traveltime"].to_numpy(dtype=np.float32)[ok]
    return np.minimum(tt, ff[:, None] * cap)


def write_exit_routes(baseline: Path, w_edges: set[str], out: Path, keep: list[tuple[float, float]],
                      cfg: dict[str, Any]) -> dict[str, int]:  # fmt: skip
    """Vehicles whose route touches the window, with exitTimes, if they enter it in a kept span."""
    from sim.policies.routes import iter_route_elements
    from sim.population.export_trips import vtype_lines

    meta = json.loads((baseline / "meta.json").read_text())
    net = Path(meta["network"])
    edges = load_edges(net if net.is_absolute() else REPO_ROOT / net)
    tt = travel_time_table(baseline, edges, float(cfg["max_congestion_factor"]))
    pos = {e: i for i, e in enumerate(edges["edge_id"])}
    nb = tt.shape[1]
    n_all = n_touch = n_keep = 0
    with out.open("w") as fh:
        fh.write(f"<routes>\n<!-- {SYNTHETIC_LABEL}; exit times from {baseline.name} -->\n")
        fh.write("\n".join(vtype_lines(1.0)) + "\n")
        for tag, dep, elem in iter_route_elements(baseline / "routes.rou.xml.gz"):
            if tag != "vehicle":
                continue
            n_all += 1
            r = elem.find("route")
            es = r.get("edges", "").split() if r is not None else []
            first = next((k for k, x in enumerate(es) if x in w_edges), None)
            if first is None:
                continue
            n_touch += 1
            t = dep
            exits = []
            for x in es:
                i = pos.get(x)
                t += float(tt[i, min(int(t // BIN), nb - 1)]) if i is not None else 0.0
                exits.append(t)
            enter = dep if first == 0 else exits[first - 1]
            if not any(a <= enter < b for a, b in keep):
                continue
            n_keep += 1
            ex = " ".join(f"{x:.2f}" for x in exits)
            fh.write(f'    <vehicle id={quoteattr(elem.get("id", ""))} type="{elem.get("type")}" '
                     f'depart="{dep:.2f}">\n        <route edges="{" ".join(es)}" '
                     f'exitTimes="{ex}"/>\n    </vehicle>\n')  # fmt: skip
        fh.write("</routes>\n")
    return {"baseline_vehicles": n_all, "touch_window": n_touch, "kept": n_keep}


def replicate(cut: Path, out: Path, copies: int, jitter: float, span: tuple[float, float],
              seed: int) -> int:  # fmt: skip
    """Cut vehicles departing in `span`, each `copies` times with uniform +/- `jitter` s."""
    from sim.population.export_trips import vtype_lines

    rng = np.random.default_rng(seed)
    rows = []
    for _, elem in ET.iterparse(cut, events=("end",)):
        if elem.tag != "vehicle":
            continue
        dep = float(elem.get("depart", "0"))
        if span[0] <= dep < span[1]:
            r = elem.find("route")
            rows.append((elem.get("id", ""), elem.get("type", "car"), dep,
                         r.get("edges", "") if r is not None else ""))  # fmt: skip
        elem.clear()
    rows.sort(key=lambda x: x[0])  # draw order independent of the cut file's order
    out_rows = []
    for vid, typ, dep, edges in rows:
        d = dep + rng.uniform(-jitter, jitter, size=copies)
        for k in range(copies):
            out_rows.append((max(d[k], span[0]), f"{vid}_r{k}", typ, edges))
    out_rows.sort()
    with out.open("w") as fh:
        fh.write(f"<routes>\n<!-- {SYNTHETIC_LABEL}; {copies} copies per sampled vehicle -->\n")
        fh.write("\n".join(vtype_lines(1.0)) + "\n")
        for dep, vid, typ, edges in out_rows:
            fh.write(f'    <vehicle id={quoteattr(vid)} type="{typ}" depart="{dep:.2f}" '
                     f'departLane="best" departSpeed="max">\n'
                     f'        <route edges="{edges}"/>\n    </vehicle>\n')  # fmt: skip
        fh.write("</routes>\n")
    return len(out_rows)


def prepare(baseline: Path, seed: int = 1) -> dict[str, Any]:
    from sim.link import cut_routes

    cfg = wcfg()
    name = cfg["name"]
    wdir = window_dir()
    out = demand_dir()
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((baseline / "meta.json").read_text())
    copies = int(round(1.0 / float(meta["sample"])))
    cut_net = wdir / f"{name}.cut.net.xml"
    w_edges = set(load_edges(cut_net)["edge_id"])
    keep = [(b - float(cfg["warmup_s"]) - 3600.0, e) for b, e in map(peak_span, cfg["peaks"])]
    t0 = time.perf_counter()
    exit_routes = out / "exit.rou.xml"
    counts = write_exit_routes(baseline, w_edges, exit_routes, keep, cfg)
    edgemap = json.loads((wdir / f"{name}.edgemap.json").read_text())
    cut = cut_routes(cut_net, exit_routes, edgemap, out / "cut.rou.xml", log=out / "cut.log")
    res: dict[str, Any] = {
        "label": SYNTHETIC_LABEL, "baseline": baseline.name, "window": name, "copies": copies,
        "seed": seed, **counts, "cut": cut, "peaks": {},
    }  # fmt: skip
    for peak in cfg["peaks"]:
        b, e = peak_span(peak)
        span = (b - float(cfg["warmup_s"]), e)
        n = replicate(out / "cut.rou.xml", out / f"demand-{peak}.rou.xml", copies,
                      float(cfg["replicate_jitter_s"]), span, seed)  # fmt: skip
        res["peaks"][peak] = {"vehicles": n, "span": span}
    res["seconds"] = round(time.perf_counter() - t0, 1)
    exit_routes.unlink()
    (out / "demand.json").write_text(json.dumps(res, indent=2))
    return res


# ---------------------------------------------------------------------------- 2. runs


def sim_args(net: Path, routes: Path, out: Path, peak: str, seed: int, fcd: bool) -> list[str]:
    cfg = wcfg()
    b, e = peak_span(peak)
    add = out / "outputs.add.xml"
    add.write_text(
        "<additional>\n"
        f'    <edgeData id="ed" freq="{int(cfg["edgedata_freq_s"])}" file="edgedata.xml" '
        'excludeEmpty="true"/>\n'
        f'    <edgeData id="w" freq="{int(cfg["weights_interval_s"])}" file="weights.xml" '
        'excludeEmpty="true"/>\n</additional>\n'
    )
    args = [
        sumo_bin("sumo"), "-n", str(net), "-r", str(routes), "--additional-files", str(add),
        "--begin", f"{b - float(cfg['warmup_s']):.0f}",
        "--end", f"{e + float(cfg['cooldown_s']):.0f}",
        "--seed", str(seed), "--step-length", str(cfg["step_length_s"]),
        "--time-to-teleport", str(cfg["time_to_teleport_s"]),
        "--ignore-route-errors", "true", "--no-step-log", "true",
        "--duration-log.statistics", "true",
        "--tripinfo-output", str(out / "tripinfo.xml"),
        "--tripinfo-output.write-unfinished", "true",
        "--tripinfo-output.write-undeparted", "true",
        "--statistic-output", str(out / "stats.xml"),
        "--log", str(out / "sumo.log"),
    ]  # fmt: skip
    if fcd:
        # vehicles near the landings only (film close-ups), not the whole window
        sel = out / "fcd_edges.txt"
        edges = load_edges(net)
        near = approach_edges(edges, float(cfg["fcd_radius_m"]))
        near |= {e for e in edges["edge_id"] if str(e).startswith("obh_")}
        sel.write_text("".join(f"edge:{e}\n" for e in sorted(near)))
        args += ["--fcd-output", str(out / "fcd.xml"), "--fcd-output.geo", "true",
                 "--fcd-output.filter-edges.input-file", str(sel)]  # fmt: skip
    return args


def simulate(net: Path, routes: Path, out: Path, peak: str, seed: int, meta: dict[str, Any],
             fcd: bool = False) -> dict[str, Any]:  # fmt: skip
    from sim.metrics import edgedata_to_parquet, parse_tripinfo

    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    run_cmd(sim_args(net, routes, out, peak, seed, fcd), log=out / "run.log")
    wall = round(time.perf_counter() - t0, 1)
    ti = parse_tripinfo(out / "tripinfo.xml")
    # every vehicle due in the run has a row (unfinished and undeparted ones too, A-obh-025):
    # time in system = (arrival, or the run's end) - planned departure, so insertion waits and
    # trips still running at the end count
    planned = planned_departures(routes)
    run_end = peak_span(peak)[1] + float(wcfg()["cooldown_s"])
    ti["planned_depart"] = ti["veh_id"].map(planned).astype(float)
    ti["arrived"] = ti["arrival"] >= 0
    ti["time_in_system_s"] = np.where(ti["arrived"], ti["arrival"], run_end) - ti["planned_depart"]
    ti.to_parquet(out / "tripinfo.parquet", index=False)
    edgedata_to_parquet(out / "edgedata.xml", out / "edgedata.parquet")
    teleports = sum(1 for ln in (out / "sumo.log").read_text().splitlines() if "Teleporting" in ln)
    if fcd:
        fcd_to_parquet(out / "fcd.xml", out / "fcd.parquet")
        (out / "fcd.xml").unlink()
    (out / "tripinfo.xml").unlink()
    with (out / "sumo.log").open("rb") as src, gzip.open(out / "sumo.log.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    (out / "sumo.log").unlink()
    b, _ = peak_span(peak)
    meta = {
        "run_id": flat_id(out), "kind": "bridge_window",
        **meta, "label": SYNTHETIC_LABEL, "tier": "B", "mode": "micro", "peak": peak,
        "seed": seed, "network": rel(net), "network_hash": net_content_hash(net),
        "routes": rel(routes), "begin_s": b - float(wcfg()["warmup_s"]),
        "edgedata_freq_s": float(wcfg()["edgedata_freq_s"]), "wall_s": wall,
        "teleports": teleports, "sumo_version": sumo_version(),
    }  # fmt: skip
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


def planned_departures(routes: Path) -> dict[str, float]:
    out = {}
    for _, el in ET.iterparse(routes, events=("end",)):
        if el.tag in ("vehicle", "trip"):
            out[el.get("id", "")] = float(el.get("depart", "nan"))
            el.clear()
    return out


def flat_id(run_dir: Path) -> str:
    """Top-level run id of a window run: obhur-<peak>-s<seed>-<run> (the API lists runs/<id>/)."""
    return f"obhur-{run_dir.parent.name}-{run_dir.name}"


def publish() -> list[str]:
    """Expose every finished window run as runs/<flat id> (a symlink) for the viewer and films;
    the control and the bridge runs name their comparison run (`baseline_run_id`)."""
    out = []
    for meta_path in sorted(RUNS.glob("*-s*/*/meta.json")):
        d = meta_path.parent
        meta = json.loads(meta_path.read_text())
        rid = flat_id(d)
        meta["run_id"] = rid
        if d.name == "baseline":
            ref_dir = None
        elif d.name == "control":
            ref_dir = RUNS / f"{d.parent.name.split('-')[0]}-s1" / "baseline"
        else:
            ref_dir = d.parent / meta.get("compare_run", "control")
        if ref_dir is not None:
            meta["baseline_run_id"] = flat_id(ref_dir)
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
        link = REPO_ROOT / "runs" / rid
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(d.relative_to(REPO_ROOT / "runs"))
        out.append(rid)
    return out


def net_content_hash(net: Path) -> str:
    from sim.common import content_hash
    from sim.metrics import xml_content_hash

    return xml_content_hash(net) if str(net).endswith(".gz") else content_hash(net)


def fcd_to_parquet(xml: Path, out: Path) -> int:
    """FCD (geo) to Parquet in the run-outputs contract names (docs/contracts/run-outputs.md §5):
    time_s, vehicle_id, vtype, lon, lat, speed_ms, angle_deg, sorted by vehicle then time."""
    cols: dict[str, list] = {k: [] for k in ("time_s", "vehicle_id", "vtype", "lon", "lat",
                                             "speed_ms", "angle_deg")}  # fmt: skip
    t = 0.0
    for ev, el in ET.iterparse(xml, events=("start", "end")):
        if ev == "start":
            if el.tag == "timestep":
                t = float(el.get("time", "0"))
            continue
        if el.tag == "vehicle":
            cols["time_s"].append(t)
            cols["vehicle_id"].append(el.get("id"))
            cols["vtype"].append(el.get("type"))
            cols["lon"].append(float(el.get("x", "nan")))
            cols["lat"].append(float(el.get("y", "nan")))
            cols["speed_ms"].append(float(el.get("speed", "nan")))
            cols["angle_deg"].append(float(el.get("angle", "nan")))
            el.clear()
        elif el.tag == "timestep":
            el.clear()
    df = pd.DataFrame(cols).astype({"time_s": "float32", "speed_ms": "float32",
                                    "angle_deg": "float32"})  # fmt: skip
    df.sort_values(["vehicle_id", "time_s"], kind="stable").to_parquet(out, index=False)
    return len(df)


def reroute(net: Path, demand: Path, weights: Path, out: Path) -> dict[str, Any]:
    """One-shot routes from each vehicle's first to last window edge on fixed weights."""
    from sim.population.export_trips import vtype_lines

    trips = out.with_name("trips.xml")
    n = 0
    with trips.open("w") as fh:
        fh.write("<routes>\n" + "\n".join(vtype_lines(1.0)) + "\n")
        for _, elem in ET.iterparse(demand, events=("end",)):
            if elem.tag != "vehicle":
                continue
            r = elem.find("route")
            es = r.get("edges", "").split() if r is not None else []
            if es:
                n += 1
                fh.write(f'    <trip id={quoteattr(elem.get("id", ""))} type="{elem.get("type")}" '
                         f'depart="{elem.get("depart")}" departLane="best" departSpeed="max" '
                         f'from="{es[0]}" to="{es[-1]}"/>\n')  # fmt: skip
            elem.clear()
        fh.write("</routes>\n")
    cfg = wcfg()
    cmd = [sumo_bin("duarouter"), "-n", str(net), "-r", str(trips), "-o", str(out),
           "--weight-files", str(weights), "--weight-attribute", "traveltime",
           "--routing-algorithm", str(cfg["routing_algorithm"]), "--ignore-errors", "true",
           "--no-warnings", "true", "--no-step-log", "true", "--routing-threads", "4",
           "--write-license", "false"]  # fmt: skip
    t0 = time.perf_counter()
    run_cmd(cmd, log=out.with_name("duarouter.log"))
    out.with_name(out.name.replace(".rou.xml", ".rou.alt.xml")).unlink(missing_ok=True)
    trips.unlink()
    routed = sum(1 for _, el in ET.iterparse(out, events=("end",)) if el.tag == "vehicle")
    return {"trips": n, "routed": routed, "seconds": round(time.perf_counter() - t0, 1)}


def variant_net(policy: str) -> Path:
    from sim.bridge.network import build_bridge_net, check_variant

    t = bridge_transform(load_bridge_policy(policy))
    assert t is not None
    base = window_dir() / f"{wcfg()['name']}.net.xml"
    work = REPO_ROOT / "runs" / "bridge-nets" / "window"
    net, _, new = build_bridge_net(base, t, work)
    chk = check_variant(base, net, new, work)
    if not chk["ok"]:
        raise RuntimeError(f"{policy}: window variant failed its checks: {chk}")
    return net


def run_peak(peak: str, seed: int, variants: list[str], fcd: list[str], force: bool,
             display_control: str | None = None) -> None:  # fmt: skip
    """Baseline (seed 1 only), control and variants for one peak and seed.

    Routing weights always come from the seed-1 window baseline, so a seed-2 control or variant
    differs from seed 1 only by the simulation's random numbers (the noise band). With
    `display_control`, the control routes are also simulated on that policy's network (bridge
    present, unused): same network hash as the policy run, so the viewer's difference mode can
    compare them, and the run measures what the unused new links alone change."""
    name = wcfg()["name"]
    base_net = window_dir() / f"{name}.net.xml"
    demand = demand_dir() / f"demand-{peak}.rou.xml"
    if not demand.exists():
        raise typer.BadParameter(f"{rel(demand)} missing: run `prepare` first")
    dmeta = json.loads((demand_dir() / "demand.json").read_text())
    root = RUNS / f"{peak}-s{seed}"
    common = {"window": name, "demand": dmeta["baseline"], "copies": dmeta["copies"]}

    def done(d: Path) -> bool:
        return (d / "meta.json").exists() and not force

    b = RUNS / f"{peak}-s1" / "baseline"
    if seed == 1 and not done(b):
        typer.echo(f"[{peak} s{seed}] baseline")
        simulate(base_net, demand, b, peak, seed, {**common, "run": "baseline"}, "baseline" in fcd)
    weights = b / "weights.xml"
    if not weights.exists():
        raise RuntimeError(f"{rel(weights)} missing: run the seed-1 baseline first")
    jobs = [("control", base_net, None)] + [(p, variant_net(p), None) for p in variants]
    if display_control:
        jobs.append((f"control-on-{display_control}", variant_net(display_control), "control"))
    for run, net, routes_of in jobs:
        d = root / run
        if done(d):
            continue
        typer.echo(f"[{peak} s{seed}] {run}")
        d.mkdir(parents=True, exist_ok=True)
        routes = d / "routes.rou.xml"
        if routes_of is None:
            info = reroute(net, demand, weights, routes)
        else:
            with gzip.open(root / routes_of / "routes.rou.xml.gz", "rb") as src:
                routes.write_bytes(src.read())
            info = {"routes_from": routes_of}
        meta = {**common, "run": run, "policy": run if run in VARIANTS else None,
                "reroute": info, "weights": rel(weights)}  # fmt: skip
        if routes_of is not None:
            meta["compare_run"] = routes_of
        simulate(net, routes, d, peak, seed, meta, run in fcd)
        with routes.open("rb") as src, gzip.open(d / "routes.rou.xml.gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
        routes.unlink()


# ---------------------------------------------------------------------------- 3. KPIs


def bridge_edges_of(run: str) -> dict[str, list[str]]:
    if run not in VARIANTS:
        return {}
    t = bridge_transform(load_bridge_policy(run))
    assert t is not None
    return {c.id: [f"obh_{c.id}_SN", f"obh_{c.id}_NS"] for c in t.bridges}


def route_users(routes: Path, spans: set[str]) -> set[str]:
    out = set()
    with gzip.open(routes) as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if el.tag == "vehicle":
                r = el.find("route")
                if r is not None and not spans.isdisjoint(r.get("edges", "").split()):
                    out.add(el.get("id", ""))
                el.clear()
    return out


def approach_edges(edges: pd.DataFrame, radius: float) -> set[str]:
    """Window edges within `radius` m of any landing junction of B1 or B2 (both banks)."""
    from sim.bridge.network import base_facts, snap_landings

    name = wcfg()["name"]
    base = window_dir() / f"{name}.net.xml"
    cfg = bridge_config()
    e, nodes, scc, offset = base_facts(base, cfg)
    t = bridge_transform(load_bridge_policy("obhur_bridge_b3"))
    assert t is not None
    snaps = snap_landings(t.bridges, e, nodes, scc, offset, cfg)
    x, y = utm_xy(edges["lon"].to_numpy(), edges["lat"].to_numpy())
    near = np.zeros(len(edges), dtype=bool)
    for r in snaps.itertuples():
        near |= np.hypot(x - (r.node_x - offset[0]), y - (r.node_y - offset[1])) <= radius
    return set(edges.loc[near, "edge_id"]) - {i for i in edges["edge_id"] if i.startswith("obh_")}


def kpis(d: Path, peak: str, ref: Path | None, approach: set[str], names: pd.Series,
         ) -> tuple[dict[str, Any], pd.DataFrame]:  # fmt: skip
    b, e = peak_span(peak)
    hours = (e - b) / 3600.0
    ti = pd.read_parquet(d / "tripinfo.parquet")
    pk = ti[(ti["planned_depart"] >= b) & (ti["planned_depart"] < e)]
    ed = pd.read_parquet(d / "edgedata.parquet")
    ed = ed[(ed["begin"] >= b) & (ed["begin"] < e)]
    per_edge = ed.groupby("edge_id").agg(entered=("entered", "sum"), loss=("timeLoss", "sum"),
                                         ss=("sampledSeconds", "sum"))  # fmt: skip
    sp = ed.assign(w=ed["speed"] * ed["sampledSeconds"]).groupby("edge_id")["w"].sum()
    per_edge["speed_kmh"] = (sp / per_edge["ss"]).fillna(0) * 3.6
    per_edge["vph"] = per_edge["entered"] / hours
    appr = per_edge[per_edge.index.isin(approach)]
    meta = json.loads((d / "meta.json").read_text())
    run = meta["run"]
    out: dict[str, Any] = {
        "run": run, "peak": peak, "seed": meta["seed"], "wall_s": meta["wall_s"],
        "teleports": meta["teleports"], "trips_peak": len(pk),
        "arrived_share": round(float(pk["arrived"].mean()), 3),
        "mean_time_in_system_s": round(float(pk["time_in_system_s"].mean()), 1),
        "mean_time_loss_s": round(float(pk["time_loss"].mean()), 1),
        "vkt_peak": round(float(pk["route_m"].sum() / 1000.0), 0),
        "vht_peak": round(float(pk["time_in_system_s"].sum() / 3600.0), 1),
        "approach_delay_veh_h": round(float(appr["loss"].sum() / 3600.0), 1),
        "approach_speed_kmh": round(float((appr["speed_kmh"] * appr["ss"]).sum()
                                          / max(appr["ss"].sum(), 1e-9)), 1),
    }  # fmt: skip
    for bid, spans in bridge_edges_of(run).items():
        out[f"{bid}_vph"] = round(float(per_edge.reindex(spans)["vph"].fillna(0).sum()), 0)
    edges_tab = per_edge[["vph", "loss", "speed_kmh"]].copy()  # loss: time loss (veh-s)
    if ref is not None:
        rti = pd.read_parquet(ref / "tripinfo.parquet").set_index("veh_id")
        cols = ["time_in_system_s", "time_loss", "route_m", "arrived"]
        both = pk.set_index("veh_id").join(rti[cols], rsuffix="_c",
                                           how="inner")  # fmt: skip
        out["paired_trips"] = len(both)
        dt = both["time_in_system_s"] - both["time_in_system_s_c"]
        out["d_time_in_system_s"] = round(float(dt.mean()), 1)
        out["d_arrived_share"] = round(float(both["arrived"].mean() - both["arrived_c"].mean()), 3)
        out["d_time_loss_s"] = round(float((both["time_loss"] - both["time_loss_c"]).mean()), 1)
        out["d_vht_peak"] = round(float(dt.sum() / 3600), 1)
        out["d_vkt_peak"] = round(float((both["route_m"] - both["route_m_c"]).sum() / 1000), 0)
        spans = {s for v in bridge_edges_of(run).values() for s in v}
        if spans and (d / "routes.rou.xml.gz").exists():
            users = route_users(d / "routes.rou.xml.gz", spans) & set(both.index)
            u = both.loc[sorted(users)]
            out["bridge_users_peak"] = len(u)
            done = u[u["arrived"] & u["arrived_c"]]  # distance compares finished trips only
            km = (done["route_m_c"] - done["route_m"]).mean() / 1000 if len(done) else 0.0
            mins = (u["time_in_system_s_c"] - u["time_in_system_s"]).mean() / 60 if len(u) else 0.0
            out["saved_km_per_user"] = round(float(km), 2)
            out["saved_min_per_user"] = round(float(mins), 1)
            non = both.drop(index=sorted(users))
            d_non = (non["time_loss"] - non["time_loss_c"]).mean()
            out["d_time_loss_s_non_users"] = round(float(d_non), 1)
        ref_edges = pd.read_parquet(ref / "edgedata.parquet")
        ref_edges = ref_edges[(ref_edges["begin"] >= b) & (ref_edges["begin"] < e)]
        rpe = ref_edges.groupby("edge_id").agg(entered=("entered", "sum"), loss=("timeLoss", "sum"))
        j = edges_tab.join(rpe.rename(columns={"loss": "loss_ref"}), how="outer").fillna(0.0)
        j["d_vph"] = j["vph"] - j["entered"] / hours
        j["d_delay_veh_h"] = (j["loss"] - j["loss_ref"]) / 3600.0
        j["street"] = names.reindex(j.index).fillna("")
        thr = float(wcfg()["winners_min_delta_vph"])
        real = ~j.index.str.startswith("obh_")
        out["edges_relieved"] = int(((j["d_vph"] <= -thr) & real).sum())
        out["edges_worsened"] = int(((j["d_vph"] >= thr) & real).sum())
        out["edges_delay_down_1vh"] = int(((j["d_delay_veh_h"] <= -1.0) & real).sum())
        out["edges_delay_up_1vh"] = int(((j["d_delay_veh_h"] >= 1.0) & real).sum())
        edges_tab = j[["street", "d_vph", "d_delay_veh_h"]]
    return out, edges_tab


def report() -> pd.DataFrame:
    from sim.bridge.network import base_facts

    cfg = wcfg()
    base = window_dir() / f"{cfg['name']}.net.xml"
    edges, _, _, _ = base_facts(base)
    names = edges.set_index("edge_id")["name"]
    approach = approach_edges(edges, float(cfg["approach_radius_m"]))
    rows, streets = [], []
    for root in sorted(RUNS.glob("*-s*")):
        peak, seed = root.name.split("-s")
        ctrl = root / "control"
        for d in sorted(p for p in root.iterdir() if (p / "meta.json").exists()):
            if d.name == "baseline":
                ref = None
            elif d.name == "control":
                ref = RUNS / f"{peak}-s1" / "baseline"
            else:
                ref = ctrl
            k, tab = kpis(d, peak, ref, approach, names)
            rows.append(k)
            if ref is not None and d.name in VARIANTS:
                tab = tab.assign(run=d.name, peak=peak, seed=int(seed))
                streets.append(tab.reset_index().rename(columns={"index": "edge_id"}))
    df = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "window_kpis.csv", index=False)
    if streets:
        st = pd.concat(streets)
        st = st[~st["edge_id"].astype(str).str.startswith("obh_")]
        top = []
        for (run, peak, seed), g in st.groupby(["run", "peak", "seed"]):
            if seed != 1:
                continue
            by = g.assign(street=g["street"].where(g["street"] != "", g["edge_id"]))
            by = by.groupby("street")[["d_vph", "d_delay_veh_h"]].sum()
            for kind, part in (("relieved", by.nsmallest(5, "d_delay_veh_h")),
                               ("worsened", by.nlargest(5, "d_delay_veh_h"))):  # fmt: skip
                top += [{"run": run, "peak": peak, "kind": kind, "street": s,
                         "d_vph": round(r.d_vph), "d_delay_veh_h": round(r.d_delay_veh_h, 1)}
                        for s, r in part.iterrows()]  # fmt: skip
        pd.DataFrame(top).to_csv(RESULTS / "window_streets.csv", index=False)
    return df


app = typer.Typer(add_completion=False, help=__doc__)


@app.command("prepare")
def prepare_cmd(
    baseline: Path = typer.Option(..., help="Tier A weekday baseline run directory"),
    seed: int = typer.Option(1, help="seed of the replicate departure jitter"),
) -> None:
    typer.echo(json.dumps(prepare(baseline, seed), indent=2))


@app.command("run")
def run_cmd_(
    peak: str = typer.Option(..., help="am or pm"),
    seed: int = typer.Option(1),
    variants: str = typer.Option(",".join(VARIANTS), help="comma-separated bridge policies"),
    fcd: str = typer.Option("", help="comma-separated runs that also write FCD (film)"),
    force: bool = typer.Option(False),
    display_control: str | None = typer.Option(
        None, help="also simulate the control routes on this policy's network (viewer diff)"
    ),
) -> None:
    run_peak(peak, seed, [v for v in variants.split(",") if v], fcd.split(","), force,
             display_control)  # fmt: skip


@app.command("publish")
def publish_cmd() -> None:
    for rid in publish():
        typer.echo(rid)


@app.command("report")
def report_cmd() -> None:
    df = report()
    typer.echo(df.to_string(index=False))


if __name__ == "__main__":
    app()
