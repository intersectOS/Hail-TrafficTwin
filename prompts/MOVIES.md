# MOVIES - cinematic films of the simulations (Track E, worktree .worktrees/trackE, branch trackE)

You are on branch `trackE`, cut from `main` after FINAL (the app runs from a clean clone:
`make demo` → API :8000, viewer :5173). Goal: a reproducible movie pipeline that turns the
existing runs into cinematic films, one film per simulation mode, plus a showreel. Status
file: `docs/status/trackE.md`; finish with the line `MOVIES: done` (or `MOVIES: blocked - reason`).

## What "cinematic" means here
- Rendered from the real run data (edge bins, trajectories, events, decision logs), never faked.
- Dark, offline, deterministic basemap built from our own data: road network drawn from
  `jeddah.net.xml` geometry (motorways brighter/wider), water/coast and 3D extruded buildings
  from the Geofabrik PBF already in `data/osm/` (osmium/pyosmium or pyrosm → GeoJSON; height =
  `height` or `building:levels` x 3.2 m, default 6 m; clip to the camera's area to keep it light).
  No external tile servers, no API keys.
- Time-of-day lighting: deck.gl LightingEffect with a sun position computed for Jeddah
  (21.54 N, 39.17 E) from the simulated clock; night = emissive road glow + vehicle headlights.
- Camera paths: keyframed (lon, lat, zoom, pitch, bearing, sim-time) with eased interpolation
  (fly-in, slow orbit, dolly along a corridor, pull-back reveal). Render clock is frame-stepped
  (no wall-clock dependence): frame i ⇒ sim time t0 + i*dt, so output is bit-stable.
- Vehicles: TripsLayer with motion trails; colour by speed or by class (emergency = pulsing red/
  blue). Edges: congestion heat with glow; difference mode: blue = relief, red = worse.
- HUD (minimal, no letter-spacing anywhere): title card, simulated clock, 2-3 KPIs counting up,
  legend, a "synthetic demand, uncalibrated" footer on every film. 16:9 1920x1080 at 30 fps by
  default; `--4k` and `--fps 60` flags optional. Letterbox optional (2.39:1 flag).

## Pipeline (new files only, see ownership in _common.md)
- `web/src/cinema/`: camera-path player, lighting, buildings layer, HUD, and a `window.__cinema`
  API: `load(spec)`, `renderFrame(i)` (resolves after deck.gl finishes drawing), `frameCount()`.
  Mount it as a route/mode (`?cinema=<spec>`) without touching the normal viewer's behaviour;
  keep edits to App.tsx additive and tiny.
- `scripts/movies/render.py` (or `sim/movies/`): Playwright-driven headless Chromium (already
  used for screenshots) steps frames, writes PNGs to `runs/movies/<film>/frames/`, then ffmpeg
  (install with `brew install ffmpeg` if missing) encodes H.264 (yuv420p, CRF 18) to
  `movies/<film>.mp4`, plus `movies/<film>.poster.png` and a ≤ 6 s, ≤ 3 MB `movies/<film>.gif`
  preview for the README. Delete frames after a successful encode. `movies/` is git-ignored.
- Film specs are YAML in `movies/specs/<film>.yaml`: run id(s), window, camera keyframes, HUD text,
  duration. `make movies` renders all; `make movie FILM=<name>` renders one.
- Showreel: `scripts/movies/showreel.py` concatenates the films with title cards and crossfades
  (ffmpeg xfade), 2-3 min, `movies/showreel.mp4`.

## Films (each 20-45 s; use existing runs in `runs/` and the `make demo` outputs; if a run is
missing, produce it with the documented demo command - one SUMO run at a time, never the city
baseline rerun, never the 25%/100% population)
1. `city-24h`   Tier A city: 24-hour time-lapse of the congestion heatmap, pull-back from the
                Corniche to the whole city, sunrise → night lighting, clock + vehicles-in-network.
2. `tahlia-street` Tier B micro window at street level (pitch ~60°), dolly along Tahlia with
                trails, rush-hour density visible.
3. `incident`   accident_tahlia vs its window baseline: side-by-side or a wipe; queue shockwave
                growing upstream; KPI = extra delay.
4. `events`     rain/flood/motorcade from Track B's scenario runs (whatever exists), one cut each.
5. `strategist` the emergency vehicle run, top-3 strategies replayed one after another with the
                decision reasons and ETAs on the HUD.
6. `evacuation` Corniche/Hamra evacuation with contraflow and phased zones lighting up.
7. `policy-lab` remote-work 30% / staggered schools / central cordon in difference mode with
                matched-control KPIs counting (use the numbers in docs/policies.md; never the raw
                unmatched deltas).
8. `loop`       ONLY if `docs/loop.md` exists on this branch (Track D merged); otherwise write a
                spec stub and note it in the status file. Do not touch `.worktrees/trackD`.
9. `showreel`   all of the above.

## Engineering rules
- Determinism: same spec + same run ⇒ identical frames (hash the first/middle/last frame in the
  test). Tests: unit tests for camera interpolation, sun position, spec validation; one smoke test
  that renders 10 frames of `tahlia-street` at 640x360 and encodes them (skip if ffmpeg missing).
- Performance budget: ≤ 2 GB RSS for the browser, ≤ 1 GB per film on disk during render,
  no frames left behind. Machine: M3 Pro, 18 GB; another agent is simulating in parallel, so
  render one film at a time and do not launch SUMO city runs.
- Docs: `docs/movies.md` (how it works, how to add a film, the spec schema, the camera-path
  cookbook, stills of each film) and a README section with the GIF previews.
- Register assumptions (default building height, sun model, trail length) in the assumptions
  register with ids `A-mov-NNN`.
- Finish with the verifier subagent: it must render one film from scratch and check the MP4
  exists, has the expected duration ± 0.5 s, 1920x1080, and that the HUD footer is present in a
  mid-film frame. Fix what it finds, then write `MOVIES: done`.
