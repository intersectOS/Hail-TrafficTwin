# Track I status: MOVIES_V2 (narration, legends, Obhur evacuation)

Branch `trackI`, worktree `.worktrees/trackI`. Owner feedback: voice-over, legends (street names,
north arrow), and the evacuation moved from Al Hamra to Obhur near the Jeddah Tower site.
Everything stays **synthetic demand, uncalibrated**; the evacuation is fictional.

## Decisions

- **TI-001 Nine films.** There are eight films plus the showreel; "all nine" is read as the eight
  films and the showreel, all re-rendered with labels and narration.
- **TI-002 Al Hamra withdrawn.** `sim/scenarios/evac_corniche_hamra.yaml` and
  `movies/specs/scenarios/evac_corniche_hamra_film.yaml` are deleted: the only tests that used the
  Hamra YAML (`tests/test_evacuation.py`: shipped-scenario validation and corridors-avoid-zone)
  now use `evac_obhur`, so no test depends on Hamra. Its results section in docs/evacuation.md is
  replaced by Obhur; historical status logs (docs/status/trackB.md, trackE.md, integration.md) are
  left as written. Al Hamra still appears as a district name (windows, Loop corridors, cordon,
  flood sites), which is not the evacuation demo.
- **TI-003 Tier A exit run re-made.** The windows were cut from `runs/tierA-exit-2f1822b7-cc34910d`,
  which no longer exists on disk. It was re-run once in this worktree with the documented command
  (`sim.link tier-a --routes runs/source-smoke-A/routes.rou.xml --seed 1`; Track B's M1 smoke route
  set, 18,001 vehicles, 1 h, meso, 110 s wall): the same config hash `cc34910d`, so the same run id.
  This is a small meso re-run of the link input, not a city baseline (the compute rule's city runs).
- **TI-004 Obhur window.** Polygon over the creek mouth (24.8 km2 with about 4 km2 of water), built
  with `sim.link window` + `cut` + `check` like the other windows; it sits in the shared
  `data/windows/obhur/` (new name, nothing overwritten). 2,339 edges, 1,014 junctions, no signals;
  2,757 cut vehicles; flow check PASS (GEH < 5 on 100 % of 91 edges, total ratio 1.000).
- **TI-005 Zone and crowd.** South bank of the creek mouth west of King Abdulaziz Road (generic
  polygon, 285 origin edges, 1.42 km2), 1,500 cars: the north bank at the Tower site is mostly a
  construction site with few streets, so the crowd sits across the water from it. Fictional
  (A-evac-039).
- **TI-006 Film option.** The strategist recommends balanced exit guidance (T90 1,402 s, no
  approval). The film shows the fastest-clearance option `far_first_full` (far-first phased release
  + balanced exits + contraflow, T90 1,349 s) because phasing and contraflow are what the film can
  show, and says on screen and in the voice-over that the recommendation is balanced guidance alone.
- **TI-007 Labels as HTML.** deck.gl's TextLayer does not shape Arabic (letters come out isolated
  and left-to-right), so street, district and landmark labels, the compass, scale bar, callouts and
  subtitles are HTML in the HUD, positioned per frame with deck's WebMercatorViewport; the browser
  shapes Arabic. Placement is greedy by priority with collision boxes; opacity is the share of the
  last 8 frames in which a label fits, so labels fade instead of popping and frames stay a pure
  function of the frame index.
- **TI-008 TTS venv.** Kokoro needs torch (large); it lives in `.venv-tts` (pinned
  `scripts/movies/tts-requirements.txt`, `make voice-setup`) and is called as a subprocess, so the
  project lock and CI stay unchanged. The CI smoke render is silent (`voice=False`); narration has
  its own tests and the TTS determinism test skips without the venv.
- **TI-009 TTS determinism.** Three sources of run-to-run differences, all fixed in the worker:
  (1) Kokoro's vocoder draws noise: torch is seeded before every line; (2) its G2P iterates over
  Python sets: the worker re-executes itself with PYTHONHASHSEED=0; (3) on the M3 the float32 CPU
  kernel of the 1x1 Conv1d `predictor.F0_proj` returned different sums for identical inputs in
  different processes (found by hashing every module's output over 6 processes: the first
  divergence was that layer), which the vocoder's sine phase turns into audible differences (up to
  368 LSB): Conv1d, ConvTranspose1d and Linear now run in float64 and cast back
  (`deterministic_cpu`). Result: 10 of 10 processes gave the same WAV for two test lines (before:
  2-3 variants in 6-10 processes). The first full render was stopped and restarted with this worker.
- **TI-011 Window cap.** The first Obhur polygon was 25.7 km2, over the 25 km2 cap that
  `tests/test_link.py` enforces. Its west and north-west vertices were pulled in over sea and the
  empty Tower site only, at least 398 m from any edge: 24.8 km2, and a rebuild into a temporary
  directory gave the byte-identical cut net (`f4fd448bd8799e25`), window net (`41f3b38254f9fbec`)
  and edge map, so every Obhur run stays valid. `obhur.window.json` records the new polygon; the
  window's `obhur.osm.gz` service-road extract is still the one cut with the first polygon (the
  graft result is identical).
- **TI-010 Subtitles.** Homebrew's ffmpeg has neither libass (`subtitles` filter) nor `drawtext`,
  so the burnt-in subtitles are drawn by the HUD from the same lines; the MP4 also carries a soft
  mov_text track and `movies/<film>.srt` sits next to it. `--no-subtitles` / `--no-voice` exist.
- **TI-012 Run ids after the register edit.** The evacuation run id hashes the settings file,
  including the assumption texts; A-evac-035's text was updated (Obhur noise band) after the first
  Obhur runs. Both runs were repeated with the committed settings: identical clearance, background
  delay and teleports, new ids `evac_obhur-obhur-s1-ecff823b` and
  `evac_obhur_film-obhur-s1-83e89905` (the old `d462eb71` / `1572ddb3` are superseded).

## MOVIES_V2 — 2026-10-17

Built:
- **Obhur evacuation.** Window `obhur` (`sim/network/windows/obhur.yaml`, 24.8 km2, 2,339 edges,
  1,014 junctions, no signals; 2,757 cut Tier A vehicles; flow check PASS, GEH < 5 on 100 % of 91
  edges, ratio 1.000). Fictional `sim/scenarios/evac_obhur.yaml` (1,500 cars, south bank of the
  creek mouth): as written T50/T90/T100 933 / 1,702 / 2,115 s (`evac_obhur-obhur-s1-ecff823b`,
  118 s wall). Strategist (`rec-20261017T000240Z-9a7e8298`, fingerprint `353c178d00b0ed14`, the
  same on a second run): recommended balanced exit guidance, T90 1,402 s (auto-eligible); fastest
  `far_first_full`, T90 1,349 s (approval). Film run `evac_obhur_film-obhur-s1-83e89905` = the
  far_first_full what-if exactly. Hamra scenario and film scenario deleted; README, docs/evacuation.md,
  docs/movies.md, docs/STATUS.md, the evacuation screenshot and the film switched to Obhur.
- **Labels and HUD** (`scripts/movies/labels.py`, `movies/landmarks.yaml`, `web/src/cinema/annotate.ts`,
  `hud.ts`): OSM street names (English, Arabic second line, one English name per Arabic name),
  road-class priority and zoom gating, greedy collision placement that also avoids the HUD,
  temporally smoothed opacity (pure function of the frame), labels rotated along the road; district
  labels at city zoom; landmarks (KAIA, KAU, Al Balad, Obhur Creek and Ras Obhur, Jeddah Tower
  site, Corniche); compass; scale bar; legend keys for zone, exits, contraflow and release bands;
  callouts at crashes, floods, motorcades, exits and contraflow; footer "fictional demo
  parameters" on the four scenario films. About 1 ms per frame.
- **Voice-over** (`scripts/movies/narrate.py`, `tts_kokoro.py`, 8 film scripts + the showreel
  script): Kokoro-82M 0.9.4 (Apache-2.0, revision f3ff3571), voice af_heart, speed 0.95, offline
  in `.venv-tts` (`make voice-setup`, pinned requirements). Shots stretch to fit speech to whole
  frames; voice track mixed, EBU R128 to -16 LUFS (measured -16.1 to -16.9 LUFS, true peak about
  -1.5 dBTP), AAC 160 kbit/s, trimmed to the film's length; soft mov_text subtitles + `.srt`;
  HUD subtitles; `--no-voice`, `--no-subtitles`; `narrate validate` rejects numbers not in the docs.
  Audio is deterministic across processes (TI-009).

Measured (final `make movies`, M3 Pro, ANGLE Metal, other agents simulating): 8 films at
1920x1080 30 fps, 30.00-52.37 s after the narration stretch (city-24h, tahlia-street and policy-lab
unstretched), 0.12-0.25 s per frame, 176-439 s per film, about 39 min in all; browser RSS max
1.07-1.50 GB (budget 2 GB); disk max 119-360 MB (budget 1 GB); no frames left; audio stream
duration = video duration on all 9 MP4s (0.000 s difference); showreel 171.0 s with one spoken
headline per film. Free disk stayed above 44 GB.

Tests: 328 passed, 1 skipped (full suite incl. the render smoke test and the TTS determinism
test, 4 min 50 s); ruff check, ruff format --check, tsc clean. New: tests/test_narration.py (12
tests: narration rules and number check, timing and stretch, voice track + SRT, mux length, labels
naming and anchors, landmarks, callout names, Hamra removal, cross-process TTS determinism).

Verifier: first pass 7/8 PASS, FAIL on audio 0.067 s longer than video on three films (loudnorm's
100 ms block padding) and the docs copying those lengths; notes on docs/STATUS.md Hamra commands,
uncited assumption ids, 8 px Arabic labels. All fixed (TI-009..012, atrim, whole-frame stretch,
larger labels), all films re-rendered. Second pass: every check PASS, including a from-scratch
`tahlia-street` render with voice whose voice hash (`d6159532e3419a82`) and frame hashes equal
the shipped ones. Its remaining note (the Obhur Creek label off-camera in the evacuation film) was
fixed with the Ras Obhur landmark; `evacuation` and the showreel were re-rendered and checked
(audio = video, landmark visible at 9 s).

Could not verify: listening quality (no audio playback here; Kokoro af_heart is the model's
highest-graded voice, pronunciation of Arabic place names is the model's own); frames or audio on
another GPU, CPU or Chrome version.
Open: the strategist film still quotes raw edge ids in its reason line (Track E open item); the
motorcade callout uses the OSM name "Prince Mohammed bin Abdulaziz Street" for Tahlia Street while
caption and voice say Tahlia Street (both names are correct); `obhur.osm.gz` in the shared window
directory was cut with the first polygon (graft result identical, TI-011).
Next: integration merges trackI (scripts/movies, web/src/cinema, movies/specs, movies/landmarks.yaml,
sim/network/windows/obhur.yaml, sim/scenarios/evac_obhur.yaml, docs) and copies the worktree runs
`evac_obhur-obhur-s1-ecff823b`, `evac_obhur_film-obhur-s1-83e89905`, `link-obhur`,
`tierA-exit-2f1822b7-cc34910d` and runs/strategist rec-20261017T000240Z-9a7e8298 to main's runs/;
`data/windows/obhur/` is already in the shared data directory.

MOVIES_V2: done
