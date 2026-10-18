"""Window (Tier B) KPIs from one simulation's outputs, and baseline-vs-scenario deltas.

Definitions
- Background vehicles = demand vehicles (event vehicles `ev.*` excluded). Travel time and delay
  (SUMO timeLoss) are means over background trips completed before the end.
- VKT / VHT from edgeData (all vehicles in the window, including unfinished ones):
  VKT = sum(sampledSeconds x speed) / 1000, VHT = sum(sampledSeconds) / 3600; mean speed = VKT/VHT.
- Queue (m): per step the longest edge queue in the window (SUMO queue-output, longest lane of
  the edge); `queue_max_m` = its maximum, `queue_p95_m` = its 95th percentile over steps.
- Queue (vehicles): halted vehicles (TraCI edge subscription, every step). `queue_max_veh` =
  most halted vehicles on one edge at any step; `halted_p95_veh` = 95th percentile over steps of
  all halted vehicles in the window. Top edges are ranked by max queue (m).
- Gridlock (rules in kpis.yaml): (a) sustained halt: halted >= max(share x running, min vehicles)
  for sustain_s; (b) jam teleports >= jam_teleports_min within one throughput bin (isolated
  jam teleports are micro-model artefacts); (c) throughput collapse vs baseline. Jam teleports
  are also reported on their own (`teleports_jam`).
  Onset = first time a rule fires.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from sim.common import REPO_ROOT, load_yaml
from sim.events.base import EVENT_VEHICLE_PREFIX
from sim.runner import parse_statistics
from sim.scenarios.outputs import p95
from sim.vtypes.schema import Param

KPI_FILE = REPO_ROOT / "sim" / "scenarios" / "kpis.yaml"


@cache
def kpi_rules() -> dict[str, Any]:
    return load_yaml(KPI_FILE)


def gridlock_params() -> dict[str, float]:
    g = kpi_rules()["gridlock"]
    return {k: float(Param.model_validate(v).value) for k, v in g.items()}


def kpi_assumption_ids() -> list[str]:
    return [Param.model_validate(v).id for v in kpi_rules()["gridlock"].values()]


def _table(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist() if path.exists() else []


def sustained_halt_onset(series: dict[str, list[float]], g: dict[str, float]) -> float | None:
    run_start = None
    for t, running, halted in zip(
        series["time"], series["running"], series["halted"], strict=False
    ):
        threshold = max(g["halted_share_min"] * running, g["halted_vehicles_min"])
        if halted >= threshold and running > 0:
            run_start = t if run_start is None else run_start
            if t - run_start >= g["sustain_s"]:
                return run_start
        else:
            run_start = None
    return None


def jam_teleport_onset(times: list[float], g: dict[str, float]) -> float | None:
    """Time of the jam teleport that brings one throughput bin to `jam_teleports_min`."""
    need, bin_s = int(g["jam_teleports_min"]), g["throughput_bin_s"]
    counts: dict[int, int] = {}
    for t in sorted(times):
        b = int(t // bin_s)
        counts[b] = counts.get(b, 0) + 1
        if counts[b] >= need:
            return t
    return None


def arrivals_per_bin(series: dict[str, list[float]], bin_s: float) -> dict[int, int]:
    out: dict[int, int] = {}
    for t, a in zip(series["time"], series["arrived"], strict=False):
        b = int((t - 1e-9) // bin_s)
        out[b] = out.get(b, 0) + int(a)
    return out


def window_kpis(sim: dict[str, Any], top_n: int | None = None) -> dict[str, Any]:
    run = Path(sim["run_dir"])
    top_n = top_n or int(kpi_rules()["queues"]["top_edges"])
    stats = parse_statistics(run / "stats.xml")
    trips = _table(run / "tripinfo.parquet")
    bg = [r for r in trips if not str(r["id"]).startswith(EVENT_VEHICLE_PREFIX)]
    n = len(bg)
    edges = _table(run / "edgedata.parquet")
    vkt = (
        sum(float(r.get("sampledSeconds") or 0) * float(r.get("speed") or 0) for r in edges) / 1000
    )
    vht = sum(float(r.get("sampledSeconds") or 0) for r in edges) / 3600
    series = sim["series"]
    g = gridlock_params()
    jam = [x for x in sim["teleport_events"] if x["reason"] == "jam"]
    halt_onset = sustained_halt_onset(series, g)
    jam_onset = jam_teleport_onset([x["t"] for x in jam], g)
    qmax = sim["edge_queue_max"]
    top = sorted(qmax.items(), key=lambda kv: (-kv[1][0], kv[0]))[:top_n]
    hmax = sim["edge_halt_max"]
    veh = stats["vehicles"]
    tel = stats["teleports"]
    return {
        "vehicles_loaded": int(veh.get("loaded", 0)),
        "vehicles_inserted": int(veh.get("inserted", 0)),
        "vehicles_running_at_end": int(veh.get("running", 0)),
        "vehicles_waiting_at_end": int(veh.get("waiting", 0)),
        "background_completed": n,
        "mean_travel_time_s": round(sum(float(r["duration"]) for r in bg) / n, 2) if n else None,
        "mean_delay_s": round(sum(float(r["timeLoss"]) for r in bg) / n, 2) if n else None,
        "mean_depart_delay_s": round(sum(float(r["departDelay"]) for r in bg) / n, 2)
        if n
        else None,
        "mean_speed_kmh": round(vkt / vht, 2) if vht else None,
        "vkt": round(vkt, 1),
        "vht": round(vht, 2),
        "teleports": int(tel.get("total", 0)),
        "teleports_jam": int(tel.get("jam", 0)),
        "teleport_share": round(int(tel.get("total", 0)) / int(veh.get("loaded", 1) or 1), 5),
        "queue_max_m": round(max(series["max_queue_m"], default=0.0), 1),
        "queue_p95_m": round(p95(series["max_queue_m"]), 1),
        "queue_max_veh": max((h for h, _ in hmax.values()), default=0),
        "halted_max_veh": int(max(series["halted"], default=0)),
        "halted_p95_veh": round(p95(series["halted"]), 1),
        "top_queued_edges": [
            {
                "edge": e,
                "max_queue_m": round(q, 1),
                "at_s": t,
                "max_halted_veh": hmax.get(e, (0, 0))[0],
            }
            for e, (q, t) in top
        ],
        "gridlock_sustained_halt_onset_s": halt_onset,
        "gridlock_jam_teleport_onset_s": jam_onset,
        "rerouted_vehicles": sim["reroutes"]["rerouted"],
        "reroute_failures": sim["reroutes"]["failed"],
    }


def emergency_kpis(sim: dict[str, Any], plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trips = {r["id"]: r for r in _table(Path(sim["run_dir"]) / "tripinfo.parquet")}
    out = []
    for p in plans:
        if p["type"] != "emergency_trip":
            continue
        for vid in p["vehicle_ids"]:
            r = trips.get(vid)
            tt = float(r["duration"]) if r else None
            out.append(
                {
                    "event": p["id"],
                    "vehicle": vid,
                    "completed": r is not None,
                    "travel_time_s": tt,
                    "depart_delay_s": float(r["departDelay"]) if r else None,
                    "free_flow_s": round(p["ff_total_s"], 2),
                    "ratio_to_free_flow": round(tt / p["ff_total_s"], 3) if tt else None,
                    "strategist": p["strategist"],
                }
            )
    return out


def convoy_kpis(sim: dict[str, Any], plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trips = {r["id"]: r for r in _table(Path(sim["run_dir"]) / "tripinfo.parquet")}
    out = []
    for p in plans:
        if p["type"] != "motorcade":
            continue
        tts = [float(trips[v]["duration"]) for v in p["vehicle_ids"] if v in trips]
        out.append(
            {
                "event": p["id"],
                "completed": len(tts),
                "vehicles": len(p["vehicle_ids"]),
                "mean_travel_time_s": round(sum(tts) / len(tts), 1) if tts else None,
                "free_flow_s": round(p["ff_total_s"], 1),
            }
        )
    return out


def edge_flows(sim: dict[str, Any], edges: list[str]) -> dict[str, float]:
    rows = _table(Path(sim["run_dir"]) / "edgedata.parquet")
    flows = dict.fromkeys(edges, 0.0)
    for r in rows:
        if r.get("id") in flows:
            flows[r["id"]] += float(r.get("entered") or 0)
    return flows


def throughput_collapse_onset(base: dict[str, Any], scen: dict[str, Any]) -> float | None:
    g = gridlock_params()
    bin_s = g["throughput_bin_s"]
    b = arrivals_per_bin(base["series"], bin_s)
    s = arrivals_per_bin(scen["series"], bin_s)
    for k in sorted(b):
        if (
            b[k] >= g["throughput_min_baseline_arrivals"]
            and s.get(k, 0) < g["throughput_collapse_ratio"] * b[k]
        ):
            return k * bin_s
    return None


DELTA_KEYS = (
    "vehicles_inserted",
    "background_completed",
    "mean_travel_time_s",
    "mean_delay_s",
    "mean_depart_delay_s",
    "vehicles_waiting_at_end",
    "mean_speed_kmh",
    "vkt",
    "vht",
    "teleports",
    "queue_max_m",
    "queue_p95_m",
    "queue_max_veh",
    "halted_p95_veh",
)


def deltas(base: dict[str, Any], scen: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in DELTA_KEYS:
        a, b = base.get(k), scen.get(k)
        if isinstance(a, int | float) and isinstance(b, int | float):
            out[k] = {
                "delta": round(b - a, 3),
                "pct": round(100 * (b - a) / a, 2) if a else None,
            }
    return out


def gridlock_flag(k: dict[str, Any], collapse_onset: float | None) -> dict[str, Any]:
    onsets = {
        "sustained_halt": k["gridlock_sustained_halt_onset_s"],
        "jam_teleports": k["gridlock_jam_teleport_onset_s"],
        "throughput_collapse": collapse_onset,
    }
    fired = {r: t for r, t in onsets.items() if t is not None}
    return {
        "gridlock": bool(fired),
        "onset_s": min(fired.values()) if fired else None,
        "rules_fired": fired,
    }
