# Assumptions register: Track C (lane audit from imagery)

Same row format as `docs/assumptions.md`; merged into it at integration. All results are
**synthetic demand, uncalibrated**.

| id | parameter | value | unit | range | source or assumption | status | used in |
|---|---|---|---|---|---|---|---|
| A-network-004 | OSM `lanes` tags as ground truth for the imagery calibration | tags taken as correct | - | - | Assumption: tags are mapper-entered and may be stale or include turn lanes; disagreements are counted against the imagery pass, so the measured precision is a lower bound when tags are wrong | assumed | sim/network/lane_audit.py (evaluate), data/osm/fixes/imagery-eval.json |
| A-network-005 | Lane count at the way's mid-segment sample represents the whole way | one sample per way | samples | 1-3 per km | Assumption: one crop per OSM way (cap 1,500 crops); long ways can change width at junctions and ramps. `lanes_min` keeps lanes netconvert adds at guessed ramps | assumed | data/osm/fixes/imagery-lanes.yaml (planned; not written, audit blocked) |
| A-network-006 | Two-way untagged roads have the same lane count in both directions | symmetric | - | - | Assumption: the analyst counts only the direction travelling up the crop; the fix applies to both directions (`direction: both`) | assumed | data/osm/fixes/imagery-lanes.yaml (planned; not written, audit blocked) |
| A-network-007 | Imagery currency | Esri World Imagery as served on the access date | - | capture dates vary, typically 1-4 years old | Source: Esri World Imagery (Esri, Maxar, Earthstar Geographics, and the GIS User Community); capture date per tile not recorded; recent road works may be missing | sourced | data/osm/fixes/imagery-lanes.yaml (`source:`) |
| A-network-008 | Ways cut from one named road are not independent samples of reading accuracy | at most 5 ways per named road and class in the attempt-2 holdout | ways | - | Assumption: one road's markings, imagery date and tag history are shared by all its ways (Prince Majid Road alone is 39 of 54 fresh trunk candidates); capping keeps one road from deciding the gate. Unnamed ways are not capped | assumed | sim/network/lane_audit.py (sample-calibration --max-per-road), data/osm/fixes/imagery-eval.json |
