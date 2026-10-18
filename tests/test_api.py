"""Viewer API on the demo window (offline, fast): ingest, bins, edge index, districts,
trajectories, reports, decisions, jobs and path safety."""

from __future__ import annotations

import json
import math
import struct
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from api.decisions import GENESIS, entry_hash, verify_chain
from api.edges import HEADER, MAGIC
from api.main import app, create_app
from sim.runner import run_smoke

LABEL = "synthetic demand, uncalibrated"


@pytest.fixture(scope="session")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    root = tmp_path_factory.mktemp("api")
    runs = root / "runs"
    mp = pytest.MonkeyPatch()
    mp.setenv("TT_RUNS_DIR", str(runs))
    mp.delenv("TT_CACHE_DIR", raising=False)  # default: <runs>/_viewer-cache
    mp.setenv("TT_LOGS_DIR", str(root / "logs"))
    a = run_smoke("B", seed=1, end=600, runs_dir=runs, quiet=True, fcd=True)
    b = run_smoke("B", seed=2, end=600, runs_dir=runs, quiet=True, fcd=True)
    yield {"root": root, "runs": runs, "run": a["run_id"], "base": b["run_id"], "meta": a}
    mp.undo()


@pytest.fixture(scope="session")
def client(env: dict[str, Any]) -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    body = TestClient(app).get("/health").json()
    assert body["status"] == "ok"
    assert body["label"] == LABEL


def test_run_list_and_meta(client: TestClient, env: dict[str, Any]) -> None:
    (env["runs"] / "_scratch").mkdir(exist_ok=True)
    (env["runs"] / "no-meta").mkdir(exist_ok=True)
    runs = client.get("/api/runs").json()
    ids = [r["run_id"] for r in runs]
    assert env["run"] in ids and env["base"] in ids
    assert "_scratch" not in ids and "no-meta" not in ids
    r = next(r for r in runs if r["run_id"] == env["run"])
    assert r["tier"] == "B" and r["label"] == LABEL and r["has"]["fcd"] and r["has"]["edgedata"]
    meta = client.get(f"/api/runs/{env['run']}").json()
    assert meta["run_id"] == env["run"] and meta["network_hash"] == env["meta"]["network_hash"]


def test_metrics_fallback(client: TestClient, env: dict[str, Any]) -> None:
    body = client.get(f"/api/runs/{env['run']}/metrics").json()
    assert body["source"] == "meta.result" and body["label"] == LABEL
    assert body["metrics"]["mean_speed_ms"] == {
        "value": env["meta"]["result"]["mean_speed_ms"],
        "unit": "m/s",
    }


def test_ingest_row_counts(client: TestClient, env: dict[str, Any]) -> None:
    from api.ingest import ensure_edgedata, ensure_fcd

    run = env["runs"] / env["run"]
    edp, fcdp = ensure_edgedata(run), ensure_fcd(run)
    assert edp is not None and fcdp is not None
    n_edge = (run / "edgedata.xml").read_text().count("<edge ")
    n_veh = (run / "fcd.xml").read_text().count("<vehicle ")
    ed = pq.read_table(edp)
    assert ed.num_rows == n_edge > 0
    assert str(ed.schema.field("edge_id").type).startswith("dictionary")
    keys = list(zip(ed["bin_begin_s"].to_pylist(), ed["edge_id"].to_pylist(), strict=True))
    assert keys == sorted(keys)
    fcd = pq.read_table(fcdp)
    assert fcd.num_rows == n_veh > 0
    fk = list(zip(fcd["vehicle_id"].to_pylist(), fcd["time_s"].to_pylist(), strict=True))
    assert fk == sorted(fk)


def _edges(client: TestClient, nhash: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    blob = client.get(f"/api/networks/{nhash}/edges.bin").content
    magic, n_edges, n_points = HEADER.unpack_from(blob, 0)
    assert magic == MAGIC
    assert len(blob) == HEADER.size + 4 * (n_edges + 1) + 8 * n_points
    starts = np.frombuffer(blob, "<u4", n_edges + 1, HEADER.size)
    coords = np.frombuffer(blob, "<f4", 2 * n_points, HEADER.size + 4 * (n_edges + 1))
    info = client.get(f"/api/networks/{nhash}/edges.json").json()
    return starts, coords.reshape(-1, 2), info


def test_edges_bin_and_json(client: TestClient, env: dict[str, Any]) -> None:
    nhash = env["meta"]["network_hash"]
    starts, coords, info = _edges(client, nhash)
    n = len(starts) - 1
    assert n == info["n_edges"] == len(info["edge_ids"]) == env["meta"]["network_stats"]["edges"]
    for key in ("names", "types", "lanes", "speed_kmh"):
        assert len(info[key]) == n
    assert starts[0] == 0 and starts[-1] == len(coords) and np.all(np.diff(starts) >= 1)
    # demo window sits in Jeddah
    assert 39.0 < coords[:, 0].min() < coords[:, 0].max() < 39.4
    assert 21.3 < coords[:, 1].min() < coords[:, 1].max() < 21.8
    assert client.get("/api/networks/deadbeef00/edges.bin").status_code == 404
    assert client.get("/api/networks/..%2F..%2Fetc/edges.bin").status_code == 404


def test_bins_and_nan(client: TestClient, env: dict[str, Any]) -> None:
    run = env["run"]
    info = client.get(f"/api/runs/{run}/bins").json()
    assert info["bin_s"] == 300 and info["n_bins"] == 2 and info["label"] == LABEL
    assert "delay_s_per_veh" in info["metrics"] and info["stats"]["speed_ms"]["p50"] > 0
    ed = pq.read_table(env["runs"] / run / "edgedata.parquet").to_pandas()
    edge_ids = client.get(f"/api/networks/{info['network_hash']}/edges.json").json()["edge_ids"]
    pos = {e: i for i, e in enumerate(edge_ids)}
    for i in range(info["n_bins"]):
        resp = client.get(f"/api/runs/{run}/bins/{i}", params={"metric": "speed_ms"})
        assert resp.headers["content-type"] == "application/octet-stream"
        assert len(resp.content) == 4 * info["n_edges"]
        arr = np.frombuffer(resp.content, "<f4")
        rows = ed[ed["bin_begin_s"] == i * info["bin_s"]]
        assert np.isfinite(arr).sum() == rows["speed_ms"].notna().sum()
        e, v = rows.iloc[0]["edge_id"], rows.iloc[0]["speed_ms"]
        assert math.isclose(arr[pos[e]], v, rel_tol=1e-6)
    delay = np.frombuffer(
        client.get(f"/api/runs/{run}/bins/0?metric=delay_s_per_veh").content, "<f4"
    )
    assert np.isnan(delay).any()  # edges without data
    assert client.get(f"/api/runs/{run}/bins/99").status_code == 404
    assert client.get(f"/api/runs/{run}/bins/0?metric=nope").status_code == 422
    cache = env["runs"] / "_viewer-cache" / "runs" / run / "speed_ms.npy"
    assert cache.exists()  # default cache under the runs dir


def test_district_effects_computed(client: TestClient, env: dict[str, Any]) -> None:
    url = f"/api/runs/{env['run']}/district-effects"
    assert client.get(url).status_code == 422  # no baseline
    body = client.get(url, params={"baseline": env["base"]}).json()
    assert body["source"] == "computed" and body["unit"] == "%" and body["label"] == LABEL
    assert body["districts"], "demo window should touch at least one district"
    for d in body["districts"]:
        assert d["district_id"].startswith(("r", "w", "n")) and math.isfinite(d["value"])
    same = client.get(url, params={"baseline": env["run"]}).json()
    assert all(d["value"] == 0 for d in same["districts"])
    assert client.get(url, params={"baseline": env["base"], "metric": "x"}).status_code == 404


def test_trajectories(client: TestClient, env: dict[str, Any]) -> None:
    url = f"/api/runs/{env['run']}/trajectories"
    full = client.get(url).json()
    assert full["label"] == LABEL and full["vehicles"]
    v = full["vehicles"][0]
    assert len(v["path"]) == len(v["timestamps"]) == len(v["speeds"])
    assert all(len(p) == 2 for p in v["path"]) and v["timestamps"] == sorted(v["timestamps"])
    lon = v["path"][0][0]
    assert round(lon, 6) == lon
    part = client.get(url, params={"begin": 100, "end": 200, "step": 5}).json()
    stamps = [t for veh in part["vehicles"] for t in veh["timestamps"]]
    assert stamps and min(stamps) >= 100 and max(stamps) <= 200
    n_full = sum(len(x["path"]) for x in full["vehicles"])
    n_part = sum(len(x["path"]) for x in part["vehicles"])
    assert n_part < n_full
    assert client.get(url, params={"step": 0}).status_code == 422


def test_missing_reports_404(client: TestClient, env: dict[str, Any]) -> None:
    for path in ("policy-report", "scenario-report", "recommendations"):
        resp = client.get(f"/api/runs/{env['base']}/{path}")
        assert resp.status_code == 404 and "not available" in resp.json()["detail"]
    assert client.get(f"/api/runs/{env['base']}/decisions").json() == []


def test_examples_and_decision_chain(client: TestClient, env: dict[str, Any]) -> None:
    from api.examples import write_examples

    run = env["run"]
    paths = write_examples(env["runs"] / run, baseline=env["base"])
    again = [p.read_text() for p in paths]
    write_examples(env["runs"] / run, baseline=env["base"])
    assert again == [p.read_text() for p in paths]  # deterministic
    recs = client.get(f"/api/runs/{run}/recommendations").json()
    assert recs["fictional"] and recs["example"] and recs["label"] == LABEL
    assert [o["rank"] for o in recs["options"]] == [1, 2, 3]
    high = [o for o in recs["options"] if o["action_class"] == "high_impact"]
    assert high and all(o["requires_approval"] for o in high)
    scen = client.get(f"/api/runs/{run}/scenario-report").json()
    assert scen["events"][0]["type"] == "accident" and scen["closures"]
    eff = client.get(f"/api/runs/{run}/district-effects").json()
    assert eff["source"] == "policy_report" and eff["districts"]

    url = f"/api/runs/{run}/recommendations/opt-1/decision"
    first = client.post(url, json={"decision": "approved", "operator": "duty-officer"}).json()
    second = client.post(
        f"/api/runs/{run}/recommendations/opt-3/decision",
        json={"decision": "rejected", "operator": "duty-officer", "note": "test"},
    ).json()
    assert first["prev_hash"] == GENESIS and second["prev_hash"] == first["hash"]
    assert first["hash"] == entry_hash(first) and first["incident_id"] == "ev1"
    log = client.get(f"/api/runs/{run}/decisions").json()
    assert [e["hash"] for e in log] == [first["hash"], second["hash"]] and verify_chain(log)
    lines = (env["runs"] / run / "decisions.jsonl").read_text().splitlines()
    assert json.loads(lines[0]) == first
    bad = {"decision": "maybe", "operator": "x"}
    assert client.post(url, json=bad).status_code == 422
    missing = f"/api/runs/{run}/recommendations/opt-404/decision"
    assert client.post(missing, json={"decision": "approved", "operator": "x"}).status_code == 404


def test_path_traversal_rejected(client: TestClient, env: dict[str, Any]) -> None:
    from fastapi import HTTPException

    from api.runs import run_dir

    for bad in ("..", "../runs", "_viewer-cache", ".hidden", "a/../../etc", "%2e%2e"):
        with pytest.raises(HTTPException):
            run_dir(bad)
    assert client.get("/api/runs/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/runs/_viewer-cache").status_code == 404
    assert client.get("/api/runs/does-not-exist/bins").status_code == 404


def test_geo(client: TestClient, env: dict[str, Any]) -> None:
    d = client.get("/api/geo/districts")
    assert d.status_code == 200 and d.json()["features"][0]["properties"]["osm_id"]
    box = "39.15,21.54,39.17,21.56"
    b = client.get("/api/geo/buildings", params={"bbox": box}).json()
    assert b["features"] and "height_m" in b["features"][0]["properties"]
    assert client.get("/api/geo/buildings", params={"bbox": "1,2,3"}).status_code == 422


def test_job_runs_and_streams(client: TestClient, env: dict[str, Any]) -> None:
    resp = client.post("/api/jobs", json={"kind": "smoke", "tier": "B", "seed": 3, "end": 300})
    job_id = resp.json()["job_id"]
    assert client.post("/api/jobs", json={"tier": "A", "seed": 1, "fcd": True}).status_code == 422
    events: list[str] = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
            if events and events[-1] == "done":
                break
    assert "log" in events and "status" in events and events[-1] == "done"
    deadline = time.monotonic() + 60
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.2)
    assert status["status"] == "done", status
    assert status["run_id"].startswith("smoke-B-s3-") and status["returncode"] == 0
    assert (env["runs"] / status["run_id"] / "edgedata.parquet").exists()
    assert client.get("/api/jobs/0123456789abcdef").status_code == 404


def test_edges_bin_header_struct() -> None:
    assert HEADER.size == struct.calcsize("<4sII") == 12


def test_default_cache_dir_under_runs(env: dict[str, Any]) -> None:
    from api import settings

    assert settings.cache_dir() == Path(env["runs"]) / "_viewer-cache"
