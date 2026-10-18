"""Write clearly FICTIONAL example reports into a Tier B (demo-window) run so that the viewer's
policy, scenario and strategist views can be demonstrated before Tracks A and B produce real ones.

    python -m api.examples <tier_B_run_id> [--baseline <run_id>] [--seed 0]

Every file carries "example": true, "fictional": true, the synthetic label and a `note`. All values
are illustrative placeholders, not model results. Output is deterministic (seeded, sorted keys).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import typer

from api import settings
from api.districts import district_map
from api.edges import EdgeIndex, load_edge_index
from api.runs import iter_runs, read_meta

NOTE = (
    "FICTIONAL EXAMPLE for viewer demonstration only. Values are illustrative placeholders, "
    "not simulation or strategist results."
)
EXAMPLE_TIMESTAMP = "2026-10-16T00:00:00Z"  # fixed so the files are reproducible
COORD_DECIMALS = 6
# illustrative ranges for the fictional numbers (not behavioural parameters)
ILLUSTRATIVE_DISTRICT_DELTA_PCT = (-12.0, 12.0)
ILLUSTRATIVE_VKT_DELTA_PCT = (-15.0, 5.0)


def _header(run_id: str, baseline: str | None) -> dict[str, Any]:
    return {
        "label": settings.LABEL,
        "run_id": run_id,
        "baseline_run_id": baseline,
        "example": True,
        "fictional": True,
        "note": NOTE,
    }


def _pick_edges(index: EdgeIndex, lanes: list[int], k: int, rng: random.Random) -> list[int]:
    multi = sorted(i for i in range(index.n_edges) if lanes[i] >= 2 and len(index.path(i)) >= 2)
    pool = multi if len(multi) >= k else sorted(range(index.n_edges))
    return rng.sample(pool, k)


def _line(index: EdgeIndex, i: int) -> dict[str, Any]:
    coords = np.round(index.path(i).astype(np.float64), COORD_DECIMALS).tolist()
    return {"type": "LineString", "coordinates": coords}


def _point(mid: np.ndarray) -> dict[str, Any]:
    return {"type": "Point", "coordinates": np.round(mid, COORD_DECIMALS).tolist()}


def _u(rng: random.Random, lo_hi: tuple[float, float]) -> float:
    return round(rng.uniform(*lo_hi), 1)


def build_examples(run: Path, baseline: str | None, seed: int) -> dict[str, dict[str, Any]]:
    meta = read_meta(run)
    if meta is None or meta.get("tier") != "B":
        raise typer.BadParameter(f"{run.name}: examples are written into Tier B runs only")
    index = load_edge_index(settings.resolve_repo_path(meta["network"]), meta["network_hash"])
    attrs = json.loads((settings.cache_dir() / meta["network_hash"] / "edges.json").read_text())
    names, lanes = attrs["names"], attrs["lanes"]
    rng = random.Random(seed)
    accident, closure, *detour = _pick_edges(index, lanes, 5, rng)
    mids = index.midpoints()
    begin = int(meta.get("begin_s", 0))
    span = int(meta.get("sim_seconds", 0))
    ev_begin, ev_end = begin + span // 2, begin + (5 * span) // 6
    run_id = run.name

    def label(i: int) -> str:
        return names[i] or f"edge {index.edge_ids[i]}"

    assign, info = district_map(index)
    present = sorted({int(d) for d in assign if d >= 0})
    policy = {
        **_header(run_id, baseline),
        "policy": {
            "id": "example-remote-work",
            "name": "Example: remote work (fictional)",
            "file": None,
        },
        "summary": {
            "vkt": {
                "baseline": 1000.0,
                "policy": None,
                "delta_pct": _u(rng, ILLUSTRATIVE_VKT_DELTA_PCT),
                "unit": "veh-km",
            }
        },
        "districts": [
            {
                "district_id": info[d]["district_id"],
                "name_en": info[d]["name_en"],
                "metrics": {
                    "mean_speed_delta_pct": _u(rng, ILLUSTRATIVE_DISTRICT_DELTA_PCT),
                    "vkt_delta_pct": _u(rng, ILLUSTRATIVE_VKT_DELTA_PCT),
                },
            }
            for d in present
        ],
        "assumptions": [],
    }
    vkt = policy["summary"]["vkt"]
    vkt["policy"] = round(vkt["baseline"] * (1 + vkt["delta_pct"] / 100), 1)

    scenario = {
        **_header(run_id, baseline),
        "scenario": {"id": "example-accident", "name": "Example accident"},
        "events": [
            {
                "id": "ev1",
                "type": "accident",
                "begin_s": ev_begin,
                "end_s": ev_end,
                "edges": [index.edge_ids[accident]],
                "geometry": _point(mids[accident]),
                "description": f"Fictional collision on {label(accident)}; one lane blocked",
            }
        ],
        "closures": [
            {
                "id": "cl1",
                "edges": [index.edge_ids[closure]],
                "begin_s": ev_begin,
                "end_s": ev_end,
                "reason": "fictional closure for demonstration",
                "geometry": _line(index, closure),
            }
        ],
        "summary": {
            "delay_veh_h": {"baseline": 10.0, "scenario": 18.0, "delta_pct": 80.0, "unit": "veh-h"}
        },
    }
    scenario["scenario"]["fictional"] = True

    recs = {
        **_header(run_id, baseline),
        "incident_id": "ev1",
        "generated_at": EXAMPLE_TIMESTAMP,
        "options": [
            {
                "option_id": "opt-1",
                "rank": 1,
                "title": f"Reroute traffic away from {label(accident)} (fictional)",
                "action_class": "high_impact",
                "requires_approval": True,
                "score": 0.8,
                "explanation": "Illustrative: diverts through-traffic onto parallel streets.",
                "effects": {"delay_veh_h_delta_pct": -30.0},
                "actions": [{"type": "reroute", "edges": [index.edge_ids[i] for i in detour]}],
            },
            {
                "option_id": "opt-2",
                "rank": 2,
                "title": "Extend green time at the nearest signal (fictional)",
                "action_class": "high_impact",
                "requires_approval": True,
                "score": 0.6,
                "explanation": "Illustrative: more green for the congested approach.",
                "effects": {"delay_veh_h_delta_pct": -15.0},
                "actions": [{"type": "signal_timing", "edges": [index.edge_ids[detour[0]]]}],
            },
            {
                "option_id": "opt-3",
                "rank": 3,
                "title": "Publish a traveller advisory (fictional)",
                "action_class": "advisory",
                "requires_approval": False,
                "score": 0.4,
                "explanation": "Illustrative: an information message only; no control action.",
                "effects": {"delay_veh_h_delta_pct": -5.0},
                "actions": [{"type": "advisory", "edges": [index.edge_ids[accident]]}],
            },
        ],
    }
    return {
        "policy_report.json": policy,
        "scenario_report.json": scenario,
        "recommendations.json": recs,
    }


def write_examples(run: Path, baseline: str | None = None, seed: int = 0) -> list[Path]:
    meta = read_meta(run) or {}
    if baseline is None:
        others = sorted(
            p.name
            for p, m in iter_runs()
            if p.name != run.name and m.get("network_hash") == meta.get("network_hash")
        )
        baseline = others[0] if others else None
    out = []
    for name, data in build_examples(run, baseline, seed).items():
        path = run / name
        path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        out.append(path)
    return out


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    run_id: str,
    baseline: str | None = typer.Option(None, help="comparison run (default: same network)"),
    seed: int = typer.Option(0),
) -> None:
    run = settings.runs_dir() / run_id
    if not run.is_dir() or run_id.startswith((".", "_")) or "/" in run_id:
        raise typer.BadParameter(f"{run_id}: not a run under {settings.runs_dir()}")
    for path in write_examples(run, baseline, seed):
        typer.echo(f"wrote {path}")


if __name__ == "__main__":
    app()
