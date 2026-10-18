# Final (M9): a runnable app from a clean clone

## FINAL — 2026-10-16
`make demo` runs from a fresh `git clone` with no manual step: setup (uv sync, npm ci), Jeddah
network (243 MB Geofabrik download + `build_city`), the demo runs (`python -m sim.demo`: Tier B
smoke, demo events scenario, strategist, evacuation, demo-scale policy comparison, one-hour mid-day
Tier A city smoke), ingest, then the API on :8000 and the viewer on :5173 opening on the Tier A
city run. Clean-clone wall time 6 min 23 s; `docker compose up --build` verified in a second clone
after adding the SUMO runtime libraries to the image. Details, numbers and decisions F-001..F-004:
`docs/STATUS.md`, section "M9 Docs and release".

Screenshots from the clean clone: `docs/img/final-city.png`, `final-tierA-midday.png`,
`final-tierB-scenario.png`, `final-strategist.png`, `final-policy.png`. (f) Loop candidate map:
not present, Track D is not merged.

Docs: README quickstart, `docs/architecture.md` (Mermaid), `docs/demo-script.md`,
`CONTRIBUTING.md`, `CHANGELOG.md`, register row A-demo-001, STATUS M9 section.

Verifier (2026-10-16): independent fresh clone of 53c1746 (/tmp/tt-verify-20261016-155907):
`make demo` PASS in 413 s (same network hash 79f35c9a, same run ids and KPIs as the author's
clone), rerun skips every step, determinism PASS (identical `scenario_report.json`), `make test`
PASS (273 tests: 271 passed, 2 skipped), screenshots, docs, hygiene and docker config PASS. Its one
FAIL (this file uncommitted with placeholders; no STATUS note on the missing demo video; no M9 test
gate) is fixed in docs/STATUS.md (M9 section) and by committing this file.

FINAL: done

## Still missing against PROJECT.md goals G1-G6
- **G1 (24 h Tier A baseline, one command, KPIs): met at a 10 % sample, with a realism gap.**
  `make city` / `sim.runner --baseline` runs it (about 2 h uncached). The full population was not
  run (sampling decision in M2). 50.5 % of vehicles teleport (TA-011): network capacity (untagged
  lanes, junction clusters, ramps) is the top realism issue; the lane audit that would fix lane
  counts is blocked on accuracy (60 % held-out precision < 80 % gate).
- **G2 (policies in YAML with reports): met.** One noise replicate per policy only; road pricing
  and ride-hail share are indicative (simplified transforms). The `make demo` policy comparison is
  demo-scale; city policy runs need the baseline.
- **G3 (events in a focus window vs the window baseline): met.** Windows are linked to the M1
  random-trip route set, not to the M2 behavioural baseline (B-D-002); re-link them.
- **G4 (top 3 emergency strategies with times and reasons): met** (Tahlia: 11.6 s; demo: 1.9 s).
  One noise replicate.
- **G5 (viewer: Tier A heatmap, Tier B vehicles, slider, comparison): met.** Tier B trajectory
  loading is not chunked (borderline frame rate on 1 h windows); strategist-only runs have no edge
  bins of their own.
- **G6 (local, open source, public data): met.** Docker verified. Runs are bit-identical per
  platform, but the demo population hash differs between macOS and Linux (last-bit PROJ area
  differences in zones); fix by rounding geometry-derived floats at the next baseline
  regeneration.
- Outside G1-G6: Loop tunnels (Track D) not merged (second integration pass needed); calibration
  (M8) dormant until real counts exist; the M9 "demo video" is replaced by the screenshot set and
  `docs/demo-script.md` (no video recorded); every result remains "synthetic demand, uncalibrated".
