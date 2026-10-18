"""Situation snapshot: run the window from its begin to the dispatch time T with the scenario's
background events (not the strategist trip), save the SUMO state and measure the network at T.

Cached under runs/strategist/snapshots/<key>/ where key = hash(scenario events, window, seed,
net / demand / additional hashes, vTypes and mix, SUMO options, T). Warm-up runs without FCD and
without per-edge subscriptions (the cost of the M5 window runs). Measured at T and stored in
snapshot.json: per-edge mean travel time over [T - A-strat-001, T) (SUMO edgeData), halted
vehicles per edge and instantaneous travel time per edge (TraCI) at T.
"""

from __future__ import annotations

import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import traci.constants as tc

from sim.common import SYNTHETIC_LABEL, file_hash, rel, sumo_bin, sumo_version
from sim.events.base import EventContext
from sim.events.registry import build_events
from sim.metrics import xml_content_hash
from sim.scenarios.simulate import start_sumo
from sim.vtypes.loader import apply_mix, write_vtypes_additional
from strategist import config as C
from strategist.fork import sumo_args
from strategist.situation import Situation

SNAPSHOT_DIR = C.RUNS_DIR / "snapshots"
STATE_FILE = "state.xml.gz"
META_FILE = "snapshot.json"


def base_spec(sit: Situation, snap_dir: Path) -> dict[str, Any]:
    """Picklable inputs shared by warm-up and forks (paths inside the snapshot directory)."""
    return {
        "net": str(sit.net),
        "demand": str(snap_dir / "demand.rou.xml"),
        "vtypes_add": str(snap_dir / "vtypes.add.xml"),
        "extra_additionals": [str(p) for p in sit.extra_adds],
        "seed": sit.seed,
        "sumo_common": sit.runner_cfg["sumo_common"],
        "tier_options": sit.runner_cfg["tier_B"]["options"] + sit.sumo_options,
        "micro_cfg": sit.runner_cfg,
        "distributions": [sit.lib.distribution_id],
        "end": float(sit.scenario.end),
    }


def _edgedata(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not path.exists():
        return out
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "edge" and el.get("traveltime") is not None:
            out[el.get("id", "")] = {
                "traveltime": float(el.get("traveltime", 0)),
                "speed": float(el.get("speed", 0)),
                "sampledSeconds": float(el.get("sampledSeconds", 0)),
            }
        el.clear()
    return out


def warm_up(sit: Situation, snap_dir: Path) -> dict[str, Any]:
    """Run begin -> T, save the state, measure; returns the snapshot record."""
    t_dispatch = sit.t_dispatch
    window_s = float(C.value("snapshot", "edge_tt_window_s"))
    snap_dir.mkdir(parents=True, exist_ok=True)
    write_vtypes_additional(snap_dir / "vtypes.add.xml", sit.mix, "B", sit.lib)
    demand_counts = apply_mix(sit.demand_src, snap_dir / "demand.rou.xml", sit.lib.distribution_id)
    tt_add = snap_dir / "edgett.add.xml"
    tt_begin = max(float(sit.scenario.begin), t_dispatch - window_s)
    tt_add.write_text(
        "<additional>\n"
        f'    <edgeData id="strategist_tt" begin="{tt_begin}" end="{t_dispatch}" '
        f'file="edgett.xml" excludeEmpty="true"/>\n</additional>\n'
    )
    spec = {**base_spec(sit, snap_dir), "run_additionals": [str(tt_add)]}
    args = sumo_args(
        spec,
        [
            "--begin", str(sit.scenario.begin),
            "--end", str(sit.scenario.end),
            "--save-state.rng",
            "--save-state.precision", str(C.model("save_state_precision")),
            "--log", rel(snap_dir / "warmup.log"),
        ],
    )  # fmt: skip
    t0 = time.perf_counter()
    conn = start_sumo(
        [sumo_bin("sumo"), *args], snap_dir / "warmup.stdout.log", f"warm-{sit.key()}"
    )
    ctx = EventContext(
        conn=conn,
        tier="B",
        t=float(sit.scenario.begin),
        distributions=frozenset(spec["distributions"]),
    )
    events = build_events(sit.plans)
    conn.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS])
    try:
        for ev in events:
            ev.dispatch(ctx)
        while ctx.t < t_dispatch:
            conn.simulationStep()
            ctx.t = conn.simulation.getTime()
            res = conn.simulation.getSubscriptionResults()
            ctx.departed = tuple(res.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
            ctx.arrived = tuple(res.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
            ctx.closures.on_step()
            for ev in events:
                ev.dispatch(ctx)
        warm_s = time.perf_counter() - t0
        t1 = time.perf_counter()
        conn.simulation.saveState(str(snap_dir / STATE_FILE))
        edges = [e for e in conn.edge.getIDList() if not e.startswith(":")]
        halted = {}
        tt_now = {}
        for e in edges:
            h = conn.edge.getLastStepHaltingNumber(e)
            if h:
                halted[e] = h
            tt_now[e] = round(conn.edge.getTraveltime(e), 3)
        running = conn.vehicle.getIDCount()
        pending = len(conn.simulation.getPendingVehicles())
        closed_lanes = sorted(
            ln
            for p in sit.plans
            for ln in p.get("closed_lanes", [])
            if not conn.lane.getAllowed(ln)
        )
        tls_state = {
            t: {"program": conn.trafficlight.getProgram(t), "phase": conn.trafficlight.getPhase(t)}
            for t in conn.trafficlight.getIDList()
        }
        measure_s = time.perf_counter() - t1
    finally:
        conn.close()
    tt_mean = _edgedata(snap_dir / "edgett.xml")
    record = {
        "label": SYNTHETIC_LABEL,
        "snapshot_id": snap_dir.name,
        "scenario": sit.scenario.id,
        "fictional": sit.scenario.fictional,
        "window": sit.window,
        "seed": sit.seed,
        "t_dispatch": t_dispatch,
        "edge_tt_window": [tt_begin, t_dispatch],
        "state_file": rel(snap_dir / STATE_FILE),
        "state_hash": state_hash(snap_dir / STATE_FILE),
        "population_hash": file_hash(snap_dir / "demand.rou.xml"),
        "demand_counts": demand_counts,
        "sumo_version": sumo_version(),
        **sit.hashes(),
        "key_material_hash": sit.key(),
        "background_events": [p["id"] for p in sit.plans],
        "measured_at_t": {
            "running": running,
            "pending_insertion": pending,
            "halted_by_edge": halted,
            "halted_total": sum(halted.values()),
            "closed_lanes": closed_lanes,
            "tls": tls_state,
        },
        "wall_s": {"warm_up": round(warm_s, 2), "save_and_measure": round(measure_s, 2)},
    }
    (snap_dir / "edge_tt.json").write_text(
        json.dumps({"mean_over_window": tt_mean, "instant_at_t": tt_now})
    )
    (snap_dir / META_FILE).write_text(json.dumps(record, indent=2))
    return record


def load_edge_tt(snap_dir: Path) -> dict[str, Any]:
    return json.loads((snap_dir / "edge_tt.json").read_text())


def state_hash(path: Path) -> str:
    """Hash of the saved state without its SUMO header comment (date, TraCI port, paths)."""
    return xml_content_hash(path)


def state_matches(path: Path, recorded: str | None) -> bool:
    """Current header-free hash, or the whole-file hash recorded before integration."""
    return recorded is not None and recorded in (state_hash(path), file_hash(path))


def get_snapshot(
    sit: Situation, fresh: bool = False, root: Path = SNAPSHOT_DIR
) -> tuple[dict[str, Any], Path, bool]:
    """(record, snapshot dir, reused?) - builds the snapshot unless a valid cached one exists."""
    snap_dir = root / sit.key()
    meta = snap_dir / META_FILE
    if not fresh and meta.exists() and (snap_dir / STATE_FILE).exists():
        record = json.loads(meta.read_text())
        if state_matches(snap_dir / STATE_FILE, record.get("state_hash")):
            return record, snap_dir, True
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    return warm_up(sit, snap_dir), snap_dir, False
