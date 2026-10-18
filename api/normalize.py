"""Map what the producers actually write to the contract shapes (docs/contracts/run-outputs.md §12).

One place for every producer-specific rule, so `api.runs` and the routers only see contract
shapes. Every function is pure (dicts in, dicts out) except `policy_districts`, which reads the
small `policy_districts.parquet`. Unknown keys are passed through; nothing here writes files.

Producers covered: `sim.runner` smoke runs (already v1), Track A baselines and policy runs
(`sim.population.baseline`, `sim.policies.run` / `report`), Track B scenario runs
(`sim.scenarios.run`), evacuation runs (`sim.events.evacuation` via `sim.scenarios.run`) and the
strategist (`strategist.run`, `strategist.evacuation`).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from api import settings
from sim.common import REPO_ROOT

PCT = 100.0  # unit conversion
WORKTREE_RE = re.compile(r"/\.worktrees/[^/]+/(.+)$")

# metric key -> unit; exact names first, then suffixes (order matters: "_ms" before "_s")
EXACT_UNITS = {
    "vkt": "veh-km",
    "vht": "veh-h",
    "vht_delay": "veh-h",
    "teleports": "veh",
    "teleports_jam": "veh",
    "teleports_evacuees": "veh",
    "reroutes": "veh",
    "rerouted_vehicles": "veh",
    "vehicles": "veh",
    "out": "veh",
    "peak_hour": "h",
}
SUFFIX_UNITS = (
    ("_kmh", "km/h"),
    ("_ms", "m/s"),
    ("_veh_h", "veh-h"),
    ("_veh_km", "veh/km"),
    ("_seconds", "s"),
    ("_s", "s"),
    ("_km", "km"),
    ("_m", "m"),
    ("_share", "-"),
    ("_factor", "-"),
    ("_pct", "%"),
    ("_t", "t"),
    ("_kg", "kg"),
    ("_veh", "veh"),
)
EVENT_TYPES = ("accident", "rain", "flood", "motorcade", "closure", "evacuation", "other")
# strategist classification -> contract action_class
ACTION_CLASS = {
    "approval_required": "high_impact",
    "auto_eligible": "advisory",
    "none": "advisory",
}
REC_ID_RE = re.compile(r"^rec-(\d{8})T(\d{6})Z")


def unit(key: str) -> str:
    if key in EXACT_UNITS:
        return EXACT_UNITS[key]
    for suffix, u in SUFFIX_UNITS:
        if key.endswith(suffix):
            return u
    return ""


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def metric_dict(values: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """{key: number} -> §3 {key: {value, unit}} (numbers only, sorted)."""
    return {k: {"value": v, "unit": unit(k)} for k, v in sorted((values or {}).items()) if _num(v)}


# ------------------------------------------------------------------------- paths and meta
def repo_relative(path: str) -> str:
    """Absolute paths into this repo or a track worktree -> repo-relative (contract §2)."""
    p = str(path)
    if not p.startswith("/"):
        return p
    m = WORKTREE_RE.search(p)
    if m:
        return m.group(1)
    try:
        return str(Path(p).relative_to(REPO_ROOT))
    except ValueError:
        return p


def resolve_network(path: str) -> Path:
    """The .net.xml for a meta path: repo-relative first, then the original absolute path."""
    rel = settings.resolve_repo_path(repo_relative(path))
    if rel.is_file():
        return rel
    orig = Path(path)
    return orig if orig.is_absolute() and orig.is_file() else rel


def _int(v: Any) -> int | None:
    return int(round(float(v))) if _num(v) else None


def normalise_meta(
    raw: dict[str, Any],
    run_id: str,
    *,
    report: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Contract §2 view of a producer meta.json (additive: original keys kept)."""
    meta = dict(raw)
    if raw.get("run_id") not in (None, run_id):
        meta["producer_run_id"] = raw["run_id"]
    meta["run_id"] = run_id
    meta.setdefault("label", settings.LABEL)
    if not meta.get("kind"):
        meta["kind"] = "other"
    if meta.get("network"):
        rel = repo_relative(str(meta["network"]))
        if rel != meta["network"]:
            meta["network_original"] = meta["network"]
            meta["network"] = rel
    # producer key -> contract key
    if isinstance(raw.get("scenario"), str):
        meta.setdefault("scenario_id", raw["scenario"])
    if isinstance(raw.get("policy"), str):
        meta.setdefault("policy_id", raw["policy"])
    if raw.get("daytype") is not None:
        meta.setdefault("day_type", raw["daytype"])
    if _num(raw.get("sample")):
        meta.setdefault("sample_fraction", raw["sample"])
    if raw.get("compare_baseline"):
        meta.setdefault("baseline_run_id", raw["compare_baseline"])
    rep = report or {}
    begin = _int(meta.get("begin_s"))
    if begin is None:
        begin = _int(rep.get("begin")) or 0
        meta["begin_s"] = begin
    if not _num(meta.get("sim_seconds")):
        end = None
        for key in ("run_end_s", "sim_end_s"):
            end = end if end is not None else _int(raw.get(key))
        if end is None:
            end = _int(rep.get("end"))
        if end is not None:
            meta["sim_seconds"] = max(0, end - begin)
    meta.update(overrides or {})
    return meta


# ------------------------------------------------------------------------- metrics (§3)
def metrics_from_file(data: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    """metrics.json in contract shape, or the Track A shape {"summary": {...}, "hourly": [...]}."""
    out = dict(data)
    out.setdefault("label", settings.LABEL)
    out.setdefault("run_id", run_id)
    m = data.get("metrics")
    if isinstance(m, dict) and all(isinstance(v, dict) and "value" in v for v in m.values()):
        out.setdefault("source", "metrics.json")
        return out
    if isinstance(data.get("summary"), dict):
        out["metrics"] = metric_dict(data["summary"])
        out.setdefault("source", "metrics.json:summary")
        return out
    return None


def metrics_from_scenario(report: dict[str, Any], role: str) -> dict[str, dict[str, Any]]:
    """KPIs of one side ("scenario" or "baseline") of a scenario_report.json."""
    return metric_dict((report.get("kpis") or {}).get(role))


def metrics_from_evacuation(report: dict[str, Any], role: str) -> dict[str, dict[str, Any]]:
    """Clearance KPIs (evacuation side) or the reference window KPIs."""
    wk = report.get("window_kpis") or {}
    if role == "reference":
        out = metric_dict(wk.get("reference"))
        ref = report.get("reference") or {}
        out.update({f"background_{k}": v for k, v in metric_dict(ref.get("background")).items()})
        return out
    res = report.get("result") or {}
    out = metric_dict(wk.get("evacuation"))
    out.update({f"clearance_{k}": v for k, v in metric_dict(res.get("clearance")).items()})
    out.update({f"background_{k}": v for k, v in metric_dict(res.get("background")).items()})
    for key in ("teleports", "teleports_evacuees", "reroutes", "contraflow_lanes_opened"):
        if _num(res.get(key)):
            out[key] = {"value": res[key], "unit": unit(key)}
    if _num(report.get("background_added_veh_h")):
        out["background_added_veh_h"] = {"value": report["background_added_veh_h"], "unit": "veh-h"}
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------- policy (§6)
def _flat_ids(ids: Any) -> list[str]:
    if isinstance(ids, dict):
        out: list[str] = []
        for v in ids.values():
            out.extend(x for x in _flat_ids(v) if x not in out)
        return out
    return [str(x) for x in ids] if isinstance(ids, list) else []


def _pct(new: Any, base: Any) -> float | None:
    if not (_num(new) and _num(base)) or base == 0:
        return None
    return round((float(new) / float(base) - 1.0) * PCT, 3)


def policy_districts(parquet: Path, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """policy_districts.parquet (zone_id, *_base, *_policy) -> §6 districts with osm_id ids.

    zone_id is the feature index in districts.geojson (sim.population.zones.load_districts);
    the English name is checked first so a different districts file cannot mislabel a row."""
    import pyarrow.parquet as pq

    props = [f.get("properties") or {} for f in features]
    by_name = {p.get("name_en"): p.get("osm_id") for p in props if p.get("name_en")}
    out = []
    for r in pq.read_table(parquet).to_pylist():
        name = r.get("name_en")
        did = by_name.get(name)
        zone = r.get("zone_id")
        if did is None and isinstance(zone, int) and 0 <= zone < len(props):
            did = props[zone].get("osm_id")
        if did is None:
            continue
        metrics = {
            "mean_speed_delta_pct": _pct(
                r.get("mean_speed_kmh_policy"), r.get("mean_speed_kmh_base")
            ),
            "vkt_delta_pct": _pct(r.get("vkt_policy"), r.get("vkt_base")),
            "mean_delay_delta_pct": _pct(r.get("mean_delay_s_policy"), r.get("mean_delay_s_base")),
            "trips_delta_pct": _pct(r.get("trips_policy"), r.get("trips_base")),
            "mean_delay_delta_s": round(r["delta_delay_s"], 2)
            if _num(r.get("delta_delay_s"))
            else None,
        }
        out.append(
            {
                "district_id": did,
                "name_en": name,
                "name_ar": r.get("name_ar"),
                "metrics": {k: v for k, v in metrics.items() if v is not None},
            }
        )
    out.sort(key=lambda d: str(d["district_id"]))
    return out


def policy_report(
    raw: dict[str, Any],
    run_id: str,
    meta: dict[str, Any],
    districts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """§6 view of a Track A policy_report.json (already-conforming reports pass unchanged)."""
    out = dict(raw)
    out.setdefault("label", settings.LABEL)
    out["run_id"] = run_id
    if not out.get("baseline_run_id"):
        out["baseline_run_id"] = raw.get("compare_baseline") or meta.get("baseline_run_id")
    if not isinstance(raw.get("policy"), dict):
        pid = raw.get("policy") or meta.get("policy_id")
        out["policy"] = {
            "id": pid,
            "name": raw.get("title") or meta.get("policy_title") or pid,
            "file": meta.get("policy_file"),
        }
    if not isinstance(raw.get("summary"), dict) and isinstance(raw.get("kpis"), list):
        out["summary"] = {
            k["kpi"]: {
                key: k[key]
                for key in ("baseline", "policy", "delta", "delta_pct", "unit", "label", "verdict")
                if key in k
            }
            for k in raw["kpis"]
            if isinstance(k, dict) and k.get("kpi")
        }
    if not (isinstance(raw.get("districts"), list)):
        if raw.get("districts") is not None:
            out["districts_overview"] = raw["districts"]
        out["districts"] = districts or []
    if "assumptions" not in out and raw.get("assumption_ids") is not None:
        out["assumptions"] = _flat_ids(raw["assumption_ids"])
    return out


# ------------------------------------------------------------------------- scenario (§7)
def _log_end(log: list[dict[str, Any]] | None, event_id: str) -> float | None:
    for e in log or []:
        if e.get("event") == event_id and e.get("action") == "end" and _num(e.get("t")):
            return float(e["t"])
    return None


def _edges(v: Any) -> list[str]:
    return [str(e) for e in v] if isinstance(v, list) else []


def _describe(ev: dict[str, Any], etype: str) -> str:
    if etype == "accident":
        n = "all" if ev.get("full_closure") else len(_edges(ev.get("closed_lanes")))
        return f"{n} lane(s) closed"
    if etype == "rain":
        return f"rain preset {ev.get('preset')}"
    if etype == "flood":
        n = len(_edges(ev.get("closed_edges")))
        return f"flood preset {ev.get('preset')}, {n} edge(s) closed"
    if etype == "motorcade":
        return f"motorcade of {ev.get('vehicles')} vehicles"
    if etype == "emergency_trip":
        return f"emergency trip ({ev.get('vtype', 'emergency')})"
    return etype


def scenario_events(
    events: list[dict[str, Any]],
    log: list[dict[str, Any]] | None,
    run_end: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Producer events (sim.events) -> §7 events and closures."""
    out_ev: list[dict[str, Any]] = []
    out_cl: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("type", "other"))
        eid = str(ev.get("id", f"ev{len(out_ev) + 1}"))
        begin = float(ev["start"]) if _num(ev.get("start")) else 0.0
        end = ev.get("end")
        if not _num(end):
            end = _log_end(log, eid) or (ev.get("max_end") if _num(ev.get("max_end")) else None)
        end = float(end) if _num(end) else run_end
        edges = _edges(ev.get("edges")) or _edges(ev.get("route"))
        if etype == "flood" and not edges:
            for site in ev.get("sites") or []:
                if isinstance(site, dict):
                    edges.extend(_edges(site.get("edges")))
        desc = _describe(ev, etype)
        out_ev.append(
            {
                "id": eid,
                "type": etype if etype in EVENT_TYPES else "other",
                "producer_type": etype,
                "begin_s": begin,
                "end_s": end,
                "edges": edges,
                "geometry": None,
                "description": desc,
            }
        )
        if etype == "accident" and ev.get("full_closure") and edges:
            out_cl.append(
                {
                    "id": f"{eid}:closure",
                    "edges": edges,
                    "begin_s": begin,
                    "end_s": end,
                    "reason": "accident (all lanes)",
                }
            )
        if etype == "flood" and _edges(ev.get("closed_edges")):
            start = ev.get("closure_start")
            out_cl.append(
                {
                    "id": f"{eid}:closure",
                    "edges": _edges(ev.get("closed_edges")),
                    "begin_s": float(start) if _num(start) else begin,
                    "end_s": end,
                    "reason": "flood",
                }
            )
    return out_ev, out_cl


def _summary(kpis: dict[str, Any], delta: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    base, other = kpis.get(a) or {}, kpis.get(b) or {}
    out = {}
    for k in base:
        if _num(base.get(k)) and _num(other.get(k)):
            row: dict[str, Any] = {"baseline": base[k], "scenario": other[k], "unit": unit(k)}
            d = delta.get(k) if isinstance(delta, dict) else None
            if isinstance(d, dict) and _num(d.get("pct")):
                row["delta_pct"] = d["pct"]
            else:
                pct = _pct(other[k], base[k])
                if pct is not None:
                    row["delta_pct"] = round(pct, 2)
            out[k] = row
    return out


def scenario_report(
    raw: dict[str, Any], run_id: str, baseline_run_id: str | None
) -> dict[str, Any]:
    """§7 view of a Track B scenario_report.json (conforming reports pass unchanged)."""
    out = dict(raw)
    out.setdefault("label", settings.LABEL)
    out["run_id"] = run_id
    if baseline_run_id and not out.get("baseline_run_id"):
        out["baseline_run_id"] = baseline_run_id
    if not isinstance(raw.get("scenario"), dict):
        sid = raw.get("scenario")
        out["scenario"] = {
            "id": sid,
            "name": raw.get("title") or sid,
            "fictional": bool(raw.get("fictional", False)),
        }
    events = raw.get("events") or []
    if events and any("begin_s" not in e for e in events if isinstance(e, dict)):
        end = float(raw["end"]) if _num(raw.get("end")) else math.inf
        out["producer_events"] = events
        out["events"], closures = scenario_events(events, raw.get("event_log"), end)
        out["closures"] = list(raw.get("closures") or []) + closures
    out.setdefault("closures", [])
    if not isinstance(raw.get("summary"), dict) and isinstance(raw.get("kpis"), dict):
        out["summary"] = _summary(raw["kpis"], raw.get("delta") or {}, "baseline", "scenario")
    if "assumptions" not in out and raw.get("assumption_ids") is not None:
        out["assumptions"] = _flat_ids(raw["assumption_ids"])
    return out


def _ring(points: Any) -> list[list[float]] | None:
    try:
        ring = [[float(p[0]), float(p[1])] for p in points]
    except (TypeError, ValueError, IndexError):
        return None
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def evacuation_report(
    raw: dict[str, Any], run_id: str, baseline_run_id: str | None
) -> dict[str, Any]:
    """§7 view of an evacuation_report.json: zone, exits, contraflow corridors as overlays."""
    out = dict(raw)
    out.setdefault("label", settings.LABEL)
    out["run_id"] = run_id
    if baseline_run_id:
        out.setdefault("baseline_run_id", baseline_run_id)
    sid = raw.get("scenario") if isinstance(raw.get("scenario"), str) else None
    out["scenario"] = {
        "id": sid,
        "name": raw.get("title") or sid,
        "fictional": bool(raw.get("fictional", False)),
        "kind": "evacuation",
    }
    ev = raw.get("evacuation") if isinstance(raw.get("evacuation"), dict) else {}
    run_end = float(raw["end"]) if _num(raw.get("end")) else math.inf
    begin = float(ev["start"]) if _num(ev.get("start")) else 0.0
    order = float(ev["order_t"]) if _num(ev.get("order_t")) else begin
    eid = str(ev.get("id", "evacuation"))
    events: list[dict[str, Any]] = []
    closures: list[dict[str, Any]] = []
    ring = _ring(ev.get("zone"))
    res = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    clear = res.get("clearance") or {}
    events.append(
        {
            "id": eid,
            "type": "evacuation",
            "begin_s": order,
            "end_s": run_end,
            "edges": [],
            "geometry": {"type": "Polygon", "coordinates": [ring]} if ring else None,
            "description": (
                f"evacuation order at {order:.0f} s for "
                f"{ev.get('vehicles', clear.get('vehicles'))} vehicles "
                f"({ev.get('phasing', 'n/a')}, exits {ev.get('exit_assignment', 'n/a')})"
            ),
            "zone_area_km2": ev.get("zone_area_km2"),
        }
    )
    assigned = ev.get("assigned") or {}
    for x in ev.get("exits") or []:
        if not isinstance(x, dict) or not x.get("edge"):
            continue
        geom = None
        if _num(x.get("lon")) and _num(x.get("lat")):
            geom = {"type": "Point", "coordinates": [x["lon"], x["lat"]]}
        events.append(
            {
                "id": f"exit:{x['edge']}",
                "type": "other",
                "producer_type": "evacuation_exit",
                "begin_s": order,
                "end_s": run_end,
                "edges": [str(x["edge"])],
                "geometry": geom,
                "description": f"exit {x.get('name') or x['edge']} "
                f"({assigned.get(x['edge'], 0)} vehicles assigned)",
            }
        )
    opened = {str(c) for c in ev.get("contraflow") or []}
    for c in ev.get("corridors") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", c.get("name", "corridor")))
        edges = _edges(c.get("inbound_edges"))
        if not edges:
            continue
        if cid in opened:
            events.append(
                {
                    "id": f"contraflow:{cid}",
                    "type": "other",
                    "producer_type": "contraflow",
                    "begin_s": order,
                    "end_s": run_end,
                    "edges": edges,
                    "geometry": None,
                    "description": f"contraflow corridor {cid} open to outbound traffic",
                }
            )
        else:
            closures.append(
                {
                    "id": f"contraflow:{cid}",
                    "edges": edges,
                    "begin_s": begin,
                    "end_s": run_end,
                    "reason": f"contraflow corridor {cid} (dormant lanes, closed)",
                }
            )
    other = raw.get("other_events") if isinstance(raw.get("other_events"), list) else []
    oe, oc = scenario_events(other, raw.get("event_log"), run_end)
    out["events"] = events + oe
    out["closures"] = closures + oc
    summary: dict[str, Any] = {}
    wk = raw.get("window_kpis") or {}
    if isinstance(wk, dict) and wk.get("reference") and wk.get("evacuation"):
        summary = _summary(wk, {}, "reference", "evacuation")
    for k, v in metric_dict(clear).items():
        summary[f"clearance_{k}"] = {"scenario": v["value"], "unit": v["unit"]}
    out["summary"] = summary
    if "assumptions" not in out and raw.get("assumption_ids") is not None:
        out["assumptions"] = _flat_ids(raw["assumption_ids"])
    return out


# ------------------------------------------------------------------------- strategist (§8)
def rec_generated_at(rec_id: str) -> str | None:
    m = REC_ID_RE.match(rec_id or "")
    if not m:
        return None
    d, t = m.groups()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}Z"


def option_id(rank: Any) -> str:
    return f"opt-{rank}"


def _explanation(o: dict[str, Any]) -> str:
    e = o.get("reason") or o.get("explanation") or ""
    return " ".join(str(x) for x in e) if isinstance(e, list) else str(e)


EFFECT_KEYS = (
    "travel_time_s",
    "vs_no_strategy_s",
    "added_veh_h",
    "t90_vs_no_strategy_s",
    "background_delay_veh_h",
    "contraflow_lane_km",
    "signals_retimed",
    "signals_preempted",
    "rescue_lane_edges",
)


def strategist_options(rec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for o in rec.get("options") or []:
        if not isinstance(o, dict) or o.get("rank") is None:
            continue
        cls = str(o.get("classification", "none"))
        action_class = ACTION_CLASS.get(cls, "high_impact")
        effects = {k: o[k] for k in EFFECT_KEYS if _num(o.get(k))}
        clear = o.get("clearance") if isinstance(o.get("clearance"), dict) else {}
        for k in ("t90_s", "t100_s"):
            if _num(clear.get(k)):
                effects[f"clearance_{k}"] = clear[k]
        out.append(
            {
                "option_id": option_id(o["rank"]),
                "rank": o["rank"],
                "title": o.get("label") or o.get("candidate_id"),
                "candidate_id": o.get("candidate_id"),
                "action_class": action_class,
                "classification": cls,
                "requires_approval": action_class == "high_impact",
                "score": o.get("score"),
                "explanation": _explanation(o),
                "effects": effects,
                "actions": o.get("actions") or [],
            }
        )
    out.sort(key=lambda x: x["rank"])
    return out


def strategist_recommendations(rec: dict[str, Any], run_id: str) -> dict[str, Any]:
    """§8 view of a strategist recommendation.json (emergency or evacuation)."""
    rid = str(rec.get("recommendation_id", ""))
    no = rec.get("no_strategy") if isinstance(rec.get("no_strategy"), dict) else {}
    return {
        "label": rec.get("label", settings.LABEL),
        "run_id": run_id,
        "incident_id": rid,
        "recommendation_id": rid,
        "generated_at": rec_generated_at(rid),
        "source": "strategist",
        "decision_log": "strategist-sqlite",
        "kind": rec.get("kind", "emergency"),
        "scenario_id": rec.get("scenario"),
        "title": rec.get("title"),
        "fictional": bool(rec.get("fictional", False)),
        "recommended": rec.get("recommended"),
        "best_beats_no_strategy": rec.get("best_beats_no_strategy"),
        "no_strategy": {
            k: no[k] for k in ("travel_time_s", "score", "background_veh_h") if _num(no.get(k))
        },
        "log_hash": rec.get("log_hash"),
        "options": strategist_options(rec),
    }


def strategist_scenario(rec: dict[str, Any], run_id: str, end_s: float) -> dict[str, Any]:
    """Overlays for a strategist-only run: closed lanes at dispatch and each option's route."""
    snap = rec.get("snapshot") if isinstance(rec.get("snapshot"), dict) else {}
    t = float(snap["t_dispatch"]) if _num(snap.get("t_dispatch")) else 0.0
    events: list[dict[str, Any]] = []
    closures: list[dict[str, Any]] = []
    closed = sorted({str(lane).rsplit("_", 1)[0] for lane in rec.get("closed_lanes_at_t") or []})
    if closed:
        closures.append(
            {
                "id": "closed-at-dispatch",
                "edges": closed,
                "begin_s": 0.0,
                "end_s": end_s,
                "reason": f"lanes closed at dispatch t = {t:.0f} s",
            }
        )
    for r in rec.get("routes") or []:
        if isinstance(r, dict) and _edges(r.get("edges")):
            events.append(
                {
                    "id": f"route:{r.get('name', r.get('rank'))}",
                    "type": "other",
                    "producer_type": "strategist_route",
                    "begin_s": 0.0,
                    "end_s": end_s,
                    "edges": _edges(r.get("edges")),
                    "geometry": None,
                    "description": f"{r.get('name', 'route')} "
                    f"({r.get('length_m', '?')} m, free flow {r.get('ff_s', '?')} s)",
                }
            )
    if rec.get("kind") == "evacuation":
        rep = evacuation_report(
            {
                "scenario": rec.get("scenario"),
                "title": rec.get("title"),
                "fictional": rec.get("fictional"),
                "end": rec.get("end"),
                "evacuation": {
                    "order_t": rec.get("order_t"),
                    "corridors": rec.get("corridors"),
                    "exits": rec.get("exits"),
                    "vehicles": rec.get("vehicles"),
                },
            },
            run_id,
            None,
        )
        events, closures = rep["events"], rep["closures"]
    return {
        "label": rec.get("label", settings.LABEL),
        "run_id": run_id,
        "baseline_run_id": None,
        "scenario": {
            "id": rec.get("scenario"),
            "name": rec.get("title") or rec.get("scenario"),
            "fictional": bool(rec.get("fictional", False)),
            "kind": "strategist",
        },
        "events": events,
        "closures": closures,
        "summary": {},
        "recommendation_id": rec.get("recommendation_id"),
    }
