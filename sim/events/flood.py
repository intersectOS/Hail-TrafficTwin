"""Flood: a rain preset (storm by default) plus closure of the flood sites inside the window.

Sites come from data/jeddah_flood_sites.yaml (top-level `sites:` list; public literature, see the
file header). A site is used if its point lies inside the window network and it passes the
scenario's `site_ids` / `min_confidence` filters. Edges closed per site: those whose OSM way ids
(`origId`, netconvert --output.original-names) match the site's `osm_ways` when the network has
origIds and a match exists; otherwise every edge within `radius_m` of the point (radius defaults:
A-event-flood-radius). Closures start `closure_delay_s` after the storm (A-event-004) and close
every lane of the edge to all classes; affected vehicles reroute (A-event-005).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from sim.common import REPO_ROOT, load_yaml, rel
from sim.events.base import Event, EventContext
from sim.events.config import model_setting, pick, preset
from sim.events.netindex import NetIndex
from sim.scenarios.schema import Flood

FLOOD_RADIUS_ID = "A-event-flood-radius"


class FloodSite(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    kind: str
    lon: float
    lat: float
    radius_m: float
    osm_ways: list[int | str] = []
    confidence: str = "low"


def load_sites(path: Path) -> list[FloodSite]:
    if not path.exists():
        raise FileNotFoundError(f"flood sites file {rel(path)} not found")
    raw = load_yaml(path)
    return [FloodSite.model_validate(s) for s in raw.get("sites", [])]


def _rank(confidence: str) -> int:
    order = model_setting("confidence_order")
    return order.index(confidence) if confidence in order else -1


def resolve(spec: Flood, idx: NetIndex, ids: list[str]) -> dict[str, Any]:
    sites_file = REPO_ROOT / (spec.sites_file or model_setting("flood_sites_file"))
    sites = load_sites(sites_file)
    if spec.site_ids is not None:
        unknown = set(spec.site_ids) - {s.id for s in sites}
        if unknown:
            raise ValueError(f"flood: unknown site ids {sorted(unknown)} in {rel(sites_file)}")
        sites = [s for s in sites if s.id in spec.site_ids]
    if spec.min_confidence is not None:
        if _rank(spec.min_confidence) < 0:
            raise ValueError(
                f"flood: min_confidence must be one of {model_setting('confidence_order')}"
            )
        sites = [s for s in sites if _rank(s.confidence) >= _rank(spec.min_confidence)]
    origids = idx.orig_ids
    chosen = []
    for s in sites:
        if not idx.contains_lonlat(s.lon, s.lat):
            continue
        method, edges = "radius", []
        if origids and s.osm_ways:
            ways = {str(w) for w in s.osm_ways}
            edges = sorted(e for e, o in origids.items() if o & ways)
            method = "origId" if edges else "radius"
        if not edges:
            edges = idx.edges_within(s.lon, s.lat, s.radius_m)
        if edges:
            chosen.append(
                {
                    "site": s.id,
                    "name": s.name,
                    "kind": s.kind,
                    "confidence": s.confidence,
                    "method": method,
                    "radius_m": s.radius_m,
                    "edges": edges,
                }
            )
    if chosen:
        ids.append(FLOOD_RADIUS_ID)
    delay = float(pick("flood", "closure_delay_s", spec.closure_delay_s, ids))
    reroute = bool(pick("flood", "reroute", spec.reroute, ids))
    lanes = sorted({ln for c in chosen for e in c["edges"] for ln in idx.lane_ids(e)})
    return {
        "type": "flood",
        "id": spec.id,
        "start": spec.start,
        "end": spec.end,
        "preset": spec.preset,
        "multipliers": preset(spec.preset, ids),
        "sites_file": rel(sites_file),
        "sites": chosen,
        "closure_start": min(spec.start + delay, spec.end),
        "closed_edges": sorted({e for c in chosen for e in c["edges"]}),
        "closed_lanes": lanes,
        "reroute": reroute,
    }


class FloodEvent(Event):
    def __init__(self, plan: dict[str, Any]) -> None:
        super().__init__(plan)
        self.closed = False

    def on_start(self, ctx: EventContext) -> None:
        ctx.weather.apply(self.id, self.plan["multipliers"])
        ctx.record(self.id, "weather_on", preset=self.plan["preset"])
        if not self.plan["sites"]:
            ctx.record(self.id, "no_sites_in_window")

    def on_step(self, ctx: EventContext) -> None:
        p = self.plan
        if not self.closed and p["closed_lanes"] and ctx.t >= p["closure_start"]:
            self.closed = True
            ctx.closures.restrict(self.id, p["closed_lanes"], [], reroute=p["reroute"])
            verified = [ln for ln in p["closed_lanes"] if not ctx.conn.lane.getAllowed(ln)]
            self.summary["closed_edges"] = p["closed_edges"]
            self.summary["lanes_closed_verified"] = len(verified)
            ctx.record(
                self.id,
                "close_sites",
                sites=[s["site"] for s in p["sites"]],
                edges=p["closed_edges"],
                verified_disallowed=len(verified),
                rerouted=ctx.closures.rerouted,
            )

    def on_end(self, ctx: EventContext) -> None:
        if self.closed:
            lanes = ctx.closures.release(self.id)
            ctx.record(self.id, "reopen_sites", lanes=len(lanes))
        ctx.weather.clear(self.id)
        ctx.record(self.id, "weather_off")
