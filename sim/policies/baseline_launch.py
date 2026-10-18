"""Run a Tier A baseline with run-time overrides, without editing sim/population/ (M4 ownership).

    python -m sim.policies.baseline_launch friday --routing-threads 8 --gzip

`--routing-threads` overrides `assignment.routing_threads` (the run then records
`routes_deterministic: false`, TA-015); `--gzip` makes the final simulation write gzipped
tripinfo/edgedata/emissions (TA-016: uncompressed 10 % city outputs are ~3 GB). Used for the M4
Friday and Ramadan baselines; both options now live in `run_baseline` and `sim.runner --baseline`.
"""

from __future__ import annotations

import typer

import sim.population.baseline as b

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    daytype: str,
    seed: int = typer.Option(1),
    sample: float = typer.Option(0.10),
    routing_threads: int | None = typer.Option(None),
    gzip: bool = typer.Option(False, "--gzip"),
) -> None:
    b.run_baseline(daytype, seed, sample, routing_threads=routing_threads, gz=gzip)


if __name__ == "__main__":
    app()
