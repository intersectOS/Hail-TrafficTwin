# Same population hash on macOS and Linux

Labels: `determinism`, `good first issue`

## Context
Runs are bit-identical per platform, but the demo population hash differs between macOS and the
Linux Docker image because of last-bit differences in PROJ-computed zone areas
(`docs/status/final.md`, G6). Cached routes and reported hashes therefore do not carry across
platforms.

## Acceptance
- Geometry-derived floats (areas, centroids, weights) rounded to a stated precision before they
  enter sampling, with the precision registered as an assumption.
- The demo population hash is the same in `docker compose run demo` and on macOS; a test pins it.
- Note in `docs/STATUS.md` that hashes changed once.

## Pointers
`sim/population/zones.py`, `sim/population/synthesize.py`, `tests/test_population.py`,
`Dockerfile.api`.
