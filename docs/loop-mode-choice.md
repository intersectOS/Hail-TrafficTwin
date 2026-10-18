# Loop mode choice: replacing the assumed shift share (Track H)

> **Synthetic demand, uncalibrated.** Every number here comes from the 10 % weekday synthetic
> population (seed 1) and its uncalibrated, gridlock-affected Tier A baseline
> (`baseline-weekday-f0.1-s1-e5f1906a-65fac195-f124c5`, 0.51 teleports per vehicle). The
> coefficients come from the literature and are not estimated for Jeddah. Read the ridership as a
> structured sensitivity, not a forecast.

## Question

Track D's Loop result (`docs/loop.md`) rests on an assumed shift share alpha (A-loop-009): a fixed
share of every eligible car tour moves to the Loop, whatever the Loop's speed, wait or fare. Its
quality flag showed that 70 % of the shifted riders would be slower door to door than by car under
the measured service. This page replaces alpha with a binary car-vs-Loop logit, so that ridership
becomes an output that responds to the service, and quantifies what that does to the result.

## Commands

```
uv run python -m sim.loop.mode_choice sweep --source-root ../trackD   # offline, ~1.5 min, no SUMO
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --demo
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --demo --service vendor
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1   # city run
uv run pytest tests/test_loop_mode_choice.py
```

`--source-root` points at the checkout that holds the starting baseline and its caches (read
only; after integration this is the main checkout, i.e. the default). Outputs:
`sim/loop/results/mode_choice.json` (summary per candidate and service),
`mode_choice_sweep.csv` (all 108 coefficient sets), `mode_choice_pairs_<id>_<service>.csv`
(shift share per station pair and hour). A city or demo policy run with `mode_choice:` also
writes `loop_mode_choice_pairs.csv` and `loop_mode_choice_legs.parquet` in its run directory and
a `mode_choice` block in `loop_report.json`.

## Method

**Who can choose.** The same eligible tours as Track D: car-driver and ride-hail tours whose every
leg runs between two different stations of one line (both ends within 1.5 km, at least 2 km apart).
The offline sweep rebuilds them from the starting baseline's plan and reproduces Track D exactly:
4,772 eligible C1 tours (Track D: 4,772), and with Track D's time-competitive rule 7,240 / 11,760
riders per day under measured / vendor service (Track D's runs: 7,240 / 11,760).

**Generalised time per leg (minutes).**

| | car (car driver / ride-hail) | Loop |
|---|---|---|
| in-vehicle | baseline simulated duration + departure delay of that same vehicle | loading stop 30 s + down and up ramps + tunnel ride at the service speed |
| out-of-vehicle | car: 3 min parking search; ride-hail: 5 min pickup x wait weight | walk access + egress (crow distance x 1.3 at 4.5 km/h) x walk weight; station wait (+ queue) x wait weight |
| money / VOT | car: fuel SAR 0.22/km; ride-hail: SAR 6.20 + 1.36/km + 0.43/min, min SAR 12 | fare per leg |
| constant | - | ASC (minutes) |

Utility V = beta_ivt x generalised minutes. A tour keeps one mode for all its legs (Track D rule),
so it chooses on the sum over its legs: P(Loop) = 1 / (1 + exp(beta x sum(Loop - car))). The tour's
uniform draw is the alpha path's own hashed draw (`loop_shuttle:shift`), so P = alpha everywhere
selects exactly the alpha path's tours (tested). A tour with a leg that has no baseline car time
(20 of 9,855 C1 legs) is not evaluated and stays by car.

**Capacity and queueing.** Two kinds of resources per hour of station arrival: the station pair
(Vegas measured 1,355 pax/h, A-loop-006; vendor 4,800, A-loop-007) and each tunnel segment
direction a leg traverses: 3600 / headway shuttle movements x 0.95 riders per movement = 644 / 2,280
riders/h (measured / vendor). The 0.95 is what Track D's C1 runs achieved (0.83-1.03): shuttles
leave part-full after the 3 min dispatch window and 0.3 empty repositioning trips share the
tunnel (A-loop-030). When expected demand D exceeds capacity C, riders on that resource face a
deterministic queue, mean (D - C) / (2 C) h (uniform arrivals within the hour, at most 60 min),
weighted as wait and fed back into the choice by successive averages (25 iterations). After the
draw, tours are admitted in order of first station arrival; a tour shifts only if every resource
of every leg still has room. Riders above capacity do not shift. Each central result is then
passed through Track D's own shuttle dispatch and capacity flags (`capacity_flags`) as a check.

**Service cases** (A-loop-021): *measured* = 90 km/h, 12.5 min station wait, 5.3 s headway (1,355
pax/h per pair); *vendor* = 160 km/h, 2 min wait, 1.5 s headway.

## Coefficients and sources

All in `sim/loop/config/mode_choice.yaml`, registered A-loop-021..030 in
`docs/assumptions-trackH.md`; citations checked 17 Oct 2026 in `docs/data-sources-trackH.md`.

| coefficient | central | sweep | source |
|---|---|---|---|
| beta_ivt (utility per min) | -0.025 | -0.015 / -0.02 / -0.05 (one at a time) | NCHRP 716 Table 4.8: home-based work -0.019 to -0.044, non-work flatter; Riyadh car-vs-Metro SP logit: car -0.022, Metro -0.029 (Youssef et al. 2021) |
| value of time | SAR 40/h | 20 / 40 / 80 | repo convention A-pol-042; GASTAT 2025 wages ~SAR 64/h Saudi, ~23/h expatriate; no Saudi VOT study |
| wait weight | 2.0 | 1.5 / 2.0 / 2.5 | NCHRP 716 (mean 2.1), Wardman 2004 (1.76), Wardman et al. 2026 (1.72) |
| walk weight | 2.0 | 1.5 / 2.0 / 3.0 (one at a time) | same sources 2.2 / 1.68 / 1.67; no significant hot-climate effect in the 2026 meta-analysis; Riyadh SP implies ~6 (upper bound) |
| Loop ASC | 10 min penalty per leg | 0 / 10 / 20 (+30 one at a time) | judgement; constants are not transferable (NCHRP 716); no Gulf or Loop estimate |
| fare | SAR 5 per leg | 0 / 5 / 10 / 20 | Riyadh Metro SAR 4 per 2 h; Jeddah bus SAR 3.45; LVCC Loop free; Vegas Loop USD 4.25 |
| car side | +3 min parking; SAR 0.22/km; ride-hail Uber KSA 2023 fares, 5 min pickup | - | Shoup 2006/2011; Aramco Oct 2026; Uber KSA blog Mar 2023 |

## Results

Riders per weekday (city-equivalent, both directions). *Grid range* = minimum / median / maximum
over the 108 sets VOT x wait weight x ASC x fare. *Fixed alpha* = Track D's alpha 0.5 runs (C1 also
alpha 0.3). *Time-competitive* = Track D's rule (only tours faster by Loop shift, then alpha 0.5).

| candidate | tunnel-km | eligible riders | service | mode choice, central | grid range (min / median / max) | fixed alpha | time-competitive | capped by capacity | peak segment riders/h (capacity) | Track D segment exceedance check |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 Al-Salamah - KAU | 17.9 | 98,550 | measured | **19,530** | 10,910 / 18,530 / 31,910 | 28,820 (0.3), 47,870 (0.5) | 7,240 | 1,480 | 640 (644) | 9.2 % |
| | | | vendor | **31,450** | 18,750 / 29,380 / 48,540 | (same) | 11,760 | 0 | 1,180 (2,280) | 0 % |
| C2 Ar Ruwais - Ar Rughamah | 10.7 | 37,810 | measured | **9,000** | 4,020 / 8,180 / 15,680 | 18,790 | 2,980 | 0 | 600 (644) | 0 % |
| | | | vendor | **13,560** | 7,340 / 12,250 / 19,960 | | 5,060 | 0 | 740 (2,280) | 0 % |
| C4 Al Bawadi - Al-Balad | 16.2 | 61,470 | measured | **6,610** | 2,160 / 5,740 / 16,620 | 30,810 | 1,360 | 0 | 410 (644) | 0 % |
| | | | vendor | **10,910** | 5,140 / 9,950 / 22,080 | | 2,540 | 0 | 550 (2,280) | 0 % |
| C6 Al Jamiah - Tahlia / Al Andalus | 17.5 | 37,060 | measured | **4,180** | 1,520 / 3,710 / 9,620 | 18,400 | 940 | 0 | 250 (644) | 0 % |
| | | | vendor | **6,520** | 3,160 / 6,000 / 13,120 | | 1,920 | 0 | 380 (2,280) | 0 % |

Implied shift share of eligible riders (central): C1 19.8 % measured / 31.9 % vendor; C2 23.8 /
35.9 %; C4 10.8 / 17.7 %; C6 11.3 / 17.6 %. Mean generalised time, car vs Loop: C1 71 vs 115 min
(measured) and 90 min (vendor); C4 45 vs 115 / 92 min. Of the admitted C1 riders, 37 % (measured)
and 30 % (vendor) are slower door to door by clock time than by car (Track D's alpha 0.3: 70 %);
the logit still admits some slower riders because of the taste spread its scale implies.

**Fare** (C1, other coefficients central): SAR 0 / 5 / 10 / 20 gives 21,560 / 19,530 / 18,070 /
14,990 riders (measured) and 35,390 / 31,450 / 28,290 / 22,150 (vendor). Over the full grid by
fare, measured: SAR 0 14,210-31,910; SAR 5 13,270-27,870; SAR 10 12,570-24,170; SAR 20
10,910-18,230.

**One at a time** (C1 measured, central 19,530): walk weight 1.5-3.0 gives 23,610-13,550 (largest
lever); VOT 20-80 gives 24,270-16,930; beta -0.015 to -0.05 gives 24,030-17,100; ASC 0-30 min gives
22,250-15,650; fare 0-20 gives 21,560-14,990; wait weight 1.5-2.5 gives 20,820-18,650. Under the
vendor service the wait weight hardly matters (2 min wait; the ride-hail pickup wait it also
weights works the other way).

**Per pair and hour** (`mode_choice_pairs_C1_measured.csv`): the shift share is highest in the
evening (18:00-22:00, 23-29 % of eligible riders), when baseline car times are worst, and 8-10 % at
05:00 and 10:00-11:00. Short pairs at the line ends (stations 0-1, 1-2, about 5 %) shift least; the
long pairs into KAU (5-7, 6-7, 14-19 %) most. Capacity binds only for C1 under the measured
service: a tunnel segment in the evening peak (queue up to 9 min) caps 1,480 riders a day; the
grid's worst case (fare 0, VOT SAR 20, wait weight 1.5, ASC 0) caps 4,920 riders, with queues up
to 21 min.

**Demo window** (`--demo`, 2.3 km line, stations ~1 km apart): 24 (measured) and 58 (vendor) of
286 eligible riders shift; the run goes end to end through the same transform, shuttles and
report as the alpha path.

## What changes in the recommendation

What can be said without the city run:

1. **Measured service (the recommended case).** Track D recommended C1 shuttle mode with
   ridership capped by the measured capacity, represented by alpha 0.3 (28,820 riders/day). The
   logit gives 19,530 (grid 10,910-31,910): about two thirds of that, three times the
   time-competitive 7,240, and still capacity-bound on a tunnel segment in the evening peak (Track
   D's segment-exceedance gate 9.2 %, just inside its 10 % limit). C1 stays well above the 5,000
   trips/day credit floor (A-loop-020) over the whole grid. Road relief can't be read off the
   ridership: Track D's runs at 7,240 and 28,820 riders gave -150 and 57,671 / 69,027 VHT/day,
   but the replicate noise is +/- 34,000 per comparison and meso delay is strongly non-linear near
   gridlock. The C1 city runs below settle it.
2. **Vendor service.** With 160 km/h and a 2 min wait the logit gives 31,450 (18,750-48,540), more
   than alpha 0.3 and with no capacity binding (segment peak 52 % of the 1.5 s headway capacity).
   The vendor case is the only one in which the Loop carries the ridership Track D assumed.
3. **Corridor order.** The logit cuts C4 and C6 much harder than C1 and C2. Against the alpha 0.5
   ridership it keeps 41 % on C1 and 48 % on C2, but only 21 % on C4 and 23 % on C6: their
   eligible car trips are shorter (45-49 min generalised against 71-73), so walking and waiting
   weigh more. Ridership per tunnel-km is C1 1,090, C2 840, C4 410 and C6 240 (measured). This
   supports Track D's choice of C1 (and C2 as the per-km runner-up) and weakens the case for C4 and
   C6, which already rested on large seed-2 values. Under the measured service C6 falls below the
   5,000 trips/day credit floor (4,180).
4. **Fare.** Within SAR 0-20 the fare moves C1's ridership by about 30 % (measured) and 37 %
   (vendor); it does not change which corridor ranks first.

## City re-evaluation (for the coordinator)

No city run was started by this track. The commands, from a checkout whose `runs/` holds the
starting baseline `baseline-weekday-f0.1-s1-e5f1906a-65fac195-f124c5` and the seed-2 replicate
`loop_noise_baseline_s2` (both in `.worktrees/trackD/runs/`; the main checkout's
`baseline-...-65b0f3` has a different config hash, so the runner would otherwise build a new
baseline, ~2 h):

```
# priority: C1, both services, both sim seeds (4 runs, ~10.6 min each = ~45 min)
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --sim-seed 2
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --service vendor
uv run python -m sim.loop.evaluate --mode-choice sim/loop/config/mode_choice.yaml --ids C1 --service vendor --sim-seed 2
# then C2, C4, C6 the same way (--ids C2,C4,C6; 12 runs, ~2.1 h)
```

Results merge into `sim/loop/results/evaluation_mode_choice.json` (Track D's `evaluation.json` is
untouched); run ids `loop_c1_mcmeasured_<hash>` and `loop_c1_mcvendor_<hash>_v160_capengineering`.

### Done on network v2 (integration pass 6, 2026-10-17)

*Synthetic demand, uncalibrated.* C1, measured service, seed 1, on the v2 network (run `runs/v2/loop_c1_mcmeasured_f26ed359`, results
`runs/v2/evaluation_mode_choice.json`; `uv run python -m scripts.pass6_v2 run loop_mc`): **14,630
riders/day** (v1 offline central 19,530; 600 capped by capacity; expected 15,017), mean P(Loop) 0.148
over 4,920 eligible tours, congestion relief **38,718 VHT/day** for the remaining vehicles, city VHT
-46,684/day (-2.4 %), AM-peak road delay -4.8 %, 49 % of admitted riders slower than by car at the mode-choice step
(52 % of simulated riders);
teleports per vehicle 0.283 -> 0.265 (quality flag). The v2 car times are shorter than v1's (the
"gridlock-affected baseline" limitation below is smaller on v2, not gone), which lowers ridership.
Not run on v2: the vendor service, seed-2 replicates and C2/C4/C6 (commands above, with
`--runs-dir`-style isolation: use `scripts/pass6_v2.py` as the pattern, because `sim.loop.evaluate`
writes to `runs/`).

## Limitations

- **Transferred coefficients.** No Jeddah or Saudi revealed-preference data; beta, the
  multipliers and the ASC come from US/UK meta-analyses and one small Riyadh stated-preference
  survey. One value of time for everyone (no income or nationality segments), although Saudi and
  expatriate wages differ by about 3x.
- **Car times from a gridlock-affected baseline.** Car door-to-door time is the baseline's
  simulated duration plus departure delay, with 0.51 teleports per vehicle; the long car times
  favour the Loop. No feedback: freed road space does not make the car faster for the next
  chooser (no equilibrium between choice and congestion).
- **No induced demand**, no new trips, no destination or time-of-day change; only tours already
  made by car or ride-hail can shift. Car passengers, buses and walkers do not choose.
- **No transfers, one line per tour**, every leg station to station (Track D rule); a tour with
  one non-eligible leg cannot shift. Walk access only (no drop-off or park-and-ride at stations).
- **Single weekday**, seed 1, one 10 % sample: each sampled rider stands for 10, so small pair-hour
  counts are coarse. The tables report the drawn riders (what a run simulates); the sum of
  probabilities differs by a median 1-3 % for C1, C2 and C6 and 7-10 % for C4 (C4 measured: 6,610
  drawn vs 5,910 expected), all in `mode_choice_sweep.csv`.
- **Capacity**: deterministic hourly queue, first-come admission; riders above capacity do not
  shift (they do not wait longer or change hour). Segment capacity uses the riders per shuttle
  movement Track D achieved (0.95); better pooling would raise it.
- **Passengers are not simulated** as persons in SUMO (as in Track D); the logit uses pre-run
  estimates of the Loop time, the same ones as Track D's time-competitive filter.
- Ride-hail fares are Uber's 2023 recommended fares; Careem and current fares are not verified.
