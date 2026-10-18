# Track G: open-source release readiness

## RELEASE — 2026-10-17
Everything a maintainer needs to publish TrafficTwin on GitHub. No remote was created and nothing
left the machine (`gh`, `git push` not run). Light compute only (no SUMO city runs, no film renders).

Built:
- **Licence and attribution audit** `docs/release-audit.md`: Python (52 packages) and npm (248)
  licences, all compatible with Apache-2.0 (SUMO EPL-2.0 OR GPL-2.0+, certifi MPL-2.0, both
  dependencies only); data sources; secrets, paths and private-data greps over the tree and the
  full history; size of history. NOTICE gained the OpenFreeMap / OpenMapTiles basemap (was
  missing), a produced-works note for screenshots/GIFs/films, and a third-party software summary.
- **CI** `.github/workflows/ci.yml`: ruff, ruff format, pytest on ubuntu-latest (SUMO runtime libs
  and osmium-tool via apt, uv 0.11.13 with cache), web `npm ci` + typecheck + build (npm cache).
  `demo-smoke.yml` (manual): `make demo CITY=0|1 DETACH=1`, probes `/health`, the viewer and
  `/api/runs`, uploads logs. `pages.yml`: builds `site/` and deploys to GitHub Pages. Every action
  pinned to a commit SHA (checkout v7.0.1, setup-uv v10.3.0, setup-node v7.1.0, upload-artifact
  v7.0.2, configure-pages v6.0.0, upload-pages-artifact v5.0.0, deploy-pages v5.0.1).
  `actionlint` 1.7.12 (installed with brew): clean.
- **CI rehearsal without `act`** (act would pull multi-GB runner images while city runs are going):
  the CI steps ran in clean containers from `git archive HEAD`. Web on node:22-alpine: `npm ci`,
  typecheck and build pass. Python on ubuntu:24.04 (+ the CI apt list + tzdata): ruff clean,
  format clean, **pytest 314 passed, 3 skipped, 7 min 25 s** (aarch64, machine shared with a city
  run).
- **Repo hygiene**: README rewritten for publication (badge row, what-it-is, hero GIF
  `city-24h.gif`, 60-second quickstart, 9-film table with lengths and MP4 sizes, results with
  caveats, hardware, project status, documentation index; the detailed command sections kept).
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md` (private vulnerability
  reporting), issue forms (bug, feature) + config, PR template, `CITATION.cff`, CHANGELOG v0.1.0
  updated (Loop, films, release; stale "Loop not merged" removed). No `FUNDING.yml`.
- **Good first issues**: 13 drafts in `docs/issues/` (lane audit accuracy, network capacity,
  25 %/100 % runs, logit mode choice, induced demand, Friday/Ramadan films, viewer compare across
  network variants I-010, cross-platform population hash, tzdata, re-link windows to the M2
  baseline, chunked trajectories, policy replicates, census tables).
- **Project page** `site/` (plain HTML + CSS, system fonts, no external assets or trackers):
  showreel poster hero, 9-film gallery (GIF previews, MP4 links to the v0.1.0 release), Loop map +
  3-line result, policy table, inline-SVG architecture diagram, quickstart.
  `scripts/build_site.sh` assembles `_site/` (copies images from `docs/img/`, fills `__REPO__`;
  9.5 MB). Rendered headless with Chrome: `docs/img/site.png`.
- **Release checklist** `docs/release-checklist.md`: history cleanup, placeholders, `gh repo
  create`, push, Pages, vulnerability reporting, workflows, tag v0.1.0, film assets (548.4 MB in
  9 files), labels and issues, LinkedIn draft (EN + AR) and badge row.

Found and fixed:
- **pytest failed on a fresh clone**: API tests read `data/jeddah/districts.geojson` and
  `buildings.geojson` (gitignored city side outputs), so CI would have failed (3 failed, 12
  errors); M9's verifier ran `make test` after `make demo` and never saw it. Added
  `data/demo/districts.geojson` (2 districts) and `data/demo/buildings.geojson` (413 footprints),
  `tests/conftest.py` points `TT_DISTRICTS` / `TT_BUILDINGS` at them (G-D-003).

Found, not fixed here (recorded):
- **Esri imagery crops in git history** (12 JPEGs, 1.24 MB, 403d2af -> removed 0bf3c0d). This track
  may not rewrite history; checklist step 1 removes them with `git filter-repo` on a fresh clone
  (rehearsed: 0 left, 31 MiB packed). The owner must do this before the first push.
- Commit author e-mail is a company address on every commit; optional mailmap in step 1.
- `ZoneInfo("Asia/Riyadh")` needs the OS tz database; bare images fail. Issue 09 (`tzdata`
  dependency; lockfile is being changed by other tracks).
- No tracked file > 5 MB and no blob > 5 MB in history (largest 2.1 MB `data/demo/demo.net.xml`).

Decisions:
- G-D-001 Validate CI with actionlint plus container runs of the same steps, not `act` (image size,
  shared machine).
- G-D-002 Pages through an Actions workflow that copies images from `docs/img/` (no duplicate
  binaries in git); the repository slug is injected at build time.
- G-D-003 Demo-window districts/buildings fixtures committed under `data/demo/` (ODbL, 132 KB)
  rather than skipping the API tests without a city build.
- G-D-004 `OWNER` and `CONDUCT_CONTACT` stay as placeholders (owner's GitHub handle and conduct
  address unknown); checklist step 2 fills them. CITATION lists Tariq Alturkestani and "The
  TrafficTwin Jeddah contributors"; the owner confirms.
- G-D-005 The build-orchestration files (`PROMPT.md`, `prompts/`, `orchestrate.sh`,
  `run_track.sh`, `.claude/`) stay public as a record of how the project was built; they contain
  no secrets or machine paths beyond `$HOME`/`/opt/homebrew` in `PATH`.
No new behavioural assumptions (no `docs/assumptions-trackG.md`).

Measured: actionlint clean (3 workflows); Linux pytest 314 passed / 3 skipped; web build 5.8 s in
the container; `_site/` 9.5 MB; repository objects 39.2 MiB loose (31 MiB packed after cleanup).

Verifier (independent subagent, 2026-10-17): all 7 items PASS, no FAIL. Evidence: actionlint
clean, 12 `uses:` pinned and each SHA matched to its tag with `git ls-remote`; pytest 314 passed /
3 skipped in the worktree and on a fresh clone without `data/jeddah`; web typecheck and build;
README commands (Tier B smoke, `sim.validate`, `loop_demo --demo`, `build_site.sh`) exit 0 and
every README link resolves; site images resolve, numbers match docs/policies.md and docs/loop.md;
CITATION.cff validates with cffconvert; LICENSE matches the Apache-2.0 text; filter-repo step
rehearsed on a trackG clone (0 crops left, 31.76 MiB). Minor points fixed: the checklist's
mailmap example no longer contains the commit e-mail; this file committed. Noted, not changed:
pytest 7-8 min and `loop_demo` 21 s were measured while a city simulation ran on the same machine
(README says about 3 min and about 10 s on an idle machine); `data/osm/jeddah.poly` is allowed by
`.gitignore` but not named in CLAUDE.md's data allowlist.

Owner actions before publishing: checklist step 1 (remove the Esri crops from history) is
mandatory; step 2 fills `OWNER` and `CONDUCT_CONTACT`.

RELEASE: done
