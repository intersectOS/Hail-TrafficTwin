"""Deterministic, vectorised sampling helpers shared by the population modules.

Each step draws from its own RNG stream (`stream(seed, name)`), so changing one step never shifts
the random numbers of another, and a 10 % sample is a subset of the 25 % sample.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd


def stream(seed: int, name: str) -> np.random.Generator:
    """Independent RNG per (seed, step name)."""
    key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little")
    return np.random.default_rng([seed, key])


def categorical(rng: np.random.Generator, probs: np.ndarray) -> np.ndarray:
    """One draw per row of a (n, k) probability matrix (rows need not be normalised)."""
    probs = np.asarray(probs, dtype=float)
    cum = np.cumsum(probs, axis=1)
    total = cum[:, -1:]
    u = rng.random((len(probs), 1)) * np.where(total > 0, total, 1.0)
    idx = (u > cum).sum(axis=1)
    return np.minimum(idx, probs.shape[1] - 1)


def choice_from(
    rng: np.random.Generator, values: Sequence, weights: Sequence[float], n: int
) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    return np.asarray(values)[rng.choice(len(values), size=n, p=w / w.sum())]


def dist_table(table: Mapping) -> tuple[list, np.ndarray]:
    """{'1': 0.2, '2': 0.8, 'assumption': ...} -> ([1, 2], probs)."""
    items = [(k, float(v)) for k, v in table.items() if k not in ("source", "assumption")]
    keys = [int(k) if str(k).isdigit() else k for k, _ in items]
    probs = np.array([v for _, v in items])
    return keys, probs / probs.sum()


def gravity_choice(
    rng: np.random.Generator,
    origins: np.ndarray,
    attraction: np.ndarray,
    dist_km: np.ndarray,
    beta: float,
) -> np.ndarray:
    """Destination zone per origin: P(j | i) ~ attraction_j * exp(-beta * d_ij)."""
    utility = attraction[None, :] * np.exp(-beta * dist_km)
    out = np.empty(len(origins), dtype=np.int64)
    if len(origins) == 0:
        return out
    order = np.argsort(origins, kind="stable")
    sorted_o = origins[order]
    bounds = np.flatnonzero(np.diff(sorted_o)) + 1
    for chunk in np.split(np.arange(len(origins)), bounds):
        i = int(sorted_o[chunk[0]])
        p = utility[i]
        if p.sum() <= 0:
            p = attraction
        cum = np.cumsum(p)
        u = rng.random(len(chunk)) * cum[-1]
        out[order[chunk]] = np.minimum(np.searchsorted(cum, u, side="right"), len(p) - 1)
    return out


class EdgeSampler:
    """Draw edges inside a zone with probability proportional to a weight column."""

    def __init__(self, zone_edges: pd.DataFrame, weight: str) -> None:
        df = zone_edges[zone_edges[weight] > 0].sort_values(["zone_id", "edge_id"])
        self.edges = df["edge_id"].to_numpy()
        self.zones = df["zone_id"].to_numpy()
        w = df[weight].to_numpy(dtype=float)
        self.start: dict[int, int] = {}
        self.cum: dict[int, np.ndarray] = {}
        if len(df) == 0:
            return
        bounds = np.flatnonzero(np.diff(self.zones)) + 1
        starts = np.concatenate([[0], bounds])
        ends = np.concatenate([bounds, [len(df)]])
        for s, e in zip(starts, ends, strict=True):
            z = int(self.zones[s])
            self.start[z] = int(s)
            self.cum[z] = np.cumsum(w[s:e])

    def has(self, zone: int) -> bool:
        return zone in self.cum

    def sample(self, rng: np.random.Generator, zones: np.ndarray) -> np.ndarray:
        out = np.empty(len(zones), dtype=object)
        if len(zones) == 0:
            return out
        order = np.argsort(zones, kind="stable")
        sz = zones[order]
        bounds = np.flatnonzero(np.diff(sz)) + 1
        for chunk in np.split(np.arange(len(zones)), bounds):
            z = int(sz[chunk[0]])
            if z not in self.cum:
                raise KeyError(f"zone {z} has no candidate edges")
            cum = self.cum[z]
            u = rng.random(len(chunk)) * cum[-1]
            k = np.minimum(np.searchsorted(cum, u, side="right"), len(cum) - 1)
            out[order[chunk]] = self.edges[self.start[z] + k]
        return out


def truncated_normal(
    rng: np.random.Generator, mean: np.ndarray, sd: np.ndarray, lo: float, hi: float
) -> np.ndarray:
    """Normal draws clipped by resampling (up to 20 rounds), then hard-clipped."""
    mean = np.broadcast_to(np.asarray(mean, dtype=float), np.shape(mean) or (1,)).copy()
    sd = np.broadcast_to(np.asarray(sd, dtype=float), mean.shape)
    x = rng.normal(mean, np.maximum(sd, 1e-9))
    for _ in range(20):
        bad = (x < lo) | (x > hi)
        if not bad.any():
            break
        x[bad] = rng.normal(mean[bad], np.maximum(sd[bad], 1e-9))
    return np.clip(x, lo, hi)


def mixture_times(
    rng: np.random.Generator,
    n: int,
    components: list[tuple[float, float, float]],
    lo: float,
    hi: float,
) -> np.ndarray:
    """n draws (seconds) from a truncated mixture of normals; sd < 0 means uniform on [lo, hi]."""
    if n == 0:
        return np.empty(0)
    w = np.array([c[0] for c in components])
    k = rng.choice(len(components), size=n, p=w / w.sum())
    means = np.array([c[1] for c in components])[k]
    sds = np.array([c[2] for c in components])[k]
    out = np.empty(n)
    uni = sds < 0
    out[uni] = rng.uniform(lo, hi, size=int(uni.sum()))
    if (~uni).any():
        out[~uni] = truncated_normal(rng, means[~uni], sds[~uni], lo, hi)
    return out


def frame_hash(*frames: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for df in frames:
        digest.update(",".join(map(str, df.columns)).encode())
        digest.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
    return digest.hexdigest()[:16]
