# Assumptions register: Track E (movies)

Same row format as `docs/assumptions.md`; merged into it at integration. The values live in
`scripts/movies/settings.yaml` (each with an `A-mov` id and a `source:` or `assumption:`). They are
display choices for the films, not inputs to any simulation; every film stays **synthetic demand,
uncalibrated**.

| id | parameter | value | unit | range | source or assumption | status | used in |
|---|---|---|---|---|---|---|---|
| A-mov-001 | Default building height (no `height`, no `building:levels`) | 6.0 | m | 3.2-12.8 | Assumption: about two storeys; films only (the viewer's buildings keep the A-network heights) | assumed | scripts/movies/basemap.py |
| A-mov-002 | Storey height for `building:levels` | 3.2 | m/level | 3.0-4.0 | Assumption: typical residential/commercial storey | assumed | scripts/movies/basemap.py |
| A-mov-003 | Sun position model | NOAA solar-position equations, Jeddah 21.54 N 39.17 E, sim clock read as AST (UTC+3), refraction ignored | - | better than 1 deg | Source: NOAA Global Monitoring Laboratory, Solar Calculation Details (https://gml.noaa.gov/grad/solcalc/calcdetails.html); checked in tests against the noon elevation and the sunrise/sunset azimuths | sourced | scripts/movies/sun.py |
| A-mov-004 | Night blend | from sun elevation 0 deg to -6 deg (civil twilight) | deg | - | Assumption: display choice for road glow, headlights and dim ambient light | assumed | scripts/movies/sun.py |
| A-mov-005 | Motion-trail length | 40 | s | 10-120 | Assumption: TripsLayer trail of the last 40 simulated seconds; display only, positions are FCD samples | assumed | scripts/movies/bundle.py, web/src/cinema/scene.ts |
| A-mov-006 | FCD sampling for vehicle paths | every sample (1 s) | samples | 1-5 | Assumption: TripsLayer interpolates linearly between 1 s samples | assumed | scripts/movies/bundle.py |
| A-mov-007 | Tier B window clock | t = 0 shown as 08:00 | local time | - | Assumption, as in strategist/scenarios/emergency_tahlia_0830.yaml: the window demand is one weekday morning hour; sets the HUD clock and the sun on window films | assumed | movies/specs/*.yaml (`clock_t0`) |
| A-mov-008 | Ambulance motion inside an edge (strategist film) | constant speed over the recorded edge time | - | - | Assumption: the what-ifs store `ambulance_edge_s` per route edge, not FCD; per-edge timings and the ETA are the run's, motion within an edge is interpolated | assumed | scripts/movies/bundle.py (`ambulance_trip`) |
