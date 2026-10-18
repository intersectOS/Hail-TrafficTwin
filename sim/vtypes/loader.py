"""Load the vType library and mixes, write SUMO vType additionals, apply the mix to demand."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import quoteattr

from sim.common import REPO_ROOT, load_yaml
from sim.vtypes.schema import MixFile, VTypeLibrary, check_mix

VTYPES_DIR = REPO_ROOT / "sim" / "vtypes"
LIBRARY_FILE = VTYPES_DIR / "types.yaml"
DEFAULT_MIX_FILE = VTYPES_DIR / "mix_default.yaml"
DEMAND_TAGS = ("vehicle", "trip", "flow")


def load_library(path: Path = LIBRARY_FILE) -> VTypeLibrary:
    return VTypeLibrary.model_validate(load_yaml(path))


def load_mix_file(path: Path = DEFAULT_MIX_FILE) -> MixFile:
    return MixFile.model_validate(load_yaml(path))


def resolve_mix(
    mix: dict[str, float] | None, library: VTypeLibrary | None = None
) -> dict[str, float]:
    """The scenario's mix, or the default mix file; validated against the library."""
    library = library or load_library()
    chosen = mix if mix is not None else load_mix_file().as_mix()
    return check_mix(chosen, set(library.types))


def mix_assumption_ids(mix: dict[str, float] | None, library: VTypeLibrary) -> list[str]:
    """Register ids a mix depends on: the default shares (if used) and params of used types."""
    ids: list[str] = []
    if mix is None:
        ids += load_mix_file().assumption_ids()
    effective = resolve_mix(mix, library)
    for name, share in effective.items():
        if share > 0:
            ids += [p.id for p in library.types[name].params.values()]
    return ids


def type_ids(library: VTypeLibrary, names: list[str]) -> list[str]:
    ids: list[str] = []
    for name in names:
        ids += [p.id for p in library.types[name].params.values()]
    return ids


def vtype_xml(name: str, library: VTypeLibrary) -> str:
    t = library.types[name]
    attrs = {
        "id": name,
        "vClass": t.vClass,
        "guiShape": t.guiShape,
        "color": t.color,
        "carFollowModel": t.carFollowModel,
        "laneChangeModel": t.laneChangeModel,
    }
    attrs.update({k: str(p.value) for k, p in t.params.items()})
    head = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())
    params = [f'        <param key="has.{d}.device" value="true"/>' for d in t.devices]
    if not params:
        return f"    <vType {head}/>"
    return "\n".join([f"    <vType {head}>", *params, "    </vType>"])


def write_vtypes_additional(
    out: Path,
    mix: dict[str, float],
    tier: str,
    library: VTypeLibrary | None = None,
    include: list[str] | None = None,
) -> Path:
    """Write every vType needed plus a vTypeDistribution `<distribution_id>` built from `mix`.

    Tier B: all library types are written (events add emergency and convoy vehicles).
    Tier A: tier_b_only types (emergency with bluelight) are refused if the mix or `include`
    asks for them, and are never written.
    """
    library = library or load_library()
    mix = check_mix(mix, set(library.types))
    if tier not in ("A", "B"):
        raise ValueError(f"tier must be A or B, got {tier!r}")
    if tier == "A":
        wanted = {k for k, v in mix.items() if v > 0} | set(include or [])
        bad = sorted(n for n in wanted if library.types[n].tier_b_only)
        if bad:
            raise ValueError(f"vTypes {bad} are Tier B only (micro-only bluelight device)")
        names = [n for n in library.types if not library.types[n].tier_b_only]
    else:
        names = list(library.types)
    members = [(n, s) for n, s in mix.items() if s > 0]
    lines = ["<additional>", *[vtype_xml(n, library) for n in names]]
    lines.append(
        f'    <vTypeDistribution id="{library.distribution_id}" '
        f'vTypes="{" ".join(n for n, _ in members)}" '
        f'probabilities="{" ".join(repr(s) for _, s in members)}"/>'
    )
    lines.append("</additional>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out


def apply_mix(demand_in: Path, demand_out: Path, distribution_id: str) -> dict[str, int]:
    """Stream a trips/routes file; vehicles, trips and flows without `type` get the distribution.

    SUMO samples each vehicle's member type from the distribution with its seeded parsing RNG,
    so the assignment is deterministic for a given `--seed` and identical for runs that load the
    same file (baseline and scenario).
    """
    counts = {"vehicles": 0, "typed_by_mix": 0, "kept_type": 0}
    demand_out.parent.mkdir(parents=True, exist_ok=True)
    depth = 0
    root_tag = "routes"
    with demand_out.open("w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        for event, elem in ET.iterparse(demand_in, events=("start", "end")):
            if event == "start":
                if depth == 0:
                    root_tag = elem.tag
                    out.write(f"<{root_tag}>\n")
                depth += 1
                continue
            depth -= 1
            if depth != 1:
                continue
            if elem.tag in DEMAND_TAGS:
                counts["vehicles"] += 1
                if elem.get("type"):
                    counts["kept_type"] += 1
                else:
                    elem.set("type", distribution_id)
                    counts["typed_by_mix"] += 1
            elem.tail = "\n"
            out.write("    " + ET.tostring(elem, encoding="unicode").rstrip() + "\n")
            elem.clear()
        out.write(f"</{root_tag}>\n")
    return counts
