---
name: policy-yaml
description: Schema and conventions for policy, day-type, scenario and vType YAML files (remote work, staggered hours, calendars, public transport line, road pricing, network change, ride-hail share; events like accident, rain, flood, motorcade, evacuation). Use when creating or validating any YAML under sim/policies, sim/daytypes, sim/scenarios or sim/vtypes.
---
# YAML conventions

All files validate against pydantic models in `sim/schemas.py`; `python -m sim.validate <file>` must pass. Every behavioural number carries `source:` (citation) or `assumption:` (free text + plausible range).

## Policy file
```yaml
id: remote_work_30            # unique, snake_case
kind: policy
title: "30% hybrid work, 3 days/week"
daytype: weekday              # baseline to compare against
transforms:
  - type: remote_work
    share: 0.30
    days_per_week: 3
    eligible_sectors: [government, private_office]
    induced_trip_probability: 0.35
    assumption: "No Saudi figure found; international WFH studies report 0.2-0.5 induced non-work tours. Range 0.2-0.5."
  - type: staggered_hours
    segment: schools
    offset_minutes: 60
    spread_minutes: 15
    source: "..."
report:
  kpis: [mean_delay, mean_speed, vkt, vht, throughput, peak_spreading, co2, nox]
  by_district: true
  top_corridors: 10
```
Transform types and their parameters: `remote_work`, `staggered_hours`, `daytype`, `pt_line` (route geojson, stops, headway_s, hours, catchment_m, shift_share), `road_pricing` (polygon, charge_sar, hours, elasticity), `network_change` (edges, lanes, speed, closed, tls_program), `ridehail_share` (share, deadhead_factor).

## Day-type file (`sim/daytypes/<name>.yaml`)
Per segment (schools, government, private_office, retail, health, industrial, students, homemaker, other): start-time distribution (`normal`/`mixture`, mean, sd, truncation), duration, tours per day, evening leisure probability; `prayer_trips` (share of persons per prayer, time offset relative to adhan); `special` flags (`ramadan`, `friday`, `umrah_season`).

## Scenario (event) file (`sim/scenarios/<name>.yaml`)
```yaml
id: accident_tahlia_0830
kind: scenario
window: tahlia
daytype: weekday
events:
  - type: accident
    start: "08:30"
    duration_min: 45
    edge: "<edge id>"
    lanes_closed: 2
    rubbernecking_factor: 0.7
    assumption: "..."
```
Event types: `accident`, `rain` (preset light|heavy|storm), `flood` (preset + closure list ref), `motorcade`, `evacuation` (zone polygon, exits, phases, contraflow), `emergency_trip` (from, to, start, strategist: true|false).

Rule: a scenario never changes the population; a policy never calls TraCI.
