# Track J — OBHUR_BRIDGE (bridges across Sharm Obhur)

## OBHUR_BRIDGE — 2026-10-17
All results: **synthetic demand, uncalibrated**. Full write-up: `docs/obhur-bridge.md`.

Built (all new files except the appended register section):
- `sim/bridge/`: `schema.py` (`BridgePolicy`: Track A's `network_change` plus a `bridges:` block),
  `network.py` (netconvert patch: abutment nodes, span, approaches, explicit lane connections;
  SCC-membership and duarouter through-route checks), `transforms.py` + `run.py` (city runs through
  Track A's `run_policy` with Track D's dispatch pattern; `--validate`), `desire.py` (desire lines,
  free-flow detours, landing accessibility), `window.py` (Tier B demand cut, baseline / matched
  control / variant micro runs, KPIs, `publish` for the viewer), `geo.py`, `config/bridge.yaml`,
  `config/sharm_obhur.geojson` (creek from the OSM coastline), `results/*.csv|json`.
- Policies `sim/policies/obhur_bridge_{b1,b2,b3}{,_3x3}.yaml`; window
  `sim/network/windows/obhur_creek.yaml`; film `movies/specs/obhur-bridge.yaml`; tests
  `tests/test_bridge.py` (17, synthetic two-bank network); `docs/obhur-bridge.md`,
  `docs/assumptions-trackJ.md` (A-obh-001..041, also appended to `docs/assumptions.md`),
  `docs/data-sources-trackJ.md`, `docs/img/obhur-desire.png`.

Measured:
- Public plans: a Sharm Obhur bridge was studied (2009), tendered by Metro Jeddah (2014-15, about
  US$1bn, 8 lanes + metro, 350-380 m water crossing), turned into a PPP (2018) and re-studied in the
  JDA Northern Obhur Road (2021-, five alignments); never awarded. No coordinates published.
- Validation on the city network (`jeddah.m2.net.xml`): all six policies pass
  `python -m sim.bridge.run <p> --validate` (every new edge in the main SCC, through-routes over each
  span both ways), 44-62 s and 1.4-1.7 GB each. B1: 1.28 km, 281 m over water; B2: 1.47 km, 890 m.
- Detour screen (no simulation, 19 min): 238,130 car trips/day cross the creek's desire line; B1 + B2
  shorten 145,370 of them by 6.0 km (2.9 min free flow); B1 does almost all of it, B2 alone 39,380
  trips by 2.6 km. Landing access: from 1.1 km away on the same bank it takes 8-24 km to reach
  three of the four landings (B1 south 1.3-1.6 km), which caps B2.
- Window (Tier B, `obhur_creek` 24.5 km2 / 2,466 edges, 48,640 AM and 43,720 PM vehicles, 25 micro
  runs of 2-4.5 min, grid 40 min): bridges carry 536-645 (B1) and 297-427 (B2) veh/h in the AM peak
  hour, under 110 in the PM; Δ time in the window per peak-hour vehicle vs the matched control is
  -16 to +53 s, sign flipping between seeds for every 2+2 variant; noise band about +/- 20 s (control
  between seeds -2.9 / -8.9 s; control re-simulated on the B3 network +17 s). No window-scale effect
  beyond noise; AM users gain nothing (landing queues, approach delay +31 % with B2), PM users save
  ~7 min each. 3+3 = 2+2. Control vs cut-route baseline: AM -68 s, PM +9 s (routing gain).
- Viewer: the API edge index of `obhur-am-s1-obhur_bridge_b3` holds its 14 new edges (2,480 edges)
  and its bins build with 0 unmatched edges (21 five-minute bins; B1 span 96-168 veh/h per bin
  direction). It shares network hash 2471937e17c2d357 with `obhur-am-s1-control-on-obhur_bridge_b3`,
  so difference mode works between them (choose it in the compare list: the runs' default
  comparison is the matched control, on the base window network).

Decisions:
- J-D-001 Bridges are `network_change` transforms with a `bridges:` block (`BridgePolicy`), run by
  `python -m sim.bridge.run` (Track D's `sim.loop.run` pattern). The brief's
  `python -m sim.policies.run <p> --validate` / `--control matched` do not exist (Track A's file, no
  such options, and its schema rejects `bridges`); the matched control is automatic.
- J-D-002 Own window `obhur_creek` instead of Track I's `obhur` (mouth only, up to 21.739 N): the
  head detour must be inside the window or a bridge cannot shorten it. Built as creek + 500 m, B1's
  mouth landings, the head interchange and a band along today's north-to-south route round the head
  (without it north-to-south trips left the window); 24.5 km2, inside the 3-25 km2 range
  (`test_window_yaml_area`). 9 % of the cut cross-creek vehicles still leave and re-enter it.
- J-D-013 A first window (39 km2, 1 km buffer) broke the window-size test and was discarded with its
  grid. It was near gridlock (26-38 % of peak vehicles finished) and showed consistent AM gains of
  25-45 s per vehicle; the final window shows none beyond noise. Recorded as a sensitivity in
  docs/obhur-bridge.md §4, not as a result.
- J-D-014 Two small edits in files Track J does not own, needed for the shared tests (keep at
  integration): `sim/schemas.py` `validate_file` validates a policy whose `network_change` has
  `bridges` as `BridgePolicy` (lazy import, like the Loop branch); `sim/policies/sweep.py` `template`
  skips policy files that are not Track A policies. Track A's `Policy` stays strict on purpose: if it
  accepted `bridges`, `sim.policies.run` would silently ignore them.
- J-D-003 Shared inputs symlinked (gitignored), same pattern as `data/jeddah`: `data/population` and
  `runs/baseline-weekday-f0.1-s1-e5f1906a-65fac195-65b0f3` -> main checkout; edge caches copied to
  `data/policies/`.
- J-D-004 Explicit lane connections onto the approaches (netconvert drops edge-only connections for
  edges whose lanes were loaded); bridges are priority 12 (primary), landings unsignalised.
- J-D-005 Detours against free-flow shortest paths, not the baseline's assigned routes (16 % longer);
  pure-Python Dijkstra (no scipy; `pyproject.toml` not owned).
- J-D-006 Window evaluated on the peak hours 06-07 and 18-19 (the busiest window-entry hours), not
  the 3-h policy peaks: about 30 min per 3-h micro run on the shared machine.
- J-D-007 KPIs cover every vehicle due in the peak hour (tripinfo with unfinished and undeparted
  vehicles; time in system = arrival or run end minus planned departure): the first grid paired
  only arrived vehicles, biased by the different arrival shares, and was discarded and re-run.
- J-D-008 Seed-2 runs reuse the seed-1 baseline's routing weights: the seed changes only the
  simulation (noise band).
- J-D-009 Register rows appended to `docs/assumptions.md` (Track I precedent) so
  `test_merged_register_holds_every_track_row` holds; `docs/assumptions-trackJ.md` is the source.
- J-D-010 Narration kept as a comment block in the film spec: Track I's `scripts/movies/narrate.py`
  is not on main, and a `*.narration.yaml` file would fail main's spec validation.
- J-D-011 `control-on-obhur_bridge_b3`: the control's routes simulated on the B3 network, so the
  viewer (same-network-hash compare only, I-010) can show the difference; the film maps sources by
  edge id and uses the matched control.
- J-D-012 FCD only for the film runs (control, B3 AM) and only on edges within 900 m of a landing.

City runs for the coordinator (NOT run here; on the v2 network): see `docs/obhur-bridge.md` §5.
```
uv run python -m sim.bridge.run obhur_bridge_b3 --validate --net data/jeddah/<v2>.net.xml
uv run python -m sim.bridge.desire access --net data/jeddah/<v2>.net.xml
uv run python -m sim.bridge.run obhur_bridge_b3 --daytype weekday --sample 0.10 --seed 1
uv run python -m sim.bridge.run obhur_bridge_b1 --daytype weekday --sample 0.10 --seed 1
uv run python -m sim.bridge.run obhur_bridge_b2 --daytype weekday --sample 0.10 --seed 1
uv run python -m sim.bridge.run obhur_bridge_b3_3x3 --daytype weekday --sample 0.10 --seed 1   # optional
uv run python -m sim.bridge.desire detour --baseline runs/baseline-weekday-f0.1-s1-<v2 ...>
make movie FILM=obhur-bridge    # after re-pointing the spec sources to the city runs
```
Estimate: 30-40 min per policy including its matched control (about 45,000 sampled vehicles
re-routed), 1.5-2 h for the three 2+2 variants; plus about 2 h if the v2 weekday baseline must be
assigned first. Then fill the *pending city run* cells of `docs/obhur-bridge.md` §5-6.

Gates: ruff clean; pytest 341 tests, 338 passed, 3 skipped. Film `make movie FILM=obhur-bridge`:
1920x1080, 36.00 s, 19.3 MB, 182 s (MP4 gitignored).

Open: the window cannot resolve the effect (noise); the city run decides. B2's value depends on
landing access (re-check on v2); no interchange or signal design; no induced demand; no bascule
opening events.

Verifier (independent agent, 2026-10-17): policies validate (window and city, B2 city check 8/8
edges in the main SCC); ruff clean; full suite 338 passed / 3 skipped; the B1 AM seed-1 window run
re-run bit for bit (48,640 tripinfo rows identical, mean time in system 1307.2 s, 711 teleports);
docs, cost arithmetic, film KPIs and noise band match the result files; change scope limited to new
files plus J-D-014. Three FAILs fixed afterwards: A-obh-025/026 registered and bridge.yaml settings
tagged; repo-relative paths (no absolute home path in sim/bridge/results/detour_summary.json, rel()
no longer resolves the data/jeddah symlink); the B1 volume range (536-645), the per-user km wording
and the stale config comments corrected. Merge note: expect a conflict at the end of
docs/assumptions.md (main has added A-loop-021..030 since the branch point); keep both sections.

OBHUR_BRIDGE: done
