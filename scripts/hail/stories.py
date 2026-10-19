"""Before/after map data for the project page's scenario cards (data/stories.json).

For every policy run (against its baseline), Tier B scenario (against its `~baseline`) and
evacuation (against its `~reference`), the edge speed/limit of both runs is averaged over the
three consecutive 5-min bins where the two differ most, and stored per edge as 0-100 (255 = no
data). Edge geometry is stored once per network: main roads only for the city, every road class
except service for a window. Only measured bins are used; nothing is interpolated.

    python -m scripts.hail.stories --out _site/data/stories.json

Synthetic demand, uncalibrated.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import typer
from fastapi.testclient import TestClient

from api.main import create_app

CITY_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary"}
WINDOW_SKIP = {"service", "services", "track", "living_street"}
SPAN_BINS = 3
app = typer.Typer(add_completion=False, help=__doc__)


def _cls(t: str) -> str:
    return t.replace("highway.", "").replace("_link", "")


def parse_edges_bin(buf: bytes) -> tuple[np.ndarray, np.ndarray]:
    assert buf[:4] == b"TTE1"
    n_edges, n_points = struct.unpack_from("<II", buf, 4)
    starts = np.frombuffer(buf, "<u4", n_edges + 1, 12)
    pos = np.frombuffer(buf, "<f4", 2 * n_points, 12 + 4 * (n_edges + 1)).reshape(-1, 2)
    return starts, pos


class Stories:
    def __init__(self) -> None:
        self.c = TestClient(create_app())
        self.geoms: dict[str, dict[str, Any]] = {}
        self.keep: dict[str, np.ndarray] = {}

    def get(self, url: str, **params: Any) -> Any:
        r = self.c.get(url, params=params or None)
        return r if r.status_code == 200 else None

    def geometry(self, nhash: str, tier: str) -> None:
        key = f"{nhash}:{tier}"
        if key in self.geoms:
            return
        info = self.get(f"/api/networks/{nhash}/edges.json").json()
        starts, pos = parse_edges_bin(self.get(f"/api/networks/{nhash}/edges.bin").content)
        types = [_cls(t) for t in info["types"]]
        keep = [i for i, t in enumerate(types) if (t in CITY_CLASSES if tier == "A" else t not in WINDOW_SKIP)]
        sel = pos[np.concatenate([np.arange(starts[i], starts[i + 1]) for i in keep])]
        w, s = sel.min(axis=0)
        e, n = sel.max(axis=0)
        span = float(max(e - w, n - s)) or 1.0
        lines = []
        for i in keep:
            p = pos[starts[i] : starts[i + 1]]
            q = np.rint(np.column_stack(((p[:, 0] - w) / span * 10000, (n - p[:, 1]) / span * 10000))).astype(int)
            flat: list[int] = [list(sorted(CITY_CLASSES)).index(types[i]) if types[i] in CITY_CLASSES else 5]
            for x, y in q:
                if len(flat) < 3 or (flat[-2], flat[-1]) != (x, y):
                    flat.extend((int(x), int(y)))
            lines.append(flat)
        self.geoms[key] = {"bbox": [float(w), float(s), float(e), float(n)], "span": span, "lines": lines,
                           "names": [info["names"][i] for i in keep]}
        self.keep[key] = np.array(keep)

    def bins(self, run: str, info: dict[str, Any]) -> np.ndarray:
        pack = []
        for i in range(int(info["n_bins"])):
            r = self.get(f"/api/runs/{run}/bins/{i}", metric="speed_rel")
            pack.append(np.frombuffer(r.content, "<f4") if r is not None else np.full(int(info["n_edges"]), np.nan, np.float32))
        return np.vstack(pack)

    def story(self, sid: str, kind: str, run: dict[str, Any], base_id: str) -> dict[str, Any] | None:
        rid, nhash, tier = run["run_id"], run["network_hash"], run["tier"]
        bi, ri = self.get(f"/api/runs/{base_id}/bins"), self.get(f"/api/runs/{rid}/bins")
        if bi is None or ri is None:
            return None
        bi, ri = bi.json(), ri.json()
        n = min(int(bi["n_bins"]), int(ri["n_bins"]))
        a, b = self.bins(base_id, bi)[:n], self.bins(rid, ri)[:n]
        self.geometry(nhash, tier)
        keep = self.keep[f"{nhash}:{tier}"]
        a, b = a[:, keep], b[:, keep]
        diff = np.nan_to_num(np.abs(b - a), nan=0.0).mean(axis=1)
        k = max(1, min(SPAN_BINS, n))
        score = np.convolve(diff, np.ones(k), "valid")
        j0 = int(np.argmax(score)) if len(score) else 0
        import warnings

        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ma, mb = np.nanmean(a[j0 : j0 + k], axis=0), np.nanmean(b[j0 : j0 + k], axis=0)

        def code(v: np.ndarray) -> list[int]:
            return [255 if not np.isfinite(x) else int(round(min(max(x, 0), 1.2) * 100)) for x in v]

        begin = float(ri.get("begin_s") or 0) + j0 * float(ri["bin_s"])
        changed = np.isfinite(ma) & np.isfinite(mb) & (np.abs(mb - ma) >= 0.15)
        return {"id": sid, "kind": kind, "tier": tier, "geom": f"{nhash}:{tier}", "run": rid, "base": base_id,
                "t0_s": begin, "t1_s": begin + k * float(ri["bin_s"]),
                "before": code(ma), "after": code(mb),
                "slower_edges": int((changed & (mb < ma)).sum()), "faster_edges": int((changed & (mb > ma)).sum())}


def build(out: Path) -> dict[str, Any]:
    S = Stories()
    runs = S.get("/api/runs").json()
    by_id = {r["run_id"]: r for r in runs}
    stories = []
    for r in runs:
        rid = r["run_id"]
        if (("demo" in rid) and not __import__("os").environ.get("STORIES_DEMO")) or rid.startswith(("smoke-", "tierA-exit", "hail-source")):
            continue
        if r["kind"] == "policy" and not rid.endswith("--control"):
            rep = S.get(f"/api/runs/{rid}/policy-report")
            base = rep.json().get("compare_baseline") if rep is not None else None
            if base in by_id:
                pid = rep.json().get("policy")
                pid = pid.get("id") if isinstance(pid, dict) else pid
                st = S.story(pid or rid, "policy", r, base)
                stories.append(st)
        elif r["kind"] in ("scenario", "evacuation") and "~" not in rid:
            base = f"{rid}~baseline" if r["kind"] == "scenario" else f"{rid}~reference"
            if base in by_id:
                stories.append(S.story(rid.split("-")[0], r["kind"], r, base))
    stories = [s for s in stories if s]
    data = {"label": "synthetic demand, uncalibrated", "metric": "speed_rel", "geoms": S.geoms, "stories": stories}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return {"stories": [(s["id"], s["kind"], s["t0_s"], s["slower_edges"], s["faster_edges"]) for s in stories],
            "kb": out.stat().st_size // 1024}


@app.command()
def main(out: Path = typer.Option(Path("_site/data/stories.json"))) -> None:
    typer.echo(json.dumps(build(out), ensure_ascii=False))


if __name__ == "__main__":
    app()
