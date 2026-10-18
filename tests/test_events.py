"""M5 schemas, vTypes, register and event resolution on the demo window (no simulation)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sim.common import REPO_ROOT, load_yaml
from sim.events import flood
from sim.events.netindex import NetIndex
from sim.events.registry import resolve_events
from sim.scenarios import register
from sim.scenarios.run import load_scenario, window_inputs
from sim.scenarios.schema import Flood, Scenario, strategist_requested
from sim.vtypes.loader import apply_mix, load_library, resolve_mix, write_vtypes_additional
from sim.vtypes.schema import VTypeLibrary, check_mix

DATA = REPO_ROOT / "tests" / "data"
SCEN_FILES = sorted((REPO_ROOT / "sim" / "scenarios").glob("*_tahlia.yaml")) + sorted(
    (DATA / "scenarios").glob("*.yaml")
)
BASE = {
    "id": "t",
    "kind": "scenario",
    "window": "demo",
    "daytype": "weekday",
    "label": "test",
    "fictional": True,
    "begin": 0,
    "end": 900,
}


@pytest.fixture(scope="module")
def idx(demo_net: Path) -> NetIndex:
    return NetIndex(demo_net)


def scen(**kw: object) -> Scenario:
    return Scenario.model_validate({**BASE, **kw})


@pytest.mark.parametrize("path", SCEN_FILES, ids=lambda p: p.name)
def test_shipped_scenarios_validate(path: Path) -> None:
    s = Scenario.model_validate(load_yaml(path))
    assert s.fictional is True
    assert s.events


def test_tahlia_demo_files_cover_every_event_type() -> None:
    types = {
        e.type
        for p in SCEN_FILES
        if p.name.endswith("_tahlia.yaml")
        for e in load_scenario(p).events
    }
    assert {"accident", "rain", "flood", "motorcade", "emergency_trip"} <= types


def test_times_and_durations() -> None:
    s = scen(events=[{"type": "rain", "start": "00:10:00", "duration_min": 5, "preset": "light"}])
    ev = s.events[0]
    assert (ev.start, ev.end, ev.id) == (600.0, 900.0, "rain_0")


@pytest.mark.parametrize(
    "bad",
    [
        {"vtype_mix": {"normal": 0.5, "slow": 0.4}},  # sums to 0.9
        {"events": [{"type": "rain", "start": 950, "duration_s": 10, "preset": "light"}]},
        {
            "events": [
                {"type": "rain", "start": 1, "duration_s": 1, "duration_min": 1, "preset": "light"}
            ]
        },
        {"events": [{"type": "rain", "start": "8:75", "duration_s": 1, "preset": "light"}]},
        {"events": [{"type": "hail", "start": 1}]},
        {
            "events": [
                {
                    "type": "accident",
                    "start": 1,
                    "duration_s": 5,
                    "edge": "x",
                    "rubbernecking_factor": 0.5,
                }
            ]
        },
        {"events": [{"type": "motorcade", "start": 1, "vehicles": 3}]},
        {
            "events": [
                {"type": "accident", "start": 1, "duration_s": 5, "edge": "x", "lanes_closed": 0}
            ]
        },
        {
            "events": [
                {"type": "rain", "id": "a", "start": 1, "duration_s": 5, "preset": "light"},
                {"type": "rain", "id": "a", "start": 2, "duration_s": 5, "preset": "light"},
            ]
        },
        {"kind": "policy"},
        {"surprise": 1},
    ],
)
def test_bad_scenarios_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        scen(**bad)


def test_override_with_assumption_is_accepted() -> None:
    s = scen(events=[{"type": "accident", "start": 1, "duration_s": 5, "edge": "x",
                      "rubbernecking_factor": 0.5, "assumption": "test value"}])  # fmt: skip
    assert s.events[0].rubbernecking_factor == 0.5


def test_mix_checks() -> None:
    lib = load_library()
    with pytest.raises(ValueError, match="unknown vTypes"):
        check_mix({"normal": 0.5, "martian": 0.5}, set(lib.types))
    assert resolve_mix(None, lib)["normal"] == pytest.approx(0.7)
    assert sum(resolve_mix(None, lib).values()) == pytest.approx(1.0)


def test_emergency_vtype_rejected_in_tier_a(tmp_path: Path) -> None:
    lib = load_library()
    with pytest.raises(ValueError, match="Tier B only"):
        write_vtypes_additional(tmp_path / "a.xml", {"normal": 0.9, "emergency": 0.1}, "A", lib)
    with pytest.raises(ValueError, match="Tier B only"):
        write_vtypes_additional(
            tmp_path / "a.xml", {"normal": 1.0}, "A", lib, include=["emergency"]
        )
    a = write_vtypes_additional(tmp_path / "a.xml", {"normal": 1.0}, "A", lib).read_text()
    assert 'id="emergency"' not in a and "bluelight" not in a
    b = write_vtypes_additional(tmp_path / "b.xml", resolve_mix(None, lib), "B", lib).read_text()
    assert 'vClass="emergency"' in b and 'guiShape="emergency"' in b
    assert '<param key="has.bluelight.device" value="true"/>' in b
    assert '<vTypeDistribution id="mix" vTypes="normal slow aggressive truck bus"' in b
    assert 'id="convoy" vClass="vip"' in b


def test_library_rules() -> None:
    raw = load_yaml(REPO_ROOT / "sim" / "vtypes" / "types.yaml")
    raw["types"]["slow"]["params"]["tau"]["value"] = 0.5
    with pytest.raises(ValidationError, match="tau"):
        VTypeLibrary.model_validate(raw)
    raw = load_yaml(REPO_ROOT / "sim" / "vtypes" / "types.yaml")
    raw["types"]["emergency"]["tier_b_only"] = False
    with pytest.raises(ValidationError, match="micro-only"):
        VTypeLibrary.model_validate(raw)
    raw = load_yaml(REPO_ROOT / "sim" / "vtypes" / "types.yaml")
    del raw["types"]["normal"]["params"]["accel"]["source"]
    with pytest.raises(ValidationError, match="source"):
        VTypeLibrary.model_validate(raw)


def test_apply_mix(tmp_path: Path) -> None:
    src = tmp_path / "in.rou.xml"
    src.write_text(
        '<routes><vType id="x"/><trip id="a" depart="0" from="e" to="f"/>'
        '<vehicle id="b" depart="1" type="x"><route edges="e f"/></vehicle></routes>'
    )
    counts = apply_mix(src, tmp_path / "out.rou.xml", "mix")
    assert counts == {"vehicles": 2, "typed_by_mix": 1, "kept_type": 1}
    out = (tmp_path / "out.rou.xml").read_text()
    assert 'id="a" depart="0" from="e" to="f" type="mix"' in out
    assert '<route edges="e f"' in out and 'type="x"' in out


def test_register_is_current_and_complete() -> None:
    assert register.is_current(), "run: python -m sim.scenarios register"
    ids = register.all_ids()
    s = load_scenario(DATA / "scenarios" / "demo_all_events.yaml")
    idx = NetIndex(REPO_ROOT / "data" / "demo" / "demo.net.xml")
    _, used = resolve_events(s, idx, load_library())
    assert set(used) <= ids


def test_missing_window_names_the_link_command() -> None:
    with pytest.raises(FileNotFoundError, match=r"python -m sim\.link"):
        window_inputs("no_such_window")


def test_evacuation_reserved_for_m7(idx: NetIndex) -> None:
    s = scen(events=[{"type": "evacuation", "start": 10, "zone": [[0, 0]]}])
    with pytest.raises(NotImplementedError, match="M7"):
        resolve_events(s, idx, load_library())


def test_strategist_flag() -> None:
    trip = {"type": "emergency_trip", "start": 5, "from": "a", "to": "b"}
    assert not strategist_requested(scen(events=[trip]))
    assert strategist_requested(scen(events=[{**trip, "strategist": True}]))


def test_reverse_edges_divided_road(idx: NetIndex) -> None:
    # Tahlia St carriageways are separate one-way edges between different nodes
    rev = idx.reverse_edges("1492421519#6", 40, 50)
    assert "38500585#3" in rev
    assert idx.reverse_edges("48364777#2", 40, 50) == ["-48364777#2"]


def test_flood_site_selection(idx: NetIndex) -> None:
    spec = Flood.model_validate(
        {
            "type": "flood",
            "id": "f",
            "start": 0,
            "duration_s": 60,
            "sites_file": "tests/data/flood_sites.yaml",
        }
    )
    ids: list[str] = []
    plan = flood.resolve(spec, idx, ids)
    by_site = {s["site"]: s for s in plan["sites"]}
    assert set(by_site) == {"TS-001", "TS-002", "TS-004"}  # TS-003 lies outside the window
    assert by_site["TS-002"]["method"] == "origId"
    assert by_site["TS-002"]["edges"] == ["166129018#0", "166129018#2"]
    assert by_site["TS-001"]["method"] == "radius"
    assert "1492421519#8" in by_site["TS-001"]["edges"]
    assert "A-event-flood-radius" in ids and "A-rain-011" in ids
    spec2 = spec.model_copy(update={"min_confidence": "medium"})
    assert {s["site"] for s in flood.resolve(spec2, idx, [])["sites"]} == {"TS-001", "TS-002"}
    spec3 = spec.model_copy(update={"site_ids": ["TS-002"]})
    assert [s["site"] for s in flood.resolve(spec3, idx, [])["sites"]] == ["TS-002"]


def test_gridlock_rules() -> None:
    from sim.scenarios.kpis import gridlock_params, jam_teleport_onset, sustained_halt_onset

    g = gridlock_params()
    assert g["jam_teleports_min"] == 10 and g["throughput_bin_s"] == 300
    # 8 jam teleports spread over an hour (a normal baseline) is not gridlock
    assert jam_teleport_onset([200.0 * i for i in range(1, 9)], g) is None
    # 9 in one bin is not, the 10th in the same bin is
    burst = [1800.0 + 10 * i for i in range(10)]
    assert jam_teleport_onset(burst[:9] + [100.0, 3000.0], g) is None
    assert jam_teleport_onset(burst, g) == burst[-1]
    # sustained halt: >= max(share x running, min vehicles) for sustain_s
    n = int(g["sustain_s"]) + 20
    series = {"time": list(range(n)), "running": [200] * n, "halted": [5] * 10 + [100] * (n - 10)}
    assert sustained_halt_onset(series, g) == 10
    series["halted"] = [100 if i % 100 else 0 for i in range(n)]
    assert sustained_halt_onset(series, g) is None


def test_scenario_vtype_mix_override(tmp_path: Path) -> None:
    lib = load_library()
    mix = resolve_mix({"normal": 0.6, "truck": 0.3, "bus": 0.1}, lib)
    assert mix == {"normal": 0.6, "truck": 0.3, "bus": 0.1}
    text = write_vtypes_additional(tmp_path / "b.xml", mix, "B", lib).read_text()
    assert 'vTypes="normal truck bus" probabilities="0.6 0.3 0.1"' in text


def test_throughput_collapse_rule() -> None:
    from sim.scenarios.kpis import gridlock_params, throughput_collapse_onset

    g = gridlock_params()
    bin_s = int(g["throughput_bin_s"])
    times = list(range(1, 4 * bin_s + 1))
    base = {"series": {"time": times, "arrived": [1 if t % 5 == 0 else 0 for t in times]}}
    # same arrivals: no collapse; arrivals stop in the third bin: collapse at its start
    assert throughput_collapse_onset(base, base) is None
    stalled = [
        a if t <= 2 * bin_s else 0 for t, a in zip(times, base["series"]["arrived"], strict=True)
    ]
    scen = {"series": {"time": times, "arrived": stalled}}
    assert throughput_collapse_onset(base, scen) == 2 * bin_s
