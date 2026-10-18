# Integration status

## INTEGRATE — 2026-10-16
Merged into `main`: trackC (M3 viewer/API; lane audit blocked), trackB (M5, M6, M7), trackA (M2, M4,
M8), in that order; only `sim/runner.py` conflicted (kept both sides). trackD (Loop tunnels) **skipped**:
its status reads `LOOP — in progress` (no `LOOP: done`), so a second integration pass is needed.
Lane audit blocked on accuracy: `jeddah.lanes.net.xml` does not exist; default network unchanged.

Gates on merged main: ruff clean; pytest 267 passed, 1 skipped (~3 min); web typecheck + build pass.
End to end (10 % sample, seed 1, synthetic demand, uncalibrated): weekday baseline (identical to
Track A's, 680 s from the route cache), remote_work_30 (mean delay -9.3 %), accident on Tahlia
(+5.7 % delay, 130 s), emergency strategist (top 3 in 11.6 s, best 68 s vs 173 s), evacuation via
`sim.runner --scenario evac_corniche_hamra` (T90 2,399 s). All five visible in the viewer through the
API (contract v1.1); screenshots `docs/img/integration-*.png`.
Verifier vs G1-G6: G1-G5 PASS; G6/hygiene/STATUS FAILs fixed (NOTICE, Esri crops untracked,
flood-site docs aligned, reproducible snapshot hash). Details and decisions I-001..I-005 in
docs/STATUS.md (Integration section).
Not verified: `docker compose up --build`.
Next: second pass to merge trackD once `LOOP: done`; re-link windows to the M2 baseline routes;
network capacity (TA-011, 50 % teleports); chunked Tier B trajectories; M9 docs and release.

INTEGRATE: done

## INTEGRATE pass 2 (Track E movies) — 2026-10-16
Merged `trackE` (MOVIES: done) into `main` with `--no-ff`. No conflicts: it was cut from main at cb98f6d.
Carried the specs, `scripts/movies/`, `web/src/cinema/`, tests, docs/movies.md, the README section and the
`docs/img/movies/` stills/GIFs. Nothing rendered under `movies/` went into git; only `movies/specs/` is tracked.
Track D was not merged or touched (still running).
Gates: ruff clean; pytest 292 passed, 1 skipped; tsc and vite build pass.
Film source runs: 11 runs that were reachable only through trackE's symlinks into the trackA, trackB and
trackE worktrees were copied into main's untracked `runs/` (I-006, about 1.1 GB). Main then rebuilt all
7 film bundles with hashes identical to Track E's; `tahlia-street` rendered in full on main (30.00 s,
155.9 s wall, same frame hashes).
Next: pass 3 for trackD once its status says `LOOP: done`, then render the `loop` film.

INTEGRATE: done

## INTEGRATE pass 3 (Track D Loop) — 2026-10-16
Merged `trackD` (`LOOP: done`) into `main` with `--no-ff` (b476837). No conflicts: purely additive plus
the one appended line in `sim/schemas.py`. Track E was not redone.
Fixes: the 21 A-loop rows merged into `docs/assumptions.md` (the register test failed after the merge);
`python -m sim.schemas` now validates `loop_*` policies; README "Loop tunnels" section.
Gates: ruff clean; pytest 316 passed, 1 skipped; tsc and vite build pass.
End to end (10 % sample, seed 1, synthetic demand, uncalibrated): `loop_demo --demo` 6.8 s, identical
to Track D's; `loop_recommended` on the city 504 s, reproduces `loop_opt_c1_a0p3` exactly (relief
57,671 VHT/day, 28,820 passengers/day). Both in the viewer via the API:
`docs/img/integration-loop{,-demo}.png`.
Loop film: real spec (C1 line and stations, morning-peak baseline, Loop-minus-baseline morning and
evening); `make movie FILM=loop` 34.00 s, 1020 frames, 246 s. Nothing copied from
`.worktrees/trackD/runs/`: its city runs had their edge Parquet pruned, so the film's run was produced
on main (I-007). Showreel: 8 films, 171.0 s (excerpts 20 s each, I-009). docs/movies.md and the README
preview updated. Verifier: 2 FAILs (bundle manifest keys, spec_sha note) fixed. Details in
docs/STATUS.md (Integration pass 3, I-007..I-010).
Open: viewer comparison across network variants (I-010).

INTEGRATE: done

## INTEGRATE pass 4 (Track G release, Track H mode choice) — 2026-10-17
Merged `trackG` (`RELEASE: done`) and `trackH` (`MODECHOICE: done`) into `main` with `--no-ff`
(de540db, b0cca5e); no conflicts. trackF, trackI, trackJ not merged or touched; nothing from
`movies/` in git; no push.
Fixes: A-loop-021..030 merged into `docs/assumptions.md` (register test green); README Loop section
gained the mode-choice command.
Gates: ruff clean; pytest 326 passed, 1 skipped; tsc passes. Demo window: mode choice 24 (measured) /
58 (vendor) riders/day, identical to Track H. No city run, no render, `make demo` not run (ports in
use by other agents). Details in docs/STATUS.md (Integration pass 4).
Owner action before any push: release checklist step 1 (Esri crops out of history).

INTEGRATE: done

## INTEGRATE pass 5 (Track J Obhur Creek bridges) — 2026-10-17
Merged `trackJ` (`OBHUR_BRIDGE: done`) into `main` with `--no-ff`; no conflicts (`docs/assumptions.md`
auto-merged, Loop and Obhur sections both kept). trackF and trackI not merged or touched; nothing from
`movies/` in git besides `movies/specs/obhur-bridge.yaml`; no push, no remote; no SUMO city run.
Gates: ruff clean; pytest 350 passed, 1 skipped; six bridge policies and all 9 film specs validate.
Film: window runs and `data/windows/obhur_creek/` copied (untracked) from the trackJ worktree; smoke
render of `obhur-bridge` on main 60/60 frames. Showreel unchanged (film not in order.yaml).
Deferred: Obhur bridge city runs on the v2 network (later pass; `docs/obhur-bridge.md` §5-6 pending).
Details in docs/STATUS.md (Integration pass 5).

INTEGRATE: done

## INTEGRATE pass 6 (Track I movies v2, Track F network v2, v2 re-evaluation) — 2026-10-17
Merged into `main` with `--no-ff`: `trackI` (`MOVIES_V2: done`; 02c353a), then `trackF`
(`NETWORK_V2: blocked` = teleport target < 10 % missed at 28.3 %, code complete; 725a8e5). Conflicts:
`.gitignore`, `NOTICE`, `CHANGELOG.md`, `docs/STATUS.md` (trackI) and `Makefile` `.PHONY` (trackF), all
resolved keeping both sides. Fixes in separate commits: README/site still showed the withdrawn Al Hamra
evacuation and old film lengths (now Obhur and the narrated renders); `obhur-bridge` narration +
showreel headline (trackI's test requires one per film); `narrate` checks `docs/obhur-bridge.md`;
`sim.bridge.run` district filter and markdown table (found in the first v2 run). The public evacuation
demo is Obhur; trackI deleted the Al Hamra scenario. No film re-rendered; nothing from `movies/`
renders in git; no push, no remote, no worktree removed.
Gates after each merge: ruff check + format clean; pytest 371 passed, 2 skipped; `npm run build` OK.
v2 on main: default network `data/jeddah/jeddah.v2.net.xml` (ae764558); v2 zones/population/route
cache copied into `data/population/` (m2 zones kept as `zones-m2/`); v2 baseline, smoke and probe runs
symlinked into `runs/` from `.worktrees/trackF/runs/`. v2 policy runs live in `runs/v2/`
(`scripts/pass6_v2.py`) so the v1 runs of the same name are not overwritten.

All runs: 10 % sample, seed 1, weekday, **synthetic demand, uncalibrated**; v2 control = baseline
`baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1` (teleports 28.3 %) or the policy's matched control.
Noise band: v1 ±34k VHT/day; v2 not measured (no second-seed v2 baseline; no city run spent on it).

| priority | run | status | v1 (m2) | v2 | teleports/veh v2 |
|---|---|---|---|---|---|
| 1 | Obhur bridge B3 (B1 + B2, 2+2) | done 07:12-07:40 | window only (no city run) | VHT -178,909 h/day (-9.2 %), AM-peak -20.9 % | 0.296 -> 0.305 |
| 2 | Staggered schools 60 | done 07:41-07:55 | AM-peak -9.1 %, VHT -19,342 h | AM-peak -1.8 %, VHT +23,033 h | 0.274 -> 0.275 |
| 3 | Loop C1, mode choice (measured) | done 07:55-08:01 | alpha 0.3: relief 57,671; logit offline 19,530 pax | relief 38,718 VHT/day, 14,630 pax | 0.283 -> 0.265 |
| 4 | Remote work 30 % | done 08:01-08:08 | VHT -210,563 h (-7.7 %) | VHT -167,819 h (-8.7 %) | 0.283 -> 0.244 |
| 5 | Central cordon | done 08:08-08:28 | VHT +309,345 h (+12.4 %) | VHT +341,271 h (+17.2 %) | 0.275 -> 0.454 |
| 6 | Obhur bridge B1 (mouth, 2+2) | done 08:28-08:57 | window only | VHT -170,801 h/day (-8.8 %) | 0.296 -> 0.303 |
| - | Loop C1 assumed share (alpha 0.3) on v2 | pending (needs its own city run) | 57,671 | - | - |
| - | Obhur bridge B2, B3 3+3 on v2 | pending | window only | - | - |
| - | Loop C1 vendor service, seed-2 replicates; C2/C4/C6 | pending | - | - | - |
| - | v2 second-seed noise band | pending | ±34k | - | - |

Commands for the pending ones (from the main checkout; each about 7-30 min on the 10 % sample):
```
uv run python -m scripts.pass6_v2 run loop_a0p3        # Loop C1 alpha 0.3 (loop_recommended)
uv run python -m scripts.pass6_v2 run bridge_b2
uv run python -m scripts.pass6_v2 run bridge_b3_3x3
uv run python -m scripts.pass6_v2 summary              # rows for docs/policies.md
# vendor service / seed 2 / other corridors: sim.loop.evaluate writes to runs/ (v1 runs there);
# follow scripts/pass6_v2.py (run_one with runs_dir=runs/v2) rather than calling it directly
```
Details: docs/STATUS.md (Integration pass 6).

INTEGRATE6: done

## RENDER_V2 pass 7 (films on network v2) — 2026-10-17
Re-rendered on main, one at a time (`make movie FILM=<name>`, Kokoro af_heart, -16 LUFS, subtitles;
`scripts.movies.spec validate` and `narrate validate` before each): `city-24h` 45.87 s (93.2 MB, GIF
2.59 MB, -16.4 LUFS), `policy-lab` 50.93 s (51.9 MB, GIF 1.78 MB, -16.4 LUFS), `obhur-bridge` 80.37 s
(35.9 MB, GIF 1.17 MB, -16.4 LUFS), then the showreel 186.3 s (9 films, 195.5 MB, GIF 2.32 MB, -16.1
LUFS). Each checked with ffprobe/ebur128: audio = video length to the frame, mov_text subtitle track,
`.srt` beside the MP4, GIF < 3 MB. No SUMO run.

Decisions:
- RV2-001 run ids: the v2 policy runs keep bare ids under `runs/v2/` that collide with the v1 runs,
  so they are exposed as symlinks `runs/v2-<policy> -> v2/<policy>` (remote_work_30,
  staggered_schools_60 (+--control), cordon_center (+--control)); the API is unchanged. The v2
  baseline was already listed at `runs/<id>`.
- RV2-002 narration length: a separate late-anchored caveat line stretched `city-24h` to 108.6 s
  (the stretch scales anchors too); it was folded into the closing line (45.87 s). `policy-lab` gives
  one v2 figure per policy with its v1 figure (first draft 68 s, cut to 50.9 s).
- RV2-003 obhur-bridge: no city-run map layer. The window network was cut from the first city
  network and the bundle would only map v2 edges onto it by id; the city numbers are a result card
  (literal KPIs from docs/obhur-bridge.md section 5) over the window difference map, captioned so.
  B2 increment = the documented "about 8,100 VHT/day" (B3 minus B1). The card shot is 9 s in the
  spec (tests cap specs at 45 s) and stretched x3.30 by the narration. Its first render failed once:
  the showreel excerpt ended at the film end and rounding put it 0.3 ms past it; excerpt now [30, 44].
- RV2-004 showreel: it embeds city-24h and policy-lab, so it was re-rendered; obhur-bridge, now
  rendered on main, joins after loop (film_names() appends specs outside order.yaml). Headlines
  updated (city-24h no longer says "forty seconds"; policy-lab = v2 remote-work VHT -8.7 %).
  The six unchanged films' narrated renders were copied from `.worktrees/trackI/movies/` into
  main's git-ignored `movies/` (specs, narration and landmarks identical to main).
- RV2-005 Al Hamra: the only occurrence is the OSM district label on the policy-lab cordon shot,
  the same as in the v1 render; TI-002 withdrew the Al Hamra evacuation demo and kept district names.
  Not suppressed (would need label-filter code); flagged for the owner.

Open: `docs/img/movies/` GIFs/stills (`make movies-docs`) and `site/index.html` (film lengths, the
v1 policy table) still show v1; README results rows now quote v2 with v1 in brackets.
Also open (verifier, all 7 checks PASS): the v2 baseline `runs/<id>` link (and `runs/v2/<id>`)
points into `.worktrees/trackF/runs/`; move the run into main's `runs/` before removing that
worktree. The `loop` film and its showreel headline (28,820 passengers/day) stay on the v1 run;
the v2 Loop figure (14,630 riders/day) would need a loop re-render. "28 to 30 percent" teleports
is the docs/obhur-bridge.md wording (0.296 control, 0.305 with bridges).

RENDER_V2: done
