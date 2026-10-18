# Commit district population tables (where the licence allows)

Labels: `data`, `good first issue`

## Context
`data/census/README.md` is still a placeholder. District populations are synthesised from GASTAT
city totals distributed by OSM building footprints. A per-district (hay) table from GASTAT or
open.data.gov.sa would replace an assumption with a source.

## Acceptance
- A public table with its licence and URL recorded in `docs/data-sources.md`, committed under
  `data/census/` only if the licence allows redistribution (otherwise a download script).
- `sim/population/zones.py` uses it when present; zone population differences reported in
  `docs/population.md`.

## Pointers
`data/census/README.md`, `sim/population/zones.py`, `sim/population/config/zones.yaml`, the
`data-scout` agent brief in `.claude/agents/data-scout.md`.
