"""Run registry (defensive, traversal-safe) and run summaries (contract §1, §2, §12).

A *run* is what the viewer lists. It is backed by a directory under runs/, in one of these forms:

- flat run: `runs/<id>/meta.json` plus outputs (smoke, baseline, policy runs);
- nested run (Track B scenario and evacuation runs): `runs/<id>/` holds meta.json and the report,
  and the simulation outputs sit in sub-directories. The primary sub-run (`scenario/`,
  `evacuation/`) is the run itself; the comparison sub-run (`baseline/`, `reference/`) is listed
  as `<id>~<sub>` and becomes the run's `baseline_run_id`;
- alias: a short pointer directory (`RUN_DIR` file, meta.run_id = another directory) is not
  listed; its name resolves to the run it points to;
- strategist-only run: a strategist recommendation whose scenario has no simulation run is listed
  as `strategist~<scenario>-<window>-s<seed>` (network, overlays, recommendations; no bins).

Directories starting with `_` or `.` and directories without a readable meta.json are skipped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from api import normalize, settings
from api.strategist_link import Rec, latest_by_key, match

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{6,64}$")
SUB_SEP = "~"
STRATEGIST_PREFIX = "strategist~"

# meta kind -> (primary sub-directory, comparison sub-directory)
NESTED = {"scenario": ("scenario", "baseline"), "evacuation": ("evacuation", "reference")}
REPORT_FILES = {"scenario": "scenario_report.json", "evacuation": "evacuation_report.json"}

OPTIONAL_FILES = {
    "policy_report": "policy_report.json",
    "scenario_report": "scenario_report.json",
    "recommendations": "recommendations.json",
    "decisions": "decisions.jsonl",
}


@dataclass
class Run:
    run_id: str
    path: Path  # directory under runs/ holding meta.json, reports and decisions.jsonl
    data_dir: Path  # directory holding edgedata / fcd
    meta: dict[str, Any]  # contract view (api.normalize.normalise_meta)
    role: str = "run"  # run | baseline | reference | strategist
    parent_id: str | None = None
    rec: Rec | None = None  # strategist recommendation (matched or the run's own)
    report: dict[str, Any] = field(default_factory=dict)  # raw scenario/evacuation report

    @property
    def tier(self) -> str | None:
        return self.meta.get("tier")


def not_available(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not available")


def _listable(path: Path) -> bool:
    return path.is_dir() and not path.name.startswith(("_", "."))


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_meta(run_dir: Path) -> dict[str, Any] | None:
    return read_json_file(run_dir / "meta.json")


def iter_runs() -> list[tuple[Path, dict[str, Any]]]:
    """Top-level run directories with their raw meta.json (v1 helper, aliases excluded)."""
    root = settings.runs_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.iterdir()):
        if not _listable(path):
            continue
        meta = read_meta(path)
        if meta is not None and not _is_alias(path, meta):
            out.append((path, meta))
    return out


def _is_alias(path: Path, meta: dict[str, Any]) -> bool:
    return (path / "RUN_DIR").is_file() and meta.get("run_id") not in (None, path.name)


def _nested_runs(path: Path, raw: dict[str, Any]) -> list[Run]:
    run_id = path.name
    kind = str(raw.get("kind"))
    report = read_json_file(path / REPORT_FILES.get(kind, "scenario_report.json")) or {}
    primary, comparison = NESTED.get(kind, (None, None))
    has_primary = primary is not None and (path / primary).is_dir()
    has_cmp = comparison is not None and (path / comparison).is_dir()
    sub_id = f"{run_id}{SUB_SEP}{comparison}"
    overrides: dict[str, Any] = {}
    if has_cmp:
        overrides["baseline_run_id"] = raw.get("baseline_run_id") or sub_id
    if has_primary:
        overrides["sub_run"] = primary
    meta = normalize.normalise_meta(raw, run_id, report=report, overrides=overrides)
    data_dir = path / primary if has_primary and primary else path
    runs = [Run(run_id, path, data_dir, meta, report=report)]
    if has_cmp and comparison:
        sub_raw = {**raw, **(read_meta(path / comparison) or {})}
        sub_meta = normalize.normalise_meta(
            sub_raw,
            sub_id,
            report=report,
            overrides={
                "kind": "baseline",
                "sub_run": comparison,
                "parent_run_id": run_id,
                "baseline_run_id": None,
                "description": f"{comparison} side of {run_id} (same demand, seed and window)",
            },
        )
        runs.append(
            Run(sub_id, path, path / comparison, sub_meta, comparison, run_id, None, report)
        )
    return runs


def _strategist_run(rec: Rec) -> Run | None:
    if not rec.network or not rec.network_hash:
        return None
    sid = f"{STRATEGIST_PREFIX}{rec.scenario}-{rec.window}-s{rec.seed}"
    if not RUN_ID_RE.match(sid):
        return None
    raw = {
        "run_id": sid,
        "label": rec.data.get("label", settings.LABEL),
        "kind": "strategist",
        "tier": "B",
        "mode": "micro",
        "seed": rec.seed,
        "scenario": rec.scenario,
        "window": rec.window,
        "fictional": bool(rec.data.get("fictional", False)),
        "network": rec.network,
        "network_hash": rec.network_hash,
        "config_hash": rec.data.get("config_hash"),
        "sim_seconds": int(rec.end_s),
        "begin_s": 0,
        "recommendation_id": rec.rec_id,
        "description": "strategist recommendation (no simulation run with edge bins)",
    }
    meta = normalize.normalise_meta(raw, sid)
    return Run(sid, rec.path.parent, rec.path.parent, meta, "strategist", None, rec)


def registry() -> tuple[dict[str, Run], dict[str, str]]:
    """(runs by id in listing order, alias name -> run id). Cheap: small JSON files only."""
    root = settings.runs_dir()
    runs: dict[str, Run] = {}
    aliases: dict[str, str] = {}
    if not root.is_dir():
        return runs, aliases
    for path in sorted(root.iterdir()):
        if not _listable(path):
            continue
        raw = read_meta(path)
        if raw is None:
            continue
        if _is_alias(path, raw):
            aliases[path.name] = str(raw["run_id"])
            continue
        if str(raw.get("kind")) in NESTED:
            for run in _nested_runs(path, raw):
                runs[run.run_id] = run
        else:
            meta = normalize.normalise_meta(raw, path.name)
            runs[path.name] = Run(path.name, path, path, meta)
    matched: set[tuple[str, str, str]] = set()
    for run in runs.values():
        if run.role == "run" and run.meta.get("kind") in NESTED:
            run.rec = match(run.meta)
            if run.rec:
                matched.add(run.rec.key)
    for key, rec in latest_by_key().items():
        if key in matched:
            continue
        srun = _strategist_run(rec)
        if srun and srun.run_id not in runs:
            runs[srun.run_id] = srun
    aliases = {a: t for a, t in aliases.items() if t in runs and a not in runs}
    return runs, aliases


def _check_id(run_id: str) -> None:
    if not RUN_ID_RE.match(run_id) or run_id.startswith(("_", ".")) or ".." in run_id:
        raise HTTPException(status_code=404, detail="run not found")


def get_run(run_id: str) -> Run:
    """The run for an id or alias; 404 for anything else (never a path outside runs/)."""
    _check_id(run_id)
    runs, aliases = registry()
    run = runs.get(run_id) or runs.get(aliases.get(run_id, ""))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    # ids match RUN_ID_RE and come from listing runs/ itself; symlinked run dirs are allowed
    if not run.path.is_relative_to(settings.runs_dir()):
        raise HTTPException(status_code=404, detail="run not found")
    return run


def run_dir(run_id: str) -> Path:
    """Directory of a run's meta/report files (v1 helper)."""
    return get_run(run_id).path


def run_meta(run_id: str) -> dict[str, Any]:
    return get_run(run_id).meta


def has_files(run: Run) -> dict[str, bool]:
    d, p = run.data_dir, run.path
    tier_b = run.tier != "A"
    is_main = run.role in ("run", "strategist")
    edge_files = ("edgedata.parquet", "edgedata.xml", "edgedata.xml.gz")
    has = {
        "edgedata": any((d / f).is_file() for f in edge_files)
        or (settings.cache_dir() / "runs" / run.run_id / "edgedata.parquet").is_file(),
        # trajectories are Tier B only (contract section 5)
        "fcd": tier_b and any((d / f).is_file() for f in ("fcd.parquet", "fcd.xml", "fcd.xml.gz")),
        "policy_report": is_main and (p / "policy_report.json").is_file(),
        "scenario_report": is_main
        and (
            (p / "scenario_report.json").is_file()
            or (p / "evacuation_report.json").is_file()
            or run.role == "strategist"
        ),
        "recommendations": is_main
        and ((p / "recommendations.json").is_file() or run.rec is not None),
        "decisions": is_main and (p / "decisions.jsonl").is_file(),
    }
    if run.rec is not None and not (p / "recommendations.json").is_file():
        from api.strategist_link import decisions

        has["decisions"] = bool(decisions(run.rec, run.run_id))
    return has


def summary(run: Run) -> dict[str, Any]:
    meta = run.meta
    return {
        "run_id": run.run_id,
        "kind": meta.get("kind"),
        "tier": meta.get("tier"),
        "mode": meta.get("mode"),
        "seed": meta.get("seed"),
        "network_hash": meta.get("network_hash"),
        "sim_seconds": meta.get("sim_seconds"),
        "label": meta.get("label", settings.LABEL),
        "baseline_run_id": meta.get("baseline_run_id"),
        "parent_run_id": run.parent_id,
        "scenario_id": meta.get("scenario_id"),
        "policy_id": meta.get("policy_id"),
        "window": meta.get("window"),
        "has": has_files(run),
    }


def network_for_hash(network_hash: str) -> Path:
    """The .net.xml of any run with this network hash (404 when no run uses it)."""
    if not HEX_RE.match(network_hash):
        raise HTTPException(status_code=404, detail="network not found")
    runs, _ = registry()
    for run in runs.values():
        meta = run.meta
        if meta.get("network_hash") == network_hash and meta.get("network"):
            net = normalize.resolve_network(str(meta.get("network_original") or meta["network"]))
            if net.is_file():
                return net
    raise HTTPException(status_code=404, detail="network not found")


def run_network(run: Run) -> Path:
    meta = run.meta
    return normalize.resolve_network(str(meta.get("network_original") or meta["network"]))


def read_optional_json(run_id: str, key: str) -> dict[str, Any]:
    """A contract file of a flat run as stored (v1 helper; the routers normalise)."""
    path = run_dir(run_id) / OPTIONAL_FILES[key]
    data = read_json_file(path) if path.is_file() else None
    if data is None:
        raise not_available(key.replace("_", " "))
    data.setdefault("label", settings.LABEL)
    return data
