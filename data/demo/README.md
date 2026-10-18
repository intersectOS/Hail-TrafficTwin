# Demo window (committed, ODbL)

Small focus window (western Tahlia Street and Al Andalus, Jeddah; bbox lon 39.148-39.166,
lat 21.542-21.558, about 3.3 km2) so tests run in seconds without downloading anything.

| file | what | produced by |
|---|---|---|
| `demo.net.xml` | SUMO network cut from the Tier A city network (edge ids identical to Tier A) | `python -m sim.network.build_window --name demo --osm-extract` |
| `demo.trips.xml` | tiny random-trips demand (seed 1, 1,800 trips/hour) | same command |
| `demo.osm.gz` | raw OSM of the bbox, input for the city-builder test | same command (`--osm-extract`) |
| `demo.window.json` | provenance: window definition, city network hash, SUMO version, network stats | same command |
| `districts.geojson` | the 2 OSM districts (admin_level 10) touching the window, cut from `data/jeddah/districts.geojson`; API tests read it via `TT_DISTRICTS` (tests/conftest.py) | `sim.network.build_city` side output, filtered to the window bbox + 0.002 deg (release audit, Track G) |
| `buildings.geojson` | the 413 building footprints touching the window (+0.003 deg), for the `/api/geo/buildings` test via `TT_BUILDINGS` | same, from `data/jeddah/buildings.geojson` |

The window definition is `sim/network/windows/demo.yaml`. Note: windows cut from the city
network inherit Tier A's road classes, so service roads are not present (decision recorded in
docs/STATUS.md).

Data (c) OpenStreetMap contributors, Open Database License (ODbL) 1.0. Synthetic demand, uncalibrated.
