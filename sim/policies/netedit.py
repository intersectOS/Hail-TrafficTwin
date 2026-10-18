"""`network_change` policies: closures, lane and speed changes and new links via a netconvert
patch on the baseline network, signal plans via an additional file.

The variant network of a city run is written next to the base network under a new name
(`data/jeddah/<base>.<policy>-<patchhash>.net.xml.gz`; the base file is never touched) and reused
when the same patch is applied again; other networks (demo, tests) get it in the run directory.
netconvert re-reads the base `.net.xml` with the structural options of
the window cutter; an empty patch reproduces the base network byte for byte (body), so baseline and
policy differ only by the edit (tested on the demo window).

Vehicles whose baseline route uses a removed edge are re-routed; trips that start or end on a
removed edge move to the nearest remaining edge of the same zone. Lane and speed changes keep the
baseline routes (no re-equilibration, TA-014); the simulation sees the new capacity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sim.common import REPO_ROOT, config_hash, rel, run_cmd, sumo_bin
from sim.policies.edges import load_edges, net_hash, utm_xy
from sim.policies.transforms import Plan
from sim.schemas import EdgeEdit, NetworkChange

CITY_NET_DIR = REPO_ROOT / "data" / "jeddah"
NETCONVERT_OPTIONS = [
    "--output.street-names", "true",
    "--output.original-names", "true",
    "--geometry.min-radius.fix.railways", "false",
    "--geometry.avoid-overlap", "false",
    "--geometry.max-grade.fix", "false",
    "--offset.disable-normalization", "true",
    "--no-warnings", "true",
]  # fmt: skip


def resolve(edges: pd.DataFrame, edit: EdgeEdit) -> list[str]:
    """Edge ids selected by an edit: explicit ids, or street name (substring) within a bbox."""
    if edit.edges:
        missing = sorted(set(edit.edges) - set(edges["edge_id"]))
        if missing:
            raise ValueError(f"unknown edges in network_change: {missing[:5]}")
        return list(edit.edges)
    assert edit.name is not None
    sel = edges["name"].str.contains(edit.name, case=False, regex=False)
    if edit.bbox is not None:
        x0, y0, x1, y1 = edit.bbox
        sel &= edges["lon"].between(x0, x1) & edges["lat"].between(y0, y1)
    ids = edges.loc[sel, "edge_id"].tolist()
    if not ids:
        raise ValueError(f"network_change: no edge named like {edit.name!r} in {edit.bbox}")
    return sorted(ids)


def patch_xml(t: NetworkChange, edges: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    closed: set[str] = set()
    attrs: dict[str, dict[str, str]] = {}
    for edit in t.edits:
        ids = resolve(edges, edit)
        if edit.closed:
            closed.update(ids)
        for eid in ids:
            if edit.lanes:
                attrs.setdefault(eid, {})["numLanes"] = str(edit.lanes)
            if edit.speed_kmh:
                attrs.setdefault(eid, {})["speed"] = f"{edit.speed_kmh / 3.6:.2f}"
    lines = ["<edges>"]
    lines += [f'    <delete id="{e}"/>' for e in sorted(closed)]
    for eid in sorted(set(attrs) - closed):
        body = " ".join(f'{k}="{v}"' for k, v in attrs[eid].items())
        lines.append(f'    <edge id="{eid}" {body}/>')
    for ne in t.new_edges:
        lines.append(
            f'    <edge id="{ne.id}" from="{ne.from_node}" to="{ne.to_node}" '
            f'numLanes="{ne.lanes}" speed="{ne.speed_kmh / 3.6:.2f}"/>'
        )
    lines.append("</edges>")
    info = {
        "closed_edges": sorted(closed),
        "changed_edges": sorted(set(attrs) - closed),
        "new_edges": [ne.id for ne in t.new_edges],
    }
    return "\n".join(lines) + "\n", info


def variant_path(base: Path, policy_id: str, patch: str, work: Path) -> Path:
    """Next to a city network in data/jeddah/ (shared, reused); else in the run directory."""
    stem = base.name.removesuffix(".gz").removesuffix(".net.xml")
    key = config_hash({"base": net_hash(base), "patch": patch})[:8]
    city = base.resolve().parent == CITY_NET_DIR.resolve()
    return (base.parent if city else work) / f"{stem}.{policy_id}-{key}.net.xml.gz"


def build_variant(base: Path, patch: str, out: Path, log: Path) -> Path:
    if out.exists():
        return out
    patch_file = log.parent / f"{out.name.removesuffix('.net.xml.gz')}.edg.xml"
    patch_file.write_text(patch)
    tmp = out.with_name(out.name + ".tmp.net.xml.gz")
    cmd = [sumo_bin("netconvert"), "-s", str(base), "-e", str(patch_file), "-o", str(tmp)]
    run_cmd([*cmd, *NETCONVERT_OPTIONS], log=log)
    tmp.rename(out)
    return out


def remap_endpoints(plan: Plan, missing: set[str]) -> int:
    """Move origins/destinations on removed edges to the nearest remaining edge of the zone."""
    from sim.population.zones import default_zone_dir, load_zones

    v = plan.vehicles
    hit_o = v["o_edge"].isin(missing).to_numpy()
    hit_d = v["d_edge"].isin(missing).to_numpy()
    if not (hit_o.any() or hit_d.any()):
        return 0
    _, zone_edges, _ = load_zones(plan.zone_dir or default_zone_dir())
    cand = zone_edges[~zone_edges["edge_id"].isin(missing) & (zone_edges["act_w"] > 0)]
    cx, cy = utm_xy(cand["lon"].to_numpy(), cand["lat"].to_numpy())
    pos = zone_edges.set_index("edge_id")[["lon", "lat", "zone_id"]]
    moved = 0
    for col, hit in (("o_edge", hit_o), ("d_edge", hit_d)):
        for i in np.flatnonzero(hit):
            eid = v.at[i, col]
            lon, lat, zone = pos.loc[eid]
            same = (cand["zone_id"] == zone).to_numpy()
            mask = same if same.any() else np.ones(len(cand), dtype=bool)
            x, y = utm_xy(np.array([lon]), np.array([lat]))
            d = np.where(mask, np.hypot(cx - x[0], cy - y[0]), np.inf)
            v.at[i, col] = cand["edge_id"].to_numpy()[int(d.argmin())]
            moved += 1
    return moved


def apply_network_change(plan: Plan, t: NetworkChange, policy_id: str) -> dict[str, Any]:
    from sim.policies.routes import routes_using

    base_net = plan.net
    base_edges = plan.edges()
    out: dict[str, Any] = {}
    if t.edits or t.new_edges:
        patch, info = patch_xml(t, base_edges)
        variant = build_variant(
            base_net,
            patch,
            variant_path(base_net, policy_id, patch, plan.work),
            plan.work / "netconvert.log",
        )
        new_edges = load_edges(variant)
        missing = set(base_edges["edge_id"]) - set(new_edges["edge_id"])
        plan.set_net(variant)
        plan.net_info = {"base": rel(base_net), "variant": rel(variant), **info}
        moved = remap_endpoints(plan, missing)
        affected: set[str] = set()
        if plan.base_routes is not None and missing:
            affected = routes_using(plan.base_routes, missing)
        # moved endpoints differ from the baseline trip, so the run re-routes them anyway
        plan.force_reroute |= affected
        out |= {
            "variant_network": rel(variant),
            "edges_closed": len(info["closed_edges"]),
            "edges_changed": len(info["changed_edges"]),
            "edges_new": len(info["new_edges"]),
            "edges_removed_in_variant": len(missing),
            "endpoints_moved": moved,
            "vehicles_rerouted_closure": len(affected),
            "closed_edge_names": sorted(
                set(base_edges.set_index("edge_id").loc[info["closed_edges"], "name"]) - {""}
            ),
        }
    if t.tls_program:
        path = Path(t.tls_program)
        if not path.exists():
            raise FileNotFoundError(f"tls_program {path} not found")
        plan.additional.append(path)
        out["tls_program"] = str(path)
    (plan.work / "network_change.json").write_text(json.dumps(out, indent=2))
    return out
