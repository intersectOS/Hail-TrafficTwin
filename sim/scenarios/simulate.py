"""One Tier B (microscopic) window simulation driven through TraCI.

The baseline and the scenario both call `run_window_sim` with the same demand, vTypes, seed and
step loop; only the event plans differ. Runs in a worker process (picklable spec in, dict out).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import sumolib
import traci.constants as tc
from traci.connection import Connection

from sim.common import REPO_ROOT, sumo_bin, sumo_env
from sim.events.base import EventContext
from sim.events.registry import build_events
from sim.runner import assert_tier_options, flatten
from sim.scenarios.outputs import (
    elements_to_parquet,
    fcd_to_parquet,
    queue_series,
    teleports_from_log,
)

CONNECT_TRIES = 600  # x CONNECT_WAIT_S: how long to wait for SUMO to open the TraCI port
CONNECT_WAIT_S = 0.05


def start_sumo(cmd: list[str], log: Path, label: str) -> Connection:
    """Start SUMO with a free TraCI port and connect (no 1 s retry sleeps as in traci.start)."""
    port = sumolib.miscutils.getFreeSocketPort()
    fh = log.open("a")
    proc = subprocess.Popen(
        [*cmd, "--remote-port", str(port)],
        stdout=fh,
        stderr=subprocess.STDOUT,
        cwd=REPO_ROOT,
        env=sumo_env(),
    )
    for _ in range(CONNECT_TRIES):
        try:
            return Connection("localhost", port, proc, None, True, label)
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"SUMO exited with {proc.returncode}; see {log}") from None
            time.sleep(CONNECT_WAIT_S)
    proc.kill()
    raise RuntimeError(f"could not connect to SUMO on port {port}")


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def run_window_sim(spec: dict[str, Any]) -> dict[str, Any]:
    """spec: run_dir, net, demand, vtypes_add, begin, end, seed, plans, sumo_common,
    tier_options, micro_cfg (runner config), edgedata_freq, distributions."""
    out = Path(spec["run_dir"])
    out.mkdir(parents=True, exist_ok=True)
    log = out / "sumo.stdout.log"
    log.unlink(missing_ok=True)
    edgedata_add = out / "edgedata.add.xml"
    edgedata_add.write_text(
        "<additional>\n"
        f'    <edgeData id="ed" freq="{spec["edgedata_freq"]}" file="edgedata.xml" '
        'excludeEmpty="true"/>\n</additional>\n'
    )
    begin, end = float(spec["begin"]), float(spec["end"])
    args = [
        "-n", _rel(spec["net"]),
        "-r", _rel(spec["demand"]),
        "--additional-files", ",".join(
            _rel(a) for a in [*spec.get("extra_additionals", []), spec["vtypes_add"], edgedata_add]
        ),
        "--begin", str(begin),
        "--end", str(end),
        "--seed", str(spec["seed"]),
        "--tripinfo-output", _rel(out / "tripinfo.xml"),
        "--statistic-output", _rel(out / "stats.xml"),
        "--log", _rel(out / "sumo.log"),
        "--fcd-output", _rel(out / "fcd.xml"),
        "--fcd-output.geo",
        "--queue-output", _rel(out / "queue.xml"),
        *flatten(spec["sumo_common"]),
        *flatten(spec["tier_options"]),
    ]  # fmt: skip
    assert_tier_options(
        "B", args, [*map(Path, spec.get("extra_additionals", [])), edgedata_add], spec["micro_cfg"]
    )
    t0 = time.perf_counter()
    conn = start_sumo([sumo_bin("sumo"), *args], log, label=f"{out.name}-{time.time_ns()}")
    ctx = EventContext(conn=conn, tier="B", t=begin, distributions=frozenset(spec["distributions"]))
    events = build_events(spec["plans"])
    edges = [e for e in conn.edge.getIDList() if not e.startswith(":")]
    for e in edges:
        conn.edge.subscribe(e, [tc.LAST_STEP_VEHICLE_HALTING_NUMBER])
    conn.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS])
    ts: dict[str, list[float]] = {"time": [], "running": [], "halted": [], "arrived": []}
    edge_halt_max: dict[str, tuple[int, float]] = {}
    try:
        for ev in events:
            ev.dispatch(ctx)
        while ctx.t < end:
            conn.simulationStep()
            ctx.t = conn.simulation.getTime()
            sim_res = conn.simulation.getSubscriptionResults()
            ctx.departed = tuple(sim_res.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
            ctx.arrived = tuple(sim_res.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
            halted = 0
            for e, r in conn.edge.getAllSubscriptionResults().items():
                h = r[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                if h:
                    halted += h
                    if h > edge_halt_max.get(e, (0, 0.0))[0]:
                        edge_halt_max[e] = (h, ctx.t)
            ts["time"].append(ctx.t)
            ts["running"].append(conn.vehicle.getIDCount())
            ts["halted"].append(halted)
            ts["arrived"].append(len(ctx.arrived))
            ctx.closures.on_step()
            for ev in events:
                ev.dispatch(ctx)
        for ev in events:
            ev.close(ctx, horizon=True)
    finally:
        conn.close()
    sim_wall = time.perf_counter() - t0

    t1 = time.perf_counter()
    fcd_rows = fcd_to_parquet(out / "fcd.xml", out / "fcd.parquet")
    queues = queue_series(out / "queue.xml")
    elements_to_parquet(out / "tripinfo.xml", "tripinfo", out / "tripinfo.parquet")
    elements_to_parquet(out / "edgedata.xml", "edge", out / "edgedata.parquet", ("begin", "end"))
    series = dict(ts)
    qmap = dict(zip(queues["time"], queues["max_queue_m"], strict=False))
    series["max_queue_m"] = [qmap.get(t, 0.0) for t in ts["time"]]
    pq.write_table(pa.table(series), out / "timeseries.parquet", compression="zstd")
    post_wall = time.perf_counter() - t1
    return {
        "run_dir": str(out),
        "series": series,
        "edge_halt_max": edge_halt_max,
        "edge_queue_max": queues["edge_max"],
        "teleport_events": teleports_from_log(out / "sumo.log"),
        "event_log": ctx.log,
        "event_summaries": {ev.id: ev.summary for ev in events},
        "reroutes": {
            "rerouted": ctx.closures.rerouted,
            "failed": ctx.closures.reroute_failures,
        },
        "fcd_rows": fcd_rows,
        "sim_wall_s": round(sim_wall, 2),
        "post_wall_s": round(post_wall, 2),
    }
