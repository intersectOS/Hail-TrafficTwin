# Add `tzdata` so prayer times work on minimal systems

Labels: `bug`, `good first issue`

## Context
`sim/daytypes/prayer.py` calls `ZoneInfo("Asia/Riyadh")`. On a minimal Linux image without the
system tz database (for example a bare `ubuntu:24.04` container) the import fails and five test
modules error at collection (found during the release audit, `docs/release-audit.md`). GitHub's
ubuntu-latest runners and macOS ship tzdata, so CI does not catch it; Windows has no system tz
database at all.

## Acceptance
- `tzdata` added as a dependency (`uv add tzdata`, lockfile updated).
- `uv run pytest -q` passes in a bare `ubuntu:24.04` container with only the SUMO runtime
  libraries installed (see the CI workflow's apt list).

## Pointers
`sim/daytypes/prayer.py`, `pyproject.toml`, `.github/workflows/ci.yml`.
