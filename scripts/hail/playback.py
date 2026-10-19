"""Vehicle playback files for the "جرّب بنفسك" page (site/try.html).

For each Tier B scenario or evacuation run that has FCD, writes under <out>/:
  index.json            the list of playable runs with their window, event start and labels
  <id>.json             the window's roads (quantised polylines), clock and per-second counters
  <id>.<side>.bin       vehicles of one side (base = without the event, scen = with it), TTV1:
                        magic, n_veh u32, t0 f32, step f32, n_frames u32; per vehicle: start frame
                        u32, n u32, n x (x u16, y u16), n x speed u8 (km/h), padded to 4 bytes.
Only simulated positions are written (every `step` seconds, no interpolation in the file).
Synthetic demand, uncalibrated.

    python -m scripts.hail.playback --runs runs --out _site/data/play
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import typer

HIDDEN = set(__import__("json").loads((Path(__file__).resolve().parents[2] / "site" / "hidden.json").read_text())["ids"])

from scripts.hail.stories import Stories, parse_edges_bin

STEP_S = 3.0
BEFORE_S = 300.0
AFTER_S = 1500.0
app = typer.Typer(add_completion=False, help=__doc__)


def _read(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def pack_side(fcd: Path, t0: float, t1: float, frame: dict[str, float]) -> tuple[bytes, dict[str, list[float]]]:
    t = pq.read_table(fcd, columns=["time", "id", "lon", "lat", "speed"]).to_pandas()
    t = t[(t["time"] >= t0) & (t["time"] < t1)]
    t = t[np.isclose(np.mod(t["time"] - t0, STEP_S), 0) | np.isclose(np.mod(t["time"] - t0, STEP_S), STEP_S)]
    w, n, span = frame["w"], frame["n"], frame["span"]
    t["x"] = np.clip(np.rint((t["lon"] - w) / span * 10000), 0, 65535).astype("<u2")
    t["y"] = np.clip(np.rint((n - t["lat"]) / span * 10000), 0, 65535).astype("<u2")
    t["f"] = np.rint((t["time"] - t0) / STEP_S).astype(int)
    t["v"] = np.clip(np.rint(t["speed"] * 3.6), 0, 255).astype("u1")
    t = t.sort_values(["id", "f"])
    n_frames = int(round((t1 - t0) / STEP_S))
    body: list[bytes] = []
    n_veh = 0
    for _vid, g in t.groupby("id", sort=False):
        f = g["f"].to_numpy()
        # split at gaps (a vehicle that leaves and re-enters the window) so frames stay consecutive
        cuts = np.flatnonzero(np.diff(f) != 1) + 1
        for part in np.split(np.arange(len(g)), cuts):
            if len(part) < 2:
                continue
            gg = g.iloc[part]
            xy = np.column_stack((gg["x"].to_numpy(), gg["y"].to_numpy())).astype("<u2").tobytes()
            sp = gg["v"].to_numpy().astype("u1").tobytes()
            chunk = struct.pack("<II", int(gg["f"].iloc[0]), len(part)) + xy + sp
            body.append(chunk + b"\0" * (-len(chunk) % 4))
            n_veh += 1
    # counters per frame: vehicles in the window and how many are stopped (< 5 km/h)
    running = np.bincount(t["f"], minlength=n_frames)[:n_frames]
    stopped = np.bincount(t["f"][t["v"] < 5], minlength=n_frames)[:n_frames]
    head = b"TTV1" + struct.pack("<IffI", n_veh, t0, STEP_S, n_frames)
    return head + b"".join(body), {"running": running.tolist(), "stopped": stopped.tolist()}


def event_marks(S: Stories, nhash: str, rep: dict[str, Any], frame: dict[str, float]) -> list[dict[str, Any]]:
    """Where each event acts: closed edges as points, motorcade / ambulance routes as lines,
    evacuation zones as polygons, in the playback's 0..10000 frame."""
    info = S.get(f"/api/networks/{nhash}/edges.json").json()
    starts, pos = parse_edges_bin(S.get(f"/api/networks/{nhash}/edges.bin").content)
    idx = {e: i for i, e in enumerate(info["edge_ids"])}
    w, n, span = frame["w"], frame["n"], frame["span"]

    def q(lon: float, lat: float) -> list[int]:
        return [int(round((lon - w) / span * 10000)), int(round((n - lat) / span * 10000))]

    def line(edges: list[str]) -> list[int]:
        pts: list[int] = []
        for e in edges:
            i = idx.get(e)
            if i is None:
                continue
            for lon, lat in pos[starts[i] : starts[i + 1]]:
                pts.extend(q(float(lon), float(lat)))
        return pts

    marks: list[dict[str, Any]] = []
    for ev in rep.get("events") or []:
        t = ev.get("type")
        if t in ("accident", "flood"):
            edges = ev.get("edges") or ev.get("closed_edges") or []
            for e in edges[:12]:
                pts = line([e])
                if pts:
                    k = len(pts) // 4 * 2
                    marks.append({"type": t, "t": ev.get("start"), "end": ev.get("end"), "pt": pts[k : k + 2]})
        elif t in ("motorcade", "emergency_trip") and ev.get("route"):
            marks.append({"type": t, "t": ev.get("start"), "end": ev.get("end"), "line": line(ev["route"])})
    evac = rep.get("evacuation")
    if isinstance(evac, dict) and evac.get("zone"):
        marks.append({"type": "evacuation", "t": evac.get("order_t"), "poly": [c for lon, lat in evac["zone"] for c in q(lon, lat)]})
    return marks


def build(runs: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    S = Stories()
    index = []
    for d in sorted(p for p in runs.iterdir() if p.is_dir()):
        rid = d.name
        sc, ev = _read(d / "scenario_report.json"), _read(d / "evacuation_report.json")
        rep = sc or ev
        if not rep or "demo" in rid and not __import__("os").environ.get("STORIES_DEMO"):
            continue
        scen = d / ("scenario" if sc else "evacuation") / "fcd.parquet"
        base = d / ("baseline" if sc else "reference") / "fcd.parquet"
        if not scen.exists():
            continue
        starts = [float(e.get("start", 0)) for e in rep.get("events", []) if isinstance(e, dict) and e.get("start") is not None]
        if ev and isinstance(rep.get("evacuation"), dict):
            ev_ = rep["evacuation"]
            starts.append(float(ev_.get("order_t") if ev_.get("order_t") is not None else ev_.get("start", 0)))
        t_event = min(starts) if starts else 0.0
        t0 = max(0.0, t_event - BEFORE_S)
        t1 = min(float(rep.get("end") or 3600), t_event + AFTER_S)
        run = next((r for r in S.get("/api/runs").json() if r["run_id"] == rid), None)
        if run is None:
            continue
        S.geometry(run["network_hash"], "B")
        geom = S.geoms[f"{run['network_hash']}:B"]
        w, s_, e, n = geom["bbox"]
        frame = {"w": w, "n": n, "span": geom["span"]}
        sid = rep.get("scenario") or rid.split("-")[0]
        if sid in HIDDEN:
            continue
        sides: dict[str, Any] = {}
        for side, fcd in (("scen", scen), ("base", base)):
            if fcd.exists():
                blob, counters = pack_side(fcd, t0, t1, frame)
                (out / f"{sid}.{side}.bin").write_bytes(blob)
                sides[side] = {"file": f"{sid}.{side}.bin", "kb": len(blob) // 1024, **counters}
        (out / f"{sid}.json").write_text(json.dumps(
            {"id": sid, "run": rid, "kind": "scenario" if sc else "evacuation", "title": rep.get("title") or rep.get("label"),
             "clock0_s": 8 * 3600, "t0": t0, "t1": t1, "t_event": t_event, "step": STEP_S,
             "bbox": geom["bbox"], "span": geom["span"], "lines": geom["lines"], "sides": sides,
             "marks": event_marks(S, run["network_hash"], rep, frame)}, ensure_ascii=False,
            separators=(",", ":")))
        index.append({"id": sid, "kind": "scenario" if sc else "evacuation", "t_event": t_event,
                      "sides": list(sides), "kb": sum(v["kb"] for v in sides.values())})
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return {"playable": index}


@app.command()
def main(runs: Path = typer.Option(Path("runs")), out: Path = typer.Option(Path("_site/data/play"))) -> None:
    typer.echo(json.dumps(build(runs, out), ensure_ascii=False))


if __name__ == "__main__":
    app()
