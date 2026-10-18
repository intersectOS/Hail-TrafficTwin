# Viewer: stream Tier B trajectories in time chunks

Labels: `viewer`, `performance`

## Context
Tier B trajectory loading is not chunked; one-hour windows load all vehicles at once and the frame
rate is borderline (`docs/status/final.md`, G5).

## Acceptance
- The API serves trajectories in time chunks (for example 5 min) from the Parquet file, and the
  viewer loads the chunk around the slider plus one ahead.
- Frame rate measured with `npm run perf` before and after on the Tahlia accident run, recorded in
  `docs/viewer.md`.

## Pointers
`api/trajectories.py`, `web/src/`, `web/scripts/perf.mjs`, `docs/contracts/run-outputs.md`.
