"""Viewer API on producer-shaped outputs (contract v1.1 §12), built offline on the demo window.

Two small smoke runs supply real SUMO edgeData / FCD. From them the fixture writes the on-disk
layouts the tracks actually produce, using the producers' own writers: a Track B scenario run
(pointer dir + hashed dir with `scenario/` and `baseline/`), an evacuation run, a Track A baseline
and policy run (SUMO-named Parquet, absolute worktree network path, Track A metrics.json and
policy_report.json), an `edgedata.xml.gz`-only run, and strategist recommendations with their
SQLite decision log.
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from api import settings
from api.main import create_app
from sim.metrics import edgedata_to_parquet
from sim.runner import run_smoke
from sim.scenarios.outputs import elements_to_parquet, fcd_to_parquet
from strategist import decision_log as L

LABEL = "synthetic demand, uncalibrated"
SCEN = "scen_demo-demo-s1-0123abcd"
EVAC = "evac_demo-demo-s1-4567ef01"


def _wj(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def _sumo_outputs(smoke: Path, out: Path) -> None:
    """Track B sub-run: SUMO-named edgedata.parquet + fcd.parquet (sim.scenarios.outputs)."""
    out.mkdir(parents=True)
    shutil.copy(smoke / "edgedata.xml", out / "edgedata.xml")
    elements_to_parquet(out / "edgedata.xml", "edge", out / "edgedata.parquet", ("begin", "end"))
    shutil.copy(smoke / "fcd.xml", out / "fcd.xml")
    fcd_to_parquet(out / "fcd.xml", out / "fcd.parquet", delete_xml=True)


def _producer_meta(smoke_meta: dict[str, Any], **kw: Any) -> dict[str, Any]:
    keep = ("seed", "config_hash", "network", "network_hash", "population_hash", "sumo_version")
    return {"label": LABEL, "tier": "B", "mode": "micro", **{k: smoke_meta[k] for k in keep}, **kw}


@pytest.fixture(scope="session")
def prod(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    root = tmp_path_factory.mktemp("producers")
    runs, smokes = root / "runs", root / "smokes"
    mp = pytest.MonkeyPatch()
    mp.setenv("TT_RUNS_DIR", str(runs))
    mp.delenv("TT_CACHE_DIR", raising=False)
    mp.delenv("TT_STRATEGIST_DB", raising=False)
    mp.delenv("TT_RUNS_READONLY", raising=False)
    a = run_smoke("B", seed=1, end=600, runs_dir=smokes, quiet=True, fcd=True)
    b = run_smoke("B", seed=2, end=600, runs_dir=smokes, quiet=True, fcd=True)
    sa, sb = smokes / a["run_id"], smokes / b["run_id"]
    edges = pq.read_table(_first_edges(sa))["id"].to_pylist()

    # -- Track B scenario run: pointer dir + hashed dir with scenario/ and baseline/
    scen = runs / SCEN
    _sumo_outputs(sa, scen / "scenario")
    _sumo_outputs(sb, scen / "baseline")
    meta = _producer_meta(a, run_id=SCEN, kind="scenario", scenario="scen_demo", window="demo")
    report = {
        "scenario": "scen_demo",
        "title": "Fictional demo crash",
        "label": LABEL,
        "fictional": True,
        "begin": 0.0,
        "end": 600.0,
        "kpis": {
            "baseline": {"mean_delay_s": 10.0, "vkt": 100.0, "top_queued_edges": []},
            "scenario": {"mean_delay_s": 15.0, "vkt": 98.0, "top_queued_edges": []},
        },
        "delta": {"mean_delay_s": {"delta": 5.0, "pct": 50.0}},
        "events": [
            {
                "type": "accident",
                "id": "crash",
                "start": 60.0,
                "end": 300.0,
                "edges": [edges[0]],
                "full_closure": True,
                "closed_lanes": [f"{edges[0]}_0"],
            },
            {
                "type": "emergency_trip",
                "id": "amb",
                "start": 120.0,
                "end": None,
                "max_end": 500.0,
                "route": edges[:3],
            },
            {
                "type": "flood",
                "id": "fl",
                "start": 100.0,
                "end": 400.0,
                "closure_start": 200.0,
                "closed_edges": [edges[1]],
                "sites": [{"edges": [edges[1]]}],
            },
        ],
        "event_log": [{"t": 240.0, "event": "amb", "action": "end"}],
    }
    _wj(scen / "meta.json", meta)
    _wj(scen / "scenario_report.json", report)
    alias = runs / "scen_demo"
    _wj(alias / "meta.json", meta)
    _wj(alias / "scenario_report.json", report)
    (alias / "RUN_DIR").write_text(f"runs/{SCEN}\n")

    # -- evacuation run
    evac = runs / EVAC
    _sumo_outputs(sa, evac / "evacuation")
    _sumo_outputs(sb, evac / "reference")
    _wj(
        evac / "meta.json",
        _producer_meta(
            a, run_id=EVAC, kind="evacuation", scenario="evac_demo", window="demo", fcd=True
        ),
    )
    _wj(
        evac / "evacuation_report.json",
        {
            "scenario": "evac_demo",
            "title": "Fictional demo crowd",
            "label": LABEL,
            "fictional": True,
            "begin": 0.0,
            "end": 600.0,
            "evacuation": {
                "type": "evacuation",
                "id": "crowd",
                "start": 0.0,
                "end": None,
                "order_t": 120.0,
                "phasing": "simultaneous",
                "exit_assignment": "nearest",
                "contraflow": [],
                "zone": [[39.15, 21.54], [39.16, 21.54], [39.16, 21.55], [39.15, 21.55]],
                "exits": [{"edge": edges[2], "name": "Exit A", "lon": 39.155, "lat": 21.545}],
                "assigned": {edges[2]: 40},
                "corridors": [{"id": "cf1", "name": "corridor", "inbound_edges": [edges[3]]}],
            },
            "result": {
                "clearance": {"vehicles": 40, "t90_s": 300.0, "t100_s": 420.0},
                "background": {"delay_veh_h": 3.0},
                "teleports": 0,
            },
            "reference": {"background": {"delay_veh_h": 2.0}},
            "window_kpis": {"reference": {"vkt": 90.0}, "evacuation": {"vkt": 120.0}},
            "other_events": [],
            "event_log": [],
        },
    )

    # -- Track A flat runs: SUMO-named Parquet, absolute worktree network path
    net_abs = f"/elsewhere/TrafficTwin/.worktrees/trackA/{a['network']}"
    for name, smoke, kind in (("base_demo", sb, "baseline"), ("pol_demo", sa, "policy")):
        d = runs / name
        d.mkdir(parents=True)
        edgedata_to_parquet(smoke / "edgedata.xml", d / "edgedata.parquet")
        m = {
            **_producer_meta(a, run_id=name, kind=kind),
            "tier": "A",
            "mode": "meso",
            "network": net_abs,
            "daytype": "weekday",
            "sample": 0.1,
            "sim_end_s": 600.0,
            "run_end_s": 600.0,
        }
        if kind == "policy":
            m.update(
                policy="pol_demo",
                policy_title="Demo policy",
                policy_file="sim/policies/x.yaml",
                compare_baseline="base_demo",
            )
        _wj(d / "meta.json", m)
    _wj(
        runs / "base_demo" / "metrics.json",
        {"label": LABEL, "run_id": "base_demo", "summary": {"vkt": 1000.0, "mean_speed_kmh": 30.0}},
    )
    feats = json.loads(settings.districts_path().read_text())["features"]
    names = [f["properties"]["name_en"] for f in feats[:2]]
    pq.write_table(
        pa.table(
            {
                "zone_id": [0, 1],
                "name_en": names,
                "name_ar": ["", ""],
                "trips_base": [100.0, 50.0],
                "trips_policy": [90.0, 50.0],
                "mean_delay_s_base": [100.0, 80.0],
                "mean_delay_s_policy": [90.0, 88.0],
                "mean_speed_kmh_base": [20.0, 30.0],
                "mean_speed_kmh_policy": [22.0, 27.0],
                "vkt_base": [1000.0, 500.0],
                "vkt_policy": [950.0, 510.0],
                "delta_delay_s": [-10.0, 8.0],
            }
        ),
        runs / "pol_demo" / "policy_districts.parquet",
    )
    _wj(
        runs / "pol_demo" / "policy_report.json",
        {
            "label": LABEL,
            "policy": "pol_demo",
            "title": "Demo policy",
            "run_id": "pol_demo",
            "compare_baseline": "base_demo",
            "kpis": [
                {
                    "kpi": "mean_delay_s",
                    "unit": "s",
                    "baseline": 100.0,
                    "policy": 90.0,
                    "delta": -10.0,
                    "delta_pct": -10.0,
                    "verdict": "better",
                }
            ],
            "districts": {"winners": [{"name_en": names[0]}], "losers": []},
            "assumption_ids": {"policy": ["A-pol-001"], "daytype": ["A-day-001", "A-pol-001"]},
        },
    )

    # -- gz-only run (baseline writers may leave edgedata.xml.gz)
    gzr = runs / "gz_demo"
    gzr.mkdir()
    with (sa / "edgedata.xml").open("rb") as src, gzip.open(gzr / "edgedata.xml.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    _wj(
        gzr / "meta.json",
        {**_producer_meta(a, run_id="gz_demo", kind="baseline"), "sim_seconds": 600},
    )

    # -- strategist: recommendations + SQLite decision log
    st = runs / "strategist"
    db = st / "decisions.sqlite"
    recs = {}
    for scenario, opts in (("scen_demo", 2), ("orphan_demo", 1)):
        options = [
            {
                "rank": k,
                "candidate_id": f"c{k}",
                "label": f"Option {k}",
                "score": 10.0 * k,
                "classification": "approval_required" if k == 2 else "auto_eligible",
                "reason": f"because {k}",
                "travel_time_s": 60.0 + k,
                "added_veh_h": -0.1,
                "actions": [{"type": "reroute"}],
            }
            for k in range(1, opts + 1)
        ]
        entry = L.append(
            db,
            "recommendation",
            f"snap-{scenario}",
            [],
            [],
            {"options": options, "run_dir": f"runs/strategist/x-{scenario}"},
        )
        rec = {
            "label": LABEL,
            "recommendation_id": entry["record_id"],
            "log_hash": entry["hash"],
            "scenario": scenario,
            "title": f"{scenario} (fictional)",
            "fictional": True,
            "window": "demo",
            "seed": 1,
            "options": options,
            "snapshot": {"t_dispatch": 120.0, "network_hash": a["network_hash"]},
            "fork": {"net": f"/elsewhere/.worktrees/trackB/{a['network']}", "end": 600.0},
            "closed_lanes_at_t": [f"{edges[0]}_0"],
            "routes": [{"name": "Route A", "edges": edges[:2], "length_m": 100.0, "ff_s": 9.0}],
        }
        _wj(st / entry["record_id"] / "recommendation.json", rec)
        _wj(st / f"{scenario}-demo-s1" / "recommendation.json", rec)  # latest copy
        recs[scenario] = rec
    yield {
        "runs": runs,
        "smoke_a": sa,
        "smoke_b": sb,
        "meta": a,
        "edges": edges,
        "recs": recs,
        "db": db,
    }
    mp.undo()


def _first_edges(smoke: Path) -> Path:
    """A SUMO-named table of the smoke run's edges (ids with data), for event fixtures."""
    out = smoke / "_ids.parquet"
    if not out.exists():
        elements_to_parquet(smoke / "edgedata.xml", "edge", out, ("begin", "end"))
    return out


@pytest.fixture(scope="session")
def client(prod: dict[str, Any]) -> TestClient:
    return TestClient(create_app())


def test_listing_aliases_and_subruns(client: TestClient, prod: dict[str, Any]) -> None:
    runs = {r["run_id"]: r for r in client.get("/api/runs").json()}
    assert "scen_demo" not in runs  # pointer dir is an alias, not a second listing
    assert SCEN in runs and f"{SCEN}~baseline" in runs
    assert runs[SCEN]["baseline_run_id"] == f"{SCEN}~baseline"
    assert runs[f"{SCEN}~baseline"]["parent_run_id"] == SCEN
    assert runs[SCEN]["has"]["edgedata"] and runs[SCEN]["has"]["fcd"]
    assert runs[SCEN]["has"]["scenario_report"] and runs[SCEN]["has"]["recommendations"]
    assert runs[EVAC]["baseline_run_id"] == f"{EVAC}~reference"
    assert runs[EVAC]["kind"] == "evacuation" and runs[EVAC]["has"]["scenario_report"]
    assert "strategist~orphan_demo-demo-s1" in runs  # recommendation without a sim run
    assert "strategist~scen_demo-demo-s1" not in runs  # matched to SCEN instead
    assert "strategist" not in runs
    alias = client.get("/api/runs/scen_demo").json()
    assert alias["run_id"] == SCEN and alias["sim_seconds"] == 600


def test_nested_bins_match_contract_ingest(client: TestClient, prod: dict[str, Any]) -> None:
    """Producer-schema bins of the scenario sub-run equal v1 bins ingested from the same XML."""
    info = client.get(f"/api/runs/{SCEN}/bins").json()
    assert info["layout"] == "sparse-v1" and info["n_bins"] == 2 and info["unmatched_edges"] == 0
    smoke = prod["runs"] / "smoke_copy"
    shutil.copytree(prod["smoke_a"], smoke, ignore=shutil.ignore_patterns("*.parquet"))
    ref = client.get("/api/runs/smoke_copy/bins").json()
    assert ref["rows"] == info["rows"]
    for metric in ("speed_ms", "speed_rel", "flow_veh_h", "delay_s_per_veh", "speed_kmh"):
        for i in range(2):
            got = np.frombuffer(
                client.get(f"/api/runs/{SCEN}/bins/{i}?metric={metric}").content, "<f4"
            )
            exp = np.frombuffer(
                client.get(f"/api/runs/smoke_copy/bins/{i}?metric={metric}").content, "<f4"
            )
            np.testing.assert_allclose(got, exp, rtol=1e-5, equal_nan=True)
    shutil.rmtree(smoke)


def test_producer_files_never_rewritten(client: TestClient, prod: dict[str, Any]) -> None:
    sub = prod["runs"] / SCEN / "scenario"
    before = {p.name: p.read_bytes() for p in sub.glob("*.parquet")}
    client.get(f"/api/runs/{SCEN}/bins")
    client.get(f"/api/runs/{SCEN}/trajectories?step=10")
    os_names = {p.name for p in sub.iterdir()}
    assert {p.name: p.read_bytes() for p in sub.glob("*.parquet")} == before
    assert os_names == {"edgedata.xml", "edgedata.parquet", "fcd.parquet"}


def test_nested_trajectories(client: TestClient, prod: dict[str, Any]) -> None:
    body = client.get(f"/api/runs/{SCEN}/trajectories").json()
    n_veh = len(
        set(pq.read_table(prod["runs"] / SCEN / "scenario" / "fcd.parquet")["id"].to_pylist())
    )
    assert body["n_vehicles"] == n_veh > 0 and body["run_id"] == SCEN
    v = body["vehicles"][0]
    assert v["timestamps"] == sorted(v["timestamps"]) and len(v["path"]) == len(v["speeds"])
    base = client.get(f"/api/runs/{SCEN}~baseline/trajectories?step=5").json()
    assert base["vehicles"] and base["run_id"] == f"{SCEN}~baseline"


def test_scenario_report_contract(client: TestClient, prod: dict[str, Any]) -> None:
    rep = client.get(f"/api/runs/{SCEN}/scenario-report").json()
    assert rep["label"] == LABEL and rep["baseline_run_id"] == f"{SCEN}~baseline"
    assert rep["scenario"] == {"id": "scen_demo", "name": "Fictional demo crash", "fictional": True}
    ev = {e["id"]: e for e in rep["events"]}
    assert ev["crash"]["type"] == "accident" and ev["crash"]["begin_s"] == 60.0
    assert ev["amb"]["type"] == "other" and ev["amb"]["producer_type"] == "emergency_trip"
    assert ev["amb"]["end_s"] == 240.0 and ev["amb"]["edges"] == prod["edges"][:3]
    assert ev["fl"]["edges"] == [prod["edges"][1]]
    cl = {c["id"]: c for c in rep["closures"]}
    assert cl["crash:closure"]["edges"] == [prod["edges"][0]]
    assert cl["fl:closure"]["begin_s"] == 200.0 and cl["fl:closure"]["end_s"] == 400.0
    assert rep["summary"]["mean_delay_s"] == {
        "baseline": 10.0,
        "scenario": 15.0,
        "unit": "s",
        "delta_pct": 50.0,
    }
    m = client.get(f"/api/runs/{SCEN}/metrics").json()["metrics"]
    mb = client.get(f"/api/runs/{SCEN}~baseline/metrics").json()["metrics"]
    assert m["mean_delay_s"]["value"] == 15.0 and mb["mean_delay_s"]["value"] == 10.0
    assert client.get(f"/api/runs/{SCEN}~baseline/scenario-report").status_code == 404


def test_evacuation_contract(client: TestClient, prod: dict[str, Any]) -> None:
    rep = client.get(f"/api/runs/{EVAC}/scenario-report").json()
    zone = rep["events"][0]
    assert zone["type"] == "evacuation" and zone["begin_s"] == 120.0 and zone["end_s"] == 600.0
    ring = zone["geometry"]["coordinates"][0]
    assert zone["geometry"]["type"] == "Polygon" and ring[0] == ring[-1] and len(ring) == 5
    exit_ev = rep["events"][1]
    assert exit_ev["geometry"]["type"] == "Point" and exit_ev["edges"] == [prod["edges"][2]]
    assert rep["closures"][0]["id"] == "contraflow:cf1"
    assert rep["summary"]["vkt"]["scenario"] == 120.0
    m = client.get(f"/api/runs/{EVAC}/metrics").json()
    assert m["source"] == "evacuation_report.json"
    assert m["metrics"]["clearance_t90_s"] == {"value": 300.0, "unit": "s"}
    ref = client.get(f"/api/runs/{EVAC}~reference/metrics").json()["metrics"]
    assert ref["background_delay_veh_h"]["value"] == 2.0
    assert client.get(f"/api/runs/{EVAC}/bins").json()["n_bins"] == 2


def test_track_a_meta_metrics_policy(client: TestClient, prod: dict[str, Any]) -> None:
    meta = client.get("/api/runs/pol_demo").json()
    assert meta["network"] == prod["meta"]["network"] and meta["network_original"].startswith("/")
    assert meta["sim_seconds"] == 600 and meta["baseline_run_id"] == "base_demo"
    assert meta["policy_id"] == "pol_demo" and meta["day_type"] == "weekday"
    info = client.get("/api/runs/pol_demo/bins").json()
    assert info["n_bins"] == 2 and "occupancy_pct" not in info["metrics_with_data"]
    rel = np.frombuffer(client.get("/api/runs/pol_demo/bins/1?metric=speed_rel").content, "<f4")
    assert np.isfinite(rel).any()  # derived from the network speed limit
    m = client.get("/api/runs/base_demo/metrics").json()
    assert m["metrics"]["mean_speed_kmh"] == {"value": 30.0, "unit": "km/h"}
    assert m["metrics"]["vkt"]["unit"] == "veh-km"
    rep = client.get("/api/runs/pol_demo/policy-report").json()
    assert rep["policy"] == {"id": "pol_demo", "name": "Demo policy", "file": "sim/policies/x.yaml"}
    assert rep["baseline_run_id"] == "base_demo"
    assert rep["summary"]["mean_delay_s"]["delta_pct"] == -10.0
    assert rep["assumptions"] == ["A-pol-001", "A-day-001"]
    assert rep["districts_overview"]["winners"]
    d0 = rep["districts"][0]
    assert d0["district_id"].startswith("r") and d0["metrics"]["mean_speed_delta_pct"] in (
        10.0,
        -10.0,
    )
    eff = client.get("/api/runs/pol_demo/district-effects").json()
    assert eff["source"] == "policy_report" and len(eff["districts"]) == 2
    comp = client.get("/api/runs/pol_demo/district-effects?baseline=gz_demo").json()
    assert comp["source"] == "computed"
    assert client.get("/api/runs/pol_demo/trajectories").status_code == 404  # Tier A


def test_gz_readonly_goes_to_cache(
    client: TestClient, prod: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ro = prod["runs"] / "gz_ro"
    ro.mkdir()
    shutil.copy(prod["runs"] / "gz_demo" / "edgedata.xml.gz", ro / "edgedata.xml.gz")
    meta = json.loads((prod["runs"] / "gz_demo" / "meta.json").read_text())
    _wj(ro / "meta.json", {**meta, "run_id": "gz_ro"})
    monkeypatch.setenv("TT_RUNS_READONLY", "1")
    info = client.get("/api/runs/gz_ro/bins").json()
    assert info["n_bins"] == 2 and info["rows"] > 0
    assert sorted(p.name for p in ro.iterdir()) == ["edgedata.xml.gz", "meta.json"]
    assert (prod["runs"] / "_viewer-cache" / "runs" / "gz_ro" / "edgedata.parquet").exists()


def test_dense_v1_cache_is_rebuilt(client: TestClient, prod: dict[str, Any]) -> None:
    cache = prod["runs"] / "_viewer-cache" / "runs" / EVAC
    client.get(f"/api/runs/{EVAC}/bins")
    info = json.loads((cache / "bins.json").read_text())
    info.pop("layout")
    (cache / "bins.json").write_text(json.dumps(info))  # looks like a v1 dense cache
    assert client.get(f"/api/runs/{EVAC}/bins").json()["layout"] == "sparse-v1"


def test_strategist_recommendations_and_sqlite_decisions(
    client: TestClient, prod: dict[str, Any]
) -> None:
    rec = prod["recs"]["scen_demo"]
    body = client.get(f"/api/runs/{SCEN}/recommendations").json()
    assert body["incident_id"] == rec["recommendation_id"] and body["source"] == "strategist"
    o1, o2 = body["options"]
    assert (o1["option_id"], o1["rank"], o1["action_class"], o1["requires_approval"]) == (
        "opt-1",
        1,
        "advisory",
        False,
    )
    assert o2["action_class"] == "high_impact" and o2["requires_approval"]
    assert o1["title"] == "Option 1" and o1["explanation"] == "because 1"
    assert o1["effects"] == {"travel_time_s": 61.0, "added_veh_h": -0.1}
    assert client.get(f"/api/runs/{SCEN}/decisions").json() == []

    url = f"/api/runs/{SCEN}/recommendations/opt-2/decision"
    entry = client.post(url, json={"decision": "approved", "operator": "duty", "note": "ok"}).json()
    assert entry["log"] == "strategist-sqlite" and entry["option_id"] == "opt-2"
    assert L.verify(prod["db"]) == []  # the strategist's own chain check covers API decisions
    last = L.records(prod["db"])[-1]
    assert last["hash"] == entry["hash"] and last["actor"] == "duty"
    assert json.loads(last["decision"])["applied"] is False
    log = client.get(f"/api/runs/{SCEN}/decisions").json()
    assert [e["hash"] for e in log] == [entry["hash"]]
    again = client.post(url, json={"decision": "rejected", "operator": "duty"})
    assert again.status_code == 409  # one decision per recommendation (strategist rule)
    assert (
        client.post(
            f"/api/runs/{SCEN}/recommendations/opt-9/decision",
            json={"decision": "approved", "operator": "x"},
        ).status_code
        == 404
    )
    assert not (prod["runs"] / SCEN / "decisions.jsonl").exists()


def test_strategist_only_run(client: TestClient, prod: dict[str, Any]) -> None:
    rid = "strategist~orphan_demo-demo-s1"
    meta = client.get(f"/api/runs/{rid}").json()
    assert meta["kind"] == "strategist" and meta["network"] == prod["meta"]["network"]
    assert client.get(f"/api/runs/{rid}/bins").status_code == 404
    rep = client.get(f"/api/runs/{rid}/scenario-report").json()
    assert rep["closures"][0]["edges"] == [prod["edges"][0]]
    assert rep["events"][0]["edges"] == prod["edges"][:2]
    recs = client.get(f"/api/runs/{rid}/recommendations").json()
    assert [o["option_id"] for o in recs["options"]] == ["opt-1"]
    nhash = meta["network_hash"]
    assert client.get(f"/api/networks/{nhash}/edges.json").status_code == 200


def test_unsafe_ids_rejected(client: TestClient) -> None:
    for bad in ("..~baseline", f"{SCEN}~..", "strategist", "_viewer-cache", "a~b~c"):
        assert client.get(f"/api/runs/{bad}").status_code == 404
