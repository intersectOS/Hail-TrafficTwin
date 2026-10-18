# MOVIES_V2 - narration, map legends and the Obhur evacuation (Track I, worktree
# .worktrees/trackI, branch trackI)

Branch `trackI` is cut from `main` (films pipeline in web/src/cinema, scripts/movies,
movies/specs, docs/movies.md). Status file: `docs/status/trackI.md`; finish with
`MOVIES_V2: done` (or `MOVIES_V2: blocked - reason`). Owner feedback on the films: "great, but
better with a voice-over and legends (street names, north arrow), and the evacuation should not be
Al Hamra (near a palace): use Obhur, north or south, near the planned Kingdom (Jeddah) Tower."

Compute rules: another agent owns SUMO CITY runs (Tier A); you may run window-scale (Tier B)
simulations and renders, one at a time; render at 1080p30; delete frames after encoding; keep the
browser under 2 GB and never run two renders at once. If `df -h /System/Volumes/Data` shows under
5 GB free, stop and write the status.

## 1. Obhur evacuation (replace Al Hamra everywhere public)
- New focus window `sim/network/windows/obhur.yaml` around Obhur Creek / the Jeddah Tower site
  (north Obhur and the creek mouth; roughly 21.70-21.76 N, 39.08-39.14 E; pick the polygon from the
  network so the window includes the creek bridges, King Abdulaziz Road / the Obhur corniche roads
  and the main exits east to Madinah Road / Al Haramain Road). Build it with the existing window
  tooling and the Tier A route set (cutRoutes), like the other windows.
- New scenario `sim/scenarios/evac_obhur.yaml` with fictional, clearly-labelled demo parameters
  (zone polygon on the creek-side residential/resort area, exits, phasing, contraflow candidates),
  run through the existing evacuation module and strategist; produce the same KPIs and report as
  the Hamra one (clearance 50/90/100 %, bottlenecks, top strategies). Register assumptions.
- Remove `evac_corniche_hamra` from the public demo set: film spec, showreel, README, docs/
  evacuation.md examples and screenshots switch to Obhur. Keep the Hamra YAML only if a test
  depends on it; otherwise delete it and note the decision (TI-nnn). The project's publication
  policy (PROJECT.md section 11) stays: demo parameters are fictional and say so on the HUD.

## 2. Legends and map annotations (all films)
- Street-name labels from the network's OSM names (`name:en` preferred, Arabic as a second line
  when available; no letter-spacing anywhere): a TextLayer with road-class priority and collision
  avoidance so only the arterials label at city zoom and local streets appear when the camera is
  low; labels follow the road direction where deck.gl allows, otherwise horizontal with a halo.
- District labels at city zoom; landmark labels where relevant (KAIA, KAU, Al Balad, Obhur
  Creek, Jeddah Tower site, Corniche) from a small reviewed `movies/landmarks.yaml`.
- A HUD compass (north arrow that rotates with the camera bearing), a scale bar that updates
  with zoom, a legend for the colour ramp (speed / delay / difference), the simulated clock, and
  the "synthetic demand, uncalibrated, fictional demo parameters" footer. Keep it minimal and
  consistent with the existing HUD style.
- Event callouts: a short leader-line label at the accident / flood / motorcade location and at
  evacuation exits and contraflow links.

## 3. Voice-over (English, natural, open model, fully offline)
- Use an open TTS that sounds human on Apple Silicon: first choice Kokoro-82M (Apache-2.0;
  `pip install kokoro` + `soundfile`, or `mlx-audio` for the MLX port) with a clear, calm
  documentary voice (e.g. af_heart or am_michael; pick one and keep it for every film); fallback
  Piper if Kokoro cannot be installed offline. Record the model, version, voice and licence in
  NOTICE and docs/movies.md. No cloud TTS.
- Write a narration script per film in `movies/specs/<film>.narration.yaml`: 4-8 lines, each
  tied to a camera keyframe or sim-time window, plain English, states what the viewer is seeing
  and the measured number (only numbers that exist in the docs: docs/policies.md, docs/loop.md,
  docs/evacuation.md, docs/strategist.md; never invent), and ends with the caveat line. Keep
  the showreel narration to the headline of each film.
- Pipeline: `scripts/movies/narrate.py` renders each line to WAV, measures durations, and the
  spec gets per-line start times (shots stretch to fit speech, never the reverse); ffmpeg muxes
  the voice track (-c:a aac 160k, loudness normalised to -16 LUFS) and burns optional subtitles
  from the same script (also written as `.srt` next to the MP4). `make movies` includes narration;
  `--no-voice` flag for silent renders. Determinism: same script + model ⇒ same audio hash.
- Re-render all nine films and the showreel with legends + narration. Ship updated GIF previews
  and stills. Verifier subagent: one film rendered from scratch, MP4 has an audio stream of the
  expected length, subtitles present, labels visible in a mid-film frame, Obhur replaces Hamra
  in every public artefact, tests green. Then the status line.
