"""Edge graph for one vClass with lane closures, Dijkstra and Yen's k-shortest loopless paths.

Nodes are network edges (as in SUMO routes); an arc a -> b exists when some connection from an
open lane of a that allows the vClass reaches a lane of b that allows it. Lanes closed by events
at T are removed, so a fully closed edge has no usable lane and drops out, and a partially
closed edge keeps only the connections of its open lanes. Path cost = sum of node costs.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from itertools import count

from sim.events.netindex import NetIndex


class EdgeGraph:
    def __init__(self, idx: NetIndex, vclass: str, closed_lanes: set[str] | None = None) -> None:
        closed = closed_lanes or set()
        self.vclass = vclass
        self.length: dict[str, float] = {}
        self.succ: dict[str, list[str]] = {}
        usable: dict[str, set[int]] = {}
        for eid, e in idx.edges.items():
            lanes = {
                ln.getIndex()
                for ln in e.getLanes()
                if ln.allows(vclass) and ln.getID() not in closed
            }
            if lanes:
                usable[eid] = lanes
                self.length[eid] = e.getLength()
        for eid, lanes in usable.items():
            e = idx.edges[eid]
            nxt: list[str] = []
            for to, conns in e.getOutgoing().items():
                tid = to.getID()
                if tid not in usable or tid == eid:
                    continue
                if any(
                    c.getFromLane().getIndex() in lanes and c.getToLane().getIndex() in usable[tid]
                    for c in conns
                ):
                    nxt.append(tid)
            self.succ[eid] = sorted(nxt)

    def __contains__(self, edge: str) -> bool:
        return edge in self.succ

    def path_cost(self, path: list[str], cost: dict[str, float]) -> float:
        return sum(cost[e] for e in path)

    def is_path(self, path: list[str]) -> bool:
        return all(p in self.succ for p in path) and all(
            b in self.succ[a] for a, b in zip(path, path[1:], strict=False)
        )

    def dijkstra(
        self,
        src: str,
        dst: str,
        cost: dict[str, float],
        banned_nodes: set[str] | frozenset[str] = frozenset(),
        banned_arcs: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[list[str], float] | None:
        if src not in self.succ or dst not in self.succ or src in banned_nodes:
            return None
        dist = {src: cost[src]}
        prev: dict[str, str] = {}
        tie = count()
        heap = [(cost[src], next(tie), src)]
        done: set[str] = set()
        while heap:
            d, _, u = heapq.heappop(heap)
            if u in done:
                continue
            if u == dst:
                path = [u]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                return path[::-1], d
            done.add(u)
            for v in self.succ[u]:
                if v in banned_nodes or v in done or (u, v) in banned_arcs:
                    continue
                nd = d + cost[v]
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, next(tie), v))
        return None

    def yen(self, src: str, dst: str, cost: dict[str, float]) -> Iterator[tuple[list[str], float]]:
        """Loopless paths in order of increasing cost (Yen 1971), generated lazily."""
        first = self.dijkstra(src, dst, cost)
        if first is None:
            return
        found: list[list[str]] = [first[0]]
        seen = {tuple(first[0])}
        yield first
        cand: list[tuple[float, int, list[str]]] = []
        tie = count()
        while True:
            last = found[-1]
            for i in range(len(last) - 1):
                root = last[: i + 1]
                banned_arcs = {
                    (p[i], p[i + 1]) for p in found if len(p) > i + 1 and p[: i + 1] == root
                }
                spur = self.dijkstra(root[-1], dst, cost, set(root[:-1]), banned_arcs)
                if spur is None:
                    continue
                path = root[:-1] + spur[0]
                if tuple(path) in seen:
                    continue
                seen.add(tuple(path))
                heapq.heappush(cand, (self.path_cost(path, cost), next(tie), path))
            if not cand:
                return
            c, _, path = heapq.heappop(cand)
            found.append(path)
            yield path, c


def overlap(path: list[str], other: list[str], length: dict[str, float]) -> float:
    """Share of `path`'s length that also lies on `other`."""
    total = sum(length[e] for e in path)
    if total <= 0:
        return 1.0
    shared = set(path) & set(other)
    return sum(length[e] for e in path if e in shared) / total
