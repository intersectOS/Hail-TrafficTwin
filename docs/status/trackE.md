# Track E: MOVIES (cinematic films of the simulations)

Branch `trackE`, worktree `.worktrees/trackE`, cut from `main` after FINAL. Everything below is
synthetic demand, uncalibrated.

## Decisions

- **E-D-001 Browser driver.** The prompt names Playwright; the repo's screenshot scripts actually use
  puppeteer-core with the installed Google Chrome (`web/scripts/lib.mjs`). The frame stepper
  `web/scripts/cinema.mjs` reuses that (no new dependency, same GPU flags: ANGLE Metal on the M3
  Pro); `scripts/movies/render.py` drives it over stdin/stdout.
- **E-D-002 Python plans, the browser draws.** Camera interpolation, sun position, KPI values,
  fades and all data preparation are Python (`scripts/movies/`, unit-tested with pytest); the
  bundle in `runs/movies/<film>/bundle/` is static. The renderer (`web/src/cinema/`) is a plain
  deck.gl `Deck` without MapLibre or React, mounted only for `?cinema=<film>` (`main.tsx` branches;
  `App.tsx` is not touched). The viewer's API is reused in-process (run registry, bins,
  FCD normaliser), read only (`TT_RUNS_READONLY=1`).
- **E-D-003 Disk budget.** Frames are written to `runs/movies/<film>/frames/` in chunks of 150 PNGs;
  each chunk is encoded (libx264 CRF 18 yuv420p, bitexact) and its PNGs deleted, then the chunks
  are joined with the concat demuxer (stream copy). A whole 1080p film as PNGs would be about
  1 GB; the chunked render stays under 0.3 GB.
- **E-D-004 Package location.** The pipeline lives in `scripts/movies/` (presentation, outside
  `sim/`): `python -m scripts.movies.render|showreel|preview|spec|basemap|assets`.
- **E-D-005 Runs used.** This worktree has no runs of its own; `runs/` holds symlinks to the main
  checkout's runs (Tier A weekday baseline, remote_work_30, accident_tahlia, the M7 evacuation),
  Track A's matched-control policy runs and Track B's event runs (rain, flood, motorcade,
  emergency) and the strategist recommendation `rec-20261016T114454Z-22d13986`. All read only.
  `data/windows` is a symlink to the main checkout (window networks).
- **E-D-006 Previews and hashes.** The poster is the middle frame of the shot holding the film's
  midpoint (the midpoint itself can fall on a cut and be black); determinism hashes are taken on the
  first, middle and last frames with content (not fully faded). GIFs are 10 fps so they last
  exactly 6 s (GIF delays are hundredths of a second; 8 or 12 fps gave 6.01 s).
- **E-D-007 One new SUMO run.** The M7 evacuation runs are "as written" (simultaneous release, no
  contraflow), so the evacuation film had nothing to show for contraflow and phasing. One window run
  was added: the strategist's `near_first_full` candidate written into a copy of the scenario
  (`movies/specs/scenarios/evac_corniche_hamra_film.yaml`), run once with
  `uv run python -m sim.events.evacuation run --scenario movies/specs/scenarios/evac_corniche_hamra_film.yaml --seed 1`
  (about 5 min) -> `runs/evac_corniche_hamra_film-tahlia-s1-99ab2558`: T50 1,365 s, T90 2,934 s,
  T100 3,673 s, 2000/2000 out, contraflow on cf1-cf3 at 1,500 s, background +59.7 veh-h.
  No city run was started.
- **E-D-008 Incident framing.** `accident_tahlia` closes the whole edge and drivers re-route
  (A-event-003): the run has no queue shockwave at the crash (stopped vehicles within 1 km of it
  stay below 5 in both runs). The film shows the side-by-side and the speed-difference map and
  says so in its caption; it does not draw a queue the run does not contain.
- **E-D-009 Strategist film.** The what-ifs saved no FCD; the ambulance is moved along each route
  edge over the recorded `ambulance_edge_s` (A-mov-008, ETAs exact), the cars around it are the
  window baseline, the crash marker is the snapshot's closed lane. Options are no strategy, then
  ranks 1-3 of the recommendation.
- **E-D-010 Policy KPIs.** The policy-lab film shows the docs/policies.md results-table numbers
  (matched control for staggered schools and the cordon), entered as literals in the spec with a
  comment; edge colours are policy minus comparison run per 5-minute bin.
- **E-D-011 Tier B clock.** Window t = 0 is shown as 08:00 (A-mov-007), as
  `strategist/scenarios/emergency_tahlia_0830.yaml`; the sun on window films follows it.
- **E-D-012 Previews in git.** `movies/` stays git-ignored (except `movies/specs/`); the README GIF
  previews and JPEG stills are copied to `docs/img/movies/` (`make movies-docs`) so the README shows
  them.
- **E-D-013 Loop.** `docs/loop.md` does not exist on this branch (Track D not merged):
  `movies/specs/loop.yaml` is a validated stub (`stub: true`), skipped by `make movies` and the
  showreel. `.worktrees/trackD` was not touched.
- **E-D-014 Register merge.** `tests/test_integration.py` requires every `docs/assumptions-*.md`
  row in `docs/assumptions.md`; the A-mov rows were added there as a new "Movies (Track E)"
  section (additive, before the notes), as the brief asks to register them in the register.
- **E-D-015 Showreel length.** All films back to back with cards ran 264 s; each spec now names a
  `showreel: [start, end]` excerpt (22-24 s), giving 2 min 55 s. Title cards are drawn with Pillow:
  Homebrew's ffmpeg has no `drawtext`.

## MOVIES — 2026-10-16
Built: `scripts/movies/` (spec schema + validator, keyframed camera paths, NOAA sun and lighting,
offline basemap from the Geofabrik PBF with buildings and a sea built from coastlines, data bundles
from the run registry, render driver with chunked H.264 encode, showreel, preview server, README
asset export), `web/src/cinema/` (deck.gl renderer at `?cinema=<film>`, `window.__cinema`
load/renderFrame/frameCount, HUD), `web/scripts/cinema.mjs` (frame stepper), 8 specs in
`movies/specs/` (7 films + the loop stub), `make movies` / `make movie FILM=` / `make movies-docs`,
`docs/movies.md`, README "Movies" section with GIF previews (`docs/img/movies/`), A-mov-001..008,
`tests/test_movies.py` (20 tests incl. the 10-frame render smoke test, run twice for determinism).
Measured (final `make movies`, M3 Pro, ANGLE Metal, another agent simulating): 7 films at 1920x1080,
30 fps, exactly their spec length (30-40 s), 0.12-0.18 s per frame, 154-269 s per film, about 25 min
in all; browser RSS max 1.0-1.5 GB (budget 2 GB); disk max 97-278 MB per film (budget 1 GB); no
frames left; GIFs exactly 6.00 s, 2.19-2.83 MB; README GIFs 0.93-1.09 MB (8 MB in git with the
stills); showreel 174.7 s (2 min 55 s), 7 films + cards with crossfades. Determinism:
`tahlia-street` rendered three times (two by me, one from scratch by the verifier): identical
frame-450 hash 9c84b771766bcacf (under the earlier hash rule), identical bundle hashes and MP4 byte size; the smoke test renders
frames 100-110 twice and the hashes match. The film JSONs now hash the first, middle and last
fade-free frames (from single-frame renders of the same bundles, `frame_hash_note`; the first
one is under the title card).
Tests: 292 passed, 1 skipped (full suite, 4 min 06 s, before the last two fixes); after them
`tests/test_movies.py` + `tests/test_integration.py` pass again (see the verifier's final pass);
ruff check, ruff format --check and tsc clean.
Verifier: first pass, the from-scratch render of `tahlia-street` PASS (30.000 s, 1920x1080,
h264 yuv420p CRF 18, footer visible in the 15 s frame, no frames left, identical hashes); one FAIL
(GIFs 6.01 s at 8-12 fps) plus notes (hashes on black fade frames, six films rendered before the
last render.py, stale numbers). Fixed in E-D-006, all films re-rendered with the final code, numbers
above re-measured. Second pass: all PASS except a ruff E501 in a docstring and hashes still on
mostly faded frames; both fixed (hashes now on fade-free frames). Final pass at 787bf9d: PASS on
all five checks.
Could not verify: whether frames are bit-identical on another GPU or Chrome version; the 4K and
60 fps flags (implemented, not rendered).
Open: the incident run re-routes instead of queueing (E-D-008), so the film has no shockwave; a
crash with `lanes_closed: 1` (as in emergency_tahlia) would show one. The strategist HUD quotes the
strategist's reason text verbatim, including raw edge ids. The loop film waits for Track D.
Next: integration — merge trackE (movies/specs, scripts/movies, web/src/cinema, the main.tsx branch,
the Makefile targets); render `loop` once Track D's docs/loop.md and runs are on the branch.

MOVIES: done
