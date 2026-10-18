"""Append-only, hash-chained decision log (contract §8).

hash = sha256 hex of the canonical JSON (sorted keys, no spaces, UTF-8) of the entry without
`hash`; prev_hash = hash of the previous line or 64 zeros. Lines are never rewritten. Logging a
decision never actuates anything (simulation and decision support only).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api import settings

GENESIS = "0" * 64
LOG_NAME = "decisions.jsonl"


def canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "hash"})).hexdigest()


def read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def verify_chain(entries: list[dict[str, Any]]) -> bool:
    prev = GENESIS
    for e in entries:
        if e.get("prev_hash") != prev or e.get("hash") != entry_hash(e):
            return False
        prev = e["hash"]
    return True


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_decision(
    run_dir: Path,
    *,
    run_id: str,
    incident_id: str | None,
    option_id: str,
    decision: str,
    operator: str,
    note: str,
) -> dict[str, Any]:
    """Append one entry under an exclusive file lock; return it."""
    path = run_dir / LOG_NAME
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            prev = GENESIS
            for line in fh:
                if line.strip():
                    prev = json.loads(line)["hash"]
            entry: dict[str, Any] = {
                "ts": _now(),
                "run_id": run_id,
                "incident_id": incident_id,
                "option_id": option_id,
                "decision": decision,
                "operator": operator,
                "note": note,
                "label": settings.LABEL,
                "prev_hash": prev,
            }
            entry["hash"] = entry_hash(entry)
            fh.seek(0, 2)
            fh.write(canonical(entry).decode() + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return entry
