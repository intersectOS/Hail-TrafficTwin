---
name: osm-jeddah-network
description: Build the Jeddah SUMO network from OpenStreetMap: Geofabrik download, polygon clip with osmium, netconvert options for a city-scale mesoscopic network and for microscopic windows, the reproducible OSM fix list, districts and buildings GeoJSON, and quality checks. Use for sim/network work.
---
# Jeddah network from OSM

## 1. Extract
- Download `https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf` (Geofabrik's GCC extract includes Saudi Arabia; verify the file list on the Geofabrik page first and use the Saudi-only file if present). Store in `data/osm/` (gitignored). Note the file date in `docs/STATUS.md`.
- Jeddah polygon: `data/osm/jeddah.poly` (committed). Start with a bounding box lon 39.00-39.40, lat 21.30-21.90 and refine to the urban area; do not include the Makkah highway beyond the city boundary in v1.
- Clip: `osmium extract -p data/osm/jeddah.poly data/osm/<extract>.osm.pbf -o data/osm/jeddah.osm.pbf` then `osmium cat data/osm/jeddah.osm.pbf -o data/osm/jeddah.osm.xml` (netconvert reads XML; for a city this is a few hundred MB, fine).

## 2. netconvert (Tier A city)
```
netconvert --osm-files data/osm/jeddah.osm.xml -o data/jeddah/jeddah.net.xml \
  --geometry.remove --ramps.guess --junctions.join --junctions.join-dist 20 \
  --tls.guess-signals --tls.discard-simple --tls.join --roundabouts.guess \
  --keep-edges.by-vclass passenger,bus,emergency,truck \
  --remove-edges.isolated --keep-edges.components 1 \
  --osm.lane-access --no-turnarounds.except-deadend \
  --output.street-names --proj.plain-geo --seed 1
```
Type map: use `$SUMO_HOME/data/typemap/osmNetconvert.xml`; drop `highway.service`, `highway.track`, `highway.living_street` for Tier A via a custom type file in `sim/network/types/city.typ.xml`. Windows (Tier B) keep service roads: `sim/network/types/window.typ.xml`.

## 3. Fix list
`data/osm/fixes/*.yaml`: each entry has `osm_way_id` or `edge_id`, `field` (lanes, oneway, speed, remove), `value`, `reason`, `date`, `author`. `sim/network/fixes.py` applies them with `netconvert --sumo-net-file ... --edges-file` patches or by rewriting `.edg.xml` before the final build. Fixes are reviewed and committed; raw OSM is not edited.

## 4. GeoJSON side outputs
- Districts: from OSM `admin_level=9/10` or `place=neighbourhood/suburb` polygons inside the clip; fall back to a Voronoi of named neighbourhood nodes. Write `data/jeddah/districts.geojson` with `name_ar`, `name_en`, area.
- Buildings: `building=*` footprints with `height` or `building:levels` (default 3 levels × 3.2 m, documented assumption) → `data/jeddah/buildings.geojson` (gitignored if > 50 MB; otherwise committed).

## 5. Quality checks (report all in STATUS.md)
- `netcheck.py data/jeddah/jeddah.net.xml --vclass passenger` → number of disconnected components (target 1 large component covering > 99 % of edges).
- Counts: edges, junctions, traffic lights, total lane-km.
- Smoke run: `randomTrips.py -n ... -e 3600 -p 0.2 --fringe-factor 5 --validate` then the `sumo-run` skill in meso mode; teleports < 0.5 %.
