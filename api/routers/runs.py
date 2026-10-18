"""Run endpoints: list, metadata, metrics, bins, district effects, trajectories, reports.

Every response is in contract shape (docs/contracts/run-outputs.md); producer-specific shapes are
mapped by api.normalize (§12).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api import normalize, settings, strategist_link
from api.bins import METRICS, bin_values, ensure_bins
from api.decisions import LOG_NAME, append_decision, read_entries
from api.districts import COMPUTED_METRIC, computed_effects, load_districts, report_effects
from api.edges import load_edge_index
from api.ingest import ensure_edgedata, ensure_fcd
from api.runs import Run, get_run, not_available, read_json_file, registry, run_network, summary
from api.trajectories import trajectories

router = APIRouter(prefix="/api/runs", tags=["runs"])
BINARY = "application/octet-stream"


def _unit(key: str) -> str:
    return normalize.unit(key)


@router.get("")
def list_runs() -> list[dict[str, Any]]:
    return [summary(run) for run in registry()[0].values()]


@router.get("/{run_id}")
def get_run_meta(run_id: str) -> dict[str, Any]:
    meta = dict(get_run(run_id).meta)
    meta.setdefault("label", settings.LABEL)
    return meta


@router.get("/{run_id}/metrics")
def get_metrics(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if run.role in ("run", "strategist"):
        data = read_json_file(run.path / "metrics.json")
        if data is not None:
            out = normalize.metrics_from_file(data, run.run_id)
            if out is not None:
                out["run_id"] = run.run_id
                return out
    kind = run.meta.get("kind")
    metrics: dict[str, Any] = {}
    source = "meta.result"
    if run.report and (run.path / "evacuation_report.json").is_file():
        metrics = normalize.metrics_from_evacuation(
            run.report, "reference" if run.role == "reference" else "evacuation"
        )
        source = "evacuation_report.json"
    elif run.report and kind in ("scenario", "baseline"):
        metrics = normalize.metrics_from_scenario(
            run.report, "baseline" if run.role == "baseline" else "scenario"
        )
        source = "scenario_report.json:kpis"
    if not metrics:
        result = run.meta.get("result")
        metrics = normalize.metric_dict(result if isinstance(result, dict) else {})
        source = "meta.result"
    return {
        "label": run.meta.get("label", settings.LABEL),
        "run_id": run.run_id,
        "source": source,
        "metrics": metrics,
    }


def _bins_info(run: Run) -> dict[str, Any]:
    if not run.meta.get("network") or not run.meta.get("network_hash"):
        raise not_available("edge bins (no network in meta.json)")
    try:
        return ensure_bins(run)
    except FileNotFoundError as exc:
        raise not_available("edge bins") from exc


@router.get("/{run_id}/bins")
def get_bins(run_id: str) -> dict[str, Any]:
    info = dict(_bins_info(get_run(run_id)))
    info["label"] = settings.LABEL
    info["run_id"] = run_id
    return info


@router.get("/{run_id}/bins/{i}")
def get_bin(run_id: str, i: int, metric: str = "speed_rel") -> Response:
    if metric not in METRICS:
        raise HTTPException(status_code=422, detail=f"unknown metric; one of {list(METRICS)}")
    run = get_run(run_id)
    info = _bins_info(run)
    if not 0 <= i < info["n_bins"]:
        raise HTTPException(status_code=404, detail="bin out of range")
    data = bin_values(run.run_id, metric, i, info["n_edges"]).tobytes()
    begin = info["begin_s"] + i * info["bin_s"]
    headers = {
        "X-Metric": metric,
        "X-Bin-Begin-S": str(begin),
        "X-Bin-End-S": str(begin + info["bin_s"]),
        "X-N-Edges": str(info["n_edges"]),
        "X-Network-Hash": str(info["network_hash"]),
        "X-Label": settings.LABEL,
    }
    return Response(content=data, media_type=BINARY, headers=headers)


def _policy_report(run: Run) -> dict[str, Any] | None:
    raw = read_json_file(run.path / "policy_report.json") if run.role == "run" else None
    if raw is None:
        return None
    districts = None
    pq_path = run.path / "policy_districts.parquet"
    if not isinstance(raw.get("districts"), list) and pq_path.is_file():
        try:
            districts = normalize.policy_districts(pq_path, load_districts())
        except (OSError, ValueError):
            districts = None
    return normalize.policy_report(raw, run.run_id, run.meta, districts)


@router.get("/{run_id}/district-effects")
def district_effects(
    run_id: str,
    baseline: str | None = None,
    metric: str = COMPUTED_METRIC,
) -> dict[str, Any]:
    run = get_run(run_id)
    meta = run.meta
    report = _policy_report(run)
    same_base = report is not None and baseline in (None, report.get("baseline_run_id"))
    rows = report_effects(report, metric) if report is not None and same_base else None
    if report is not None and rows is not None:
        return {
            "label": settings.LABEL,
            "run_id": run_id,
            "baseline_run_id": report.get("baseline_run_id"),
            "source": "policy_report",
            "metric": metric,
            "unit": "%" if metric.endswith("_pct") else _unit(metric),
            "example": bool(report.get("example", False)),
            "districts": rows,
        }
    if metric != COMPUTED_METRIC:
        raise not_available(f"district metric {metric!r}")
    baseline = baseline or meta.get("baseline_run_id")
    if not baseline:
        raise HTTPException(status_code=422, detail="baseline run required (?baseline=<run_id>)")
    base = get_run(baseline)
    if base.meta.get("network_hash") != meta.get("network_hash"):
        raise HTTPException(status_code=422, detail="runs do not share a network_hash")
    run_pq = ensure_edgedata(run.data_dir, run_id=run.run_id)
    base_pq = ensure_edgedata(base.data_dir, run_id=base.run_id)
    if run_pq is None or base_pq is None:
        raise not_available("edge bins")
    index = load_edge_index(run_network(run), meta["network_hash"])
    try:
        rows = computed_effects(run_pq, base_pq, index)
    except FileNotFoundError as exc:
        raise not_available("districts") from exc
    return {
        "label": settings.LABEL,
        "run_id": run_id,
        "baseline_run_id": base.run_id,
        "source": "computed",
        "metric": metric,
        "unit": "%",
        "method": "sampled-seconds-weighted mean speed per district, run vs baseline, all bins",
        "districts": rows,
    }


@router.get("/{run_id}/trajectories")
def get_trajectories(
    run_id: str,
    begin: float | None = None,
    end: float | None = None,
    step: int = Query(1, ge=1),
) -> dict[str, Any]:
    run = get_run(run_id)
    if run.tier != "B":
        raise not_available("trajectories (Tier B only)")
    fcd = ensure_fcd(run.data_dir, run_id=run.run_id, tier="B")
    if fcd is None:
        raise not_available("trajectories")
    return trajectories(fcd, run.run_id, begin, end, step)


@router.get("/{run_id}/policy-report")
def policy_report(run_id: str) -> dict[str, Any]:
    report = _policy_report(get_run(run_id))
    if report is None:
        raise not_available("policy report")
    return report


@router.get("/{run_id}/scenario-report")
def scenario_report(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if run.role == "strategist" and run.rec is not None:
        return normalize.strategist_scenario(run.rec.data, run.run_id, run.rec.end_s)
    if run.role != "run":
        raise not_available("scenario report")
    base = run.meta.get("baseline_run_id")
    raw = read_json_file(run.path / "scenario_report.json")
    if raw is not None:
        return normalize.scenario_report(raw, run.run_id, base)
    raw = read_json_file(run.path / "evacuation_report.json")
    if raw is not None:
        return normalize.evacuation_report(raw, run.run_id, base)
    raise not_available("scenario report")


def _native_recs(run: Run) -> dict[str, Any] | None:
    if run.role not in ("run", "strategist"):
        return None
    data = read_json_file(run.path / "recommendations.json")
    if data is None:
        return None
    data.setdefault("label", settings.LABEL)
    data["run_id"] = run.run_id
    return data


@router.get("/{run_id}/recommendations")
def recommendations(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    native = _native_recs(run)
    if native is not None:
        return native
    if run.rec is not None:
        return normalize.strategist_recommendations(run.rec.data, run.run_id)
    raise not_available("recommendations")


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    operator: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=4000)


@router.post("/{run_id}/recommendations/{option_id}/decision")
def decide(run_id: str, option_id: str, body: DecisionIn) -> dict[str, Any]:
    run = get_run(run_id)
    native = _native_recs(run)
    if native is None and run.rec is not None:
        return strategist_link.append_decision(
            run.rec, option_id, body.decision, body.operator, body.note, run.run_id
        )
    if native is None:
        raise not_available("recommendations")
    options = [o for o in native.get("options") or [] if o.get("option_id") == option_id]
    if not options:
        raise HTTPException(status_code=404, detail="option not found")
    return append_decision(
        run.path,
        run_id=run.run_id,
        incident_id=native.get("incident_id"),
        option_id=option_id,
        decision=body.decision,
        operator=body.operator,
        note=body.note,
    )


@router.get("/{run_id}/decisions")
def decisions(run_id: str) -> list[dict[str, Any]]:
    run = get_run(run_id)
    if run.role not in ("run", "strategist"):
        return []
    if (run.path / "recommendations.json").is_file() or run.rec is None:
        return read_entries(run.path / LOG_NAME)
    return strategist_link.decisions(run.rec, run.run_id)
