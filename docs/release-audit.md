# Release audit (v0.1.0, Track G, 2026-10-17)

What was checked before publishing TrafficTwin Jeddah on GitHub, what was found, and what was
fixed. Commands are repeatable from the repo root. Nothing was pushed or published.

## Summary

| check | result | action |
|---|---|---|
| Code licence | Apache-2.0 `LICENSE` (full text), `pyproject.toml` and `web/package.json` say Apache-2.0 | none |
| Python dependency licences | all permissive or weak copyleft; SUMO is EPL-2.0 OR GPL-2.0-or-later (dependency, not vendored) | listed in NOTICE |
| npm dependency licences | all permissive; two dual-licensed packages used under their permissive option | listed in NOTICE |
| Data sources | OSM (ODbL), GASTAT (open-data terms), OpenFreeMap basemap (runtime only), Esri imagery (local only) | NOTICE: basemap and produced-works sections added |
| Fonts | none redistributed; viewer uses system fonts, title cards use the renderer's system fonts | noted in NOTICE |
| Esri imagery crops in the tree | none tracked | none |
| **Esri imagery crops in history** | **12 JPEG crops (1.24 MB) added in 403d2af, deleted in 0bf3c0d; still in history** | **owner removes them before the first push (checklist step 1)** |
| Secrets (tree and full history) | none found | none |
| Home or machine paths (tree and full history) | no `/Users/...` or `/home/...` path; `$HOME` and `/opt/homebrew` only in the local orchestration scripts | none |
| Private or partner data | none (`data/` is gitignored except demo, OSM fixes, census placeholder, public flood-site list) | none |
| Large files | largest tracked file 2.1 MB (`data/demo/demo.net.xml`); no blob over 5 MB anywhere in history; 39 MB of objects in total | none |
| Commit author e-mail | all 125+ commits carry a company e-mail address | owner decides (checklist step 1, optional mailmap) |
| Fresh-clone tests | **API tests failed without a city build** (they read `data/jeddah/*.geojson`, gitignored) | fixed: demo-window fixtures (below) |
| Minimal Linux images | prayer times need the system tz database (`ZoneInfo("Asia/Riyadh")`); absent in a bare `ubuntu:24.04` | CI runner has it; issue `docs/issues/09-tzdata-dependency.md` |

## 1. Licences

### Python (from `uv.lock`, the installed `.venv`; `importlib.metadata`)

| licence | packages |
|---|---|
| MIT | adhanpy, annotated-doc, annotated-types, anyio, duckdb, fastapi, fonttools, h11, iniconfig, markdown-it-py, mdurl, pluggy, pydantic, pydantic-core, pyogrio, pyparsing, pyproj, pytest*, pyyaml, rich, ruff*, six, typer, typing-inspection |
| BSD-3-Clause | click, contourpy, geopandas, httpcore*, httpx*, idna, pandas, psutil, shapely, starlette, uvicorn |
| BSD-2-Clause | pygments |
| Apache-2.0 | opentelemetry-api, pyarrow; packaging (Apache-2.0 OR BSD-2-Clause) |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| matplotlib, cycler, kiwisolver | matplotlib licence (PSF-style) / BSD-style |
| pillow | MIT-CMU |
| python-dateutil | Apache-2.0 / BSD dual |
| shellingham | ISC |
| typing_extensions | PSF-2.0 |
| certifi | MPL-2.0 (weak copyleft, unmodified, not vendored) |
| eclipse-sumo, sumo-data, sumolib, traci | EPL-2.0 OR GPL-2.0-or-later |

`*` dev only. Apache-2.0 code may depend on all of these. SUMO and certifi are installed from
PyPI at setup, never copied into the repository; the Docker image installs them the same way.

### Web (`web/package-lock.json`, 248 packages)

| scope | licences (count) |
|---|---|
| production (156) | MIT 115, ISC 14, BSD-3-Clause 13 (MapLibre GL JS and its parts), Apache-2.0 7, BSD-2-Clause 3, 0BSD 1, `MIT OR Apache-2.0` 1 (@maplibre/mlt), `MIT AND Zlib` 1 (pako), `MIT OR GPL-3.0-or-later` 1 (jszip, used under MIT) |
| dev only (92) | MIT 80, Apache-2.0 5, ISC 5, BSD-3-Clause 2 |

deck.gl and React are MIT; Vite, TypeScript and puppeteer-core are dev only.

Command:
```bash
cd web && node -e 'const l=require("./package-lock.json");const o={};for(const[p,v]of Object.entries(l.packages)){if(!p)continue;const k=(v.dev?"dev ":"prod ")+v.license;o[k]=(o[k]||0)+1}console.log(o)'
```

### Data

| source | used for | licence and terms | in the repo |
|---|---|---|---|
| OpenStreetMap via Geofabrik | network, districts, buildings, POIs, demo window | ODbL 1.0, attribution "(c) OpenStreetMap contributors" | `data/demo/*` and `data/osm/jeddah.poly`, `data/osm/fixes/` (derived, ODbL); the 243 MB extract is downloaded at build |
| GASTAT open data | Jeddah population total, labour statistics | GASTAT open-data terms, attribution | numbers in YAML with `source:`; no tables committed yet |
| Public literature and press | flood-site list | facts with citations | `data/jeddah_flood_sites.yaml` |
| OpenFreeMap (OpenMapTiles schema) | viewer basemap at runtime | OpenFreeMap terms; OpenMapTiles, data ODbL | not redistributed; screenshots in `docs/img/` show it with attribution |
| Esri World Imagery | lane audit (blocked) | Esri terms; no redistribution | crops gitignored; aggregate accuracy statistics only in `data/osm/fixes/imagery-eval.json` (no imagery, no per-road imagery-derived counts) |
| Eclipse SUMO | simulator | EPL-2.0 OR GPL-2.0-or-later | PyPI dependency |

NOTICE changes in this release: a "Basemap tiles in the viewer" section (OpenFreeMap and
OpenMapTiles were missing), an "Images and films" section (screenshots, GIFs and films are ODbL
Produced Works; no fonts redistributed), and a "Third-party software" summary.

## 2. Tracked files: secrets, paths, private data

```bash
git ls-files | wc -l                                              # 419 before this track
git grep -n -I -E '/Users/|/home/[a-z]' -- . ':!uv.lock'          # none
git grep -n -I -iE 'api[_-]?key|secret|token|password|BEGIN .*PRIVATE|ghp_|AKIA' -- . ':!*.lock' ':!web/package-lock.json'
```
Hits are documentation of the rules, the commercial-API adapter stubs that read
`GOOGLE_MAPS_API_KEY` / `TOMTOM_API_KEY` / `HERE_API_KEY` from the environment (no values), and a
path-traversal test. No `.env` file was ever committed (`git log --all --diff-filter=A
--name-only`).

Machine-specific references: `orchestrate.sh` and `run_track.sh` (the scripts that ran the
parallel Claude Code tracks) prepend `$HOME/.local/bin:/opt/homebrew/bin` to `PATH`; they are
kept as a record of how the project was built, together with `PROMPT.md` and `prompts/`.
`api/normalize.py` and two API tests mention `.worktrees/` to normalise run paths produced in
worktrees; they contain no machine paths. Localhost URLs are the documented dev ports.

## 3. History

```bash
git count-objects -vH                          # 1,581 loose objects, 39.2 MiB, no packs
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '$1=="blob" && $2>1000000' | sort -k2 -n -r      # largest blob 2.09 MB (demo.net.xml)
git log --all --format='%h %s' -- docs/img/lane-audit   # 403d2af adds, 0bf3c0d removes 12 crops
```

- **No file over 5 MB** in the tree or in history; the GIF previews are 0.9-1.1 MB each, the
  largest screenshot 1.1 MB. Rendered MP4s (21-186 MB) were never committed (`movies/*` is
  gitignored except `movies/specs/`).
- **Esri crops in history.** Twelve 512 px Esri World Imagery crops (`docs/img/lane-audit/*.jpg`,
  1.24 MB) were committed by the lane-audit track and removed during integration. They are still
  reachable from every later commit. Esri's terms do not allow redistribution, so the history must
  not be pushed as is. This track may not rewrite history; the checklist's step 1 removes them on
  a fresh clone with `git filter-repo --invert-paths --path docs/img/lane-audit/`. Rehearsed on a
  throwaway clone of `main` (125 commits): 0 crop paths left, 31 MB packed, commit count
  unchanged.
- Full-history secret scan (`git log -p --all` for GitHub, OpenAI, AWS, Slack, Google key and
  private-key patterns): no hits apart from a URL slug.
- Author identity: every commit is authored with a company e-mail address. Publishing makes it
  public; the checklist offers a mailmap rewrite to a GitHub no-reply address in the same
  filter-repo pass.

## 4. Fresh-clone and CI findings (fixed)

The previous CI had never run. Running its steps in clean Linux containers from `git archive
HEAD` (ubuntu:24.04 for Python, node:22-alpine for the web) found:

1. **API tests depended on the city build.** `tests/test_api.py` and `tests/test_api_producers.py`
   read `data/jeddah/districts.geojson` and `buildings.geojson`, which are gitignored and only
   exist after `make city-net` (the M9 verifier ran `make test` after `make demo`, so it never
   saw this). 3 failures and 12 errors on a fresh clone. Fixed: `data/demo/districts.geojson`
   (2 districts, 8 KB) and `data/demo/buildings.geojson` (413 footprints, 124 KB), both cut from
   the city side outputs to the demo window (ODbL like the rest of `data/demo/`), and
   `tests/conftest.py` sets `TT_DISTRICTS` / `TT_BUILDINGS` to them unless already set.
2. **System tz database.** `sim/daytypes/prayer.py` needs `Asia/Riyadh` from the OS; a bare
   `ubuntu:24.04` image has none (5 test modules fail at collection). ubuntu-latest runners and
   macOS ship tzdata, so CI passes; adding the `tzdata` PyPI package is issue 09 (it changes the
   lockfile, which other tracks are editing).
3. **eclipse-sumo Linux binaries** need `libatomic1 libx11-6 libxext6 libxrender1 libgl1`
   (known from M9's Docker work); the CI installs them explicitly instead of relying on the runner
   image.

Results of the container runs are in `docs/status/trackG.md`.

## 5. What a maintainer should keep doing

- Run the history checks above before every release; never commit imagery crops, counts, OD
  tables, `.env` files or real-city emergency plans (PROJECT.md section 11).
- Keep NOTICE in step with new data sources and runtime services.
- Update the pinned action SHAs together (Dependabot for `github-actions` can do it).
