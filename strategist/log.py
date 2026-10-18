"""Decision log tools.

python -m strategist.log verify [--db runs/strategist/decisions.sqlite]
python -m strategist.log show [--db ...] [--last 20]
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from strategist import decision_log as L
from strategist.config import DEFAULT_DB

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def verify(db: Path = typer.Option(DEFAULT_DB, help="decision log (SQLite)")) -> None:
    """Walk the hash chain; exit 1 on any break, edited record or missing trigger."""
    problems = L.verify(db)
    if problems:
        for p in problems:
            typer.echo(f"BROKEN {p}")
        raise typer.Exit(code=1)
    n = len(L.records(db))
    head = L.records(db)[-1]["hash"] if n else L.GENESIS
    typer.echo(f"OK {n} records, chain intact, append-only triggers present; head {head}")


@app.command()
def show(
    db: Path = typer.Option(DEFAULT_DB, help="decision log (SQLite)"),
    last: int = typer.Option(20, help="show the last N records"),
) -> None:
    for r in L.records(db)[-last:]:
        rec = json.loads(r["recommendation"])
        dec = json.loads(r["decision"])
        if r["kind"] == "recommendation":
            what = f"top {len(rec.get('options', []))} options, best {rec.get('best_label')}"
        else:
            what = (
                f"{dec.get('decision')} option {dec.get('option_rank')} "
                f"of {dec.get('recommendation_id')}"
            )
        typer.echo(
            f"{r['seq']:>4} {r['timestamp']} {r['kind']:<14} {r['record_id']} "
            f"snapshot {r['snapshot_id']} actor {r['actor']}: {what} | hash {r['hash'][:12]}"
        )


if __name__ == "__main__":
    app()
