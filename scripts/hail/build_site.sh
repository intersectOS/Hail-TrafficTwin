#!/usr/bin/env bash
# Assemble the Hail project page and the static viewer into one directory for GitHub Pages.
#   scripts/hail/build_site.sh <out_dir> <owner/repo>
# Needs: runs/ ingested (python -m api.ingest --all), web/node_modules, web/public/data/edges.geojson.
set -euo pipefail
OUT=$(realpath -m "${1:-_site}"); REPO=${2:-intersectOS/Hail-TrafficTwin}; NAME=${REPO#*/}
rm -rf "$OUT"; mkdir -p "$OUT/data"
sed "s#__REPO__#${REPO}#g" site/index.html > "$OUT/index.html"
cp site/style.css site/page.js site/try.html site/try.css site/try.js "$OUT/"
cp site/actual.html site/actual.js "$OUT/" 2>/dev/null || true
uv run python -m scripts.hail.site_data --edges web/public/data/edges.geojson --runs runs --out "$OUT/data"
(cd web && VITE_STATIC=1 npx vite build --base "/${NAME}/viewer/" --outDir "$OUT/viewer" --emptyOutDir)
uv run python -m scripts.hail.export_static --out "$OUT/viewer/api"
uv run python -m scripts.hail.stories --out "$OUT/data/stories.json"
uv run python -m scripts.hail.playback --runs runs --out "$OUT/data/play"
if [ "$(cat "$OUT/data/play/index.json")" = "[]" ]; then
  # no city scenarios yet: run the small demo-window tests so «جرّب بنفسك» has something to play
  uv run python -m sim.demo --only events --only evacuation || true
  STORIES_DEMO=1 uv run python -m scripts.hail.playback --runs runs --out "$OUT/data/play"
fi
rm -rf "$OUT/viewer/data"   # dev-only GeoJSON copies; the static viewer reads viewer/api/
if [ -f data/observed/tomtom_traveltimes.json ]; then
  uv run python -m scripts.hail.observed_compare --out "$OUT/data/observed.json" --roads "$OUT/data/roads.json"
fi
touch "$OUT/.nojekyll"
find "$OUT" -type f -size +90M -print -delete   # GitHub Pages: 100 MB per file, 1 GB per site
echo "site built in $OUT ($(du -sh "$OUT" | cut -f1))"
