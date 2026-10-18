"""vType tools.

python -m sim.vtypes write --out runs/x/vtypes.add.xml --tier B [--mix normal=0.8,slow=0.2]
python -m sim.vtypes check
"""

from __future__ import annotations

from pathlib import Path

import typer

from sim.vtypes.loader import load_library, load_mix_file, resolve_mix, write_vtypes_additional

app = typer.Typer(add_completion=False, help=__doc__)


def parse_mix(text: str | None) -> dict[str, float] | None:
    if not text:
        return None
    pairs = [p.split("=") for p in text.split(",") if p]
    return {k.strip(): float(v) for k, v in pairs}


@app.command()
def write(
    out: Path = typer.Option(...),
    tier: str = typer.Option("B"),
    mix: str | None = typer.Option(None, help="name=share,... (default: mix_default.yaml)"),
) -> None:
    lib = load_library()
    write_vtypes_additional(out, resolve_mix(parse_mix(mix), lib), tier, lib)
    typer.echo(f"wrote {out}")


@app.command()
def check() -> None:
    lib = load_library()
    mix = load_mix_file()
    typer.echo(f"{len(lib.types)} vTypes OK; default mix {mix.as_mix()}")


if __name__ == "__main__":
    app()
