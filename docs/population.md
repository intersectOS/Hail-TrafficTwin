# Synthetic population and Tier A demand (M2)

> All outputs: **synthetic demand, uncalibrated**. Every behavioural number lives in YAML with a
> `source:` or `assumption:` and is registered in `docs/assumptions-trackA.md`; citations are in
> `docs/data-sources-trackA.md`.

## Pipeline and commands

```bash
uv run python -m sim.population.zones                                   # TAZs (~30 s)
uv run python -m sim.population.synthesize --seed 1 --sample 0.10       # persons (~15 s full city)
uv run python -m sim.population.activities --daytype weekday --seed 1 --sample 0.10
uv run python -m sim.population.modes --daytype weekday --seed 1 --sample 0.10
uv run python -m sim.population.export_trips --daytype weekday --seed 1 --sample 0.10 --out runs/x
uv run python -m sim.daytypes.prayer 2026-10-18                         # adhan times
uv run python -m sim.schemas sim/daytypes/*.yaml                        # validate day types

# the whole chain plus assignment, simulation, metrics and plots in one command:
uv run python -m sim.runner --baseline --daytype weekday --sample 0.10 --seed 1
uv run python -m sim.fidelity --window demo --seed 1                    # meso vs micro (PROJECT.md 9.4)
```

| stage | module | config | output (gitignored) |
|---|---|---|---|
| zones | `sim/population/zones.py` | `config/zones.yaml` | `data/population/zones/` (zones, candidate edges, GeoJSON) |
| persons | `synthesize.py` | `config/population.yaml` | `data/population/pop-<key>-s<seed>-f<sample>/` (Parquet + hash) |
| activity chains | `activities.py` + `sim/daytypes/*.yaml` | `config/activities.yaml` | `.../trips-<daytype>-<key>/trips.parquet` |
| modes, vehicles | `modes.py` | `config/modes.yaml` | in memory |
| SUMO export | `export_trips.py` | `config/export.yaml` | `runs/<id>/trips.xml`, `vehicles.parquet` |
| baseline | `baseline.py` (via `sim.runner --baseline`) | `config/baseline.yaml` | `runs/<id>/` (meta, metrics, Parquet, plots, report.md) |
| KPIs | `sim/metrics.py` | - | `metrics.json`, `metrics_hourly/district.parquet`, `report.md` |

### Zones (TAZ)
The 112 OSM districts (admin_level 10, `data/jeddah/districts.geojson`) are the zones. The census
control total (3,712,917, GASTAT 2022, place Jiddah) is spread by a blend of residential building
footprint area (0.5), residential-street length in the main strongly connected component (0.35)
and `landuse=residential` area (0.15). The footprint proxy alone is the brief's choice, but OSM has
only 27,783 footprints for the city and many districts have none; the street-length term keeps
those districts populated (A-pop-001). The airport, seaport, naval base and industrial-area
districts hold no residents. Jobs and attractions come from OSM POIs (1,667 shops, 1,161
food outlets, 315 offices, 347 health sites, 198 schools, 35 universities, 630 mosques) and landuse,
blended with the resident share for unmapped local activity (A-pop-002). Each zone is snapped to
its candidate edges inside the main SCC (134,342 edges): local streets for homes, all
non-motorway edges for activities. Zones without edges neither house nor attract anyone.

### Persons
Households by nationality and type (Saudi family, non-Saudi family, non-Saudi shared housing);
heads and spouses first, dependents fill the residual of the census age targets. Status, sector,
licence and car access as in `population.yaml`; a home edge per household; primary locations
(workplace, school, university) by gravity with distance decay. The full population is synthesised
and households are then sampled with an independent stream, so the 10 % sample is a subset of the
25 % sample. Determinism: one RNG stream per step (`sampling.stream(seed, name)`).

### Activity chains and day types
Main tour per segment (seven work sectors, school, university) with participation, start and
duration distributions per day type, retail split shifts and errands on the way home; secondary
tours (shopping, leisure, personal) by status, chained after the person is home, evening-heavy;
mosque trips keyed to the adhan of the simulated date (adhanpy, Umm al-Qura method; people at
work or school at dhuhr/asr pray there); Friday Jumu'ah to a district mosque; airport ground trips
and a Makkah gate share. Times past midnight wrap into the early morning of the same day. Day
types: `weekday`, `friday`, `saturday`, `ramadan_weekday`, `umrah_season`.

### Modes and vehicle trips
Fixed shares by group (adult, labour housing, pupil, child, mosque, airport) and car availability
(driver, household car, no car). Walking only under 1.2 km; bus only if both ends are within 500 m
of an OSM bus stop (no GTFS and no OSM bus routes exist). Exported vehicles: car, chauffeured,
ride-hail/taxi, school-escort cars with the driver's empty legs, school and company buses (1/25
per person trip). Walk, passenger and city-bus trips are not vehicles in M2 (bus lines: M4).

## Measured: weekday, seed 1, 10 % sample
Run `baseline-weekday-f0.1-s1-e5f1906a-65fac195-f124c5` (population hash 65fac195), one command
(`python -m sim.runner --baseline --daytype weekday --sample 0.10 --seed 1`), m2 network, meso,
capacity scaling x10, 3 incremental duaIterate steps, 120 s teleport time. Gridlock-affected: read
every KPI together with the teleport share.

| quantity | value |
|---|---|
| persons (sample) / person trips | 371k / 1,006,762 (2.69 per person) |
| vehicle trips loaded (sample / city-equivalent) | 389,289 / 3.89 M (1.05 per resident) |
| completed (share) | 385,153 (0.992) |
| teleports (jam) | 196,721 = 0.51 per loaded vehicle (quality flag: high) |
| mean trip length / duration / delay | 14.6 km / 42.7 min / 31.3 min |
| mean speed | 20.5 km/h (night 70-74, 06-08 h 17-19, 18-22 h 13-15) |
| VKT / VHT (city-equivalent) | 56.1 M km / 2.74 M h (2.01 M h delay) |
| top hour, share of departures | 06:00-07:00, 9.6 % |
| CO2 / NOx (HBEFA defaults) | 26,185 t / 16,217 kg per day |
| runtime | assignment 118 min (routing 24/29/47 min, sims 2/5/11 min), final sim 9 min, post 1.3 min; 129 min total |
| peak memory (RSS, largest process) | 3.7 GB (duarouter), 3.1 GB (sumo) |

25 % sample: started at 05:40 alongside the 10 % run and stopped by the overnight monitor at 06:27
(logs/INTERVENTION.md) for disk (99 % full) and swap pressure, still in step-0 routing after 45 min
under contention (10 %: 24 min). Not completed; see docs/status/trackA.md.
Plots: `runs/<id>/plots/` (departures, trip length, trips per person).

## Sanity ranges (published Saudi figures or stated assumptions)

| quantity | model | sanity range | basis |
|---|---|---|---|
| mean Saudi household size | 4.79 | 4.5-5.2 | GASTAT 2022: 4.8 |
| mean non-Saudi household size (family / shared) | 3.61 / 2.48 | overall 2.0-3.5 | GASTAT 2022: 2.7 overall |
| Saudi share | 0.519 | 0.45-0.55 | Makkah region 2022: 0.518 |
| age shares | within 0.01 of targets (60+ Saudi 0.062 vs 0.056) | +/-0.02 | GASTAT 2022 bands |
| workers / population | 0.50 | 0.40-0.55 | KSA employed ~45 % of residents (LMS 2025 + civil service) |
| person trips per resident (incl. children) | 2.69 (2.71 incl. airport ground trips) | 1.7-2.8 | Jeddah 2014: 6 M trips/day (~1.7/person); data-scout range 2.0-2.8 for Saudis |
| vehicle trips per resident | 1.05 | 1.0-1.5 | PROJECT.md section 2 sizing: 1.2-1.5 |
| car-type modes (car + chauffeured + escort + passenger) share of person trips | 0.74 | 0.70-0.90 | Riyadh ~85 % car (2021) |
| public (city) bus share | 0.0003 - **below range** | 0.01-0.03 | Jeddah 2014: 1.2 %; 2025 ridership ~12k/day. Low because only 49 OSM bus stops and no routes/GTFS exist (TA-002); bus lines arrive in M4 |
| school + company bus share (private collective) | 0.101 (school 0.022, company 0.079) | no published range | assumption: labour housing and schools run their own buses (shares in sim/population/config/modes.yaml; occupancy A-mode-001) |
| ride-hail + taxi share | 0.084 | 0.03-0.10 | TGA 2024 app trips ~1 % + street/informal taxis |
| mean commute (home-work) distance | 15.5 km | 10-20 km | data-scout: 20-35 min one way |
| mean home-school distance | 3.7 km | 2-5 km | assumption (local schools) |
| share of vehicle departures in the top hour | 0.096 | 0.08-0.15 | assumption: early school + government starts make a sharp AM peak |
| simulated mean vehicle trip duration (10 % baseline) | 42.7 min, mean 14.6 km - **fails** | 20-35 min (commute) | data-scout: 20-35 min one way. Fails because the baseline is gridlock-affected (TA-011; 0.51 teleports per vehicle) |
