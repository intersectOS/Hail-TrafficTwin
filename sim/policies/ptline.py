"""`pt_line` policies: a bus line built with SUMO's ptlines2flows.py.

Stops are given as (lon, lat) points; each is snapped, per direction, to the nearest edge whose
lane 0 allows buses and whose heading follows the line. ptlines2flows.py runs on a sub-network cut
around the line (edge ids match the city network; it computes stop times with a short SUMO run, so
the city net is not loaded into Python). Its flows join the policy run as an extra route file and
its stops as an additional file. Bus vehicles are real vehicles in a sampled, capacity-scaled run,
so each bus uses the road like 1/sample cars (conservative; noted in the report).
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import quoteattr

import numpy as np

from sim.common import python_tool_cmd, run_cmd, sumo_bin
from sim.policies.edges import utm_xy
from sim.policies.netedit import NETCONVERT_OPTIONS
from sim.policies.transforms import Plan
from sim.schemas import PtLine, hhmm_to_s

SNAP_MAX_M = 200.0
MARGIN_DEG = 0.015  # sub-network margin around the stops (~1.5 km)


def snap_stops(plan: Plan, t: PtLine, reverse: bool) -> list[tuple[str, float]]:
    """(edge id, lane length) per stop for one direction."""
    e = plan.edges()
    cand = e[e["bus"] & (e["length"] >= 25.0) & ~e["edge_id"].str.startswith(":")]
    ex0, ey0 = utm_xy(cand["lon0"].to_numpy(), cand["lat0"].to_numpy())
    ex1, ey1 = utm_xy(cand["lon1"].to_numpy(), cand["lat1"].to_numpy())
    mx, my = utm_xy(cand["lon"].to_numpy(), cand["lat"].to_numpy())
    hx, hy = ex1 - ex0, ey1 - ey0
    hn = np.hypot(hx, hy) + 1e-9
    stops = t.stops[::-1] if reverse else t.stops
    sx, sy = utm_xy(np.array([s.lon for s in stops]), np.array([s.lat for s in stops]))
    out = []
    for i in range(len(stops)):
        a, b = max(i - 1, 0), min(i + 1, len(stops) - 1)
        dx, dy = sx[b] - sx[a], sy[b] - sy[a]
        cos = (hx * dx + hy * dy) / (hn * (np.hypot(dx, dy) + 1e-9))
        dist = np.hypot(mx - sx[i], my - sy[i])
        score = np.where(cos > 0.5, dist, np.inf)
        k = int(score.argmin())
        if not np.isfinite(score[k]) or score[k] > SNAP_MAX_M:
            raise ValueError(f"pt_line {t.line_id}: no bus edge near stop {stops[i].name!r}")
        out.append((str(cand["edge_id"].iloc[k]), float(cand["length"].iloc[k])))
    return out


def build_line(plan: Plan, t: PtLine) -> dict[str, Any]:
    work = plan.work / f"pt_{t.line_id}"
    work.mkdir(parents=True, exist_ok=True)
    directions = [("f", False), ("r", True)] if t.both_directions else [("f", False)]
    stop_lines, line_lines = ["<additional>"], ["<ptLines>"]
    lons, lats, groups = [], [], []
    for tag, rev in directions:
        snapped = snap_stops(plan, t, rev)
        stops = t.stops[::-1] if rev else t.stops
        line_lines.append(
            f'    <ptLine id="{t.line_id}_{tag}" name={quoteattr(t.line_id)} '
            f'line="{t.line_id}" type="bus" period="{t.headway_s:g}" completeness="1">'
        )
        for i, ((edge, length), stop) in enumerate(zip(snapped, stops, strict=True)):
            sid = f"{t.line_id}_{tag}_{i}"
            mid = length / 2.0
            stop_lines.append(
                f'    <busStop id="{sid}" lane="{edge}_0" startPos="{max(mid - 10, 0):.1f}" '
                f'endPos="{min(mid + 10, length):.1f}" name={quoteattr(stop.name)} '
                f'lines="{t.line_id}"/>'
            )
            line_lines.append(f'        <busStop id="{sid}" name={quoteattr(stop.name)}/>')
            lons.append(stop.lon)
            lats.append(stop.lat)
            groups.append(len(t.stops) - 1 - i if rev else i)
        line_lines.append("    </ptLine>")
    stop_lines.append("</additional>")
    line_lines.append("</ptLines>")
    stops_file = work / "stops.add.xml"
    lines_file = work / "ptlines.xml"
    stops_file.write_text("\n".join(stop_lines) + "\n")
    lines_file.write_text("\n".join(line_lines) + "\n")
    # sub-network around the line (same edge ids), so ptlines2flows stays small
    x0, x1 = min(lons) - MARGIN_DEG, max(lons) + MARGIN_DEG
    y0, y1 = min(lats) - MARGIN_DEG, max(lats) + MARGIN_DEG
    sub = work / "sub.net.xml.gz"
    log = work / "ptlines2flows.log"
    run_cmd(
        [sumo_bin("netconvert"), "-s", str(plan.net), "-o", str(sub),
         "--keep-edges.in-geo-boundary", f"{x0},{y0},{x1},{y1}", *NETCONVERT_OPTIONS],
        log=log,
    )  # fmt: skip
    h0, h1 = hhmm_to_s(t.hours[0]), hhmm_to_s(t.hours[1])
    flows = work / "flows.rou.xml"
    run_cmd(
        python_tool_cmd(
            "ptlines2flows.py",
            "-n", str(sub), "-l", str(lines_file), "-s", str(stops_file),
            "-o", str(flows), "-t", str(work / "trips.xml"), "-r", str(work / "vehroutes.xml"),
            "-i", str(work / "stopinfos.xml"), "-p", f"{t.headway_s:g}",
            "-b", f"{h0:.0f}", "-e", f"{h1:.0f}", "--vtype-prefix", "pt_",
            "-d", f"{t.stop_duration_s:g}", "--seed", str(plan.seed), "--min-stops", "2",
        ),
        log=log,
    )  # fmt: skip
    if "<flow" not in flows.read_text():
        raise RuntimeError(f"ptlines2flows produced no flows for {t.line_id} (see {log})")
    plan.additional.append(stops_file)
    plan.extra_routes.append(flows)
    return {
        "stop_lon": np.array(lons),
        "stop_lat": np.array(lats),
        "stop_group": np.array(groups),
        "directions": len(directions),
        "departures": int(len(directions) * np.ceil((h1 - h0) / t.headway_s)),
        "flows": flows,
    }
