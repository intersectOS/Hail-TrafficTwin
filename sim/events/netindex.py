"""Static network lookups used to resolve events before a run (main process, sumolib).

Workers never load sumolib: events are resolved into plain data (lanes, edges, routes,
free-flow times) that the TraCI side applies.
"""

from __future__ import annotations

import math
import re
from functools import cached_property
from pathlib import Path

import sumolib

ANTIPARALLEL_DEG = 135.0  # headings differing by more than this count as opposite directions


def _heading(edge: sumolib.net.edge.Edge) -> float:
    (x1, y1), (x2, y2) = edge.getShape()[0], edge.getShape()[-1]
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def _sample(shape: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    pts = [shape[0]]
    for (x1, y1), (x2, y2) in zip(shape, shape[1:], strict=False):
        seg = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(seg // step))
        pts += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(1, n + 1)]
    return pts


class NetIndex:
    def __init__(self, net_file: Path) -> None:
        self.path = Path(net_file)
        self.net = sumolib.net.readNet(str(net_file), withInternal=True)

    # --- edges -------------------------------------------------------------------------------
    @cached_property
    def edges(self) -> dict[str, sumolib.net.edge.Edge]:
        return {e.getID(): e for e in self.net.getEdges() if e.getFunction() != "internal"}

    def edge(self, edge_id: str) -> sumolib.net.edge.Edge:
        if edge_id not in self.edges:
            raise ValueError(f"edge {edge_id!r} is not in {self.path.name}")
        return self.edges[edge_id]

    def split_parts(self, edge_id: str) -> list[str]:
        """`<id>` plus Tier B split parts `<id>.s<k>` (B-D-001), ordered by k."""
        pat = re.compile(rf"^{re.escape(edge_id)}\.s(\d+)$")
        parts = sorted(
            ((int(m.group(1)), eid) for eid in self.edges if (m := pat.match(eid))),
        )
        return [edge_id, *[eid for _, eid in parts]]

    def reverse_edges(
        self,
        edge_id: str,
        search_m: float,
        sample_m: float,
        exclude_types: tuple[str, ...] = (),
    ) -> list[str]:
        """Opposite-direction edges: same two nodes reversed; for divided roads (separate
        carriageways, different nodes) the nearest anti-parallel edges within `search_m` of
        points sampled every `sample_m` along the edge."""
        e = self.edge(edge_id)
        a, b = e.getFromNode(), e.getToNode()
        same_nodes = sorted(
            o.getID()
            for o in b.getOutgoing()
            if o.getFunction() != "internal" and o.getToNode() == a and o.getID() != edge_id
        )
        if same_nodes:
            return same_nodes
        heading = _heading(e)
        shape = e.getShape()
        found: set[str] = set()
        for x, y in _sample(shape, sample_m):
            best = None
            for o, d in self.net.getNeighboringEdges(x, y, r=search_m, includeJunctions=False):
                if o.getFunction() == "internal" or o.getID() == edge_id:
                    continue
                if o.getType() in exclude_types:
                    continue
                diff = abs((_heading(o) - heading + 180) % 360 - 180)
                if diff > ANTIPARALLEL_DEG and (best is None or d < best[1]):
                    best = (o.getID(), d)
            if best:
                found.add(best[0])
        name = e.getName()
        same_name = {f for f in found if name and self.edge(f).getName() == name}
        return sorted(same_name or found)

    def lane_ids(self, edge_id: str) -> list[str]:
        return [lane.getID() for lane in self.edge(edge_id).getLanes()]

    # --- origIds -----------------------------------------------------------------------------
    @cached_property
    def orig_ids(self) -> dict[str, set[str]]:
        """edge id -> OSM way ids (from lane/edge `origId` params, netconvert
        --output.original-names). Empty dict if the net has none."""
        out: dict[str, set[str]] = {}
        for eid, e in self.edges.items():
            vals = []
            if e.getParam("origId"):
                vals.append(e.getParam("origId"))
            vals += [ln.getParam("origId") for ln in e.getLanes() if ln.getParam("origId")]
            ids = {tok.lstrip("-") for v in vals for tok in str(v).split()}
            if ids:
                out[eid] = ids
        return out

    # --- geometry ----------------------------------------------------------------------------
    def lonlat_to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        return self.net.convertLonLat2XY(lon, lat)

    def contains_lonlat(self, lon: float, lat: float) -> bool:
        x, y = self.lonlat_to_xy(lon, lat)
        xmin, ymin, xmax, ymax = self.net.getBoundary()
        return xmin <= x <= xmax and ymin <= y <= ymax

    def edges_within(self, lon: float, lat: float, radius_m: float) -> list[str]:
        x, y = self.lonlat_to_xy(lon, lat)
        found = self.net.getNeighboringEdges(x, y, r=radius_m, includeJunctions=False)
        return sorted({e.getID() for e, _ in found if e.getFunction() != "internal"})

    # --- routing -----------------------------------------------------------------------------
    def fastest_path(self, from_edge: str, to_edge: str, vclass: str) -> list[str]:
        path, _ = self.net.getFastestPath(self.edge(from_edge), self.edge(to_edge), vClass=vclass)
        if not path:
            raise ValueError(f"no {vclass} route from {from_edge} to {to_edge}")
        return [e.getID() for e in path]

    def check_route(self, route: list[str], vclass: str) -> None:
        for a, b in zip(route, route[1:], strict=False):
            ea, eb = self.edge(a), self.edge(b)
            if eb not in ea.getAllowedOutgoing(vclass):
                raise ValueError(f"route not connected for {vclass}: {a} -> {b}")

    def free_flow_times(
        self, route: list[str], speed_factor: float, max_speed: float
    ) -> list[float]:
        """Per-edge free-flow time: length / min(limit x speedFactor, vType maxSpeed).

        This is SUMO's allowed speed of a vehicle on a lane (MSLane::getVehicleMaxSpeed)."""
        out = []
        for eid in route:
            e = self.edge(eid)
            v = min(e.getSpeed() * speed_factor, max_speed)
            out.append(e.getLength() / v if v > 0 else math.inf)
        return out

    def junction_movements(self, prev_edge: str | None, edge_id: str, mode: str) -> list[str]:
        """Internal (via) lanes of the movements to hold at the from-node of `edge_id`.

        mode `all_other_movements`: every movement through the node except prev_edge -> edge_id.
        mode `entering_only`: only movements from other edges into edge_id.
        """
        node = self.edge(edge_id).getFromNode()
        lanes: set[str] = set()
        for inc in node.getIncoming():
            if inc.getFunction() == "internal":
                continue
            for out, conns in inc.getOutgoing().items():
                if inc.getID() == prev_edge and out.getID() == edge_id:
                    continue
                if mode == "entering_only" and out.getID() != edge_id:
                    continue
                for c in conns:
                    via = c.getViaLaneID()
                    if via:
                        lanes.add(via)
        return sorted(lanes)
