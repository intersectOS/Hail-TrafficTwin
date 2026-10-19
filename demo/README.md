# Demo window (committed, ODbL)

Small focus window in central Hail (Barzan, Al Olaya, Labdah, King Khalid Hospital and King
Abdulaziz Road; bbox lon 41.690-41.708, lat 27.512-27.528, about 3.2 km2) so tests run in seconds
without downloading anything.

| file | what | produced by |
|---|---|---|
| `demo.net.xml` | SUMO network cut from the Tier A city network (edge ids identical to Tier A) | `python -m sim.network.build_window --name demo --osm-extract` |
| `demo.trips.xml` | tiny random-trips demand (seed 1, 1,800 trips/hour) | same command |
| `demo.osm.gz` | raw OSM of the bbox, input for the city-builder test | same command (`--osm-extract`) |
| `demo.window.json` | provenance: window definition, city network hash, SUMO version, network stats | same command |
| `districts.geojson` | the 14 OSM districts (admin_level 10) touching the window (+0.002 deg), cut from `data/hail/districts.geojson`; API tests read it via `TT_DISTRICTS` | `sim.network.build_city` side output, filtered to the window bbox |
| `buildings.geojson` | the 35 building footprints touching the window (+0.003 deg), for the `/api/geo/buildings` test via `TT_BUILDINGS` | same, from `data/hail/buildings.geojson` |

The window definition is `sim/network/windows/demo.yaml`. Windows cut from the city network inherit
Tier A's road classes, so service roads are not present.

Data (c) OpenStreetMap contributors, Open Database License (ODbL) 1.0. Synthetic demand, uncalibrated.
