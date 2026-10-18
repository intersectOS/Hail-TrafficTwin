#!/usr/bin/env bash
# Assemble the Hail project page and the static viewer into one directory for GitHub Pages.
#   scripts/hail/build_site.sh <out_dir> <owner/repo>
# Needs: runs/ ingested (python -m api.ingest --all), web/node_modules, web/public/data/edges.geojson.
set -euo pipefail
OUT=$(realpath -m "${1:-_site}"); REPO=${2:-intersectOS/Hail-TrafficTwin}; NAME=${REPO#*/}
rm -rf "$OUT"; mkdir -p "$OUT/data"
sed "s#__REPO__#${REPO}#g" site/index.html > "$OUT/index.html"
cp site/style.css site/page.js "$OUT/"
uv run python -m scripts.hail.site_data --edges web/public/data/edges.geojson --runs runs --out "$OUT/data"
(cd web && VITE_STATIC=1 npx vite build --base "/${NAME}/viewer/" --outDir "$OUT/viewer" --emptyOutDir)
uv run python -m scripts.hail.export_static --out "$OUT/viewer/api"
uv run python -m scripts.hail.stories --out "$OUT/data/stories.json"
rm -rf "$OUT/viewer/data"   # dev-only GeoJSON copies; the static viewer reads viewer/api/
touch "$OUT/.nojekyll"
echo "site built in $OUT ($(du -sh "$OUT" | cut -f1))"
