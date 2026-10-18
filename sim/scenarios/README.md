# sim/scenarios

Scenario (event) files and the window scenario runner (M5). Synthetic demand, uncalibrated;
scenario files are fictional (PROJECT.md section 11).

- `schema.py`: pydantic models; events are a discriminated union on `type` (accident, rain,
  flood, motorcade, emergency_trip; evacuation is reserved for M7 and rejected at run time).
  `strategist_requested(scenario)` is the flag Track B's M6 reads.
- `*_tahlia.yaml`: demo scenarios for each event type on the `tahlia` window.
- `run.py`: baseline + scenario (same demand, mix, seed and step loop; the baseline keeps only
  probe events, i.e. emergency trips), in two worker processes. `simulate.py` is the TraCI step
  loop; `outputs.py` streams FCD/queue/tripinfo/edgeData into Parquet; `kpis.py` + `kpis.yaml`
  window KPIs and gridlock rules; `report.py` writes `scenario_report.{json,md}`.
- `run.yaml`: SUMO settings shared by both runs (collision rule).
- `register.py`: regenerates docs/assumptions-trackB.md from the YAML files.

    python -m sim.runner --scenario accident_tahlia --window tahlia --seed 1
    python -m sim.scenarios validate sim/scenarios/*_tahlia.yaml
    python -m sim.scenarios register --check
