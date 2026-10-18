---
name: sumo-run
description: How to run SUMO headless in this repo (meso for Tier A, micro for Tier B), the standard options and outputs, how to check teleports and runtime, and how to run long simulations in the background. Use whenever launching or debugging a SUMO run.
---
# Running SUMO in TrafficTwin

Always go through `python -m sim.runner` once it exists; before that, use these conventions directly.

## Environment
- `uv run` for every Python command. `SUMO_HOME` = directory reported by `python -c "import sumolib, os; print(os.path.dirname(sumolib.__file__))"` → its parent `sumo/` folder contains `tools/` and `bin/` when installed from the `eclipse-sumo` wheel. If installed via brew, `SUMO_HOME=$(brew --prefix sumo)/share/sumo`.
- Record `sumo --version` in every run's `meta.json`.

## Tier A (city, mesoscopic)
```
sumo -n data/jeddah/jeddah.net.xml -r runs/<id>/trips.rou.xml \
  --mesosim --meso-junction-control --meso-tls-penalty 0.5 \
  --begin 0 --end 86400 --step-length 1 --seed <seed> \
  --time-to-teleport 300 --ignore-route-errors \
  --additional-files runs/<id>/edgedata.add.xml \
  --tripinfo-output runs/<id>/tripinfo.xml \
  --statistic-output runs/<id>/stats.xml --duration-log.statistics --log runs/<id>/sumo.log --no-step-log
```
No FCD on Tier A. `edgedata.add.xml` contains `<edgeData id="ed" freq="300" file="edgedata.xml" excludeEmpty="true"/>` (and an `<edgeData type="emissions" .../>` entry when CO2/NOx are needed).

## Tier B (window, microscopic)
Same without `--mesosim`, plus `--fcd-output runs/<id>/fcd.xml --fcd-output.geo --device.fcd.period 1` and `--device.bluelight.explicit <emergency ids>` for emergency vehicles. Convert FCD to Parquet with a streaming parser immediately and delete the XML.

## Checks after every run
- `grep -c "Teleport" runs/<id>/sumo.log` and the `teleports` figure in `stats.xml`; teleports / loaded vehicles must be < 0.5 % for a smoke run.
- `stats.xml` → `vehicles loaded/inserted/running/waiting`, `duration`, `realtime factor`. Copy them into `meta.json`.
- If `waiting` grows without bound, demand is too high for the network or an entry edge is broken: check `netcheck.py` and the fix list before scaling demand.

## Background runs
`nohup <command> > logs/<name>.log 2>&1 &` then poll with `tail -n 20 logs/<name>.log`. Never wait synchronously for more than two minutes.
