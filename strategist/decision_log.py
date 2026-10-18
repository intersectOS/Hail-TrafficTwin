"""Append-only, hash-chained decision log in SQLite (PROJECT.md 9.10).

Each record: record_id, kind (recommendation | decision), situation snapshot id, candidates,
scores, recommendation, human decision, actor, timestamp (UTC ISO 8601), prev_hash and hash =
sha256 over the canonical JSON (sorted keys, no whitespace) of all those fields, prev_hash
included. JSON fields are stored as canonical JSON text and hashed as stored, so verification
does not depend on float re-serialisation. The first record's prev_hash is 64 zeros.

Append-only is enforced by triggers that RAISE on UPDATE and DELETE. `verify` walks the chain
and also reports missing triggers (someone dropped them to edit rows). Limit: deleting the last
records (after dropping the triggers) leaves a valid shorter chain; compare the head hash with
one kept elsewhere (each recommendation.json stores the hash of its record) to detect that.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
KINDS = ("recommendation", "decision")
TRIGGERS = ("records_no_update", "records_no_delete")
HASHED = (
    "record_id",
    "kind",
    "snapshot_id",
    "candidates",
    "scores",
    "recommendation",
    "decision",
    "actor",
    "timestamp",
    "prev_hash",
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('recommendation', 'decision')),
    snapshot_id TEXT NOT NULL,
    candidates TEXT NOT NULL,
    scores TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
BEGIN SELECT RAISE(ABORT, 'decision log is append-only: UPDATE refused'); END;
CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
BEGIN SELECT RAISE(ABORT, 'decision log is append-only: DELETE refused'); END;
"""


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def record_hash(fields: dict[str, str]) -> str:
    return hashlib.sha256(canonical({k: fields[k] for k in HASHED}).encode()).hexdigest()


def connect(db: Path) -> sqlite3.Connection:
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def new_id(kind: str) -> str:
    prefix = "rec" if kind == "recommendation" else "dec"
    return f"{prefix}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def append(
    db: Path,
    kind: str,
    snapshot_id: str,
    candidates: Any,
    scores: Any,
    recommendation: Any,
    decision: Any = None,
    actor: str = "strategist",
    record_id: str | None = None,
) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    con = connect(db)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT hash FROM records ORDER BY seq DESC LIMIT 1").fetchone()
        fields = {
            "record_id": record_id or new_id(kind),
            "kind": kind,
            "snapshot_id": snapshot_id,
            "candidates": canonical(candidates),
            "scores": canonical(scores),
            "recommendation": canonical(recommendation),
            "decision": canonical(decision),
            "actor": actor,
            "timestamp": datetime.now(UTC).isoformat(timespec="microseconds"),
            "prev_hash": row["hash"] if row else GENESIS,
        }
        fields["hash"] = record_hash(fields)
        cols = ", ".join(fields)
        con.execute(
            f"INSERT INTO records ({cols}) VALUES ({', '.join('?' for _ in fields)})",
            list(fields.values()),
        )
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return fields


def records(db: Path) -> list[dict[str, Any]]:
    con = connect(db)
    try:
        return [dict(r) for r in con.execute("SELECT * FROM records ORDER BY seq")]
    finally:
        con.close()


def get(db: Path, record_id: str) -> dict[str, Any] | None:
    con = connect(db)
    try:
        r = con.execute("SELECT * FROM records WHERE record_id = ?", (record_id,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def decisions_for(db: Path, recommendation_id: str) -> list[dict[str, Any]]:
    out = []
    for r in records(db):
        if (
            r["kind"] == "decision"
            and json.loads(r["decision"]).get("recommendation_id") == recommendation_id
        ):
            out.append(r)
    return out


def verify(db: Path) -> list[str]:
    """Problems found (empty list = chain intact). Does not create the db if missing."""
    db = Path(db)
    if not db.exists():
        return [f"{db}: no such decision log"]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    problems: list[str] = []
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        for t in TRIGGERS:
            if t not in names:
                problems.append(f"append-only trigger {t} is missing")
        prev = GENESIS
        for r in con.execute("SELECT * FROM records ORDER BY seq"):
            fields = dict(r)
            if fields["prev_hash"] != prev:
                problems.append(
                    f"seq {fields['seq']} ({fields['record_id']}): prev_hash does not match "
                    "the previous record (record removed or reordered)"
                )
            if record_hash(fields) != fields["hash"]:
                problems.append(
                    f"seq {fields['seq']} ({fields['record_id']}): hash mismatch (record edited)"
                )
            prev = fields["hash"]
    finally:
        con.close()
    return problems
