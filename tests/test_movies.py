"""Movie pipeline (Track E): camera interpolation, sun position, spec validation, bundle helpers
and a 10-frame render smoke test (skipped without ffmpeg, Chrome, web deps or the Tier B run)."""

from __future__ import annotations

import json
import math
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from scripts.movies import camera as cam
from scripts.movies.bundle import clock_text, fill_text, flatten, quantize, vehicle_class
from scripts.movies.spec import SPECS_DIR, Film, Keyframe, film_names, load_film
from scripts.movies.sun import lighting, sun_position
from sim.common import REPO_ROOT

JEDDAH = (21.54, 39.17)


def _film(**over: object) -> Film:
    data: dict[str, object] = {
        "film": "t",
        "title": "T",
        "duration_s": 4,
        "sources": {"a": {"run": "r"}},
        "shots": [
            {
                "id": "s1",
                "duration_s": 2,
                "layers": {"heat": "a"},
                "camera": [
                    {"t": 0, "lon": 39.0, "lat": 21.0, "zoom": 10, "sim_t": 0},
                    {"t": 2, "lon": 39.2, "lat": 21.2, "zoom": 12, "sim_t": 100, "ease": "linear"},
                ],
            },
            {
                "id": "s2",
                "duration_s": 2,
                "layers": {"heat": "a"},
                "camera": [{"t": 0, "lon": 39.1, "lat": 21.1, "zoom": 11, "sim_t": 500}],
            },
        ],
    }
    data.update(over)
    return Film.model_validate(data)


# ----------------------------------------------------------------------------- camera


def test_easing_endpoints_and_monotone() -> None:
    for kind in ("linear", "in", "out", "in_out"):
        assert cam.ease(0, kind) == 0
        assert cam.ease(1, kind) == 1
        xs = [cam.ease(u / 50, kind) for u in range(51)]
        assert all(b >= a for a, b in zip(xs, xs[1:], strict=False))
    assert cam.ease(0.5, "in_out") == pytest.approx(0.5)
    assert cam.ease(0.99, "hold") == 0 and cam.ease(1, "hold") == 1


def test_camera_interpolation_endpoints_midpoint_and_hold() -> None:
    keys = [
        Keyframe(t=0, lon=39.0, lat=21.0, zoom=10, pitch=0, bearing=170, sim_t=0),
        Keyframe(
            t=10, lon=39.2, lat=21.4, zoom=14, pitch=60, bearing=-170, sim_t=600, ease="linear"
        ),
    ]
    a = cam.camera_at(keys, 0)
    assert (a.lon, a.lat, a.zoom, a.sim_t) == (39.0, 21.0, 10, 0)
    m = cam.camera_at(keys, 5)
    assert m.zoom == pytest.approx(12)
    assert m.pitch == pytest.approx(30)
    assert m.sim_t == pytest.approx(300)
    assert abs(m.bearing) == pytest.approx(180)  # shorter arc through 180, not through 0
    assert m.lon == pytest.approx(39.1)
    # Web Mercator midpoint lies slightly north of the arithmetic mean latitude
    assert 21.2 < m.lat < 21.21
    end = cam.camera_at(keys, 25)
    assert (end.lon, end.lat, end.zoom, end.sim_t) == (39.2, 21.4, 14, 600)


def test_sim_time_linear_between_timed_keys_and_held_outside() -> None:
    keys = [
        Keyframe(t=0, lon=0, lat=0, zoom=1),
        Keyframe(t=2, lon=0, lat=0, zoom=1, sim_t=100),
        Keyframe(t=6, lon=0, lat=0, zoom=1, sim_t=500, ease="in_out"),
        Keyframe(t=8, lon=0, lat=0, zoom=1),
    ]
    assert cam.sim_time_at(keys, 0) == 100
    assert cam.sim_time_at(keys, 4) == pytest.approx(300)  # sim clock is not eased
    assert cam.sim_time_at(keys, 8) == 500


def test_frame_plan_is_frame_stepped_and_covers_shots() -> None:
    film = _film()
    plans = cam.plan_frames(film, 30)
    assert len(plans) == 120
    assert plans[0].film_t == 0 and plans[61].film_t == pytest.approx(61 / 30)
    assert [p.shot for p in plans].index(1) == 60
    assert plans[59].camera.sim_t == pytest.approx(100 * 59 / 60)
    assert plans[-1].camera.sim_t == 500
    again = cam.plan_frames(film, 30)
    assert [p.camera for p in plans] == [p.camera for p in again]


# ----------------------------------------------------------------------------- sun


def test_sun_noon_elevation_and_azimuth_jeddah() -> None:
    # Solar noon in Jeddah in mid-October is about 12:00 AST; elevation = 90 - lat + declination
    # (declination about -9.3 deg on 18 Oct), sun due south.
    s = sun_position(date(2026, 10, 18), 12 * 3600 + 60, *JEDDAH, 3)
    assert s.elevation_deg == pytest.approx(90 - 21.54 - 9.6, abs=0.6)
    assert s.azimuth_deg == pytest.approx(180, abs=6)


def test_sun_rises_east_sets_west_and_is_below_horizon_at_night() -> None:
    d = date(2026, 10, 18)
    rise = sun_position(d, 6 * 3600 + 20 * 60, *JEDDAH, 3)
    sets = sun_position(d, 17 * 3600 + 50 * 60, *JEDDAH, 3)
    night = sun_position(d, 23 * 3600, *JEDDAH, 3)
    assert abs(rise.elevation_deg) < 2 and 90 < rise.azimuth_deg < 110
    assert abs(sets.elevation_deg) < 2 and 250 < sets.azimuth_deg < 270
    assert night.elevation_deg < -30
    # the clock may run past midnight (a 24 h film from 02:00 to 02:00)
    nxt = sun_position(d, 86400 + 12 * 3600, *JEDDAH, 3)
    assert nxt.elevation_deg == pytest.approx(
        sun_position(date(2026, 10, 19), 12 * 3600, *JEDDAH, 3).elevation_deg, abs=1e-6
    )


def test_summer_solstice_noon_sun_is_north_of_zenith_in_jeddah() -> None:
    # Jeddah (21.5 N) is south of the Tropic of Cancer: at the June solstice the noon sun is in
    # the north (declination 23.4 > latitude).
    s = sun_position(date(2026, 6, 21), 12 * 3600 + 25 * 60, *JEDDAH, 3)
    assert s.elevation_deg == pytest.approx(90 - (23.44 - 21.54), abs=0.8)
    assert s.azimuth_deg < 30 or s.azimuth_deg > 330


def test_lighting_day_night_blend() -> None:
    day = lighting(sun_position(date(2026, 10, 18), 12 * 3600, *JEDDAH, 3))
    night = lighting(sun_position(date(2026, 10, 18), 22 * 3600, *JEDDAH, 3))
    assert day["night"] == 0 and night["night"] == 1
    assert day["sun_intensity"] > 1 and night["sun_intensity"] == 0
    dx, dy, dz = day["direction"]
    assert dz < 0 and math.hypot(dx, dy, dz) == pytest.approx(1, abs=1e-4)
    assert dy > 0  # noon sun in the south: light travels north


# ----------------------------------------------------------------------------- specs


def test_every_shipped_spec_validates() -> None:
    names = film_names()
    assert {
        "city-24h",
        "tahlia-street",
        "incident",
        "events",
        "strategist",
        "evacuation",
        "policy-lab",
        "loop",
    } <= set(names)
    for name in names:
        film = load_film(name)
        assert film.film == name
        if not film.stub:
            assert 20 <= film.duration_s <= 45


def test_loop_is_a_stub_until_track_d_is_merged() -> None:
    film = load_film("loop")
    assert film.stub == (not (REPO_ROOT / "docs" / "loop.md").exists())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"duration_s": 5}, "sum of shot durations"),
        ({"film": "Bad Name"}, "pattern"),
        ({"sources": {}}, "unknown source"),
    ],
)
def test_spec_validation_errors(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _film(**change)


def test_spec_rejects_unsorted_keyframes_and_bad_kpis() -> None:
    shot = {
        "id": "s",
        "duration_s": 4,
        "layers": {"heat": "a"},
        "camera": [
            {"t": 0, "lon": 0, "lat": 0, "zoom": 1, "sim_t": 0},
            {"t": 0, "lon": 0, "lat": 0, "zoom": 1},
        ],
    }
    with pytest.raises(ValidationError, match="strictly increasing"):
        _film(shots=[shot])
    shot["camera"] = [{"t": 0, "lon": 0, "lat": 0, "zoom": 1, "sim_t": 0}]
    shot["hud"] = {"kpis": [{"label": "x", "value": 1, "series": "running", "source": "a"}]}
    with pytest.raises(ValidationError, match="exactly one"):
        _film(shots=[shot])
    shot["layers"] = {"mode": "diff", "heat": "a"}
    shot["hud"] = {}
    with pytest.raises(ValidationError, match="diff needs"):
        _film(shots=[shot])


def test_spec_file_names_match_film_ids() -> None:
    for path in SPECS_DIR.glob("*.yaml"):
        if path.stem != "order" and "." not in path.stem:  # <film>.narration.yaml = scripts
            assert load_film(str(path)).film == path.stem


# ----------------------------------------------------------------------------- bundle helpers


def test_quantize_round_trip_and_nan() -> None:
    v = np.array([0.0, 0.5, 1.0, 1.7, -0.2, np.nan])
    q = quantize(v, 0.0, 1.0, 254)
    assert q.tolist() == [0, 127, 254, 254, 0, 255]
    back = q[:3] / 254
    assert np.allclose(back, [0, 0.5, 1], atol=1 / 254)


def test_vehicle_classes_from_vtype_and_event_ids() -> None:
    assert vehicle_class("normal", "smoke12") == 0
    assert vehicle_class("truck", "x") == 1
    assert vehicle_class("bus", "x") == 2
    assert vehicle_class("emergency", "ev.ambulance_1") == 3
    assert vehicle_class("convoy", "ev.convoy_tahlia_eb.0") == 4
    assert vehicle_class("normal", "ev.corniche_crowd.12") == 5


def test_facts_text_and_clock() -> None:
    facts = {"a": flatten({"x": {"y": 1.234}, "label": "Route A", "l": [1, 2]})}
    assert fill_text("{a.label} in {a.x.y:.1f} s", facts) == "Route A in 1.2 s"
    with pytest.raises(KeyError):
        fill_text("{a.missing}", facts)
    assert facts["a"]["l.0"] == 1
    film = _film(clock_t0="08:00")
    assert clock_text(film, 1800) == "08:30"
    assert clock_text(_film(), 93600 - 1) == "01:59"


# ----------------------------------------------------------------------------- render smoke


def _render_ready() -> str | None:
    if not shutil.which("ffmpeg"):
        return "ffmpeg missing (brew install ffmpeg)"
    if not shutil.which("node") or not (REPO_ROOT / "web" / "node_modules").exists():
        return "node or web/node_modules missing"
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    import os

    if not Path(os.environ.get("CHROME_PATH", chrome)).exists():
        return "Google Chrome missing (set CHROME_PATH)"
    run = REPO_ROOT / "runs" / "accident_tahlia-tahlia-s1-257eae8d"
    if not (run / "baseline").exists():
        return "Tier B run accident_tahlia-tahlia-s1-257eae8d not in runs/"
    return None


@pytest.mark.skipif(_render_ready() is not None, reason=str(_render_ready()))
def test_render_smoke_ten_frames_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.movies.render import render_film

    # the API tests point TT_RUNS_DIR at a temporary directory for the whole session
    monkeypatch.setenv("TT_RUNS_DIR", str(REPO_ROOT / "runs"))
    monkeypatch.delenv("TT_CACHE_DIR", raising=False)
    monkeypatch.setenv("TT_RUNS_READONLY", "1")
    # the 640x360 bundle and frames go to tmp, not the real runs/movies cache
    monkeypatch.setenv("TT_MOVIES_DIR", str(tmp_path / "movies"))

    metas = []
    for k in range(2):
        out = tmp_path / f"r{k}"
        # silent: the voice-over needs the TTS venv (tests/test_narration.py covers it)
        metas.append(
            render_film(
                "tahlia-street", size=(640, 360), frames=(100, 110), out_dir=out, voice=False
            )
        )
        mp4 = out / "tahlia-street.mp4"
        assert mp4.exists() and (out / "tahlia-street.poster.png").exists()
        info = metas[-1]["mp4"]
        assert (info["width"], info["height"], info["frames"]) == (640, 360, 10)
        assert info["codec"] == "h264" and info["pix_fmt"] == "yuv420p"
        assert info["duration_s"] == pytest.approx(10 / 30, abs=0.05)
        frames_dir = tmp_path / "movies" / "tahlia-street" / "frames"
        assert not frames_dir.exists() or not any(frames_dir.iterdir())  # no frames left behind
        meta = json.loads((out / "tahlia-street.json").read_text())
        # first, middle, last frame free of fades (after the title card)
        assert set(meta["frame_sha256_16"]) == {"100", "105", "109"}
    # same spec + same run => identical first, middle and last frames
    assert metas[0]["frame_sha256_16"] == metas[1]["frame_sha256_16"]


def test_settings_assumptions_are_registered() -> None:
    import re

    import yaml

    settings = (REPO_ROOT / "scripts" / "movies" / "settings.yaml").read_text()
    ids = set(re.findall(r"A-mov-\d{3}", settings))
    register = (REPO_ROOT / "docs" / "assumptions.md").read_text()  # merged (Track E + Track I)
    assert ids and ids <= set(re.findall(r"^\| (A-mov-\d{3}) ", register, re.M))
    for block in yaml.safe_load(settings).values():
        if isinstance(block, dict):
            for v in block.values():
                if isinstance(v, dict) and "id" in v:
                    assert "source" in v or "assumption" in v, v["id"]


def test_loop_film_draws_the_recommended_alignment() -> None:
    film = load_film("loop")
    if film.stub:
        pytest.skip("Track D not merged")
    for shot in film.shots:
        assert shot.layers.line is not None and len(shot.layers.line) == 8
        assert shot.layers.stations == shot.layers.line
