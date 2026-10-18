"""Reproducible OSM fix list.

Fixes live in ``data/osm/fixes/*.yaml`` (reviewed and committed); raw OSM is never edited.
Each fix targets an OSM way (``osm_way_id``) or a SUMO edge (``edge_id``) and is applied to a
built network as a netconvert patch: an edge file that updates or deletes the matching edges.

    python -m sim.network.fixes check --net data/jeddah/jeddah.net.xml
    python -m sim.network.fixes apply --net in.net.xml --out out.net.xml
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Literal

import typer
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim.common import REPO_ROOT, run_cmd, sumo_bin

DEFAULT_FIXES_DIR = REPO_ROOT / "data" / "osm" / "fixes"

Field_ = Literal["lanes", "lanes_min", "speed", "oneway", "remove"]


class Fix(BaseModel):
    """One reviewed correction."""

    model_config = ConfigDict(extra="forbid")

    id: str
    osm_way_id: int | None = None
    edge_id: str | None = None
    field: Field_
    value: int | float | bool | str | None = None
    direction: Literal["both", "forward", "backward"] = "both"
    reason: str
    date: dt.date
    author: str
    osm_note: str | None = Field(default=None, description="upstream OSM status / changeset")
    # provenance of machine-derived fixes (e.g. the imagery lane audit); None for reviewed fixes
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    method: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Fix:
        if (self.osm_way_id is None) == (self.edge_id is None):
            raise ValueError(f"fix {self.id}: give exactly one of osm_way_id or edge_id")
        if self.field in ("lanes", "lanes_min") and not (
            isinstance(self.value, int) and self.value >= 1
        ):
            raise ValueError(f"fix {self.id}: lanes needs a positive integer value")
        if self.field == "speed" and not (
            isinstance(self.value, int | float) and not isinstance(self.value, bool)
        ):
            raise ValueError(f"fix {self.id}: speed needs a number (km/h)")
        if self.field == "oneway" and self.value not in ("forward", "backward"):
            raise ValueError(f"fix {self.id}: oneway value must be 'forward' or 'backward'")
        return self


class FixFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list[Fix] = Field(default_factory=list)


def load_fixes(fixes_dir: Path = DEFAULT_FIXES_DIR) -> list[Fix]:
    """Load and validate every ``*.yaml`` in ``fixes_dir`` (sorted for determinism)."""
    fixes: list[Fix] = []
    seen: set[str] = set()
    for path in sorted(Path(fixes_dir).glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        for fix in FixFile.model_validate(raw).fixes:
            if fix.id in seen:
                raise ValueError(f"duplicate fix id {fix.id} in {path}")
            seen.add(fix.id)
            fixes.append(fix)
    return fixes


def index_edges(net: Path) -> dict[str, list[str]]:
    """Map OSM way id -> SUMO edge ids, from the ``origId`` lane params (streaming parse).

    Requires the network to be built with ``--output.original-names``.
    """
    by_way: dict[str, list[str]] = defaultdict(list)
    current: str | None = None
    found_for_current = False
    for event, elem in ET.iterparse(net, events=("start", "end")):
        if event == "start" and elem.tag == "edge":
            current = elem.get("id") if elem.get("function") != "internal" else None
            found_for_current = False
        elif event == "end" and elem.tag == "param" and current and not found_for_current:
            if elem.get("key") == "origId":
                for way in (elem.get("value") or "").split():
                    by_way[way].append(current)
                found_for_current = True
        elif event == "end" and elem.tag == "edge":
            current = None
            elem.clear()
    return dict(by_way)


def edge_lanes(net: Path) -> dict[str, int]:
    """Non-internal edge id -> number of lanes (streaming parse)."""
    lanes: dict[str, int] = {}
    for _, elem in ET.iterparse(net, events=("end",)):
        if elem.tag == "edge":
            if elem.get("function") != "internal":
                lanes[elem.get("id", "")] = len(elem.findall("lane"))
            elem.clear()
    return lanes


def resolve(fix: Fix, by_way: dict[str, list[str]], all_edges: dict[str, int]) -> list[str]:
    """Edges a fix applies to, honouring ``direction`` (backward = SUMO ids starting with '-')."""
    if fix.edge_id is not None:
        return [fix.edge_id] if fix.edge_id in all_edges else []
    edges = sorted(set(by_way.get(str(fix.osm_way_id), [])))
    if fix.direction == "forward":
        edges = [e for e in edges if not e.startswith("-")]
    elif fix.direction == "backward":
        edges = [e for e in edges if e.startswith("-")]
    return edges


def build_patch(fixes: list[Fix], net: Path) -> tuple[ET.Element, dict[str, list[str]]]:
    """Build an ``.edg.xml`` patch; return it with the resolved edges per fix id."""
    by_way = index_edges(net)
    all_edges = edge_lanes(net)
    root = ET.Element("edges")
    resolved: dict[str, list[str]] = {}
    for fix in fixes:
        edges = resolve(fix, by_way, all_edges)
        resolved[fix.id] = edges
        for edge in edges:
            if fix.field == "remove":
                ET.SubElement(root, "delete", id=edge)
            elif fix.field == "oneway":
                # keep the direction named by `value`, delete the other one
                reverse = edge.startswith("-")
                if (fix.value == "forward") == reverse:
                    ET.SubElement(root, "delete", id=edge)
            elif fix.field == "lanes_min":
                # raise to at least `value`; keeps extra lanes netconvert added at ramps
                if all_edges[edge] < int(fix.value):
                    ET.SubElement(root, "edge", id=edge, numLanes=str(fix.value))
            elif fix.field == "lanes":
                ET.SubElement(root, "edge", id=edge, numLanes=str(fix.value))
            elif fix.field == "speed":
                ET.SubElement(root, "edge", id=edge, speed=f"{float(fix.value) / 3.6:.4f}")
    return root, resolved


def apply_fixes(
    net_in: Path,
    net_out: Path,
    fixes_dir: Path = DEFAULT_FIXES_DIR,
    log: Path | None = None,
    strict: bool = True,
) -> dict[str, list[str]]:
    """Apply the fix list to ``net_in`` and write ``net_out``.

    With no fixes the network is copied through netconvert unchanged (a documented no-op).
    With ``strict``, a fix that matches no edge is an error (stale fix after an OSM update).
    """
    fixes = load_fixes(fixes_dir)
    patch, resolved = build_patch(fixes, net_in)
    unmatched = [fid for fid, edges in resolved.items() if not edges]
    if unmatched and strict:
        raise ValueError(f"fixes matched no edge (stale?): {', '.join(unmatched)}")
    patch_file = Path(net_out).with_suffix(".fixes.edg.xml")
    ET.indent(patch)
    ET.ElementTree(patch).write(patch_file, encoding="UTF-8", xml_declaration=True)
    cmd = [
        sumo_bin("netconvert"),
        "--sumo-net-file",
        str(net_in),
        "--edge-files",
        str(patch_file),
        "--output-file",
        str(net_out),
        "--output.street-names",
        "--output.original-names",
        "--no-warnings",
    ]
    run_cmd(cmd, log=log)
    return resolved


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def check(
    net: Path = typer.Option(..., help="built network to resolve fixes against"),
    fixes_dir: Path = typer.Option(DEFAULT_FIXES_DIR),
) -> None:
    """Validate the fix files and show which edges each fix resolves to."""
    fixes = load_fixes(fixes_dir)
    _, resolved = build_patch(fixes, net)
    for fix in fixes:
        target = fix.osm_way_id if fix.osm_way_id is not None else fix.edge_id
        edges = resolved[fix.id]
        typer.echo(f"{fix.id}: {fix.field}={fix.value} on {target} -> {len(edges)} edge(s) {edges}")


@app.command()
def apply(
    net: Path = typer.Option(...),
    out: Path = typer.Option(...),
    fixes_dir: Path = typer.Option(DEFAULT_FIXES_DIR),
) -> None:
    """Apply the fix list to a network."""
    resolved = apply_fixes(net, out, fixes_dir)
    typer.echo(f"applied {len(resolved)} fix(es) -> {out}")


if __name__ == "__main__":
    app()
