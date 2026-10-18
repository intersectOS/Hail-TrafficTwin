---
name: lane-audit-imagery
description: How to count lanes on untagged roads from aerial imagery with a vision pass — which imagery is permitted, tile maths, crop preparation, the calibration-before-audit rule, the structured result format and how results enter the OSM fix list. Use for sim/network/lane_audit.py and any imagery-derived network fix.
---
# Lane audit from imagery

## Imagery source and licence
- Use **Esri World Imagery** tiles: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` (Web Mercator, 256 px). Esri permits OpenStreetMap-style derivation from this layer; attribute "Esri, Maxar, Earthstar Geographics, and the GIS User Community" in `NOTICE` and in `docs/lane-audit.md`.
- Do NOT fetch Google Maps or Google Earth imagery: Google's terms forbid deriving datasets from it and OSM bans it for the same reason. Bing/Azure Maps requires a key; skip it.
- Be polite to the tile server: one request at a time per process, a small local cache under `data/imagery/` (gitignored), a descriptive User-Agent, and a 0.2 s delay.

## Tile maths and crops
- Zoom 19 (about 0.3 m/px at Jeddah's latitude) is the default; a 3.5 m lane is about 12 px. Use zoom 18 only for very wide motorways.
- For a sample point (lon, lat): tile x = floor((lon+180)/360 * 2^z); tile y = floor((1 - ln(tan(lat) + sec(lat))/pi)/2 * 2^z). Fetch the 3x3 neighbourhood, stitch, then crop 512x512 centred on the point and rotate so the road bearing points up (so lanes appear as vertical stripes). Draw a thin marker on the sampled carriageway only; untagged OSM ways are usually one carriageway of a dual carriageway, so the analyst must count the marked side only.
- Save as PNG with a small caption strip: way id, class, bearing, "count lanes on the marked carriageway only".

## Procedure
1. **Calibration before audit.** 40 tagged ways, stratified by class; blind counts; agreement rate and a confidence threshold chosen so precision is at least 80 %. Record in `data/osm/fixes/imagery-eval.json`. No audit without this.
2. **Audit** untagged ways by class priority, capped (default 1,500 crops). Batches of 20 crops per `imagery-analyst` call. The analyst returns strict JSON per crop: `{way_id, lanes_marked_side, oneway_visible, median_visible, confidence (0-1), note}`. Confidence below the threshold is discarded, not rounded up.
3. **Fix list entries** (`data/osm/fixes/imagery-lanes.yaml`): `osm_way_id`, `field: lanes`, `value`, `confidence`, `method: imagery-analyst`, `source: "Esri World Imagery tile z19/<x>/<y>, accessed YYYY-MM-DD"`, `date`, `author: lane-audit`. Keep them separate from human-reviewed fixes.
4. **Rebuild to a new network file name** and compare lane-km, teleports and smoke runtime before and after.

## Known failure modes
Shadows from tall buildings, parked cars on the kerb lane, construction, slip roads and bus lanes. The analyst should lower confidence in those cases rather than guess.
