#!/usr/bin/env bash
# Assemble the static project page (site/) into a deployable directory for GitHub Pages.
# Images are copied from docs/img/ so no binary is stored twice in git; __REPO__ in the HTML is
# replaced with the GitHub "owner/name" (TT_REPO, else the origin remote, else a placeholder).
#
#   scripts/build_site.sh [out_dir]          default out_dir: _site
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-_site}"
REPO="${TT_REPO:-}"
if [[ -z "$REPO" ]]; then
  url="$(git remote get-url origin 2>/dev/null || true)"
  REPO="$(sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##' <<<"$url")"
  [[ "$REPO" == */* && "$REPO" != *:* ]] || REPO="OWNER/TrafficTwin"
fi
rm -rf "$OUT"
mkdir -p "$OUT/img/movies"
cp site/style.css "$OUT/"
sed "s#__REPO__#${REPO}#g" site/index.html >"$OUT/index.html"
cp docs/img/movies/*.gif docs/img/movies/*.jpg "$OUT/img/movies/"
cp docs/img/loop-candidates.png "$OUT/img/"
touch "$OUT/.nojekyll"
missing=$(grep -o 'src="img/[^"]*"' "$OUT/index.html" | sed 's/src="//; s/"$//' | while read -r f; do
  [[ -f "$OUT/$f" ]] || echo "$f"; done)
if [[ -n "$missing" ]]; then echo "missing images: $missing" >&2; exit 1; fi
echo "site built in $OUT for $REPO ($(du -sh "$OUT" | cut -f1))"
