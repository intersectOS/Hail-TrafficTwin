# TrafficTwin Jeddah — status
Last updated: 2026-10-17 (pass 8: Arabic voice-over edition of every film, `movies/<film>.ar.mp4`; pass 7: city-24h, policy-lab, obhur-bridge and the showreel re-rendered on the network-v2 runs; pass 6: Track I movies v2 and Track F network v2 merged; policy re-evaluation on v2)
Environment: macOS (Apple M3 Pro, 11 cores, 18 GB RAM); Python 3.12.13 (uv-managed venv, uv 0.11.13);
Eclipse SUMO 1.28.0 from the PyPI `eclipse-sumo` wheel (works on macOS arm64; brew not needed),
SUMO_HOME = `.venv/lib/python3.12/site-packages/sumo`; osmium-tool 1.19.1 (brew); node 25, Vite 7,
MapLibre GL 5, TypeScript 5.

All results: **synthetic demand, uncalibrated**.

## Milestones
| M | Title | State | Evidence |
|---|---|---|---|
| M0 | Skeleton | done | verifier 2026-10-15; 26 tests then |
| M1 | Jeddah network | done | smoke-A-s1-5b8a19d3-ab76d081: 0.144 % teleports; docs/network-qa.md |
| M2 | Population and baseline | done (Track A) | 10 % weekday baseline 389,289 vehicles; reproduced on main: integration run below |
| M3 | Viewer and API | done (Track C) | contract v1.1 `docs/contracts/run-outputs.md`; docs/img/integration-*.png; `docker compose up` verified in M9 |
| M4 | Policy lab | done (Track A) | remote_work_30 reproduced on main: mean delay -9.3 %, AM peak -9.4 %, VKT -1.6 %, CO2 -6.9 % |
| M5 | Focus windows and events | done (Track B) | accident_tahlia on main: mean delay +5.7 % vs window baseline, 130 s wall |
| M6 | Emergency strategist | done (Track B) | top 3 in 11.6 s on main; best (68 s) beats no strategy (173 s) |
| M7 | Evacuation | done (Track B); public demo moved to Obhur (Track I) | evac_obhur via `sim.runner --scenario`: T50/T90/T100 933/1,702/2,115 s; strategist recommends balanced exits (T90 1,402 s); the Al Hamra demo was withdrawn (TI-002) |
| M8 | Calibration (dormant) | done (Track A) | synthetic round trip GEH<5 100 %; no real counts |
| M9 | Docs and release | done | `make demo` from a fresh clone: 6 min 23 s, screenshots docs/img/final-*.png; `docker compose up --build` verified; section below |
| LANE_AUDIT, v2 | Lane counts from imagery | blocked - accuracy (Track C) | held-out precision 60 % < 80 % gate; `jeddah.lanes.net.xml` not written, so not promoted |
| MOVIES | Cinematic films (Track E) | done (Track E), merged in integration pass 2; `loop` film added in pass 3 | 8 films; `loop` rendered on main 34.00 s, 246 s; showreel 171.0 s (8 films); docs/movies.md |
| LOOP | Loop tunnels | done (Track D), merged in integration pass 3 | recommended C1 + shuttle alpha 0.3 reproduced on main: relief 57,671 VHT/day, 28,820 passengers/day; docs/loop.md |
| RELEASE | Release readiness (Track G) | done (Track G), merged in integration pass 4 | CI + demo-smoke + Pages workflows, README, community files, `docs/release-checklist.md`; owner must remove the Esri crops from history before any push |
| MODECHOICE | Loop mode choice (Track H) | done (Track H), merged in integration pass 4 | C1 central 19,530 (measured) / 31,450 (vendor) riders/day vs 28,820 at fixed alpha 0.3; demo window 24 / 58 reproduced on main; docs/loop-mode-choice.md; v2 city run (pass 6): 14,630 riders/day, relief 38,718 VHT/day, teleports 0.283 -> 0.265 |
| OBHUR_BRIDGE | Obhur Creek bridges (Track J) | done (Track J, window scale), merged in integration pass 5; B1 and B3 city runs on v2 in pass 6 (B2, 3+3 pending) | six `network_change` policies validate; window: no effect beyond +/- 20 s; city v2 (10 %, seed 1, matched control): B3 -178,909 VHT/day (-9.2 %), B1 -170,801 (-8.8 %), teleports about 0.30 per vehicle, B1 span saturated; docs/obhur-bridge.md |
| MOVIES_V2 | Narration, map labels, Obhur evacuation (Track I) | done (Track I), merged in integration pass 6 | 8 films + showreel re-rendered with Kokoro voice-over, subtitles, street/district/landmark labels, compass, scale bar, callouts; audio = video length on all 9; evacuation film moved to Obhur (`evac_obhur`); docs/status/trackI.md. Pass 7 (v2 films): `city-24h` 45.87 s, `policy-lab` 50.93 s and `obhur-bridge` 80.37 s (first render on main, city-scale v2 result card) re-rendered on the v2 runs, showreel 186.3 s (9 films); all -16.1 to -16.4 LUFS, audio = video, subtitles, GIFs < 3 MB; docs/movies.md |
| NETWORK_V2 | Tier A network v2 (Track F) | blocked - teleport target (Track F), merged in integration pass 6 as the default profile | v2 `jeddah.v2.net.xml` (ae764558): 10 % weekday baseline teleports 28.3 % vs 50.5 % on m2 (target < 10 % not reached), mean delay 1,172.6 s vs 1,876.5 s; v1 and m2 still build; docs/network-v2.md |
| ARABIC_VO | Arabic voice-over edition of every film (pass 8) | done | Chatterbox Multilingual (MIT) cloning a ClArTTS reader (CC-BY-4.0), offline on CPU (RA-001, docs/movies-arabic.md); 9 films + showreel as `movies/<film>.ar.mp4`, x1.03-x1.20 of the English length, -16.2 to -16.5 LUFS, audio = video, `ara` tracks, `.ar.srt`; English films untouched |

## Integration — 2026-10-16
Merged on `main`: trackC (c5b3203), trackB (46fc412), trackA (13ed16e), in that order. Conflicts only
in `sim/runner.py` (CLI options and dispatch), resolved by keeping both sides. trackD (Loop tunnels)
was **not merged**: its status file still reads `LOOP — in progress` and its runs were active during
integration; a second integration pass is needed once it writes `LOOP: done`.
Lane audit: both passes are `blocked - accuracy`, so `data/jeddah/jeddah.net.xml` stays the default
network (no hash change, demo window not re-cut).

Fixes and wiring done at integration:
- `sim.runner --scenario evac_*` dispatches to `sim.events.evacuation.run` (B-D-026); the event
  registry registers the evacuation class lazily (`build_events`).
- `run_baseline` gained `routing_threads` and `gz` (`sim.runner --baseline --routing-threads N --gzip`);
  `sim.policies.baseline_launch` is now a thin wrapper (TA-016 fold-in).
- Register: `strategist/strategist.yaml`, `strategist/weights.yaml` and `sim/scenarios/evac_settings.yaml`
  added to the Track B register sources (B-D-024, B-D-031); all track rows merged into
  `docs/assumptions.md` (256 ids, one duplicate row A-act-006 removed); a test keeps them in step.
- API contract v1.1 (additive, reader-side `api/normalize.py`, `api/strategist_link.py`): scenario
  and evacuation runs expose their `scenario/`/`evacuation/` sub-run with a `~baseline`/`~reference`
  comparison run; pointer dirs resolve to the hashed run; strategist recommendations map to §8
  options and API approvals append to the strategist's own SQLite chain; policy reports get the
  §6 shape from `policy_districts.parquet`; gzipped edgeData accepted; bins cache stores only edges
  with data (224 MB instead of ~1.55 GB per 24 h city run). Producers' files are untouched.
- `pillow` is a direct dependency (C-001); README carries the M2-M8 commands and the viewer/API
  commands; stub comments removed from docker-compose and Dockerfile.api.
- Gates: ruff clean, pytest 267 passed / 1 skipped (about 3 min), web typecheck and build pass.
  Local npm has `omit=dev` and the shell sets `NODE_ENV=production`: use `npm ci --include=dev`.

End to end on the merged code (10 % sample, seed 1; all **synthetic demand, uncalibrated**):
| run | command | wall | result |
|---|---|---|---|
| baseline-weekday-f0.1-s1-e5f1906a-65fac195-65b0f3 | `sim.runner --baseline --daytype weekday --sample 0.10 --seed 1 --routing-threads 8 --gzip` (gzips edgeData, emissions and tripinfo; build.log and sumo.log stay plain) | 680 s (assignment from the route cache; sim 616 s, peak 2.8 GB) | identical to Track A's run: routes hash a297ac7632dd529d, 389,289 vehicles, mean delay 1,876.5 s, 20.46 km/h, VKT 56.1 M, CO2 26,185 t; teleports 50.5 % (TA-011) |
| remote_work_30 | `sim.runner --policy remote_work_30 --daytype weekday --sample 0.10 --seed 1` | 779 s (about 13 min) | mean delay -9.3 %, AM-peak -9.4 %, VKT -1.6 %, VHT -7.7 %, CO2 -6.9 % (same routes hash 01ff40085fb11d11 as Track A) |
| accident_tahlia-tahlia-s1-257eae8d | `sim.runner --scenario accident_tahlia --window tahlia --seed 1` | 130 s | mean delay 97.8 -> 103.5 s (+5.7 %), as in M5 |
| strategist rec-20261016T114454Z-22d13986 | `strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1` | 11.6 s | Route A + rescue lane 68 s, Route B + preemption 89 s, Route C 95 s; no strategy 173 s |
| evac_corniche_hamra-tahlia-s1-162d21cb | `sim.runner --scenario evac_corniche_hamra --seed 1` (scenario withdrawn by Track I, TI-002; replaced by `evac_obhur`, docs/evacuation.md) | 328 s | 2,000/2,000 out; T50 1,264 s, T90 2,399 s, T100 3,004 s; background +90.1 veh-h |

Viewer: all five appear in `/api/runs`; the baseline, policy, accident and evacuation runs carry their comparison runs (the strategist recommendation has none: it has no run of its own, `strategist~...`); screenshots
`docs/img/integration-{baseline,policy,policy-districts,accident,strategist,evacuation}.png`
(`node web/scripts/screenshot-runs.mjs web/scripts/integration-shots.json`, API on 8010 because
port 8000 was held by Track C's API).

Decisions:
- I-001 The baseline E2E reused Track A's route cache (APFS clones of `data/population/`,
  `data/policies/`, and Track B's `data/windows/`) instead of a 2 h re-assignment; the cache key
  matched, and the outputs are identical. Its config hash differs (65b0f3 vs f124c5) because
  `baseline.yaml` changed after Track A's run (e434ce0); the route key did not.
- I-002 Contract conformance is reader-side (contract v1.1, §12) so no producer output or test
  changed; native `recommendations.json` runs keep `decisions.jsonl`, strategist runs use its SQLite log.
- I-003 Lane audit not promoted (blocked); default network unchanged.
- I-004 trackD skipped (not done); second integration pass required.

Verifier (2026-10-16, whole repo vs PROJECT.md G1-G6): G1-G5 PASS; G6, hygiene and STATUS FAILs
fixed: NOTICE no longer claims imagery-derived lanes (audit blocked) and the 12 Esri crops in
docs/img/lane-audit/ are untracked and gitignored (they remain in git history from trackC); the flood-site list
stays public (I-005) with docs, .gitignore and CLAUDE.md aligned; the strategist snapshot
`state_hash` ignores the SUMO header (approve also accepts the old whole-file hash); policy reports
point at docs/assumptions.md; three STATUS wording fixes.
- I-005 `data/jeddah_flood_sites.yaml` stays committed: a reviewed compilation of publicly reported
  flood sites (press and papers, B-D-005/007) that the brief asks for. Scenario files that pair sites
  with timings stay fictional. Reverse by untracking it if the owner treats the list as private.

Could not verify at integration (verified in M9): `docker compose up --build`. Not verified: a fresh,
uncached 2 h assignment on the merged code (the cache path was exercised instead).
Open: network capacity (TA-011: 50 % teleports in the city baseline) is the top realism issue; the
windows are linked to the M1 smoke route set, not to the M2 baseline (B-D-002), so re-link them to
the baseline routes; Tier B trajectory loading should be chunked (p5 30 fps on 1 h windows);
strategist-only runs have no edge bins; one noise replicate per policy and strategist.

## M9 Docs and release — 2026-10-16
One command from a clean clone: `make demo` (or `make setup city-net demo-runs ingest serve`).
Built: `Makefile` (demo, setup, city-net, demo-runs, ingest, serve, city, test, screenshots, stop),
`run_app.sh` (API + Vite, port checks, `--detach`, `TT_API_PORT`/`TT_WEB_PORT`/`TT_NO_OPEN`),
`python -m sim.demo` + `sim/config/demo.yaml` (six steps, skipped when done, manifest
`runs/demo-manifest.json`), `sim/scenarios/demo_events.yaml`, `sim.runner --smoke --begin`,
`web/scripts/final-shots.mjs`, a `demo` service in `docker-compose.yml`, `.dockerignore`, and the
docs: README quickstart, `docs/architecture.md` (Mermaid), `docs/demo-script.md`, `CONTRIBUTING.md`,
`CHANGELOG.md`; register row A-demo-001.

Clean-clone proof (`git clone` of b6e11e8 into /tmp, `TT_API_PORT=8010 TT_NO_OPEN=1 make demo
DETACH=1`, port 8000 was held by a stale Track C uvicorn): passed first time, **6 min 23 s** wall
including the 243 MB Geofabrik download (latest extract, 2026-10-16), `build_city` 145 s (156,126
edges, 72 traffic lights, net hash 79f35c9a: same size as main's 5b8a19d3, newer OSM data), and the
demo steps:
| step | run | wall | result |
|---|---|---|---|
| tier-b | smoke-B-s1-25c06763-9cfa755f | 2.9 s | 1,800 trips, 0 teleports |
| events | demo_events-demo-s1-342c09a8 | 8.0 s | mean delay 30.8 -> 54.4 s, max queue 13.5 -> 133 m, 15 re-routed |
| strategist | strategist~emergency_demo-demo-s1 | 1.9 s | Route B 65 s, Route A + rescue lane 69 s, Route C 108 s; no strategy 72 s |
| evacuation | evac_demo-demo-s1-ed042153 | 6.2 s | 150/150 out; T50/T90/T100 383/642/733 s |
| policy | demo-remote_work_30 vs baseline-weekday-f1-s1-25c06763-32b0cbf8-1ea5e5 | 10.1 s | demo scale (8,000 residents): VKT -1.6 %, VHT -1.4 % |
| tier-a | smoke-A-s1-79f35c9a-1f109fdd | 170 s | 12:00-13:00, 3,600 random trips, 0 teleports, RTF 253 |

Screenshots from that clone (`make screenshots`, headless Chrome): `docs/img/final-city.png`,
`final-tierA-midday.png` (slider 12:30), `final-tierB-scenario.png` (vehicles + accident),
`final-strategist.png` (three ranked options), `final-policy.png` (difference mode + report).
(f) Loop: **not present** (Track D not merged), so no `final-loop.png`.

Docker (`docker compose up --build` in a second fresh clone): the first attempt failed: the
eclipse-sumo Linux binaries need `libatomic1`, `libx11-6`, `libxext6`, `libxrender1` and `libgl1`
even headless (never seen before because compose had never been run). Fixed in `Dockerfile.api`;
then the `demo` job built the same network hash (79f35c9a) and the same Tier B, scenario,
strategist and evacuation run ids as macOS and the same Tier A run id (smoke-A-s1-79f35c9a-1f109fdd,
289 s in the container vs 170 s native); `api` turned healthy, `web` served the viewer, and
`/api/runs` through the Vite proxy listed all 9 runs (host ports 8020/5180 via `TT_API_PORT` /
`TT_WEB_PORT`); a headless screenshot of the containerised viewer matched final-city.png. The
download path ran in the failed attempt; the second attempt reused the downloaded extract.

Gates: ruff and format clean; pytest on main 272 passed / 1 skipped (about 3 min); in a fresh
clone 273 tests, 271 passed / 2 skipped (the Tahlia window data is gitignored, so its test skips);
web typecheck clean.

Verifier (2026-10-16, its own fresh clone /tmp/tt-verify-20261016-155907 of 53c1746, ports
8030/5190): clean-clone `make demo` PASS in 413 s with the same run ids and KPIs as above; a second
`make demo` skips every step (4 s); determinism PASS (`--force` rerun of `events`:
`scenario_report.json` identical); screenshots, `make test`, docs, hygiene and docker config PASS.
Its one FAIL (STATUS honesty: `docs/status/final.md` uncommitted with placeholders, no word about
the demo video, no M9 test gate) is fixed by this block and the committed final.md.

Not delivered from PROJECT.md M9: a **demo video**. None was recorded (headless session); the
screenshot set `docs/img/final-*.png` and the 5-minute script `docs/demo-script.md` stand in for it.
The list of what is still missing against G1-G6 is in `docs/status/final.md`.

Decisions:
- F-001 `make demo` builds the city network by default (the brief asks for the city view);
  `CITY=0` skips the download and the Tier A step.
- F-002 The policy comparison in the demo runs on a demo-scale population of the demo window
  (four rectangular quadrant "districts", A-demo-001), because a city policy needs the 2 h
  baseline. The city result (remote_work_30: mean delay -9.3 %) is quoted from M4.
- F-003 The Tier A demo is a one-hour random-trip smoke at 12:00 (`--begin`, additive) so the
  slider opens at mid-day; behavioural 24 h demand is `make city`.
- F-004 Demo runs are skipped when their outputs exist (manifest), so `make demo` restarts in
  seconds; `make setup` runs `npm ci` only when `web/package-lock.json` changed (verifier note: it
  wiped `node_modules` under a running Vite server).

Open (M9): demo population hash differs between macOS and the Linux container
(`baseline-...-32b0cbf8-...` vs `-0d65c7fc-`): PROJ/shapely zone areas differ in the last float
bits (0.825160229218671 vs 0.8251602292184539 km2). Runs are bit-identical per platform; to make
them identical across platforms, round geometry-derived floats in `sim/population/zones.py` at the
next baseline regeneration (it changes every population hash and invalidates the 2 h route cache).

## Integration pass 2 (Track E movies) — 2026-10-16
Merged `trackE` (cut from main at cb98f6d, so no conflicts) with `--no-ff`. Carried: `scripts/movies/`,
`movies/specs/` (the only tracked path under the ignored `movies/`: `.gitignore` is now
`movies/*` + `!movies/specs/`), `web/src/cinema/`, the `?cinema=` branch in `web/src/main.tsx`,
`web/scripts/cinema.mjs`, Makefile targets `movies`, `movie`, `showreel`, `movies-docs`,
`docs/movies.md`, the README "Movies" section, the `docs/img/movies/` stills and GIF previews
(7 GIFs + 8 JPGs, about 8 MB), `tests/test_movies.py`, the A-mov-001..008 register rows (already in
`docs/assumptions.md` on the branch, E-D-014). No MP4, frame or rendered output from `movies/` is in git.
Track D (`.worktrees/trackD`, Loop tunnels) was neither merged nor touched; the `loop` spec stays a stub.

Gates on merged main (logs/integrate-e-gates.log, logs/integrate-e-pytest.log): ruff check + format clean;
pytest 292 passed, 1 skipped (incl. the 20 movie tests and the render smoke test); `tsc --noEmit` and
`vite build` pass. Fix found by the verifier: the render smoke test wrote its 640x360 bundle into the
real `runs/movies/` cache; `movies_runs_dir()` now honours `TT_MOVIES_DIR` and the test uses a temp dir.

Decision I-006 (film source runs): the films read 11 runs that existed only in other worktrees (Track A
`cordon_center`, `staggered_schools_60` and their `--control` runs; Track B rain, flood, motorcade,
emergency and `evac_flood_balad` window runs; Track E's `evac_corniche_hamra_film` scenario and run,
E-D-007), reached through symlinks in `.worktrees/trackE/runs/`. They were copied (rsync, about 1.1 GB,
real directories, sources untouched) into main's untracked `runs/`, so the films rebuild from main
alone. Bundle caches (`runs/movies/`) and `_viewer-cache` were not copied (both regenerate).

End to end on main: `python -m scripts.movies.render tahlia-street` gave 1920x1080, 30.00 s, 21.6 MB,
900 frames at 0.12-0.15 s each, 155.9 s wall, browser RSS max 1,256 MB; bundle hashes and the
fade-free frame hashes are identical to Track E's render (only timing and RSS differ). The other six
films (`city-24h`, `incident`, `events`, `strategist`, `evacuation`, `policy-lab`) were rendered as
frames 100-101 (2 frames each) to a scratch directory: all bundle hashes identical to Track E's. Full `make movies`
(about 25 min) was not repeated on main.
Note: in this shell `NODE_ENV=production`, so a bare `npm ci` skips devDependencies (no `tsc`/`vite`);
`make setup` already passes `--include=dev`.
Open: the `loop` film waits for Track D (next integration pass: merge trackD once `LOOP: done`, then
`make movie FILM=loop`); incident film has no shockwave (E-D-008); strategist HUD shows raw edge ids.

## Integration pass 4 (Track G release, Track H mode choice) — 2026-10-17
Merged `trackG` (`RELEASE: done`, verifier PASS) then `trackH` (`MODECHOICE: done`, verifier PASS)
with `--no-ff` (de540db, b0cca5e). No conflicts and no shared files between the two branches.
trackF, trackI and trackJ were not merged and their worktrees not touched; nothing from `movies/` went
into git; no push, no remote. Light pass (machine shared with three running agents): no city run,
no render.

Fixes on main: the 10 rows A-loop-021..030 from `docs/assumptions-trackH.md` merged into
`docs/assumptions.md` (sub-table after A-loop-020), which turns TH-005
(`test_merged_register_holds_every_track_row`, expected pre-integration failure) green; README Loop
section gained the mode-choice command (TH-005 note).

Gates: ruff check + format clean; pytest 326 passed, 1 skipped (9 min 54 s under load; the skip is
the lane-audit fix-list test); `tsc --noEmit` passes. `make demo` (serves the app on ports 8000/5173,
in use by other agents) was not run; Track G's verifier ran its steps on a fresh clone.

Demo window on main (synthetic demand, uncalibrated): `sim.loop.evaluate --mode-choice
sim/loop/config/mode_choice.yaml --demo` gives 24 riders/day (measured service) and `--service vendor`
58 riders/day, of 286 eligible legs, 0 capped: identical to Track H's numbers. Logs
`logs/integration4-mc-demo-{measured,vendor}.log`.

Open (carried from the tracks):
- Owner, before the first push: `docs/release-checklist.md` step 1 (remove the 12 Esri crops from
  history with `git filter-repo`) is mandatory; step 2 fills `OWNER` and `CONDUCT_CONTACT` (G-D-004).
- `docs/issues/04-mode-choice.md` was written before Track H; Track H now covers its core (logit
  mode choice for the Loop); the issue can be narrowed to city-wide mode choice and road-time feedback.
- Mode-choice city runs (`evaluate --mode-choice ... --ids C1`) not run on main; Track H's offline
  sweep read Track D's baseline (TH-004). Not started here (city runs belong to another agent).

## Pass 8 (Arabic voice-over edition) — 2026-10-17
Owner's request: Arabic films for Arabic speakers, English films for English speakers.
- **Voice (RA-001).** Chatterbox Multilingual (Resemble AI, MIT, `ResembleAI/chatterbox` 5bb1f6ee)
  cloning ClArTTS utterance 417 (MBZUAI, CC-BY-4.0), in its own venv `.venv-tts-ar` (torch 2.6),
  CPU, seed 1, exaggeration 0.9, cfg 0.4; then pauses capped at 0.3 s and tempo x1.12 (ffmpeg
  atempo). Compared with Chatterbox's built-in voice and Piper `ar_JO-kareem` (clips, 22 kHz,
  unclear data licence); Fish S1-mini (CC-BY-NC-SA, gated) and XTTS-v2 (CPML) not tested.
  Whisper back-transcription: 0 % CER on the test lines. Digits are misread, so numbers are spoken
  as words (`say`) and shown as digits in the subtitles (`text`).
- **Pipeline.** `--lang ar` through narrate/render/showreel (not a fork): `voice.ar` settings,
  cache `runs/movies/_voice_ar/`, outputs `<film>.ar.*`, tracks tagged `ara`, HUD subtitles
  `dir="auto"`; `make movie FILM=x LANG=ar`, `make movies-ar`, `make voice-setup-ar`. `narrate
  validate` checks each Arabic script against its English one (anchors, subtitle digits, spoken
  number words read back by `ar_numbers`, closing «طلب اصطناعي، غير معاير»).
- **Measured.** Synthesis of 56 lines: about 1.5 min per line per worker on the CPU; 2 workers (4
  swapped on 18 GB). Films: city-24h 55.13 s, tahlia-street 30.90 s, incident 48.90 s, events
  47.17 s, strategist 54.77 s, evacuation 59.37 s, policy-lab 58.17 s, loop 53.53 s, obhur-bridge
  89.20 s, showreel 186.33 s (x1.03-x1.20 of English; first plan was x1.30-x1.74 before the tempo
  step and tighter lines). Renders 3-7 min each.
- **Issues met.** The evacuation run is only in `.worktrees/trackI/runs` (rendered read-only with
  TT_RUNS_DIR); the first Arabic showreel cut the closing caveat (fixed, and showreel.py now
  fails on it). Listen-check list in docs/movies-arabic.md (123.8 in events, «ونفق لوب» in the
  showreel, «فالحجم استرشادي», «غير معاير» in two caveats).
- Not translated: title cards, captions, KPI labels, legend (English, from the specs); map labels
  stay bilingual.

## Integration pass 6 (Track I movies v2, Track F network v2) — 2026-10-17
Merged `trackI` (`MOVIES_V2: done`; 02c353a) then `trackF` (`NETWORK_V2: blocked` = teleport target
missed, code complete; 725a8e5), both `--no-ff`.

Conflicts and fixes:
- trackI: `.gitignore` (both: `_site/` and `!movies/landmarks.yaml`), `NOTICE` (both: basemap/images
  /dependencies blocks from Track G and the Kokoro-82M block), `CHANGELOG.md` (trackI's Unreleased
  section above main's 0.1.0 public-release entry), `docs/STATUS.md` (both milestone rows).
- trackF: `Makefile` `.PHONY` (both `city-net-v1` and `voice-setup`).
- Fixes after the trackI merge (separate commit): README films table and results row and the Pages
  site still described the withdrawn Al Hamra evacuation (Track G wrote them after trackI branched);
  now Obhur (T50/T90/T100 933/1,702/2,115 s; strategist T90 1,402 s) and the v2 film lengths/sizes.
  The `obhur-bridge` film (trackJ) had no narration, which trackI's test requires: its narration
  moved from the spec comment to `movies/specs/obhur-bridge.narration.yaml`, `narrate` now also
  checks numbers against `docs/obhur-bridge.md`, and the showreel narration has an `obhur-bridge`
  headline (with its own caveat, since unrendered films are skipped). The Al Hamra window is not a
  scenario any more (trackI deleted `evac_corniche_hamra`); the `tahlia` window stays for the other
  Tier B events. Films were not re-rendered; trackI's renders stay in `.worktrees/trackI/movies/`.

Gates after each merge: ruff check + format clean; pytest 371 passed, 2 skipped; `npm run build` OK.

Network v2 on main: `sim/population/config/{baseline,zones}.yaml`, `sim/config/runner.yaml` and the
Makefile now point at `data/jeddah/jeddah.v2.net.xml` (hash ae7645589de321f9, shared symlink).
Untracked data on main: the m2-based zones moved to `data/population/zones-m2/`; the v2 zones
(d949c812), population dir `pop-0609d42c29-s1-f0.1` (hash 346893f2) and route cache `373481fcdd235924`
copied from the trackF worktree (123 MB). Runs linked, not copied (1.4 GB):
`runs/baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1`, `runs/smoke-A-s1-ae764558-ab76d081` and
the ten `runs/probes/*` -> `.worktrees/trackF/runs/`. `python -m scripts.pass6_v2 check` resolves the v2
baseline from main (network ae764558, population 346893f2), so `sim.policies.run` would not start a new
assignment.

v2 policy runs go to `runs/v2/` (`scripts/pass6_v2.py`), because `run_policy` deletes an existing
`runs/<policy id>` and the v1/m2 runs (e.g. `runs/remote_work_30`) must stay; `runs/v2/<baseline id>`
links to the same trackF run. Run log: `logs/orch/pass6-runs.log`.

v2 re-evaluation (Part 2): all six priority runs finished (07:12-08:57, one at a time; 8 routing
threads; log `logs/orch/pass6-runs.log`), 10 % sample, seed 1, each against the v2 weekday baseline
(and its matched control where the policy re-routes vehicles). Every number is synthetic demand,
uncalibrated; teleport shares are a quality flag (v2 baseline 28.3 %). Seed-noise band: v1 ±34k
VHT/day; no second-seed v2 baseline exists, so not recomputed.

| run (runs/v2/) | wall | v1 (m2) result | **v2 result** | teleports/veh v2 (base -> policy) |
|---|---|---|---|---|
| `obhur_bridge_b3` (B1 + B2) | 28 min | window only: within +/- 20 s noise | VHT -178,909 h/day (-9.2 %), AM-peak delay -20.9 % | 0.296 -> 0.305 |
| `staggered_schools_60` | 14 min | AM-peak -9.1 %, top-hour -19.1 %, VHT -19,342 h | AM-peak -1.8 %, top-hour -13.3 %, VHT +23,033 h (in noise) | 0.274 -> 0.275 |
| `loop_c1_mcmeasured_f26ed359` | 7 min | alpha 0.3: 28,820 pax, relief 57,671 VHT/day; logit offline 19,530 pax | 14,630 pax/day, relief 38,718 VHT/day, city VHT -46,684 | 0.283 -> 0.265 |
| `remote_work_30` | 7 min | delay -9.3 %, VHT -210,563 h | delay -11.4 %, AM-peak -13.2 %, VHT -167,819 h | 0.283 -> 0.244 |
| `cordon_center` | 20 min | delay +20.1 %, VHT +309,345 h | delay +29.7 %, VHT +341,271 h | 0.275 -> 0.454 |
| `obhur_bridge_b1` (mouth) | 29 min | window only | VHT -170,801 h/day (-8.8 %), AM-peak -18.6 % | 0.296 -> 0.303 |

Fix found by the B3 run: `sim.bridge.run.write_bridge_report` matched Obhur districts on the first
three columns (never the names), so its district table was always empty, and its markdown needed the
missing `tabulate` package (f1a4c00). Disk stayed at 40-41 GB free (nothing deleted). Verifier
(independent agent) found number and label nits in the new sections; fixed. Docs updated:
`docs/policies.md` (v2 section), `docs/obhur-bridge.md` §5-6, `docs/loop.md`, `docs/loop-mode-choice.md`.

## Integration pass 5 (Track J Obhur Creek bridges) — 2026-10-17
Merged `trackJ` (`OBHUR_BRIDGE: done`, verifier PASS after three fixes on the branch; head 4c5d387) with
`--no-ff`. No conflicts: `docs/assumptions.md` auto-merged with both the Loop (A-loop-001..030) and
the Obhur (A-obh-001..041, 21 rows) sections kept. The branch is additive (`sim/bridge/`,
`sim/policies/obhur_bridge_*.yaml`, `sim/network/windows/obhur_creek.yaml`, `tests/test_bridge.py`,
`docs/obhur-bridge.md`, `docs/assumptions-trackJ.md`, `docs/data-sources-trackJ.md`,
`docs/img/obhur-desire.png`, `movies/specs/obhur-bridge.yaml`) plus two small additive hooks:
`sim.schemas.validate_file` dispatches `network_change` policies with a `bridges:` block to
`BridgePolicy`; `sim.policies.sweep.template` skips policies other tracks own. trackF and trackI not
merged or touched; nothing from `movies/` in git besides the spec; no push, no remote; no SUMO run.

Gates: ruff check + format clean; pytest 350 passed, 1 skipped (5 min 39 s); all six bridge policies
validate through `sim.schemas.validate_file`; `scripts.movies.spec validate` OK for all 9 specs.

Film: the window runs and the window network (gitignored) were copied from the trackJ worktree into
main's untracked `runs/obhur-window/`, `runs/bridge-nets/`, the 25 `runs/obhur-{am,pm}-*` links and
`data/windows/obhur_creek/` (about 400 MB, byte-identical, so the network hashes match). Smoke render
on main `render obhur-bridge --frames 0:60 --size 640x360 --out /tmp/...`: 60/60 frames, 41 s. Full
render not repeated (Track J: 1920x1080, 36.00 s, 182 s). `obhur-bridge` is not in
`movies/specs/order.yaml`, so the showreel is unchanged (8 films).

Deferred (by instruction): the Obhur bridge city runs, on the v2 network, in a later pass. Commands and
estimate (1.5-2 h for the three 2+2 variants plus about 2 h for a v2 baseline) in
`docs/status/trackJ.md`; `docs/obhur-bridge.md` §5-6 keep their *pending city run* cells until then.
The public evacuation demo stays on Obhur (this merge touches no evacuation scenario).

## Integration pass 3 (Track D Loop) — 2026-10-16
Merged `trackD` (status `LOOP: done`, verifier PASS at 21:00) with `--no-ff` (b476837). No conflicts:
the branch is additive (`sim/loop/`, `sim/policies/loop_*.yaml`, `docs/loop.md`,
`docs/assumptions-trackD.md`, `docs/data-sources-trackD.md`, `docs/img/loop-candidates.png`,
`tests/test_loop*.py`) plus the one appended line in `sim/schemas.py`. Track E was not redone.

Fixes on main: (1) the merge broke `test_merged_register_holds_every_track_row`: the 21 A-loop rows
are now in `docs/assumptions.md` (section "Loop tunnels (Track D)"); `docs/data-sources.md` points to
the two track source lists. (2) `python -m sim.schemas sim/policies/loop_*.yaml` failed: under
`-m` the module is `__main__` and `app()` ran before the appended Loop import, so `validate_file` now
validates policies with a `loop_*` transform as `LoopPolicy` (lazy import). (3) README gained a
"Loop tunnels (Track D)" section and the `loop` GIF in the Movies preview.

Gates: ruff check + format clean; pytest 316 passed, 1 skipped (4 min 30 s); `tsc --noEmit` and
`vite build` pass.

End to end on main (10 % sample, seed 1, synthetic demand, uncalibrated):
- `uv run python -m sim.loop.run loop_demo --demo`: 6.8 s; Loop report identical to Track D's
  (2.26 km, 3 stations, relief 0 VHT/day, net person-h -49). In the viewer through the API
  (`TT_RUNS_DIR=runs/loop-demo/runs`, the demo's own runs dir): `docs/img/integration-loop-demo.png`.
- `uv run python -m sim.loop.run loop_recommended`: 504 s (sim 388 s), start/compare baseline
  `...-65b0f3` (outputs identical to Track D's `...-f124c5`, I-001). Reproduces Track D's
  `loop_opt_c1_a0p3` exactly: relief 57,671 VHT/day (+2.12 %), 28,820 passengers/day, segment
  exceedance 0.017, AM-peak road delay -2.85 %, city VHT saved 61,140/day. Listed by `/api/runs` with
  its baseline: `docs/img/integration-loop.png`.

Loop film: `movies/specs/loop.yaml` is now a real spec (3 shots, 34 s): C1 alignment and its 8
stations over the morning-peak baseline, then difference mode (`loop_recommended` minus the
baseline) in the morning peak along the corridor and the evening peak across the city. KPIs are copied
from the docs/loop.md Recommendation table. `make movie FILM=loop` (final spec): 1920x1080, 1020 frames, 34.00 s,
69.7 MB, 0.19 s/frame, 246 s, browser RSS max 1,363 MB, disk max 308 MB. Showreel rebuilt with 8 films:
171.0 s, 5130 frames; README GIFs and stills re-exported (`loop.gif` 1.05 MB, `loop.jpg`).
Verifier (independent agent): merge hygiene, register, schema CLI, film numbers against docs/loop.md,
reproduction of `loop_opt_c1_a0p3`, docs and screenshots PASS; `loop_demo` run twice gives identical
outputs. Two FAILs fixed: the manifest keys above (I-008) and the stale `spec_sha` note (I-009);
caption nits fixed (relief KPI says two-seed mean; C8 is an airport test, not a hot-spot pick).

Decisions:
- I-007 Film source run: Track D's city runs had their edge Parquet pruned (disk rule,
  `evaluate --prune`), so none of `.worktrees/trackD/runs/` could feed a heat map and **nothing was
  copied** from it. Instead the recommended policy file was run on main (`runs/loop_recommended`,
  173 MB, gitignored), with identical results to `loop_opt_c1_a0p3` (above).
- I-008 Renderer: two optional layer fields, `line` (open polyline) and `stations` (points), in
  `scripts/movies/spec.py`, `web/src/cinema/{types,scene}.ts` (additive; other specs unchanged, bundle
  manifests unchanged: `bundle.py` leaves the two keys out of `manifest.json` when unset, verifier
  fix; `city-24h` re-bundled on main has Track E's bundle hashes). Test
  `test_loop_film_draws_the_recommended_alignment`.
- I-009 Showreel length: with the 8th film the showreel was 198 s, over the 2-3 min brief, so every
  spec's `showreel:` excerpt is now 20 s (171 s total). The field is read only by `showreel.py`, so
  film frames and bundles are unchanged; the six films rendered in Track E's worktree were cloned
  (`cp -c`) into main's `movies/` rather than re-rendered (their bundle hashes match main's, pass 2);
  the recorded `spec_sha` in `movies/<film>.json` of those six and of `tahlia-street` predates this
  excerpt edit (only the `showreel:` line changed); `loop` was re-rendered after it and matches.
- I-010 The viewer offers no comparison for Loop runs: it compares only runs on the same network
  hash, and a Loop run uses the tunnel variant network (`8427a6128498c026`). The film's
  difference mode matches edges by id, so it works; a viewer compare across variant networks is a
  follow-up.

## Measured
- M0: pytest 26 tests, 8.6 s wall (demo window only, offline). Demo window: 939 edges, 401 junctions,
  1 traffic light, 114.36 lane-km. Tier B demo smoke (micro, seed 1, 1 h, 1,800 trips): 0.76 s,
  1 teleport (0.056 %). Same seed twice: identical population_hash and results (verifier, seed 3).
- M1 city network (`data/jeddah/jeddah.net.xml`, OSM 2026-10-14, 3 fixes): 156,126 edges, 62,513
  junctions, 72 traffic lights, 171,590 lanes, 20,952.88 lane-km, 18,010.64 edge-km; 353 MB net
  XML; build 56 s (netconvert + fixes + side outputs). Main strongly connected component 99.10 % of
  passenger edges. Districts: 112 polygons (OSM admin_level 10). Buildings: 27,783 footprints, 9.7 MB.
- M1 Tier A smoke (meso, seed 1, 0-3600 s, 18,001 random trips, period 0.2 s): inserted 17,994,
  completed 10,825, running at end 7,169; SUMO wall 24.1 s (real-time factor 149; SUMO's own
  performance figure 306); demand generation (randomTrips + duarouter, 5 routing threads) 500 s;
  teleports 26 (all jam) = 0.144 %; mean route length 24.8 km. Peak RSS of the meso run 2.87 GB
  (measured on the pre-extension network, same demand size).
- M2-M8 measured numbers: see the integration table above and the track handoffs below
  (docs/population.md, docs/policies.md, docs/events.md, docs/strategist.md, docs/evacuation.md,
  docs/calibration.md, docs/viewer.md, docs/lane-audit.md).

## Decisions
- D-001 SUMO install path: `uv` + `eclipse-sumo` 1.28.0 wheel (macOS arm64 wheel installs and runs;
  sumolib and traci 1.28.0 from PyPI). `sim/common.py` sets SUMO_HOME from the wheel.
- D-002 Python 3.12 pinned (`.python-version`, `requires-python >=3.12,<3.13`).
- D-003 OSM extract: Geofabrik has no Saudi-only file; `asia/gcc-states-latest.osm.pbf` is used
  (243 MB, replication timestamp 2026-10-14T20:21:12Z, downloaded 2026-10-15).
- D-004 Jeddah polygon `data/osm/jeddah.poly`: lon 39.02-39.33, lat 21.26-21.90 (south edge moved from 21.30, D-014), tapered in the
  north-east and cut at lon 39.33 in the east so the Makkah highway beyond the city is excluded.
  Sea inside the box carries no roads. Rough; refine when an official boundary is available.
- D-005 Demo window = western Tahlia Street + Al Andalus, bbox lon 39.148-39.166, lat 21.542-21.558
  (3.3 km2), placed after locating Tahlia Street (OSM way 38500585) in the data.
- D-006 The city network was built before the demo window was committed, so the M0 demo window
  was produced directly by the M1 pipeline (`build_window --name demo`), as the brief asks for M1.
- D-007 Windows are cut from the city `.net.xml` (not rebuilt from OSM) so edge ids match Tier A
  exactly (required by cutRoutes in M5). Consequence: windows do not contain service roads.
  Revisit in M5 (option: a window-specific OSM rebuild plus an id-mapping step).
- D-008 netconvert reads gzip OSM XML directly; the city clip is stored as `jeddah.osm.gz`.
- D-009 Tool commands run from the repo root with repo-relative paths so SUMO headers in committed
  outputs do not contain local paths; run hashes (`population_hash`) ignore XML comments.
- D-011 Commit order: the M0 commit already contains the M1 builder code (written in the same
  session); M1 is declared done only in its own commit after its verifier run.
- D-013 Fix list: King Abdulaziz Road carriageways (ways 85191646, 43061113, 1071541010) have no
  `lanes` tag and defaulted to 2 lanes while tagged segments carry 4; fixed with a new
  `lanes_min: 4` fix type (raises only, keeps guessed ramp lanes). FIX-0001..0003 -> 68 edges.
- D-014 Polygon extended south from lat 21.30 to 21.26 after QA showed a 161 km southern district
  was unreachable (its only access crossing lay outside the clip): teleports 0.228 % -> 0.144 %,
  main SCC 98.61 % -> 99.10 %.
- D-015 Traffic lights stay OSM-only (`--tls.guess-signals --tls.discard-simple --tls.join`, 72
  programs from 338 OSM signal nodes). `--tls.guess` tested: 222 programs at the default threshold,
  30,275 at threshold 40, because untagged roads default to 100 km/h. Revisit after the
  untagged-lanes/speeds overlay (docs/network-qa.md).
- D-016 Buildings GeoJSON is 9.7 MB (< 50 MB) but stays gitignored with the rest of data/jeddah
  (CLAUDE.md: only data/demo, data/osm/fixes and data/census are committed); rebuilt by build_city.
- D-017 Strong connectivity is measured with `python -m sim.network.netinfo scc` (passenger lane
  connections, iterative Tarjan). Cut windows are far from strongly connected (demo: 49.7 %), because
  boundary edges are entry-only or exit-only; M5's cutRoutes link supplies through traffic.
- D-018 Lane-level outputs (`--lanechange-output`, `--queue-output`, `--lanedata-output`) added to
  the Tier A micro-only guard; `time-to-teleport` registered as A-sim-002 and the inherited typemap
  defaults for untagged roads as A-network-003.
- D-012 `run_claude.sh` (local launcher) is gitignored; `PROMPT.md` is committed as the session brief.
- D-010 Local npm is configured with `omit=dev`; use `npm install --include=dev` in `web/`.

## Open issues
- Untagged major roads: 83 % of secondary, 73 % of primary, 65 % of trunk km lack `lanes`; most
  untagged roads default to 1-2 lanes at 100 km/h. Largest realism gap; M2 type overlay planned.
- Traffic-light coverage far below reality (72 programs; 2,264 major 3+-approach junctions without
  a signal). Not verified against any official inventory.
- City baseline teleports 50.5 % of vehicles at 10 % (TA-011): network capacity (untagged lanes,
  junction clusters, ramps), not demand, is the binding issue. Lane audit blocked on accuracy.
- Assignment of an uncached 10 % baseline takes about 2 h (8 routing threads, not repeatable;
  1 thread is repeatable but slower: TA-013/TA-015). Routes are cached by key.
- Viewer compare is limited to runs on the same network hash, so Loop (and any network-variant)
  runs show no baseline comparison in the viewer (I-010); the films compare by edge id.
- Disk: 80 GB free at the end of integration (was at 99 % mid-day); 10 % city runs are 0.3-0.6 GB
  each with gzip, the bins cache about 0.2 GB per 24 h run.

## Handoffs

## M0 Skeleton — 2026-10-15
Built: git repo on `main`; section 8 layout (packages with `__init__.py`, placeholder READMEs for
population, daytypes, policies, vtypes, scenarios, events, strategist, api); `pyproject.toml` +
`uv.lock` (Python 3.12, eclipse-sumo 1.28.0, sumolib/traci, geo and API stack, ruff, pytest);
LICENSE (Apache-2.0), NOTICE (OSM ODbL, SUMO EPL-2.0, GASTAT); `.gitignore`; docker-compose (api
stub with `/health` + Vite web); GitHub Actions CI (ruff check/format, pytest, web typecheck);
docs/STATUS.md, docs/assumptions.md, docs/data-sources.md; demo window in `data/demo/`
(Tahlia / Al Andalus, 3.3 km2, 1,800 random trips) plus its raw OSM for the builder test.
Measured: 26 tests pass in 8.6 s; demo 939 edges / 401 junctions / 1 TLS / 114.36 lane-km; Tier B
demo smoke 0.76 s for 1 h, 0.056 % teleports; determinism confirmed by the verifier.
Decisions: D-001 to D-012 above (SUMO from the wheel, Python 3.12, GCC extract, polygon, demo bbox,
windows cut from the city net).
Could not verify: that the Docker images build and that the eclipse-sumo wheel's shared libraries
load inside python:3.12-slim (not built in this session); CI not yet run on GitHub (no remote).
Next: M1 Jeddah network — city build, fix list with a real fix, window cutter, meso smoke run.

## M1 Jeddah network — 2026-10-15
Built: `sim.network.build_city` (Geofabrik GCC extract -> osmium clip to `data/osm/jeddah.poly` ->
gzip OSM XML -> netconvert with `sim/network/config/city.yaml` + Tier A type overlay -> fix list ->
districts, buildings and viewer GeoJSON + `jeddah.build.json` provenance); `sim.network.fixes`
(pydantic-validated YAML fix list: lanes, lanes_min, speed, oneway, remove; resolved via OSM
`origId`; strict mode fails on stale fixes) with three real fixes on King Abdulaziz Road;
`sim.network.build_window` (cuts windows from the city net so edge ids match Tier A; regenerated the
committed demo); `sim.network.netinfo` (streaming stats, SCC, edge GeoJSON); `sim.runner --smoke`
(random trips, meso Tier A / micro Tier B, run metadata, Tier A micro-only guard); Vite + MapLibre
viewer stub (`web/`, screenshot `docs/img/m1-viewer.png`); docs/network-qa.md, docs/data-sources.md.
Measured: city net 156,126 edges, 62,513 junctions, 72 traffic lights, 20,952.88 lane-km, build
56 s; main SCC 99.10 % of passenger edges; 112 districts, 27,783 buildings (9.7 MB). Tier A smoke
(seed 1, 1 h, 18,001 random trips): SUMO 24.1 s (real-time factor 149), demand generation 500 s,
26 teleports = 0.144 % (limit 0.5 %), peak memory about 2.9 GB (measured on the pre-extension network, same demand size). Tests: 27 pass in about 10 s.
Decisions: D-013 (lanes_min fixes), D-014 (polygon south to 21.26), D-015 (OSM-only signals),
D-016 (buildings stay gitignored), D-017 (SCC tool; windows not strongly connected), D-018.
Population sampling implications for M2 (18 GB RAM): a 1 h meso run of 18k vehicles (about 7k
simultaneously on the network) peaked at about 2.9 GB, and meso speed was about 150x real time. A
full-population weekday is 4.5-5.5 M vehicle trips (PROJECT.md section 2), so peak simultaneous
vehicles will be in the hundreds of thousands at the 07:00 peak. Meso memory grows roughly with
loaded routes plus running vehicles, so measure before choosing: plan a 10 % sample first, then 25 %,
and only then 100 %. Load routes incrementally (sorted route files, `--route-steps`), keep FCD off,
and stream edgeData. The binding cost is routing, not simulation: random-trip routing took 500 s
for 18k trips, so 5 M trips with several duaIterate iterations is hours to days. M2 should therefore
(1) route a 25 % sample with `--scale 4`-style capacity scaling as the default, (2) cache routes by
(network hash, population hash, day type, seed), (3) use duarouter routing threads and fewer
iterations on Tier A, and (4) snap zones to edges in the main SCC only.
Could not verify: real Jeddah lane counts on untagged roads (no imagery check) and the real signal
count; official district boundaries or district-level population (none found); the northern
enclave's exit restriction; Docker image builds; CI on GitHub (no remote configured).
Next: M2 Population and baseline. First three tasks:
1. Zones: districts as TAZs snapped to main-SCC edges, with census control total 3,712,917 (place
   Jiddah, GASTAT 2022) spread by residential building footprint area; registered as assumptions.
2. Untagged-road overlay: argued lanes/speeds per road class (A-network-003) and the next fixes
   (Al Harameen Road way 346621217), then re-run the smoke to confirm teleports stay < 0.5 %.
3. Synthetic population + weekday activity chains for a 10 % sample, routed with duaIterate, with
   runtime and memory measured at 10 % and 25 % to make the sampling decision.

## Track handoffs (merged from docs/status/track*.md; full logs stay there)

### M2 (Track A)
### M2 handoff (2026-10-16 08:30)
ruff clean; pytest 45 passed (demo window); verifier PASS after one fix round (assignment
determinism, sanity table, status corrections). Carried forward: re-run the 10 % baseline with 1
routing thread when ~15 GB are free (closes TA-013 for the reported run); 25 % run and the 10 % vs
25 % capacity-scaling check (A-sim-101); network capacity (TA-011) is the top issue for the
lane-audit/network work; README M2 command at integration (`uv run python -m sim.runner --baseline
--daytype weekday --sample 0.10 --seed 1`).
M2: done

### M4 (Track A)
### M4 handoff (2026-10-16 13:45)
Built: policy models in `sim/schemas.py` + `python -m sim.validate`; `sim/policies/`: transforms
(remote_work with per-sector shares, staggered_hours, daytype, pt_line via ptlines2flows.py,
road_pricing with elasticity and edge-weight penalty, network_change via netconvert patch,
ridehail_share), incremental re-routing runner with matched controls, policy report (KPIs, peak
spreading, district winners/losers, top-10 relieved/worsened corridors, assumption ids, label),
parallel sweep (CSV + PNG), results summary, baseline launcher; `sim.runner --policy` (additive);
`sim/metrics.py` reads gzipped outputs. 9 demo policies incl. the composed Ramadan + 30 % remote.
Measured (10 % sample, seed 1, all "synthetic demand, uncalibrated"; table in docs/policies.md):
- New city baselines: Ramadan weekday 451,313 vehicle trips (4.51 M city-equivalent), mean delay
  1,805 s, 0.48 teleports/vehicle; Friday 385,392 (3.85 M), mean delay 1,596 s, peak hour 11:00,
  0.60 teleports/vehicle; Friday assignment 71 min (8 threads), final runs 10 min (Friday) and 20 min (Ramadan).
- Policies vs matching baseline (mean delay / AM-peak delay / VKT / CO2): remote_work_30 -9.3 /
  -9.4 / -1.6 / -6.9 %; staggered_schools_60 (vs control) -1.1 / -9.1 / +0.2 / -0.6 %, top-hour
  share -19 %; friday -14.9 / -98.0 / -3.3 / -13.0 %; ramadan_weekday -3.8 / -33.1 / +13.8 /
  +12.4 %; bus_line_tahlia +2.5 / +0.7 / -0.2 / +1.7 %; cordon_center (vs control) +20.1 / +8.6 /
  -0.4 / +10.4 %; close_corniche_road (vs control) +1.1 / +0.7 / -0.1 / +0.6 %; ramadan_remote_30
  (vs Ramadan) -9.8 / -13.9 / -1.2 / -7.2 %; ridehail_plus_10 +1.5 / -0.5 / +2.7 / +4.7 %.
- Noise replicate (sim seed 2): mean delay +1.8 %, VHT +1.3 % (one replicate). Placebo (8 %
  re-routed, no trip changed): mean delay -20.1 %, VHT -13.3 % (TA-018).
- Sweep remote_work share 0.1-0.5: 5 points, 2 processes, 33 min wall; linear, mean delay -3.1 %
  to -15.4 %, AM-peak -3.5 % to -15.6 %: no tested share halves the morning peak. The 0.3 point
  reproduces remote_work_30 bit for bit (tripinfo hash 81cd70d69a1a0790).
- Run cost: 14-17 min per incremental policy run, 17-24 min with its matched control.
- Tests: ruff clean; pytest 72 passed (demo window, ~1.5 min).
Commands (README at integration): `uv run python -m sim.runner --policy remote_work_30 --daytype
weekday --sample 0.10 --seed 1`; `uv run python -m sim.policies.sweep --policy remote_work --param
share=0.1:0.5:0.1 --sample 0.10`; `uv run python -m sim.validate sim/policies/*.yaml`.
Could not verify: real-world magnitudes (no counts; uncalibrated); whether the bus-line effect
exceeds noise (one replicate only); a deterministic 1-thread assignment of any city baseline (all
three use 8 threads and are reproducible from the route cache only).
Integration notes: `sim/schemas.py` also changed two existing lines (docstring, typing import);
`sim/validate.py` and `docs/img/m4-remote-work-sweep.png` are new; fold the `--gzip` option of
`sim/policies/baseline_launch.py` into baseline.py; the network variant
`data/jeddah/jeddah.m2.close_corniche_road-8376e92d.net.xml.gz` lives in the shared data dir; run
provenance stores absolute network paths (runs/ is untracked; make relative before publishing).
Next: more assignment steps and replicates to shrink the routing-gain and noise bands; README
commands at integration; network capacity (TA-011) remains the top issue.

Verifier: PASS on all 11 criteria after two fix rounds (per-sector share test, status accuracy).
M4: done


### M8 (Track A)
See docs/status/trackA.md (M8 block) and docs/calibration.md.
M8: done

### M3 (Track C)
Built: `api/` (FastAPI, file-backed: runs, metrics, bins, edges, district effects, trajectories,
reports, recommendations + decision POST with SHA-256 chain, jobs with SSE progress, ingest,
examples), `tests/test_api.py` (15 tests, about 8 s, tmp run dirs), `web/` (React 19 + TS strict +
Vite 7 + deck.gl 9.4 + MapLibre 5: run picker, Tier A binary PathLayer by 5-minute bin, metrics
speed_rel/speed/delay/density/flow, baseline-vs-scenario and difference mode, district choropleth,
extruded buildings, Tier B TripsLayer by speed or vType, event and closure overlays, 0-24 h slider
with play/pause/speed, strategist panel with approve/reject and decision log, policy/scenario tables,
start-run form with SSE, fps/heap HUD, deep-link URL params), `web/scripts/screenshot.mjs` +
`perf.mjs`, `docs/viewer.md`, six screenshots `docs/img/m3-*.png`.

Measured: ingest of all runs 12.5 s, peak 469 MB; city edgedata (116 MB XML, 324,033 rows) to
Parquet 2.9 s at 231 MB peak (242 MB at 3x the input, so memory is flat); city edge index from the
353 MB net 3.7 s, 156,126 edges, 434,982 points, edges.bin 4.10 MB (2.07 MB gzip). One city bin
624,504 B (38-44 KB gzip at smoke demand) = 7.5 MB raw per simulated hour per metric. Tier B
trajectories 1 h, 1,800 vehicles: 9.5 MB (2.3 MB gzip). Viewer, headless Chrome with the Metal GPU
(ANGLE Metal Renderer: Apple M3 Pro): full city at 300x 59.9 fps median (vsync cap), p5 59.5-59.9,
uncapped 172 fps median with an orbiting camera; Tier B 59.9 fps; JS heap 131-154 MB; Chrome RSS
0.86-1.39 GB across two measurement sessions; recolour of 156k edges per bin 2.2-2.9 ms. Gates:
ruff clean, pytest 63 passed / 2 skipped (Pillow, lane audit), `npm run typecheck` and `build` pass.
Verifier (two passes): all engineering criteria PASS; `docker compose up` UNVERIFIED; its fixes (this
status block, the memory range, Tier A never reports FCD) were applied in 6dab21c. The verifier's view:
the track work passes; M3 as a project milestone also needs the root README update and one successful
`docker compose up --build` at integration. `docs/img/m3-events.png` still shows the old doubled
"(fictional) (fictional)" scenario title (examples regenerated after the screenshot).

Could not verify: `docker compose up`. The API image builds (`logs/m3-docker-build.log`), but
Docker Desktop hung on the first bind mount from `~/Documents` (looks like a macOS privacy prompt
nobody could answer), then its daemon stopped responding; it needs someone at the Mac. The
compose file, Dockerfile and vite proxy were reviewed statically by the verifier. The Docker
credential helper (`credsStore: desktop`) also blocked image pulls in this non-interactive session; a
clean DOCKER_CONFIG worked. Approve and start-run were exercised by the tests and curl, not clicked in
the browser. Real policy/scenario/strategist reports do not exist yet (the views use fictional
examples). Only one vType exists in the smoke runs, so "colour by type" shows one colour.

Integration notes: update the root README viewer section (lines 60-68 still say "M1 stub" / "API
stub") with `uv run uvicorn api.main:app --port 8000` + `cd web && npm install --include=dev && npm
run dev`, and drop the "stub" comments in docker-compose.yml and Dockerfile.api; run
`docker compose up --build` once Docker Desktop is healthy. Consider `VITE_API_TARGET=http://api:8000`
in compose and a `runs/`-based job log dir. Tracks A and B: write `edgedata.parquet` (or keep XML and
let ingest convert), `meta.baseline_run_id`, and the report files per the contract.

Next: once Tracks A/B produce a 24 h baseline and a policy run, replay them in the viewer and re-run
`npm run perf` on 288 bins; chunk Tier B trajectory loading for long windows.

Integration pending: root README demo commands, `docker compose up --build`.
M3: done

### Lane audit v2 (Track C)
Measured: calibration (50) single-read exact 66 % / 54 %, reads agree 76 %, agreed counts 26/38 =
68.4 % (motorway 19/23, trunk 7/15). No threshold reaches 80 % on >= 15 kept (0.8 -> 81.8 % on 11).
Holdout (30) single reads 80 % / 80 %, agree 93 %, agreed 23/28 = 82.1 % (motorway 12/15, trunk
11/13); 80.0-90.9 % at every cut keeping >= 10. Prince Majid Road (tag 3): 6 of the 12 agreed
calibration errors; both reads say 4 on five of its ways. Sensitivity (information only, not the
gate): without it, the calibration threshold is 0.45 (83.3 % on 18), effectively motorway-only (only
6 trunk ways remain, none agreed and correct), and the holdout at 0.45 is 87.0 % on 23 (85.0 % on
20 without its Prince Majid ways). Crops: 247 audit crops in 411 s (1,236 tiles). Ten analyst calls in parallel, about 100 s.
ruff clean, pytest 74 run (72 passed, 2 skipped).

Not done because of the block: the audit reads, `imagery-lanes.yaml`, `jeddah.lanes.net.xml`, the
after-smoke. The before-smoke is unchanged (26 teleports = 0.144 %, 22.4 s). `jeddah.net.xml`
untouched.

Could not verify: Prince Majid Road's real lane count (tag 3, edited 2026-05-17, vs three blind
passes reading 4); the Esri capture dates.

Next: a person checks the six Prince Majid Road sections read as 4 or 6 (1432320656, 1432320655,
1024884983, 444383287, 646811886, 41519535). The other 7 calibration sections and 4 of the 5
holdout sections read 3, so the lane count may vary along the road. If only the five sections
read as 4 have 4, fix those tags and re-run `evaluate-two-reads`: the calibration reaches 31/38 =
81.6 %, and the rule picks 0.75 (exactly 80 % on 15, so only just). If the whole road has 4, the
calibration drops to 63.2 %. Then read the 247 audit crops (26 calls) and run `write-fixes`,
`rebuild` and the smoke. If they have 3, keep trunk out. A motorway-only pass would need its own
fresh motorway holdout, because this pass's motorway figures have been seen. Integration: add
`pillow` to pyproject.

LANE_AUDIT_V2: blocked - accuracy

### M5 (Track B)
### M5 summary — 2026-10-16
Built: four windows (tahlia, kaia_corridor, al_balad, kau_faisaliyah) with service roads grafted onto
the city cut (`sim/link.py window`); Tier A exit-time run and cutRoutes link with edge-map rewrite
and Webster-retimed window signals (`tier-a`, `cut`, `tls`); flow check (`check`); vType library and
mixes (`sim/vtypes/`); scenario schema, validator and assumption-register generator
(`sim/scenarios/`); TraCI events accident, rain, flood, motorcade, emergency_trip (`sim/events/`);
`python -m sim.runner --scenario <id> --window <w> --seed <n>` (additive) with baseline + scenario
in parallel, FCD/tripinfo/edgeData/timeseries to Parquet (FCD XML deleted), window KPIs (delay,
speed, VKT, VHT, queues, gridlock, emergency TT vs free flow and vs baseline, convoy) and
`runs/<id>/scenario_report.{json,md}`; `data/jeddah_flood_sites.yaml` (25 sourced sites);
`docs/events.md`; register `docs/assumptions-trackB.md` (114 rows).
Measured: flow check pass on all four windows (tahlia GEH<5 90.2 % of 420 edges, total ratio 0.910;
others 100 %, 0.99+). Tahlia window 10,074 edges / 3,888 junctions / 7 TLS, 4,597 cut vehicles;
baseline 3,652 inserted, mean delay 97.8 s, 13 teleports (0.34 % of 3,855 loaded). Scenario mean delay deltas:
accident +5.7 %, heavy rain +23.3 %, flood +123.8 %, motorcade -11.2 % (not interpretable),
emergency +4.8 % with the ambulance at 2.0x free flow. About 190-205 s wall per scenario (emergency 119 s)
(baseline and scenario in parallel). accident_tahlia run twice (lead and verifier): identical KPIs.
Tests: 79 pass (about 30-60 s on the shared machine); ruff clean.
Could not verify: rain-effect citations (Agarwal et al. 2005, Rakha et al. 2008, HCM 2010
Exhibit 10-15) and AASHTO wet deceleration, quoted from memory and marked unverified; flood-site
locations beyond OSM matching; gridlock detection on a real gridlocked run (unit-tested only).
Open: reviewed signal program for the Madinah Rd / Tahlia cluster (tahlia link margin is thin);
motorcade KPI for held traffic; link_assumptions.yaml is kept in step with link.yaml by hand;
Tier A exit run 1.12 % teleports over 4 h (hot spots for the network owner); an Al Faisaliyyah
window; fold the service-road graft into build_window at integration.
Next: M6 Emergency strategist — (1) save Tier B state at the emergency dispatch time and fork
what-ifs with loadState; (2) candidates: k-shortest time-dependent routes, signal preemption along
each, rescue-lane enforcement; (3) rank against the no-strategy baseline from `emergency_tahlia`.
M5: done


### M6 (Track B)
### M6 summary — 2026-10-16
Built: `strategist/` (snapshot, fork, graph/Yen, candidates, controllers for preemption, rescue lane
and holds, parallel evaluate, rank, classify, explain, decision log, register); CLIs
`python -m strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1`,
`python -m strategist.approve <recommendation_id> [--option n] [--actor a] [--reject]`,
`python -m strategist.log verify|show`; `docs/strategist.md`; 25 strategist tests.
Measured (tahlia, seed 1, M3 Pro, load average 50-60 from other tracks): cold 29.9 s (warm-up to
1800 s 13.3 s + save 2.5 s); from the saved state 10.1-13.5 s total, evaluation of 9 what-ifs
6.6-9.1 s; within the 60 s budget. No strategy 173 s (free flow 47.4 s; 77 s of it on
`444771953#1`). Top 3: Route A + rescue lane 68 s (-105 s), Route B + preemption + rescue lane
89 s (-84 s), Route C only 95 s (-78 s); all auto_eligible; background delay changes <= 0.22 of
~27.7 veh-h (noise level). Best beats no strategy: yes. Determinism: three runs + verifier's two
runs identical (fingerprint c345c0094c51cc15); approve reproduced 68.0 s; log verify OK.
Tests: 104 pass (about 80 s under load); ruff clean. Verifier: 12/12 PASS (before the B-D-022
wording fix; full suite, CLI, approve and verify rerun after it).
Could not verify: preemption and rescue-lane parameters (no Jeddah specification found); bluelight
device behaviour without the sublane model (identical in every candidate).
Open: each what-if is one run from one state, so options close in time (ranks 2 and 3: Route C
passes the 77 s signal in 4 s on arrival timing alone) are not robustly ordered — add repeated
runs with varied RNG and report the spread; merge A-strat rows into the Track B register;
weather/motorcade re-application after load; snapshot rebuild race between concurrent runs; the
log cannot detect deletion of its newest records without an external head hash; the side-entry
hold had no measurable effect here.
Next: M7 Evacuation (zone evacuation, contraflow, phasing, clearance metrics, evacuation strategies).
M6: done


### M7 (Track B)
### M7 summary — 2026-10-16
Built: `sim/events/evacuation.py` (zone origins, auto exits, reverse free-flow trees, seeded
evacuee sampling, nearest / balanced assignment, simultaneous / near-first / far-first release,
contraflow corridor detection + netconvert edit + Webster retime, run-time contraflow and signal
plan, clearance T50/T90/T100, bottleneck edges, background delay; `run`, `validate`, `net`,
`register` CLIs); `strategist/evacuation.py` (screening candidates, parallel what-ifs + noise
replicate, score, classification, explanations, explicit recommendation, decision log, `approve`);
`sim/scenarios/evac_settings.yaml` (A-evac-001..038), `evac_demo.yaml`, `evac_corniche_hamra.yaml`,
`evac_flood_balad.yaml`; `docs/evacuation.md` (method, contraflow mechanics, results tables,
register block); 42 tests in `tests/test_evacuation.py` and `tests/test_evacuation_run.py`.
Commands:
`uv run python -m sim.events.evacuation run --scenario evac_obhur --seed 1` (was `evac_corniche_hamra`, withdrawn by Track I),
`uv run python -m sim.events.evacuation run --scenario evac_flood_balad --seed 1`,
`uv run python -m strategist.evacuation run --scenario <id> --seed 1`,
`uv run python -m strategist.evacuation approve <recommendation_id> --option 1`.
Measured (seed 1, SUMO 1.28.0, load average 30-50 from other tracks):
- Al Hamra (tahlia window; 2,000 vehicles, zone 2.06 km2, 6 exits, 3 corridors 7.3 lane-km):
  as written T50 1,264 s, T90 2,399 s, T100 3,004 s, 2,000/2,000 out, 214 teleports (125
  evacuees), background +90.1 veh-h versus the reference (537.4); bottleneck Hail Street
  (`-1486721509#7.s5`, 16.2 halted veh-h). Demo command 292-308 s wall. Strategist: 11 what-ifs (incl.
  no strategy) + replicate in 540-631 s; noise band T90 +/-3 s, T100 +/-19 s, delay +/-8.1 veh-h; recommendation
  **no strategy** (no option beats it on score); fastest = contraflow cf1+cf2 (T90 -90 s, T100
  -258 s, +25.3 veh-h, 5.3 lane-km, score 2,857 vs 2,702). Three strategist runs: same fingerprint
  cac0abd33e53160d (log records 12, 14, 17; final rec-20261016T053046Z-750c78f4).
- Al Balad flood day (al_balad window; storm + FS-002 closed; 2,000 vehicles, 0.92 km2, 6 exits,
  3 corridors 10.6 lane-km): as written only 1,755/2,000 out by the run end, T50 2,768 s, T90 not
  reached, 602 teleports (503 evacuees); background +291.8 veh-h. Demo command 197-221 s wall.
  Strategist: 11 what-ifs + replicate in 310-353 s; noise band T90/T100 n/a (neither run reaches
  them), delay
  +/-13.3 veh-h; recommendation **balanced exit guidance + evacuation signal plan** (auto_eligible):
  T90 4,493 s, T100 5,212 s, 2,000/2,000 out, score 4,860 vs 8,550. Approved in the log
  (final: dec-20261016T054527Z-939a23de on rec-20261016T053643Z-624adbd0); `strategist.log verify`
  OK, 19 records. Three strategist runs: same fingerprint ff134cd308b9f3e9 (records 13, 15, 18).
- Demo window (`evac_demo`, 150 vehicles): T50 383 s, T90 642 s, T100 733 s (verifier, twice, and
  the strategist's no-strategy run); 5-15 s per command.
- The demo command and the strategist's no-strategy what-if gave identical clearance on all three
  windows; light and FCD run paths identical on the demo window (test).
- Contraflow net edit: netconvert + retime 6-37 s per scenario (cached by hash).
Could not verify: every evacuation parameter (no Jeddah evacuation, event-parking or contraflow
data; HCM saturation flow quoted from memory, A-evac-011); the inbound-carriageway match is
geometric (checked by name in the corridor tables, not against imagery); why contraflow moves the
Al Balad bottleneck to Dhahab Street; clearance is flattered by jam teleports (125-503 evacuee
teleports in the as-written runs).
Open: one noise replicate is a crude band (more replicates would firm up close rankings); the
reversed lanes have no crossover geometry and copy the corridor speed; evacuation is not wired into
`sim.runner --scenario` (registry and schema are M5 files: B-D-026); the A-evac rows live in
docs/evacuation.md until integration adds evac_settings.yaml to the register SOURCES (B-D-031);
README commands to copy at integration (B-D-033); superseded recommendation records from the
earlier Al Hamra runs (before B-D-032/034/035/036) remain in the append-only log as records 8-11
(rec-20261016T034544Z-092be3ed, ...T040041Z-b087e28c, ...T041245Z-aa5f90d0, ...T042644Z-cbb10229);
records 12-15 are the final simulation code before reporting-only changes and match the final
records 17 (Al Hamra, rec-20261016T053046Z-750c78f4) and 18 (Al Balad, rec-20261016T053643Z-624adbd0);
record 16 approves record 15, record 19 approves record 18.
Next: M8 Calibration (Track A) — Track B's next work is integration: registry/runner wiring for
evacuation, register merge, README commands.
Disk: the shared volume was at 99 % (about 1-6 GB free) during M7 and the verifier's first test
run failed on a full disk; M7 outputs under runs/ are about 0.7 GB (superseded strategist run dirs
are kept because decision-log records point at them). Long city runs by any track can hit this.
Tests: 146 pass (full suite, about 1.5 min under load); 42 of them M7; ruff clean.
Verifier: first pass FAIL on documentation accuracy (stale status numbers), an unregistered
threshold and a missing assumption id in outputs; all fixed (B-D-038), city demos and strategists
rerun with unchanged fingerprints; second pass PASS on all items except one stale register range
in this block, fixed in the same commit as this line.
M7: done

### MOVIES (Track E)
Summary (full log in docs/status/trackE.md, decisions E-D-001..015): a film pipeline over existing runs.
Python plans each frame (camera keyframes, NOAA sun, KPIs, fades, bundles in `runs/movies/<film>/bundle/`),
the deck.gl renderer at `?cinema=<film>` draws it, headless Chrome steps frames, chunked H.264 encode keeps
disk under 0.3 GB per film. 7 films at 1080p30 (30-40 s each, about 25 min in all), showreel 174.7 s,
GIF previews 6.00 s. Determinism: `tahlia-street` rendered three times with identical hashes; the smoke
test renders frames 100-110 twice. Display-only assumptions A-mov-001..008; no simulation result changes.
Not verified: bit-identical frames on another GPU or Chrome; the 4K and 60 fps flags.
MOVIES: done

### LOOP (Track D)
Summary (full log in docs/status/trackD.md, decisions TD-001..015): Boring-style Loop tunnels on the
Tier A model. Desire lines and time-loss corridors pick 8 candidate alignments (C1-C8); each is one
city run in shuttle mode plus a seed-2 replicate; greedy selection under 25 tunnel-km with a knapsack
correction picks C1 Al-Salamah - King Abdulaziz University (17.9 km, 8 stations, USD 268-714 M). The
sweep (mode, speed, toll, alpha, radius, capacity, time-competitive shift) recommends shuttle mode
capped by the measured capacity (alpha 0.3): relief 63,349 VHT/day two-seed mean (band 23,435 to
103,263), AM-peak road delay -2.85 %, 141.9 VHT/day per USD M at central capex. Private-EV at
SAR 10 overloads the tunnel at measured capacity. Noise is about +/- 34,000 VHT/day per comparison.
Assumptions A-loop-001..020 (merged); sources `docs/data-sources-trackD.md`.
LOOP: done

### RELEASE (Track G)
Summary (full log in docs/status/trackG.md, decisions G-D-001..005): CI with pinned actions,
demo-smoke and Pages workflows, project page `site/`, README for publication, NOTICE, CITATION,
community files, 13 good-first issues, `docs/release-audit.md` and `docs/release-checklist.md`.
Fixed pytest on a fresh clone (demo-window districts/buildings fixtures). Esri crops in history and
the commit e-mail are owner actions (checklist step 1). No new behavioural assumptions.
RELEASE: done

### MODECHOICE (Track H)
Summary (full log in docs/status/trackH.md, decisions TH-001..007): car-vs-Loop tour-level logit on
generalised time with pair and segment capacity caps and a deterministic queue (MSA), replacing the
fixed shift share alpha when a policy sets `mode_choice:`; the alpha path is unchanged (hash tested).
Central C1 19,530 / 31,450 riders/day (measured / vendor service) vs 28,820 at alpha 0.3; C1
measured is segment-capacity bound in the evening. Assumptions A-loop-021..030 (merged); sources
`docs/data-sources-trackH.md`; method `docs/loop-mode-choice.md`.
MODECHOICE: done

### OBHUR_BRIDGE (Track J)
Summary (full log in docs/status/trackJ.md, decisions J-D-001..014): Obhur Creek crossings B1 (mouth),
B2 (mid-creek), B3 (both), 2+2 and 3+3, as `network_change` policies with a netconvert patch builder
(SCC and through-route checks). Detour screen: 238,130 car trips/day cross the creek's desire line;
B1 + B2 shorten 145,370 by 6.0 km (free flow). Tier B window (24.5 km2) with matched control: bridges
carry 536-645 (B1) / 297-427 (B2) veh/h in the AM peak, but the time-in-window change (-16 to +53 s)
is within noise (about +/- 20 s); the city run decides. Assumptions A-obh-001..041 (merged); sources
`docs/data-sources-trackJ.md`; write-up `docs/obhur-bridge.md`.
OBHUR_BRIDGE: done
