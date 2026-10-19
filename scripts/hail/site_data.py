"""Data files for the project page (site/): Hail's main roads for the hero, and a results summary.

    python -m scripts.hail.site_data --edges web/public/data/edges.geojson --runs runs --out _site/data

roads.json   main roads (motorway..tertiary) as flat, quantised polylines in a local 0..10000 frame:
             {"bbox": [w, s, e, n], "classes": [...], "lines": [[class, x0, y0, x1, y1, ...], ...]}
results.json headline numbers read from the policy, scenario, strategist and evacuation reports in
             runs/ (only what the reports measured; nothing is computed here). Synthetic demand,
             uncalibrated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

HIDDEN = set(__import__("json").loads((Path(__file__).resolve().parents[2] / "site" / "hidden.json").read_text())["ids"])

CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary"]
app = typer.Typer(add_completion=False, help=__doc__)


def roads(edges: Path) -> dict[str, Any]:
    fc = json.loads(edges.read_text())
    feats = []
    for f in fc["features"]:
        t = str(f["properties"].get("type", "")).replace("highway.", "").replace("_link", "")
        if t in CLASSES:
            feats.append((CLASSES.index(t), f["geometry"]["coordinates"]))
    xs = [c[0] for _, cs in feats for c in cs]
    ys = [c[1] for _, cs in feats for c in cs]
    w, e, s, n = min(xs), max(xs), min(ys), max(ys)
    span = max(e - w, n - s)
    lines = []
    for k, cs in feats:
        pts: list[int] = [k]
        last = None
        for lon, lat in cs:
            p = (round((lon - w) / span * 10000), round((n - lat) / span * 10000))
            if p != last:
                pts.extend(p)
                last = p
        if len(pts) >= 5:
            lines.append(pts)
    return {"bbox": [w, s, e, n], "span": span, "classes": CLASSES, "lines": lines}


def _read(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def results(runs: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"label": "synthetic demand, uncalibrated", "policies": [], "scenarios": [],
                           "strategist": [], "evacuations": [], "baselines": []}
    dirs = sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []
    for d in dirs:
        if d.name.startswith("demo") or "-demo-" in d.name or d.name.endswith("--control"):
            continue  # the demo-window runs are tests, not results
        meta = _read(d / "meta.json") or {}
        pol = _read(d / "policy_report.json")
        if pol:
            out["policies"].append({"run_id": d.name, "id": pol.get("policy"), "title": pol.get("title"),
                                    "sample": pol.get("sample"),
                                    "kpis": {k["kpi"]: {"baseline": k.get("baseline"), "policy": k.get("policy"),
                                                        "delta_pct": k.get("delta_pct"), "unit": k.get("unit")}
                                             for k in pol.get("kpis") or []}})
        sc = _read(d / "scenario_report.json")
        if sc and sc.get("window") != "demo":
            k = sc.get("kpis") or {}
            keep = ("mean_delay_s", "mean_travel_time_s", "mean_speed_kmh", "vht", "queue_max_m", "halted_max_veh", "teleports")
            out["scenarios"].append({"run_id": d.name, "id": sc.get("scenario"), "title": sc.get("title") or sc.get("label"),
                                     "baseline": {x: (k.get("baseline") or {}).get(x) for x in keep},
                                     "scenario": {x: (k.get("scenario") or {}).get(x) for x in keep},
                                     "emergency": sc.get("emergency"), "convoy": sc.get("convoy")})
        ev = _read(d / "evacuation_report.json")
        if ev and ev.get("window") != "demo":
            out["evacuations"].append({"run_id": d.name, "id": ev.get("scenario"), "title": ev.get("title") or ev.get("label"),
                                       "clearance": (ev.get("result") or {}).get("clearance")})
        if d.name.startswith("baseline-") and meta.get("results"):
            out["baselines"].append({"run_id": d.name, "daytype": meta.get("daytype"), "sample": meta.get("sample"),
                                     "results": meta.get("results")})
    for f in sorted((runs / "strategist").glob("*/recommendation.json")) if (runs / "strategist").exists() else []:
        rec = _read(f)
        if not rec or str(rec.get("window")) == "demo":
            continue
        out["strategist"].append({"id": rec.get("scenario"), "title": rec.get("title"), "options": [
            {k: o.get(k) for k in ("rank", "label", "travel_time_s", "no_strategy_tt_s", "vs_no_strategy_s",
                                   "classification", "reason")} for o in (rec.get("options") or [])[:3]]})
    for key in ("policies", "scenarios", "evacuations", "strategist"):
        out[key] = [x for x in out[key] if x.get("id") not in HIDDEN]
    return out


@app.command()
def main(edges: Path = typer.Option(...), runs: Path = typer.Option(Path("runs")), out: Path = typer.Option(...)) -> None:
    out.mkdir(parents=True, exist_ok=True)
    r = roads(edges)
    (out / "roads.json").write_text(json.dumps(r, separators=(",", ":")))
    res = results(runs)
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    typer.echo(f"roads: {len(r['lines'])} lines, {(out / 'roads.json').stat().st_size // 1024} KB; "
               f"results: {len(res['policies'])} policies, {len(res['scenarios'])} scenarios")


if __name__ == "__main__":
    app()
