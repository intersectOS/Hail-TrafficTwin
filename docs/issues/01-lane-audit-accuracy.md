# Lane audit from imagery: raise held-out precision above the 80 % gate

Labels: `network`, `help wanted`

## Context
Most major Jeddah roads lack an OSM `lanes` tag (83 % of secondary, 73 % of primary and 65 % of
trunk km), so they default to 1-2 lanes and the city network is far below real capacity.
`sim/network/lane_audit.py` reads lane counts from aerial imagery crops with a vision pass, but its
held-out precision is 60 % against an 80 % gate, so nothing is applied and
`data/jeddah/jeddah.lanes.net.xml` is never written. Calibration numbers are in
`data/osm/fixes/imagery-eval.json`.

## Acceptance
- Held-out precision at or above 80 % on the existing holdout set, at a coverage stated in
  `docs/lane-audit.md` (same two-read protocol, or a better one that is documented).
- Calibration and holdout sets unchanged, or a new frozen holdout explained in the doc.
- No imagery crops committed (they stay under `data/imagery/` and `docs/img/lane-audit/`, both
  gitignored).

## Pointers
`sim/network/lane_audit.py`, `.claude/skills/lane-audit-imagery/SKILL.md`, `docs/lane-audit.md`
(failure analysis: median islands, worn markings, service roads). Ideas: crop orientation along
the road, larger context, per-class thresholds, a "skip" class for unreadable crops.
