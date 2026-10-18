# Calibration (M8): dormant path, data request

All TrafficTwin results are **synthetic demand, uncalibrated**. No Jeddah traffic counts or
origin-destination data are available. M8 builds and proves the calibration path so that it can
run on the day a data partner delivers counts. Until such a fit has been run and reviewed, the
label stays.

## What the pipeline does

```
count CSV ──► edgeData targets ──► routeSampler.py ──► calibrated routes ──► SUMO (meso) ──► GEH report
  (partner)    (× population        (picks among the       (vehicles per        hourly edge     (share of counts
               sample share)         day type's baseline    hour that fit        counts          with GEH < 5)
                                     routes)                the counts)
travel-time CSV (optional) ─────────────────────────────────────────────────► segment-time check (± 15 %)
```

| step | module | notes |
|---|---|---|
| read and validate counts | `sim/adapters/counts.py` | `detector_id, edge_id, hour, count`; unknown edge ids stop the run |
| read travel times | `sim/adapters/traveltimes.py` | `segment_id, edge_ids, hour, travel_time_s, samples` |
| commercial sources | `sim/adapters/commercial.py` | interfaces only (Google Routes, TomTom, HERE); no API calls |
| fit routes to counts | `sim/calibrate.py` → SUMO `routeSampler.py` | candidates = newest `runs/baseline-<daytype>-*` routes unless `--routes` is given |
| re-simulate and score | `sim/calibrate.py` | Tier A meso with the baseline's capacity scaling; GEH per (edge, hour) |
| synthetic counts | `sim/adapters/synthetic.py` | round-trip test only; never presented as data |
| counts from a baseline run | `sim/adapters/baseline_counts.py` | city mechanics check only (A-cal-006); not data |

Commands:

```bash
# validate a partner file against the city network
uv run python -m sim.adapters.counts check counts.csv --net data/jeddah/jeddah.m2.net.xml
# calibrate a day type against its baseline routes (10 % sample: counts are scaled by 0.1)
uv run python -m sim.calibrate --counts counts.csv --daytype weekday --seed 1 \
    --travel-times traveltimes.csv --counts-source "Jeddah Municipality, Oct 2026"
# synthetic round trip on the demo window (what the tests run)
uv run python -m sim.adapters.synthetic --net data/demo/demo.net.xml --out runs/synthetic-demo
uv run python -m sim.calibrate --counts runs/synthetic-demo/counts.csv --net data/demo/demo.net.xml \
    --routes runs/synthetic-demo/candidates.rou.xml --sample 1.0 \
    --travel-times runs/synthetic-demo/traveltimes.csv --counts-source synthetic --before
```

Each run writes `runs/calibrate-<daytype>-s<seed>-<counts hash>-<config hash>/`: `report.md`,
`meta.json` (seed, config hash, counts hash, network hash, candidate-routes hash, SUMO version),
`geh.csv`, `calibrated.rou.xml`, routeSampler's `mismatch.xml`, and `traveltimes.json` when travel
times are given. The command exits with code 2 when the GEH target is missed.

## Acceptance metric

GEH for hourly flows: `GEH = sqrt(2 (M - C)^2 / (M + C))`, M = simulated, C = counted vehicles per
hour. A fit passes when at least **85 % of counts have GEH < 5** (A-cal-001, the UK DMRB / WebTAG
convention). Simulated counts are measured in the re-simulation (`entered` per edge per hour),
not read from routeSampler's own estimate, so congestion and timing effects are included.

## Proof without data (synthetic round trip)

On the demo window (seed 1), a truth demand of random trips (1,800 veh/h for 2 hours) is simulated
in meso; 40 detector edges with at least 30 veh/h in both hours give 80 counts. routeSampler then
chooses among an unrelated candidate set (random trips with seed 1001, 7,200 veh/h, 14,400
vehicles):

| measure | value |
|---|---|
| counts with GEH < 5 | **100 % (80 of 80)**, mean GEH 0.32, max 0.74 |
| candidate routes simulated unchanged (`--before`) | 0 % with GEH < 5, mean GEH 18.8 (4x too much traffic) |
| sampled vehicles | 2,802 of 14,400 candidates |
| travel times (10 single-edge segments x 2 hours = 20 rows) | 20 of 20 within ± 15 %, mean abs error 1.8 % |
| same with a 50 % sample (`--sample 0.5`) and in micro (`--mode micro`) | 100 % with GEH < 5 |
| runtime | about 4 s for the synthetic counts, about 3 s per calibration (with `--before`) |

Same seed twice gives identical calibrated routes (content hash), the same run id and an identical
GEH report (test; candidate routes are hashed without SUMO's timestamped header).

What the round trip does **not** prove: the demo has light traffic, so travel times match
trivially; real counts carry measurement error, missing hours and detectors on edges the OSM
network splits differently; and a city fit needs counts for all hours of the day (routeSampler
only places vehicles that pass a counted edge in a counted hour).

## City-scale check (Tier A, weekday baseline, 10 % sample)

To check the default `--daytype weekday` path at city scale, counts were derived from the weekday
10 % baseline's own edgeData with `python -m sim.adapters.baseline_counts` (A-cal-006: 50 edges
picked with seed 1 among edges carrying at least 1 vehicle in every selected hour and at least 30
per hour on average, in sample units; counts = `entered` / 0.1), then fitted against the 389,289
baseline routes. The counts files stay in `/tmp` (derived, not committed); runs are under `runs/`
(untracked).

```bash
uv run python -m sim.adapters.baseline_counts --daytype weekday --hours 0-23 --out /tmp/city24/counts.csv
uv run python -m sim.calibrate --counts /tmp/city24/counts.csv --daytype weekday --seed 1
```

| run (id) | eligible edges | counts | GEH < 5 | mean GEH | sampled vehicles | wall; peak RSS |
|---|---|---|---|---|---|---|
| hours 10-11 (`calibrate-weekday-s1-3589cd5a-334e0110`) | 4,845 | 100 | 80.0 % (FAIL); hour 10: 64 %, volume 0.81; hour 11: 96 %, volume 1.00 | 3.51 | 6,938 | 78-114 s; routeSampler 3.8-4.2 GB (two identical-result runs) |
| full day 0-23 (`calibrate-weekday-s1-f40885bc-334e0110`) | 7,535 | 1,200 | **87.7 % (PASS)**; hourly 62-96 % | 2.48 | 101,578 | 508 s (routeSampler 399 s); routeSampler 4.2 GB, SUMO 2.6 GB |

The full-day result was identical in two runs (before and after the run-id fix). Wall times were
measured with another track's SUMO run on the same machine.

Reading: the 2-hour fit misses in its first hour because nothing departs before 10:00, while in
the baseline trips that started earlier (mean trip about 18 min) still cross the detectors after
10:00. Partner counts must therefore cover the whole day (or the fitted window must start with an
uncounted warm-up hour); the data request asks for 24 hours. In the full-day fit the weakest
hours are 00:00 (72 %) and 05:00 (62 %, the start of the morning ramp, where routeSampler's uniform
departures within the hour miss the steep rise). These counts come from an uncalibrated,
congested baseline (TA-011): the check proves the mechanics at city scale, not Jeddah realism.

## Known limits and decisions

- routeSampler runs in greedy sampling mode. Its linear-programming optimiser (`--optimize`) needs
  scipy, which is not a project dependency; add it if real counts leave large under- or overflow.
- Sampled vehicles take one vType (`car` from the candidate file). `--keep-attributes` is not
  used because it restores each candidate's original depart time and breaks the hourly placement;
  so the mode mix (ride-hail, company bus, ...) of the baseline is not preserved in the fit.
- routeSampler places departures within the counted hour; counts are measured by edge entry time,
  so long trips that cross an hour boundary shift a little volume into the next hour.
- Duplicate detectors on one edge and hour are averaged (A-cal-003): lane detectors must be summed
  by the partner (or before the CSV is written).
- Travel times validate; they are not fitted. Using them as `duarouter` weights to regenerate the
  candidate routes is the next step once real data exists.
- Calibrated output is labelled "synthetic demand, uncalibrated" with
  `calibration_status: fitted, not reviewed` until a human reviews a real-count fit.

## Data request for a Jeddah partner

For Jeddah Municipality, the Transport General Authority, the Roads General Authority or a
traffic-data company. **Partner data is never committed to the repository**: it stays outside the
repo or under the gitignored `data/` tree, and only aggregate GEH results are published, with the
partner's consent.

1. **Classified or total vehicle counts, hourly**, for a typical weekday (Sunday to Thursday,
   outside school holidays and Ramadan), and if possible a Friday and a Ramadan weekday:
   - one row per detector and hour: `detector_id, location (lat, lon or road name and direction),
     hour, count` (all lanes of one direction summed);
   - at least **24 hours**, ideally averaged over several weeks with the number of days averaged;
   - priority corridors: King Abdulaziz Road, Prince Sultan Road, Madinah Road, Al Haramain
     Expressway, Tahlia Street, Palestine Street, Prince Majid Road, the Corniche; plus screenlines
     crossing the city north to south;
   - target: **100 or more count locations** (a few hundred is better), both directions.
2. **Detector metadata**: position, direction, lane count, detector type (loop, radar, camera), and
   known outages; so each detector can be mapped to one SUMO edge (`edge_id`). We do the mapping and
   send it back for confirmation.
3. **Travel times** (optional, very useful): mean and sample size per corridor segment and hour
   (Bluetooth/ANPR or probe data), with segment end points.
4. **Signal timing plans** for the main corridors (optional; improves the network more than demand).
5. **Licence terms**: permission to use the data for calibration and to publish aggregate fit
   statistics; whether derived calibrated demand may be shared.

Delivery: CSV or Excel with the fields above; we convert to `counts.csv`
(`detector_id, edge_id, hour, count`) and `traveltimes.csv`
(`segment_id, edge_ids, hour, travel_time_s, samples`).
