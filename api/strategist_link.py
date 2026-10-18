"""Strategist recommendations and their decision log, as seen by the viewer API (contract §8, §12).

The strategist (Track B) writes `runs/strategist/**/recommendation.json` and records every
recommendation and decision in the hash-chained, append-only SQLite log
`runs/strategist/decisions.sqlite` (strategist.decision_log). For a strategist-backed run that log
is the single source of truth: the API reads decisions from it and appends approvals to it with
the strategist's own `append` (same chain rule: sha256 over canonical JSON, prev_hash genesis
64 zeros), so `python -m strategist.log verify` covers API decisions too. Such runs never get a
`decisions.jsonl`. Approving logs the decision only; it never re-runs or actuates anything
(`python -m strategist.approve` remains the path that re-runs an option from the saved state).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from api import settings
from api.normalize import option_id, rec_generated_at

# directories inside runs/strategist that never hold a top-level recommendation
SKIP_DIRS = {"snapshots", "whatif", "candidates", "inputs"}


@dataclass
class Rec:
    rec_id: str
    path: Path
    data: dict[str, Any]

    @property
    def scenario(self) -> str | None:
        return self.data.get("scenario")

    @property
    def window(self) -> str | None:
        return self.data.get("window")

    @property
    def seed(self) -> Any:
        return self.data.get("seed")

    @property
    def network_hash(self) -> str | None:
        snap = self.data.get("snapshot") if isinstance(self.data.get("snapshot"), dict) else {}
        return self.data.get("network_hash") or snap.get("network_hash")

    @property
    def network(self) -> str | None:
        fork = self.data.get("fork") if isinstance(self.data.get("fork"), dict) else {}
        return self.data.get("network") or fork.get("net")

    @property
    def end_s(self) -> float:
        fork = self.data.get("fork") if isinstance(self.data.get("fork"), dict) else {}
        for v in (self.data.get("end"), fork.get("end")):
            if isinstance(v, int | float):
                return float(v)
        return 3600.0  # fallback span for overlays only (not a model assumption)

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.scenario), str(self.window), str(self.seed))

    @property
    def generated_at(self) -> str:
        return rec_generated_at(self.rec_id) or ""


_cache: dict[Path, tuple[float, Rec | None]] = {}


def _load(path: Path) -> Rec | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    rec: Rec | None = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("recommendation_id") and data.get("options"):
            rec = Rec(str(data["recommendation_id"]), path, data)
    except (OSError, ValueError):
        rec = None
    _cache[path] = (mtime, rec)
    return rec


def all_recs() -> list[Rec]:
    """Every recommendation once (latest-copy dirs deduplicated), newest first."""
    root = settings.runs_dir() / "strategist"
    if not root.is_dir():
        return []
    found: dict[str, Rec] = {}
    for pattern in ("*/recommendation.json", "*/*/recommendation.json"):
        for path in sorted(root.glob(pattern)):
            if SKIP_DIRS & set(path.relative_to(root).parts):
                continue
            rec = _load(path)
            if rec and rec.rec_id not in found:
                found[rec.rec_id] = rec
    return sorted(found.values(), key=lambda r: (r.generated_at, r.rec_id), reverse=True)


def latest_by_key() -> dict[tuple[str, str, str], Rec]:
    out: dict[tuple[str, str, str], Rec] = {}
    for rec in all_recs():
        out.setdefault(rec.key, rec)
    return out


def match(meta: dict[str, Any]) -> Rec | None:
    """Latest recommendation for a scenario/evacuation run (same scenario, window, seed, net)."""
    sid = meta.get("scenario_id")
    if not sid:
        return None
    key = (str(sid), str(meta.get("window")), str(meta.get("seed")))
    rec = latest_by_key().get(key)
    if rec is None:
        return None
    if rec.network_hash and meta.get("network_hash") and rec.network_hash != meta["network_hash"]:
        return None
    return rec


def by_id(rec_id: str) -> Rec | None:
    return next((r for r in all_recs() if r.rec_id == rec_id), None)


# ------------------------------------------------------------------------- decision log
def _records(db: Path) -> list[dict[str, Any]]:
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM records ORDER BY seq")]
    except sqlite3.DatabaseError:
        return []
    finally:
        con.close()


def _entry(r: dict[str, Any], run_id: str) -> dict[str, Any]:
    d = json.loads(r["decision"]) if r.get("decision") else {}
    d = d if isinstance(d, dict) else {}
    return {
        "ts": r["timestamp"],
        "run_id": run_id,
        "incident_id": d.get("recommendation_id"),
        "option_id": option_id(d.get("option_rank")),
        "decision": d.get("decision"),
        "operator": r["actor"],
        "note": d.get("note", ""),
        "label": d.get("label", settings.LABEL),
        "prev_hash": r["prev_hash"],
        "hash": r["hash"],
        "record_id": r["record_id"],
        "log": "strategist-sqlite",
        "applied_run_dir": d.get("applied_run_dir"),
        "source": d.get("source", "strategist"),
    }


def decisions(rec: Rec, run_id: str) -> list[dict[str, Any]]:
    """Decision records of this recommendation, in chain order, in the §8 entry shape."""
    out = []
    for r in _records(settings.strategist_db()):
        if r["kind"] != "decision":
            continue
        try:
            d = json.loads(r["decision"])
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("recommendation_id") == rec.rec_id:
            out.append(_entry(r, run_id))
    return out


def append_decision(
    rec: Rec, option: str, decision: str, operator: str, note: str, run_id: str
) -> dict[str, Any]:
    """Append a decision record with the strategist's own chain code; 409 when it must not."""
    from strategist import decision_log as L

    db = settings.strategist_db()
    opts = {option_id(o.get("rank")): o for o in rec.data.get("options") or []}
    chosen = opts.get(option)
    if chosen is None:
        raise HTTPException(status_code=404, detail="option not found")
    if not db.is_file():
        raise HTTPException(status_code=409, detail="strategist decision log not found")
    problems = L.verify(db)
    if problems:
        raise HTTPException(status_code=409, detail=f"decision log fails verification: {problems}")
    record = L.get(db, rec.rec_id)
    if record is None or record["kind"] != "recommendation":
        raise HTTPException(status_code=409, detail="recommendation not in the decision log")
    if rec.data.get("log_hash") and rec.data["log_hash"] != record["hash"]:
        raise HTTPException(
            status_code=409, detail="recommendation.json does not match its decision-log record"
        )
    if L.decisions_for(db, rec.rec_id):
        raise HTTPException(
            status_code=409, detail="recommendation already has a decision (one per recommendation)"
        )
    payload = {
        "label": settings.LABEL,
        "recommendation_id": rec.rec_id,
        "option_rank": chosen.get("rank"),
        "candidate_id": chosen.get("candidate_id"),
        "option_label": chosen.get("label"),
        "classification": chosen.get("classification"),
        "decision": decision,
        "note": note,
        "run_id": run_id,
        "source": "api",
        "applied": False,
        "actuated": False,
    }
    entry = L.append(
        db,
        "decision",
        record["snapshot_id"],
        [chosen.get("candidate_id")],
        [{"candidate_id": chosen.get("candidate_id"), "score": chosen.get("score")}],
        {"recommendation_id": rec.rec_id, "recommendation_hash": record["hash"]},
        payload,
        actor=operator,
    )
    return _entry(dict(entry), run_id)
