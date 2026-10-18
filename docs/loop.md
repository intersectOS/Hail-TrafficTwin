# Jeddah Loop tunnels: siting and optimal policy (Track D)

> **Synthetic demand, uncalibrated.** Every number on this page comes from a synthetic population
> on an uncalibrated Tier A (mesoscopic) model of Jeddah, 10 % weekday sample, seed 1. The
> baseline is gridlock-affected in both peaks (TA-011, 0.51 teleports per vehicle). Read the
> results as a comparison of corridors and policies under stated assumptions, not as a forecast.

## Question

Boring Company style "Loop" systems are small-bore (3.6 m) twin tunnels with surface stations and
station-to-station electric vehicles (Las Vegas: Tesla Model Y driven by staff; Dubai: RTA
contract, Feb 2026, 6.4 km pilot and 22.2 km full system). Which Jeddah corridors would relieve the
most congestion, and which way of running them (shuttle service or private-EV toll tunnel, speed,
toll) gives the most relief per riyal?

## Commands

```
uv run python -m sim.loop.site                                   # candidates + map (seconds)
uv run python -m sim.loop.evaluate --candidates sim/loop/candidates.yaml   # one city run each
uv run python -m sim.loop.evaluate --sim-seed 2                  # seed-2 replicates
uv run python -m sim.loop.optimise                               # greedy + sweep, fills this page
uv run python -m sim.loop.run loop_demo --demo                   # demo policy, demo window, ~10 s
uv run python -m sim.loop.run loop_recommended                   # recommended policy, city 10 %
```

Runs go to `runs/<policy id>/` (`loop_report.md`, Track A's `policy_report.md`). Machine-readable
results: `sim/loop/candidates.yaml`, `sim/loop/results/*.json|csv`.

## Model

**Tunnel network** (`sim/loop/network.py`). For an alignment (ordered stations), one tunnel node
under each station, one single-lane tunnel edge per direction between consecutive stations
(length = crow distance x 1.15), and a down ramp and an up ramp (150 m, 40 km/h) per station to
the nearest non-signalised junction with main-road edges in the network's main strongly connected
component. Intermediate stations are bypassed by through vehicles (express service). The network is
written under a new name (`data/jeddah/jeddah.loop-<key>.net.xml.gz`); the base network is not
touched. Shuttle mode admits only the shuttle class (SUMO `custom1`); private-EV mode admits
passenger cars and connects the surface approaches to the down ramps.

**Capacity.** SUMO meso has no per-vehicle headway, so tunnel and ramp edges carry a meso edge type
with their own headway, scaled by 1/sample like every other headway (A-sim-101). Two scenarios:
*measured*, 1,355 passengers/h per station pair (Las Vegas, July 2021), i.e. one shuttle every
5.3 s at 2 passengers; *engineering*, one vehicle every 1.5 s (brief range 1-2 s), i.e. 4,800
passengers/h per direction at 2 passengers (vendor side, not demonstrated).

**Shuttle mode** (`loop_shuttle`). A car-driver or ride-hail tour shifts if every leg runs between
two different stations of one line (origin within R_o, destination within R_d, at least 2 km
apart); a share alpha of those tours shifts (hashed draw per tour, so alpha sweeps are nested).
Their car trips are removed; passengers reach the station after a walk and fill shuttles of 2 in
arrival order per station pair (a shuttle leaves with its last passenger, 30 s loading stop), plus
0.3 empty repositioning trips per loaded trip. Passengers are not simulated as persons: their
door-to-door time is estimated after the run (walk, wait, simulated shuttle trip) and compared
with the same leg by car in the baseline. Quality flags: share of shifted passengers above the
station-pair capacity in their hour; tunnel segment utilisation; share of riders slower than by
car.

**Private-EV mode** (`loop_private`). The tunnels are open to passenger cars; the toll per entry
becomes a routing penalty (toll / value of time, SAR 40/h) on the down ramps. Every car whose ends
lie within 2.5 km of two different stations gets a one-shot route on the baseline's congested
travel times (Track A's incremental routing, TA-014) and uses the tunnel only if it is faster
including the toll. Because this re-routes baseline vehicles, each run comes with Track A's
matched control (TA-018): the same cars re-routed on the base network without the tunnel. The
headway limit applies in the simulation; one-shot routing does not see it, so a popular free
tunnel queues at its portals.

**Siting** (`sim/loop/site.py`). Desire lines are district-to-district vehicle trips x baseline
delay per trip; top corridors are street names ranked by the day's time loss. Station sites are
delay-weighted trip-end hot spots (750 m grid, at least 1.5 km apart); every pair of sites 6-25
tunnel-km apart becomes a straight alignment with 4-8 stations at 1.5-3 km, intermediate stations
snapped to the best site within 700 m, scored by the baseline delay of trips both of whose ends
fall within 1.5 km of two different stations. Eight candidates are chosen by captured delay per
tunnel-km with an overlap rule. KAIA airport, Al Balad/Corniche, Tahlia/Al Andalus and KAU are
added as sites without any bonus: an anchor not covered by a data-driven pick gets its best
alignment as an explicit test candidate.

**Objective: congestion relief.** City VHT falls simply because shifted cars disappear; counting
their hours as "saved" would reward removing trips, not relieving traffic. The decision metric is
therefore *congestion relief*: the hours (travel time plus departure delay) saved by the vehicles
that are on the road in both runs (same vehicle, shuttles excluded), per USD M of capex. Riders'
extra door-to-door time against their own baseline car trip is reported as net person-hours
(relief minus riders' extra time). City VHT saved is shown for reference.

**Evaluation and optimisation.** Each candidate is one city policy run (shuttle, alpha 0.5,
90 km/h, measured capacity) against the baseline, and again with simulation seed 2 against the
seed-2 baseline replicate (Track A's replicate machinery): single runs near gridlock are noisy
(a sim-seed change alone moves city VHT by about 1 %). Candidates are ranked on the two-seed mean
relief per tunnel-km. The greedy step takes them in that order within the 25 km budget, skipping
overlaps and any candidate whose two seeds disagree in sign or whose mean is inside the two-seed
noise; if one corridor alone relieves more than the whole per-km greedy set (the budget left
after the first pick may fit nothing), it is taken instead (standard knapsack correction). The
selected set is run together. The sweep varies the levers (mode, tunnel speed, toll) and,
separately, the uncertainties (alpha, access radius, capacity, and a time-competitive shift in
which only legs faster by Loop than by car may shift, under measured and vendor speeds and
waits). The recommendation is the lever setting with the most relief per USD M at central
assumptions that passes the quality gate (pair and tunnel-segment capacity exceedance at most
10 %, teleports not worse than the comparison beyond the replicate's change, positive relief).

## Candidate corridors

![Loop candidates](img/loop-candidates.png)

Top desire lines (city-equivalent vehicle trips and delay hours per weekday, both directions;
full list `sim/loop/results/desire_lines.csv`):

| districts | crow km | trips/day | delay h/day | delay min/trip |
|---|---|---|---|---|
| Al Naseem - Al Faiha'a | 3.0 | 19,620 | 11,340 | 34.7 |
| Al Naseem - As Sulimaniyah | 2.5 | 18,810 | 10,929 | 34.9 |
| Al Naseem - Al Faisaliyyah | 6.9 | 11,570 | 9,568 | 49.6 |
| Al-Salamah - Al Naseem | 11.3 | 8,140 | 9,101 | 67.1 |
| KAIA airport district - Ar Rughamah | 23.7 | 8,150 | 8,900 | 65.5 |
| Al Naseem - Bani Malik | 1.7 | 20,100 | 8,633 | 25.8 |

Top time-loss corridors (edgedata, city-equivalent vehicle-hours of time loss per weekday):
Al Haramain Road 293,778; Madinah Road 262,727; Prince Majid Road 129,188; King Abdullah Road
62,724; King Fahd Road 59,183; Al Lith Road 56,841; King Abdulaziz Road 49,393; Palestine Road
30,953; Prince Mohammed bin Abdulaziz (Tahlia) Street 29,343 (`sim/loop/results/corridors.csv`).
Short desire lines (under 2 km crow-fly) cannot shift to a station-to-station Loop.

<!-- LOOP:candidates -->
| id | alignment | origin | tunnel-km | stations | station sites (district or anchor) | captured delay h/day (siting score) | capturable trips/day |
|---|---|---|---|---|---|---|---|
| C1 | Al-Salamah - King Abdulaziz University | data | 17.9 | 8 | Al-Salamah · Al-Salamah · Al Faisaliyyah · Al Aziziyah · Al-Musharifah · Al Naseem · Al Naseem · King Abdulaziz University | 62,845.3 | 103,690 |
| C2 | Ar Ruwais - Ar Rughamah | data | 10.7 | 5 | Ar Ruwais · Al Wurud · Al Faiha'a · Al Naseem · Ar Rughamah | 26,178.3 | 40,150 |
| C3 | Al Marwah - Ath Thaghr | data | 17.3 | 8 | Al Marwah · Al-Safa · Al-Safa · Al-Rehab · Al-Rehab · Al Naseem · King Abdulaziz University · Ath Thaghr | 38,508.0 | 74,050 |
| C4 | Al Bawadi - Al-Balad | data | 16.2 | 7 | Al Bawadi · Al Bawadi · Al-Rawdah · Al Andalus · Al Hamra · Al Baghdadiyah Al Gharbiyah · Al-Balad | 20,652.8 | 65,090 |
| C5 | Al Marwah - Al-Zahra | data | 12.2 | 6 | Al Marwah · Al Marwah · Al-Rabwah · Al Bawadi · Al-Salamah · Al-Zahra | 12,928.7 | 42,820 |
| C6 | Al Jamiah - Tahlia / Al Andalus | data | 17.5 | 8 | Al Jamiah · Ath Thaghr · Al Faiha'a · Al Faiha'a · Ash Sharafiyah · Al Hamra · Al Andalus · Tahlia / Al Andalus | 13,729.5 | 38,780 |
| C7 | Al Baghdadiyah Al Gharbiyah - Al-Nahdah | data | 15.8 | 7 | Al Baghdadiyah Al Gharbiyah · Ar Ruwais · Al Andalus · Al-Rawdah · Al-Zahra · Al-Zahra · Al-Nahdah | 10,163.6 | 48,300 |
| C8 | KAIA airport (Terminal 1) - King Abdulaziz University | anchor test: KAIA airport (Terminal 1) | 23.3 | 8 | KAIA airport (Terminal 1) · King Abdulaziz International Airport · Al Marwah · Al-Safa · Al-Safa · Al-Rehab · Al Naseem · King Abdulaziz University | 32,523.2 | 60,620 |
<!-- /LOOP:candidates -->

## Ranking (one city run per candidate)

Shuttle mode, alpha 0.5, 90 km/h, measured capacity, 10 % sample. Relief, VHT and passengers are
city-equivalent per weekday. "Relief seed 1" is against the baseline, "seed 2" against the seed-2
baseline replicate; ranking is on the mean per tunnel-km. Capex at USD 15 / 25 / 40 M per km; the
per-USD-M range runs from high to low capex. Flags are from the seed-1 run.

<!-- LOOP:ranking -->
| rank | id | alignment | origin | tunnel-km | stations | passengers/day | relief seed 1 | relief seed 2 | relief mean | relief/day per km | relief/day per USD M (range) | AM-peak road delay % (seed 1) | city VHT saved (seed 1) | net person-h (seed 1) | capex USD M | pair exceedance | segment peak util. | riders slower than car | teleports/veh |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | C2 | Ar Ruwais - Ar Rughamah | data | 10.7 | 5 | 18,790 | 37,693 | 53,160 | 45,426 | 4,249.4 | 170.1 (106.3 to 283.4) | -0.1 | 36,246 | 37,025 | 160-427 | 0.0 | 0.8 | 0.6 | 0.5 |
| 2 | C1 | Al-Salamah - King Abdulaziz University | data | 17.9 | 8 | 47,870 | 53,476 | 71,539 | 62,508 | 3,499.9 | 140.0 (87.5 to 233.3) | -4.7 | 55,707 | 28,484 | 268-714 | 0.0 | 1.5 | 0.8 | 0.5 |
| 3 | C4 | Al Bawadi - Al-Balad | data | 16.2 | 7 | 30,810 | 21,984 | 90,265 | 56,124 | 3,464.4 | 138.5 (86.6 to 230.9) | -0.8 | 29,211 | 6,915 | 243-648 | 0.0 | 1.2 | 0.9 | 0.5 |
| 4 | C6 | Al Jamiah - Tahlia / Al Andalus | data | 17.5 | 8 | 18,400 | 18,950 | 87,784 | 53,367 | 3,046.1 | 121.8 (76.1 to 203.1) | -0.2 | 17,051 | 12,037 | 263-701 | 0.0 | 0.8 | 0.8 | 0.5 |
| 5 | C3 | Al Marwah - Ath Thaghr | data | 17.3 | 8 | 35,320 | 14,767 | 89,538 | 52,152 | 3,018.1 | 120.7 (75.5 to 201.2) | -0.6 | 15,439 | 2,983 | 259-691 | 0.0 | 1.1 | 0.8 | 0.5 |
| 6 | C8 | KAIA airport (Terminal 1) - King Abdulaziz University | anchor test: KAIA airport (Terminal 1) | 23.3 | 8 | 29,240 | -15,677 | 67,700 | 26,012 | 1,115.4 | 44.6 (27.9 to 74.3) | -0.6 | -2,305 | -22,173 | 350-933 | 0.0 | 1.0 | 0.8 | 0.5 |
| 7 | C7 | Al Baghdadiyah Al Gharbiyah - Al-Nahdah | data | 15.8 | 7 | 23,320 | -49,218 | 52,503 | 1,642 | 103.7 | 4.1 (2.6 to 6.9) | -0.5 | -41,350 | -61,167 | 238-633 | 0.0 | 0.9 | 0.9 | 0.5 |
| 8 | C5 | Al Marwah - Al-Zahra | data | 12.2 | 6 | 19,680 | -49,085 | 16,946 | -16,070 | -1,311.8 | -52.5 (-32.8 to -87.4) | -0.2 | -41,651 | -56,863 | 184-490 | 0.0 | 0.9 | 0.9 | 0.5 |
<!-- /LOOP:ranking -->

## Greedy selection under the 25 km budget

<!-- LOOP:greedy -->
| candidate | tunnel-km | relief/day per km | decision | selected km |
|---|---|---|---|---|
| C2 | 10.7 | 4,249.4 | dropped: C1 alone relieves more | - |
| C1 | 17.9 | 3,499.9 | selected (relieves more alone than the per-km greedy set) | 17.9 |
| C4 | 16.2 | 3,464.4 | over budget with C1 (34.1 > 25 km) | - |
| C6 | 17.5 | 3,046.1 | over budget with C1 (35.4 > 25 km) | - |
| C3 | 17.3 | 3,018.1 | over budget with C1 (35.1 > 25 km) | - |
| C8 | 23.3 | 1,115.4 | sign differs between sim seeds (-15,677 / 67,700) | - |
| C7 | 15.8 | 103.7 | sign differs between sim seeds (-49,218 / 52,503) | - |
| C5 | 12.2 | -1,311.8 | sign differs between sim seeds (-49,085 / 16,946) | - |
<!-- /LOOP:greedy -->

## Sweep on the selected corridors

<!-- LOOP:sweep -->
| configuration | role | tunnel-km | passengers or cars re-routed | relief VHT/day | relief % | relief/day per USD M | AM-peak road delay % | net person-h/day | city VHT saved | pair exceedance | segment exceedance | segment peak util. | riders slower than car | teleports/veh | quality gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shuttle, central (alpha 0.5, 90 km/h, measured capacity) | lever | 17.9 | 47,870 | 53,476 | 2.0 | 119.8 (74.9 to 199.6) | -4.7 | 28,484 | 55,707 | 0.0 | 0.3 | 1.5 | 0.8 | 0.5 | tunnel segment exceedance 30.0% |
| shuttle at 50 km/h | lever | 17.9 | 47,870 | 42,679 | 1.6 | 95.6 (59.7 to 159.3) | -3.8 | 11,982 | 40,528 | 0.0 | 0.3 | 1.5 | 0.8 | 0.5 | tunnel segment exceedance 30.4% |
| shuttle at 160 km/h | lever | 17.9 | 47,870 | 95,570 | 3.5 | 214.0 (133.8 to 356.7) | -4.0 | 74,372 | 105,300 | 0.0 | 0.3 | 1.5 | 0.8 | 0.5 | tunnel segment exceedance 30.5% |
| private-EV, SAR 10 toll, 90 km/h | lever | 17.9 | 378,770 | 98,743 | 3.8 | 221.1 (138.2 to 368.6) | -1.9 | - | 88,739 | - | - | 3.0 | - | 0.4 | tunnel segment peak utilisation 2.98 (teleport-assisted) |
| private-EV, SAR 0 toll, 90 km/h | lever | 17.9 | 378,770 | 163,662 | 6.2 | 366.5 (229.1 to 610.9) | -5.5 | - | 154,778 | - | 0.9 | 6.0 | - | 0.4 | tunnel segment exceedance 88.7% |
| private-EV, SAR 25 toll, 90 km/h | lever | 17.9 | 378,770 | 44,913 | 1.7 | 100.6 (62.9 to 167.6) | -0.2 | - | 40,330 | - | 0.0 | 0.3 | - | 0.4 | ok |
| shift share alpha 0.3 | uncertainty | 17.9 | 28,820 | 57,671 | 2.1 | 129.2 (80.7 to 215.3) | -2.9 | 54,150 | 61,140 | 0.0 | 0.0 | 1.1 | 0.7 | 0.5 | ok |
| shift share alpha 0.7 | uncertainty | 17.9 | 68,480 | 73,455 | 2.7 | 164.5 (102.8 to 274.2) | -5.6 | 27 | 66,853 | 0.0 | 0.6 | 1.8 | 0.9 | 0.5 | tunnel segment exceedance 56.7% |
| access radius 800 m | uncertainty | 17.9 | 5,240 | 2,394 | 0.1 | 5.4 (3.4 to 8.9) | -1.1 | 3,408 | 6,747 | 0.0 | 0.0 | 0.3 | 0.5 | 0.5 | ok |
| private-EV, SAR 10 toll, engineering capacity (1.5 s headway) | uncertainty | 17.9 | 378,770 | 86,699 | 3.3 | 194.2 (121.4 to 323.6) | -2.4 | - | 77,014 | - | 0.0 | 0.8 | - | 0.4 | ok |
| engineering capacity (1.5 s headway, vendor side) | uncertainty | 17.9 | 47,870 | 53,476 | 2.0 | 119.8 (74.9 to 199.6) | -4.7 | 57,647 | 68,724 | 0.0 | 0.0 | 0.4 | 0.6 | 0.5 | ok |
| time-competitive shift only, measured case (90 km/h, 12.5 min wait, 5.3 s headway) | uncertainty | 17.9 | 7,240 | -150 | -0.0 | -0.3 (-0.2 to -0.6) | -0.8 | 5,855 | 1,140 | 0.0 | 0.0 | 0.8 | 0.0 | 0.5 | no relief |
| time-competitive shift only, Vegas-like 50 km/h, 12.5 min wait | uncertainty | 17.9 | 6,020 | 26,755 | 1.0 | 59.9 (37.5 to 99.9) | -1.1 | 31,602 | 29,361 | 0.0 | 0.0 | 0.6 | 0.0 | 0.5 | ok |
| time-competitive shift only, vendor case (160 km/h, 2 min wait, 1.5 s headway) | uncertainty | 17.9 | 11,760 | 69,542 | 2.5 | 155.7 (97.3 to 259.6) | -2.7 | 79,620 | 68,686 | 0.0 | 0.0 | 0.3 | 0.0 | 0.5 | ok |

Private-EV use: private-EV, SAR 10 toll, 90 km/h: 16,320 entries/day, toll revenue SAR 163,200/day; private-EV, SAR 0 toll, 90 km/h: 148,560 entries/day, toll revenue SAR 0/day; private-EV, SAR 25 toll, 90 km/h: 750 entries/day, toll revenue SAR 18,750/day; private-EV, SAR 10 toll, engineering capacity (1.5 s headway): 16,320 entries/day, toll revenue SAR 163,200/day.
<!-- /LOOP:sweep -->

## Recommendation

<!-- LOOP:recommendation -->
**Corridors:** C1 (Al-Salamah - King Abdulaziz University, 17.86 km); 17.86 tunnel-km of the 25 km budget.

**Policy:** shift share alpha 0.3 (ridership capped by the measured capacity) (run `runs/loop_opt_c1_a0p3`; policy file `sim/policies/loop_recommended.yaml`).

| item | value |
|---|---|
| congestion relief, VHT/day | 63,349 (mean of 57,671, 69,027: 1 seed-1 run(s) and the seed-2 replicate; band 23,435 to 103,263 with the replicate noise) |
| relief per day per USD M | 141.9 at central capex (band 32.8 to 385.4 with noise and capex range) |
| capex USD M (low / central / high) | 268 / 446 / 714 |
| AM-peak road delay change | -2.85 % |
| passengers (or cars re-routed) per day | 28,820 |
| net person-hours per day | 54,150 |
| pair / segment capacity exceedance | 0.000 / 0.017 |
| riders slower than by car | 0.697 |
| teleports per vehicle | 0.482 |
| quality gate | ok |

Vendor-capacity case (engineering headway 1.5 s, not demonstrated): private-EV, SAR 10 toll, engineering capacity (1.5 s headway): 86,699 VHT/day (`runs/loop_opt_c1_private_toll10_capeng`); engineering capacity (1.5 s headway, vendor side): 53,476 VHT/day (`runs/loop_opt_c1_capeng`).

Other options: shuttle, central (alpha 0.5, 90 km/h, measured capacity): 63,908 VHT/day (tunnel segment exceedance 30.0%); private-EV, SAR 10 toll, 90 km/h: 98,743 VHT/day (tunnel segment peak utilisation 2.98 (teleport-assisted)); private-EV, SAR 0 toll, 90 km/h: 163,662 VHT/day (tunnel segment exceedance 88.7%); private-EV, SAR 25 toll, 90 km/h: 44,913 VHT/day (only 750 Loop trips/day (< 5,000): relief is noise).
<!-- /LOOP:recommendation -->

### C1 on network v2 (integration pass 6, 2026-10-17)

All numbers: **synthetic demand, uncalibrated**.
One city run on the v2 network (`docs/network-v2.md`) against the v2 weekday baseline
`baseline-weekday-f0.1-s1-ae764558-346893f2-a998e1` (seed 1, 10 % sample), with the Track H
mode-choice logit (measured service) instead of the fixed alpha: run
`runs/v2/loop_c1_mcmeasured_f26ed359` (`uv run python -m scripts.pass6_v2 run loop_mc`; 6.6 min wall).
The assumed-share variant (alpha 0.3, `loop_recommended`) was not re-run on v2: it needs its own city
run. v1 numbers above stay; the v1 alpha-0.3 run is not a like-for-like control for the logit run.

| item | v1 (m2), alpha 0.3, seed 1 | v1, mode choice (offline, no SUMO) | **v2, mode choice, seed 1** |
|---|---|---|---|
| passengers per day | 28,820 | 19,530 | **14,630** (600 capped) |
| congestion relief, VHT/day (remaining vehicles) | 57,671 (two-seed mean 63,349) | not run | **38,718** (+1.99 %) |
| city VHT saved per day | 61,140 | not run | 46,684 (-2.4 %) |
| relief per day per USD M (central capex 446) | 129.2 | - | 86.7 |
| AM-peak road delay change | -2.85 % | - | -4.81 % (city AM-peak -5.07 %) |
| net person-hours per day | 54,150 | - | 42,062 |
| riders slower than by car (simulated) | 0.697 | - | 0.52 (mode-choice step: 0.49 of admitted riders) |
| teleports per vehicle (base -> policy) | 0.482 | - | 0.283 -> 0.265 |

Reading: on v2 the car is faster (baseline mean delay 1,173 s vs 1,877 s on m2), so fewer car tours
choose the Loop (14,630 vs 19,530 riders/day under the same logit) and the relief is about two
thirds of v1's alpha-0.3 run. It is about 1.1 times the v1 seed-noise band (±34k VHT/day); the v2
band is not measured. 26-28 % of vehicles still teleport on v2: a quality flag on every number here.

## Noise and checks

<!-- LOOP:noise -->
- Baseline replicate (sim seed 2, `runs/loop_noise_baseline_s2`, no policy): relief -34,236 VHT/day and city VHT +36,252 VHT/day against seed 1; teleports/veh 0.515 (+0.0092). One comparison is therefore uncertain by about +/- 34,236 VHT/day, a two-seed mean by about +/- 24,209.
- Network placebo (`runs/loop_opt_c1_placebo_a0`: tunnels and ramps built, alpha 0, no shuttles): relief +4,036 VHT/day (inside the noise band means the tunnel network alone does not move the surface KPIs).
- Recommended configuration re-simulated with sim seed 2 (`runs/loop_opt_c1_a0p3-sim2`): relief 69,027 VHT/day against the seed-2 baseline.
<!-- /LOOP:noise -->

## Vendor claims versus measured figures

Which parts of the result rest on measured operation and which on vendor claims:

| input | measured / sourced | vendor claim | what it does to the result |
|---|---|---|---|
| tunnel capacity | 1,355 pax/h per station pair (Las Vegas, July 2021) = one shuttle every 5.3 s at 2 pax | 1-2 s headways (4,500-90,000 pax/h claims) | **Decisive.** At measured capacity the C1 tunnel overloads at alpha 0.5 (30 % of segment traversals over capacity) and carries about alpha 0.3 (28,820 pax/day); private-EV at SAR 10 draws 3x the capacity. At 1.5 s headway both fit (shuttle alpha 0.5: 53,476 VHT/day; private-EV SAR 10: 86,699 VHT/day). |
| tunnel speed | 35 mph (56 km/h) at Las Vegas | "up to 100 mph" (Dubai) | **No effect on road relief in shuttle mode**: shuttles never use surface roads, so the 50 / 90 / 160 km/h runs (42,679 / 53,476 / 95,570 VHT/day) differ only by simulation noise. Speed matters for riders and in private mode. |
| station wait | 10-15 min reported at Las Vegas (uncited) | ~2 min on-demand | Under the measured wait 70 % of shifted riders are slower door to door than by car. If only time-competitive riders shift, C1 carries 7,240 pax/day (measured) vs 11,760 (vendor: 160 km/h, 2 min wait, 1.5 s headway), +62 %; their relief (-150 vs 69,542 VHT/day) differs by more than the noise but each is a single run. |
| cost | USD 15-40 M per km from LVCC, Music City and Dubai contracts | - | Spreads relief per USD M by a factor 2.7 for any configuration. |
| shift share alpha | **not sourced** (assumption, no mode-choice model) | - | The largest behavioural driver: relief rises from alpha 0.3 to 0.7 only until capacity binds, and a time-competitive shift removes most of it under measured service. |

In short: the recommendation (shuttle, capped at measured capacity) uses measured capacity and the
assumed shift share; the larger private-EV benefit (86,699 VHT/day) exists only under the vendor
headway; vendor speed claims do not change road relief at all.

## Findings

1. **Where the delay is.** The heaviest desire lines (vehicle trips x baseline delay) all touch
   the Al Naseem / As Sulimaniyah / Al Faiha'a belt east of the centre (each 8,000-11,000 delay
   hours/day), plus Al-Salamah - Al Naseem and KAIA - Ar Rughamah. The top time-loss corridors are
   Al Haramain Road, Madinah Road and Prince Majid Road, then King Abdullah, King Fahd, Al Lith and
   King Abdulaziz roads (see the corridor list above; `sim/loop/results/corridors.csv`).
2. **Which corridors.** Five candidates are positive in both seeds with a two-seed mean above the
   noise: C1 Al-Salamah - KAU (62,508 VHT/day mean; seeds 53,476 / 71,539; 17.9 km), C4 Al Bawadi -
   Al Balad (56,124; 21,984 / 90,265), C6 Al Jamiah - Tahlia / Al Andalus (53,367; 18,950 /
   87,784), C3 Al Marwah - Ath Thaghr (52,152; 14,767 / 89,538) and C2 Ar Ruwais - Ar Rughamah
   (45,426; 37,693 / 53,160; 10.7 km, best per km). Only C1 and C2 are above the one-run noise in
   both seeds; C3, C4 and C6 rest on a large seed-2 value. C8 (KAIA - KAU), C7 and C5 change sign
   between seeds and are not supported. Of the anchors, KAU emerges from the data (end of C1,
   next to the Al Naseem hot spot); Al Balad (C4) and Tahlia / Al Andalus (C6) are weakly
   supported; the KAIA airport line (C8) is not.
3. **Selection under 25 km.** C1 alone (17.86 km, USD 268-714 M). C2 is the most efficient per
   km, but nothing else fits beside it and C1 alone relieves more (knapsack correction).
4. **Policy.** Shuttle mode on C1 with ridership limited to what the measured capacity carries
   (about alpha 0.3, 28,820 passengers/day): congestion relief 63,349 VHT/day for the vehicles
   still on the road (mean of seed 1, 57,671, and seed 2, 69,027; band 23,435 to 103,263 with the
   replicate noise), AM-peak road delay -2.9 %, about 142 VHT/day per USD M at central capex
   (band 33 to 385 with noise and the capex range), about 16 M vehicle-hours/year at 250 days.
   Net of riders' extra door-to-door time it is 54,150 person-hours/day (seed 1). Behavioural and
   capacity uncertainties are separate rows of the sweep table (alpha 0.7 and access radius 800 m:
   73,455 and 2,394 VHT/day; time-competitive shift: -150 to 69,542).
5. **Private-EV toll tunnel does not work at measured capacity.** At SAR 10 the one-shot routes
   send 16,320 cars/day into a tunnel that carries about 680/h per direction: queues teleport
   through (3x capacity in the peak), so its 98,743 VHT/day is not credible. At SAR 25 only 750
   cars/day use it and its relief is noise. A toll between SAR 10 and 25 might fit capacity
   (untested). Under the vendor headway, SAR 10 fits and gives the largest credible relief of all
   runs (86,699 VHT/day, SAR 163,200/day toll revenue).
6. **Riders.** The fixed shift share is generous: under the measured 12.5 min wait about 70 % of
   shifted riders are slower than by car. Real ridership would be closer to the time-competitive
   runs (6,000-12,000 passengers/day on C1), where relief is small under measured service.
7. **Noise dominates small effects.** One comparison is uncertain by about +/- 34,000 VHT/day
   (baseline replicate); runs that differ only in tunnel attributes spread over 43,000-96,000
   VHT/day, and the shuttle dispatch window alone moved C1 from 71,047 to 53,476. (Changing only
   the tunnel headway, an additional file, left road results bit-identical: the engineering and
   measured shuttle rows show the same relief.) Effects under ~1.5 % of city VHT cannot be
   separated from noise with two seeds.

## Caveats

- **Synthetic, uncalibrated, gridlock-affected baseline.** Meso delay is strongly non-linear near
  gridlock (Track A: removing ~2 % of trips can cut mean delay by ~10 %); VHT savings here are
  larger than a calibrated, less congested network would show. Rankings between corridors are more
  robust than the absolute savings.
- **Exogenous shift share.** alpha is assumed, not modelled; the rider-time flag shows how many
  shifted legs would be slower by Loop than by car. A real system would attract fewer of those.
  Track H replaces alpha with a car-vs-Loop logit (`docs/loop-mode-choice.md`, `--mode-choice`):
  C1 carries about 19,500 riders/day under the measured service (range 10,900-31,900 over value of
  time, wait weight, ASC and fare) and 31,500 under the vendor service, against 28,820 at alpha
  0.3; the city relief under mode choice is not yet re-simulated.
- **No induced demand, no re-equilibration.** Freed road space is not refilled by new or re-routed
  trips (one-shot routing, A-pol-090), which flatters every option equally.
- **Passengers are not simulated.** Walk, wait and transfers are estimated; there are no transfers
  between lines and no station dwell queues beyond the loading stop and the tunnel headway.
- **Private mode routing** is one-shot on baseline travel times and does not anticipate the
  tunnel's own queue; the matched control removes the generic routing gain (TA-018).
- **Costs** are per alignment-km from three projects with different scopes (LVCC, Music City,
  Dubai); no Saudi ground conditions, utilities or land costs. No operating cost or fare revenue in
  the per-USD-M metric (toll revenue is reported for private mode).
- **Weekday only**; Friday, Ramadan and event days are not evaluated.
- **Noise.** Candidates have two seeds; sweep runs one (the recommended configuration two). The
  seed-2 baseline is more congested than seed 1, and relief from a more congested start is
  larger, so seed-2 estimates run higher.
- **Teleports.** Tier A's 120 s teleport time lets queued vehicles jump through a full tunnel;
  tunnel segment exceedance is the flag for this, and configurations above 10 % are not credited.
- **Untested:** intermediate tolls (SAR 10-25), private-EV at measured capacity with a ramp
  metering rule, transfers between lines, more than one corridor within the budget.

Assumptions: `docs/assumptions-trackD.md` (A-loop-001..020). Sources:
`docs/data-sources-trackD.md`. Decisions: `docs/status/trackD.md` (TD-001..).
