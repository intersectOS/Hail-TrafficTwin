# strategist

Emergency strategist (M6, PROJECT.md 9.9 / 9.10), Tier B windows only: snapshot of the window at
the dispatch time, candidate strategies (k-shortest routes on measured travel times, signal
preemption, rescue-lane proxy, side-entry holds), parallel what-if forks with `loadState`,
weighted ranking, measured-only explanations, auto-eligible / approval-required classification
and a hash-chained append-only SQLite decision log.

    python -m strategist.run --scenario emergency_tahlia_0830 --window tahlia --seed 1
    python -m strategist.approve <recommendation_id> [--option 1] [--reject]
    python -m strategist.log verify

Settings: `strategist.yaml`; score weights: `weights.yaml`; situations: `scenarios/`.
Documentation and measured results: `docs/strategist.md`. Synthetic demand, uncalibrated.
