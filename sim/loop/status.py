"""Append a line to the Track D status file (docs/status/trackD.md)."""

from __future__ import annotations

from sim.common import REPO_ROOT

STATUS = REPO_ROOT / "docs" / "status" / "trackD.md"


def append_status(line: str) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.open("a") as fh:
        fh.write(line.rstrip() + "\n")
