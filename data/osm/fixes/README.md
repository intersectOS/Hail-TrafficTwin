# OSM fix list

Reviewed corrections applied reproducibly by `sim/network/fixes.py` after netconvert (raw OSM is
never edited). One or more `*.yaml` files, each:

```yaml
fixes:
  - id: FIX-0001                 # unique across all files
    osm_way_id: 123456789        # or edge_id: "123456789#2" (exactly one)
    field: lanes                 # lanes | lanes_min | speed (km/h) | oneway (forward|backward) | remove
    value: 3
    direction: both              # both | forward | backward (backward = SUMO ids starting with '-')
    reason: "Why, with evidence (imagery, adjacent segments, ground truth)"
    date: 2026-10-15
    author: traffictwin
    osm_note: "upstream status (not yet edited in OSM / changeset id)"
```
`python -m sim.network.fixes check --net data/jeddah/jeddah.net.xml` lists the edges each fix
resolves to. A fix that matches no edge fails the build (stale after an OSM update); upstream
confident fixes to OpenStreetMap.
