# Lane audit from aerial imagery (Track C)

Status: **blocked - accuracy** after two attempts (2026-10-16). No imagery-derived lane counts were
written to the fix list, and the city network was not rebuilt (`jeddah.net.xml` untouched, no
`jeddah.lanes.net.xml`).

- Attempt 2 (motorway + trunk only, two independent reads): the calibration set found no
  confidence threshold that gives 80 % precision on at least 15 agreed counts (agreed precision
  68.4 %, 26/38). The fresh 30-way holdout scored 82.1 % on its agreed counts (23/28), but under the
  protocol fixed before reading, it can only be scored at a threshold chosen on the calibration set.
  Most of the disagreement between the two sets comes from one road (Prince Majid Road, below).
- Attempt 1 (all four classes, one read): 60 % held-out precision (below the "Attempt 1" heading).

All simulation results remain **synthetic demand, uncalibrated**.

Imagery: Esri World Imagery (Esri, Maxar, Earthstar Geographics, and the GIS User Community),
`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer`, accessed
2026-10-16. Only lane counts would be derived; the example crops below are reproduced with this
attribution (see `NOTICE`). Google imagery was not used (its terms forbid derived datasets).

## Attempt 2: motorway and trunk, two independent reads (2026-10-16)

### Protocol (fixed before any crop was read)

- **Scope.** Motorway and trunk ways only. Audit list: 247 untagged ways of at least 60 m (89
  motorway, 158 trunk), all within the 600-crop cap. Crops in this pass: 50 + 30 + 247 = 327.
- **Two reads.** Every crop is read twice by the `imagery-analyst` subagent, in separate
  calls. Read A sees the crops in set order, 20 per batch. Read B sees them shuffled (seed 7),
  so its batches have different neighbours. Each call gets a folder that holds only the PNG
  crops (`data/imagery/<set>/reads/read-{a,b}/batch-NNN/`): blindness is enforced, not just
  instructed. A count is accepted only if both reads give the same integer **and** both
  confidences are at or above the threshold, i.e. the lower one is (`combine_reads`).
- **Instruction.** Same as attempt 1 (quoted under "Method" below), with one change. The
  bridge-deck clause is removed from the "at most 0.3" list, and this sentence is added at the end:
  "A bridge or flyover deck with clear dashed lines is read like any other carriageway." Each
  prompt was `READ-TAG <set>/<read>/<batch>`, then the folder path, then "Glob *.png in this folder
  and Read every image. Do not open any other file or folder.", the instruction, and "Final reply:
  one JSON object per crop, one per line, nothing else, in your standard format." A copy is kept
  (gitignored) in `data/imagery/v2-prompts/instruction.txt`. Crops, sample points and zoom are
  unchanged (C-007).
- **Calibration set** (chooses the threshold): the 50 motorway and trunk ways of attempt 1's
  calibration (20) and holdout (30) sets, 25 motorway and 25 trunk, read again under the new
  protocol.
- **Fresh holdout**: 30 tagged motorway and trunk ways never used before (seed 3, excluding every
  earlier set and the reviewed fixes). It has 17 motorway and 13 trunk ways, with **at most 5 ways
  per named road and class**. Without that cap, Prince Majid Road would supply 39 of the 54
  candidate trunk ways. Ways cut from one road are not independent samples, and the audit
  population (untagged trunk ways) does not contain that road (C-021).
- **Gate.** The threshold is chosen on the calibration set's agreed counts with the attempt-1 rule
  (lowest confidence giving at least 80 % precision on at least 15 kept crops, and staying at or
  above 80 % at every higher threshold; C-008). The holdout must then reach at least 80 % at that
  threshold, on at least 10 kept agreed crops. All 160 reads (calibration and holdout) were taken
  before anything was scored.

### Results (`data/osm/fixes/imagery-eval.json`, `protocol: two-reads`)

| set | ways | single read exact (A / B) | reads agree | agreed counts correct | threshold | precision at threshold |
|---|---|---|---|---|---|---|
| calibration (re-read) | 50 | 66 % / 54 % | 76 % (38) | **68.4 %** (26/38) | **none** | - |
| fresh holdout | 30 | 80 % / 80 % | 93 % (28) | 82.1 % (23/28) | not reached | (information only) |
| pooled | 80 | - | - | 74.2 % (49/66) | - | - |

Calibration agreed-precision curve (lower read confidence >= t): 0.2 -> 68.4 % (38 kept), 0.5 ->
69.2 % (26), 0.7 -> 68.4 % (19), 0.75 -> 66.7 % (15), 0.8 -> 81.8 % (11), 0.85 -> 100 % (7).
No point reaches 80 % with 15 or more kept, so no threshold was chosen.

By class, agreed counts correct: calibration motorway 19/23 (82.6 %) and trunk 7/15 (46.7 %);
holdout motorway 12/15 (80.0 %) and trunk 11/13 (84.6 %). For information only, holdout
precision at every confidence cut keeping at least 10 agreed crops stays between 80.0 % and 90.9 %
(0.5 -> 20/22).

**Decision: `LANE_AUDIT_V2: blocked - accuracy`.** The brief says to proceed only if held-out
precision on agreed counts reaches 80 %. Read alone, the holdout figure (82.1 %) would meet that.
It was not used, for two reasons fixed before any read:
1. The protocol needs a threshold from the calibration set, and the calibration set produced none.
2. Choosing a threshold after looking at the holdout would turn it into a second calibration set.

Added afterwards, not part of the gate: the two blind sets disagree (68 % vs 82 %) and pool to
74 %. The holdout margin is also thin: 23/28, and one more error would give 78.6 %.
Agreement between reads did raise precision (single reads 54-80 %, agreed reads 68-82 %). It did
not remove systematic errors, because both reads usually make the same mistake on the same crop.
The audit crops are on disk (247, `data/imagery/v2-audit/`), but none were read.

### Where the calibration errors come from

12 agreed calibration counts disagree with the tags:
- **Prince Majid Road (trunk, tagged `lanes=3`): 6.** Both reads say 4 on five ways
  (1432320656, 1432320655, 1024884983, 444383287, 646811886) and 6 on one (41519535). Attempt 1
  gave the same reads (4, and 6 on 41519535), except 646811886, which it read as 5. Of the road's
  13 agreed calibration counts, the other 7 read 3 and match the tag. In the holdout, both reads
  give 3 on four of its five ways and 2 on the fifth (41409169, a tunnel portal). So the road reads
  as 3 on most sections and as 4 on a few. Either those sections really are wider, or the
  imagery or the tag is out of date there, and a tag-based score cannot tell which
  (A-network-004). The tag was edited on 2026-05-17.
- **Motorway: 4 under or overcounts by one lane.** 43172347 reads 3 against tag 4: the
  carriageway has 3 lanes plus a merge lane at the gore. Also 302761815 (3 vs 4), 43172615 (3 vs 4,
  no markings, 0.3) and 46874457 (5 vs 4, 0.3).
- **Trunk connectors: 2.** 1074526712 (tag 1, read 4) is the connector drawn beside the main
  carriageway, already noted in attempt 1. 134839727 reads 3 against tag 2.

Sensitivity check, recorded in the eval file and **not used for the gate**: without Prince Majid
Road, the calibration rule picks threshold 0.45 with 83.3 % on 18 kept crops. That is effectively
a motorway-only threshold: only 6 trunk ways remain, 2 agreed, none correct. The holdout at 0.45 is
87.0 % (20/23), or 85.0 % (17/20) without its Prince Majid ways. The block therefore comes down to
the six Prince Majid sections read as 4 or 6, plus weak evidence on other trunk roads.

### What would unblock it

1. **A person checks the six Prince Majid Road sections** read as 4 or 6 (1432320656,
   1432320655, 1024884983, 444383287, 646811886, 41519535), on site or on dated imagery. The
   number of lanes may vary along the road, so these sections need checking one by one. If only
   the five sections read as 4 really have 4 lanes, fix their tags (or add reviewed fixes) and re-run
   `evaluate-two-reads`. The calibration then reaches 31/38 agreed (81.6 %), and the rule picks
   threshold 0.75 (12 of 15 kept, exactly 80 %, so only just). If the whole road has 4, the seven
   sections read as 3 become errors and the calibration drops to 24/38 (63.2 %). If those sections
   have 3, the method overcounts on wide urban trunk roads, and trunk should stay out of the audit.
   A motorway-only pass then needs its own fresh motorway holdout: it was not pre-declared here,
   and the motorway figures (calibration 19/23, holdout 12/15) were seen.
2. The audit is then ready to run: 26 analyst calls (247 crops x 2 reads), then
   `write-fixes`, `rebuild`, the after-smoke, and the network-effect table below.
3. Not tried: a geometry check that drops samples whose ticks do not fall on the carriageway
   (connector ways such as 1074526712), and dated imagery to settle stale-tag questions.

### Reproduce attempt 2

```bash
uv run python -m sim.network.lane_audit subset-set --set v2-calibration \
    --from-set calibration --from-set holdout --classes motorway,trunk
uv run python -m sim.network.lane_audit sample-calibration --n 30 --seed 3 --set v2-holdout \
    --exclude-set calibration --exclude-set holdout --exclude-set archive/calibration-v1-midpoint \
    --exclude-set v2-calibration --classes motorway,trunk --max-per-road 5
uv run python -m sim.network.lane_audit select-audit --cap 600 --set v2-audit --classes motorway,trunk
for s in v2-calibration v2-holdout v2-audit; do
  uv run --with pillow python -m sim.network.lane_audit crops --set $s
  uv run python -m sim.network.lane_audit prepare-reads --set $s     # read-a / read-b folders
done
# imagery-analyst: one call per batch folder; the prompt starts with "READ-TAG <set>/<read>/<batch>",
# then the folder path and data/imagery/v2-prompts/instruction.txt. Then:
uv run python -m sim.network.lane_audit collect-reads --transcripts <session>/subagents
uv run python -m sim.network.lane_audit evaluate-two-reads --sensitivity-exclude-road "Prince Majid Road"
# only if passed: read v2-audit the same way, then write-fixes, rebuild, smoke (see below)
```

Measured: crops 50 in 6 s (cached tiles), 30 in 82 s (251 tiles), 247 in 411 s (1,236 tiles).
The 10 analyst calls ran in parallel in about 100 s.

---

# Attempt 1: all major classes, one read (2026-10-16)

Status: **blocked - accuracy**. The blind calibration against OSM `lanes` tags did not reach 80 %
precision on held-out ways at any usable confidence threshold. The committed `imagery-eval.json`
now holds attempt 2. Attempt 1's file is in git at commit 403d2af.

## Why

`docs/network-qa.md` found that most major roads in the Jeddah extract have no `lanes` tag, so
netconvert's type defaults apply (`osmNetconvert.typ.xml`: motorway, trunk and primary 2 lanes per
direction, secondary 1). The audit was meant to replace those defaults with counts read from
imagery, but only if accuracy was measured first.

## Inventory (OSM extract 2026-10-14, `data/osm/jeddah.osm.pbf`)

`python -m sim.network.lane_audit inventory` (osmium tags-filter + export, geodesic lengths):

| class | ways | km | untagged ways | untagged km | untagged ways >= 60 m | untagged one-way |
|---|---|---|---|---|---|---|
| motorway | 190 | 450.7 | 92 | 278.1 | 89 | 92 |
| trunk | 243 | 159.2 | 163 | 103.9 | 158 | 163 |
| primary | 927 | 866.1 | 744 | 612.5 | 613 | 705 |
| secondary | 1,651 | 1,496.3 | 1,471 | 1,259.8 | 985 | 1,120 |
| **total** | 3,011 | 2,972.3 | 2,470 | 2,254.3 | 1,845 | 2,080 |

76 % of major-road km have no `lanes` tag. The capped audit list (1,500 ways: 89 motorway, 158
trunk, 610 primary, 643 secondary, longest first; the three King Abdulaziz Road ways under reviewed
fixes FIX-0001..0003 are excluded) is in `data/imagery/audit/ways.json` (gitignored).

## Method

- **Sample point.** One per way: the midpoint of the way's longest straight segment, with that
  segment's bearing (decision C-007). The first attempt used the geodesic midpoint of the whole
  way. That put about a quarter of the samples on junctions, tunnel portals or curves.
- **Crop.** Zoom 19 (0.278 m/px at 21.5 N), tiles stitched around the point, rotated so the
  direction of travel points up, 512 x 512 px cropped and upscaled 2x (0.139 m/px in the PNG). Red
  ticks at the top and bottom edges mark the sampled carriageway. A caption gives the way id,
  class, one-way/two-way and bearing; the lane tag is never shown, so the reading is blind.
  Tiles are fetched one request at a time with a 0.2 s delay and a descriptive User-Agent, and
  cached under `data/imagery/tiles/`. The run fetched 3,274 tiles (about 3 per second).
- **Reading.** Done by the `imagery-analyst` subagent in batches of 20, using the same instruction
  for calibration, holdout and audit (below). The analyst returns strict JSON per crop.
- **Truth.** The OSM tags: `lanes` on one-way ways; on two-way ways `lanes:forward`, or half an even
  `lanes` (A-network-004). 98 of the 100 sampled tagged ways are one-way; the 2 two-way ways were read correctly.
- **Threshold rule.** Choose the lowest confidence threshold whose precision is at least 80 % with
  at least 15 crops kept. Precision must also stay at or above 80 % at every higher threshold that
  still keeps 15 crops, so a lucky point on the curve is never chosen (C-008). The threshold is
  chosen on the 40-way calibration set and then checked on a disjoint 60-way holdout. The audit
  runs only if the holdout precision at that threshold is also at least 80 % (C-009).

Analyst instruction (verbatim, after the folder path):

> Each crop is rotated so the sampled road's direction of travel points UP. The sampled carriageway
> is the one under the red ticks at the top and bottom edges (centre column, red arrowhead at the
> top). Count the through lanes for traffic travelling UP on that carriageway only. On a two-way
> road without a median, count only the lanes right of the centre line. Exclude shoulders, parking,
> bus bays, diverging slip roads and ramps, frontage/service roads beyond a separator, and the
> opposite carriageway. Base the count on lane markings (dashed lines between lanes: lanes = dashed
> lines + 1) and on vehicles driving side by side. Confidence must be the honest probability that
> your integer is exactly right: clear dashed lines along the carriageway under the ticks:
> 0.7-0.95; markings partly hidden by shadows, trees or traffic: 0.4-0.7; no visible markings
> (estimate from width only), the ticks on a junction, roundabout, tunnel portal, bridge deck,
> construction, or no road under the ticks: at most 0.3, and say why.

## Results (`data/osm/fixes/imagery-eval.json`)

| set | ways | exact agreement, all crops | within +/-1 | threshold | kept | precision at threshold |
|---|---|---|---|---|---|---|
| calibration v1 (whole-way midpoint, earlier prompt) | 40 | 70.0 % | 95.0 % | 0.6 (same rule) | 15 | 80.0 % |
| calibration v2 (longest segment) | 40 | 70.0 % | 95.0 % | **0.5** | 18 | **83.3 %** |
| holdout (disjoint, seed 2) | 60 | 58.3 % | 88.3 % | 0.5 (from calibration) | 20 | **60.0 %** |
| pooled v2 + holdout | 100 | 63.0 % | 91.0 % | none reaches 80 % with >= 15 kept | - | - |

v1 figures come from the gitignored archive `data/imagery/archive/calibration-v1-midpoint/`; the
committed `imagery-eval.json` holds v2, the holdout and the pooled set. The calibration pass was
itself marginal: 15 of 18 correct at 0.5, so one more error would have meant 77.8 %.

Exact agreement by class over all crops (calibration n=10 per class / holdout n=15 per class):
motorway 70 % / 93 %, trunk 70 % / 33 %, primary 80 % / 40 %, secondary 60 % / 67 %. At the 0.5
threshold, the holdout kept 6/6 motorway crops correct and 3/3 secondary, but only 1/8 trunk and 2/3
primary.

On the pooled 100, the highest thresholds show precision 0.80 -> 69.6 % (23 kept), 0.85 -> 91.7 %
(12 kept) and 0.90 -> 100 % (2 kept). Only 12 % of crops reach 0.85, which is too few for both the
rule and the audit.

**Decision: `LANE_AUDIT: blocked - accuracy`.** The calibration v2 threshold did not hold on the
holdout (60 % vs the 80 % requirement). `imagery-lanes.yaml` was not written, `jeddah.lanes.net.xml`
was not built, and the audit stopped after 115 of 1,500 crops; none of them was read.

## Failure analysis

1. **Confidence does not separate right from wrong.** The 50 crops rated at or below 0.3 were 64 %
   correct, about the same as the crops rated 0.5 and above (pooled 71 % at 0.5). With this signal,
   no threshold can buy precision.
2. **Overcounting on wide urban trunk roads.** 19 of the 25 holdout errors are overcounts (+1: 12,
   +2 or more: 7). Prince Majid Road (ref 70, tagged `lanes=3`, edited 2026-05-17) dominates the
   trunk sample: it is 58 of the 79 comparable tagged trunk ways, so it supplied 19 of the 25
   sampled trunk ways (9 calibration, 10 holdout). In the holdout, four of its ways were read as 4
   at 0.70-0.80 (1432320656, 444383287, 1432320655, 1024884983) and one as 6 at 0.80 (41519535).
   That is 5 of the 8 errors among the 20 crops kept at the threshold (`1432320656.jpg` shows three
   dashed lines, i.e. 4 lanes). Either the tag or the imagery is out of date, and a tag-based
   metric cannot tell which. Without Prince Majid Road the holdout is 11/14 = 78.6 % at the
   threshold, still under 80 %, so the block does not rest on this one road.
3. **Geometry vs carriageway.** Two trunk ways tagged `lanes=1` (1074526712, 715 m; 1076102293,
   132 m) were both read as 4. On 1074526712 (`1074526712.jpg`) the ticks fall on a hatched strip
   beside a 4-lane carriageway, and the analyst counted that carriageway. The way looks like a
   connector drawn next to the main road. 1076102293 was not inspected by eye.
4. **Tags that look wrong.** For example, secondary 208082834 is tagged 2, but the crop shows two
   clear dashed lines, so 3 lanes. Motorway 43172347 is tagged 4, but the crop shows 3 lanes plus
   a merge lane at the gore. These count as errors under the blind rule, so the measured precision
   is a lower bound when tags are wrong (A-network-004). Visual adjudication was not used to change
   the score.
5. **Hard scenes.** Tunnel portals, roundabouts, flyover decks, deep building shadows and fresh
   asphalt without markings. The analyst lowered confidence on these as instructed, but its
   low-confidence guesses were often right anyway (point 1).
6. **The prompt's bridge-deck cap.** Capping bridge decks at 0.3 suppressed several correct,
   clearly marked reads (e.g. motorway 659909045 and secondary 1132416433, both correct at 0.3). It cost coverage, not precision, and the
   prompt was kept unchanged so that calibration and holdout stay comparable.

## Example crops (`docs/img/lane-audit/`, pred vs tag, analyst confidence)

The crops are Esri World Imagery and are no longer committed (integration, licence); regenerate them locally with the crop step of `sim/network/lane_audit.py`.

| crop | class | tag | read | conf | note |
|---|---|---|---|---|---|
| ![](img/lane-audit/1132416434.jpg) 1132416434 | motorway (Al Harameen Rd) | 4 | 4 | 0.85 | correct, clear dashes |
| ![](img/lane-audit/1486013090.jpg) 1486013090 | motorway | 4 | 4 | 0.85 | correct |
| ![](img/lane-audit/865489283.jpg) 865489283 | motorway | 4 | 4 | 0.90 | correct (holdout) |
| ![](img/lane-audit/338704468.jpg) 338704468 | secondary | 3 | 3 | 0.85 | correct, service road excluded |
| ![](img/lane-audit/208082834.jpg) 208082834 | secondary | 2 | 3 | 0.80 | tag looks wrong (3 lanes visible) |
| ![](img/lane-audit/1432320656.jpg) 1432320656 | trunk (Prince Majid Rd) | 3 | 4 | 0.75 | imagery shows 4; stale tag or imagery |
| ![](img/lane-audit/1074526712.jpg) 1074526712 | trunk | 1 | 4 | 0.80 | connector way beside the main carriageway |
| ![](img/lane-audit/43172347.jpg) 43172347 | motorway | 4 | 3 | 0.80 | merge lane at the gore |
| ![](img/lane-audit/444205771.jpg) 444205771 | trunk | 3 | 3 | 0.10 | tunnel portal: low confidence, guessed right |
| ![](img/lane-audit/31134732.jpg) 31134732 | primary | 2 | 2 | 0.15 | roundabout under the ticks |
| ![](img/lane-audit/646811886.jpg) 646811886 | trunk | 3 | 5 | 0.40 | deep building shadow |
| ![](img/lane-audit/659909045.jpg) 659909045 | motorway | 4 | 4 | 0.30 | bridge deck capped at 0.3, read correct |

## Network effect

Not measured, because no imagery fixes passed. Same-session baseline on the unchanged network
(`python -m sim.runner --smoke --tier A --seed 1 --net data/jeddah/jeddah.net.xml`, run
`smoke-A-s1-5b8a19d3-ab76d081`): 156,126 edges, 20,952.88 lane-km, 18,001 random trips loaded,
26 teleports (all jam) = 0.144 %, SUMO wall time 22.4 s for 3,600 s (real-time factor 160),
demand generation 542 s. This reproduces M1 exactly (same network hash, config hash, teleports).

## What would unblock it

- **Human adjudication.** Start with Prince Majid Road (5 of the 8 confident holdout errors). A
  person reviews the 37 disagreements among the 100 calibration and
  holdout crops against current imagery or a site visit, and decides tag-wrong vs read-wrong. If
  the tags are the main error source, re-score against adjudicated truth with the same rule.
- **Motorway-only audit.** Motorways read 21/25 correct overall (84 %; holdout 14/15). This
  subgroup was found after the fact, so it needs its own fresh holdout of at least 30 tagged
  motorway ways before any motorway fixes are written. The audit list has 89 untagged motorway ways
  (278 km).
- **Better confidence.** Two independent analyst passes per crop, accepting only agreeing reads,
  and possibly two sample points per way. This must be re-validated on a fresh holdout. Drop the
  bridge-deck cap.
- **Geometry check.** Skip samples whose ticks do not fall on asphalt (connector ways, gores).
- **Enforced blindness.** The analyst was blind by instruction only: `ways.json` (with the tags)
  sits beside the `crops/` folder and the analyst can read files. No sign that it did, but a re-run
  should give the analyst a folder with crops only.

## Reproduce

```bash
uv run python -m sim.network.lane_audit inventory
uv run python -m sim.network.lane_audit sample-calibration --n 40 --seed 1
uv run python -m sim.network.lane_audit sample-calibration --n 60 --seed 2 --set holdout --exclude-set calibration
uv run --with pillow python -m sim.network.lane_audit crops --set calibration
uv run --with pillow python -m sim.network.lane_audit crops --set holdout
# imagery-analyst subagent: 20 crops per call, instruction above; JSON lines saved to
# data/imagery/<set>/results/batch-NNN.jsonl
uv run python -m sim.network.lane_audit evaluate     # -> data/osm/fixes/imagery-eval.json
# only if the eval passed:
uv run python -m sim.network.lane_audit select-audit --cap 1500
uv run --with pillow python -m sim.network.lane_audit crops --set audit
uv run python -m sim.network.lane_audit write-fixes  # -> data/osm/fixes/imagery-lanes.yaml
uv run python -m sim.network.lane_audit rebuild      # -> data/jeddah/jeddah.lanes.net.xml
uv run python -m sim.runner --smoke --tier A --seed 1 --net data/jeddah/jeddah.lanes.net.xml
```
The analyst readings are not bit-reproducible; the committed `imagery-eval.json` holds every
reading (`rows`, `holdout.rows`) so the scoring can be recomputed.
