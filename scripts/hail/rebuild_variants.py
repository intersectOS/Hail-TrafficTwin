"""Rebuild the policy network variants (data/hail/hail.v2.<policy>-<hash>.net.xml.gz) that a city
run created, from the same base network and the same patch, so a machine that only has the run
directories (the `publish` workflow) can ingest those runs. The variant name carries the hash of
base + patch, so the rebuilt file has the same name; the run's network hash is checked after.

    python -m scripts.hail.rebuild_variants
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sim.common import REPO_ROOT
from sim.policies.edges import load_edges, net_hash
from sim.policies.netedit import build_variant, patch_xml, variant_path
from sim.schemas import validate_file

BASE = REPO_ROOT / "data" / "hail" / "hail.v2.net.xml"
app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(runs: Path = typer.Option(REPO_ROOT / "runs")) -> None:
    edges = load_edges(BASE)
    logs = REPO_ROOT / "logs"
    logs.mkdir(exist_ok=True)
    for f in sorted((REPO_ROOT / "sim" / "policies").glob("*.yaml")):
        pol = validate_file(f)
        for t in getattr(pol, "transforms", []):
            if getattr(t, "type", None) != "network_change" or not (t.edits or t.new_edges):
                continue
            patch, _ = patch_xml(t, edges)
            out = variant_path(BASE, pol.id, patch, runs)
            build_variant(BASE, patch, out, logs / f"rebuild-{pol.id}.log")
            want = {json.loads(m.read_text()).get("network_hash") for m in runs.glob(f"{pol.id}-*/meta.json")}
            got = net_hash(out)
            typer.echo(f"{pol.id}: {out.name} hash {got} (runs: {sorted(h for h in want if h)})")


if __name__ == "__main__":
    app()
