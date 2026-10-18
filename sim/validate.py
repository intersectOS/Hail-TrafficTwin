"""Validate behavioural YAML files (day types, policies) against the models in sim/schemas.py.

python -m sim.validate sim/policies/remote_work_30.yaml sim/daytypes/friday.yaml
python -m sim.validate sim/policies/*.yaml
"""

from __future__ import annotations

from pathlib import Path

import typer

from sim.schemas import validate_file

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(files: list[Path]) -> None:
    failed = 0
    for f in files:
        try:
            validate_file(f)
        except Exception as exc:  # report every file, then fail
            failed += 1
            typer.echo(f"FAIL {f}: {exc}")
        else:
            typer.echo(f"ok {f}")
    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
