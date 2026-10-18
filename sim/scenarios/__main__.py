"""Scenario tools.

python -m sim.scenarios validate sim/scenarios/*.yaml
python -m sim.scenarios run accident_tahlia --window tahlia --seed 1
python -m sim.scenarios register [--check]
"""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from sim.common import load_yaml
from sim.scenarios import register as reg
from sim.scenarios.schema import Scenario

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def validate(files: list[Path]) -> None:
    """Validate scenario files against the schema (exit 1 on any error)."""
    bad = 0
    for f in files:
        try:
            s = Scenario.model_validate(load_yaml(f))
            typer.echo(f"OK   {f}: {s.id} ({len(s.events)} events, window {s.window})")
        except (ValidationError, ValueError) as exc:
            bad += 1
            typer.echo(f"FAIL {f}: {exc}")
    if bad:
        raise typer.Exit(code=1)


@app.command()
def run(
    scenario: str,
    window: str | None = typer.Option(None),
    seed: int = typer.Option(1),
    serial: bool = typer.Option(False, help="run baseline and scenario one after the other"),
    end: float | None = typer.Option(None, help="override the scenario end (s)"),
) -> None:
    from sim.scenarios.run import run_scenario

    run_scenario(scenario, window, seed, parallel=not serial, end=end)


@app.command()
def register(check: bool = typer.Option(False)) -> None:
    if check:
        if not reg.is_current():
            typer.echo(
                "docs/assumptions-trackB.md is out of date: python -m sim.scenarios register"
            )
            raise typer.Exit(code=1)
        typer.echo(f"current: {reg.describe()}")
        return
    reg.write()
    typer.echo(f"wrote {reg.describe()}")


if __name__ == "__main__":
    app()
