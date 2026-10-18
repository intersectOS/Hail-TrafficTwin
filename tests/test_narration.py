"""Voice-over, subtitles and map labels for the films (MOVIES_V2). Offline; the TTS test needs
the narration venv (`make voice-setup`) and skips without it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from scripts.movies import narrate
from scripts.movies.bundle import _is_edge_id, street_en
from scripts.movies.labels import anchors, landmark_labels, street_labels
from scripts.movies.spec import SPECS_DIR, Film, film_names, load_film
from sim.common import REPO_ROOT


def _film() -> Film:
    shot = {
        "layers": {"heat": "a"},
        "camera": [
            {"t": 0, "lon": 39.1, "lat": 21.5, "zoom": 14, "sim_t": 0},
            {"t": 10, "lon": 39.1, "lat": 21.5, "zoom": 14, "sim_t": 600},
        ],
    }
    return Film.model_validate(
        {
            "film": "x",
            "title": "x",
            "duration_s": 20,
            "title_card_s": 2,
            "showreel": [5, 15],
            "sources": {"a": {"run": "r"}},
            "shots": [
                {"id": "s1", "duration_s": 10, **shot},
                {"id": "s2", "duration_s": 10, **shot},
            ],
        }
    )


def _nar(lines: list[dict[str, object]]) -> narrate.Narration:
    return narrate.Narration.model_validate({"film": "x", "lines": lines})


def test_every_film_has_a_valid_narration() -> None:
    known = narrate.doc_numbers()
    for name in film_names():
        film = load_film(name)
        if film.stub:
            continue
        nar = narrate.load_narration(name)
        assert nar is not None, f"{name}: no narration script"
        assert narrate.check(nar, film, known) == [], name
    reel = narrate.load_narration("showreel")
    assert reel is not None and narrate.check(reel, None, known) == []
    assert {ln.film for ln in reel.lines} == {n for n in film_names() if not load_film(n).stub}


def test_check_rejects_invented_numbers_and_missing_caveat() -> None:
    nar = _nar(
        [
            {"shot": "s1", "text": "It saves 987654 hours."},
            {"shot": "s1", "text": "A second line."},
            {"shot": "s2", "text": "A third line."},
            {"shot": "s2", "text": "No caveat here."},
        ]
    )
    errs = narrate.check(nar, _film(), {"1"})
    assert any("987654" in e for e in errs) and any("caveat" in e for e in errs)


def test_timing_stretches_shots_to_fit_speech_never_the_reverse() -> None:
    film = _film()
    nar = _nar(
        [
            {"shot": "s1", "at": 0, "text": "one"},
            {"shot": "s1", "text": "two"},
            {"shot": "s2", "sim_t": 300, "text": "three, synthetic demand, uncalibrated"},
        ]
    )
    wav = Path("w.wav")
    t = narrate.plan_timing(film, nar, [6.0, 6.0, 2.0], [wav] * 3)
    cfg = narrate._settings()
    # the first line waits for the title card; lines never overlap
    assert t.lines[0].start_s >= film.title_card_s
    assert t.lines[1].start_s >= t.lines[0].end_s + cfg["gap_s"] - 1e-9
    # shot 1 holds 12 s of speech: stretched; shot 2 is not
    assert t.stretch["s1"] > 1.0 and t.stretch["s2"] == 1.0
    s1_end = film.shots[0].duration_s * t.stretch["s1"]
    assert t.lines[1].end_s + cfg["tail_s"] <= s1_end + 1e-6
    # sim_t 300 is the middle of shot 2 (sim 0..600 over 10 s)
    assert t.lines[2].start_s == pytest.approx(s1_end + 5.0)
    stretched = narrate.apply_timing(film, t)
    assert stretched.duration_s == pytest.approx(t.duration_s)
    assert stretched.shots[0].camera[-1].t == pytest.approx(10 * t.stretch["s1"])
    assert stretched.shots[0].camera[-1].sim_t == 600  # the sim clock is not stretched
    a, b = stretched.showreel
    assert a == pytest.approx(5 * t.stretch["s1"]) and b == pytest.approx(s1_end + 5)


def test_voice_track_and_srt(tmp_path: Path) -> None:
    import wave

    rate = 24000
    clip = tmp_path / "a.wav"
    with wave.open(str(clip), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.ones(rate // 2) * 1000).astype("<i2").tobytes())
    h1 = narrate.voice_track([(1.0, clip), (3.0, clip)], 5.0, tmp_path / "v1.wav")
    h2 = narrate.voice_track([(1.0, clip), (3.0, clip)], 5.0, tmp_path / "v2.wav")
    assert h1 == h2 and narrate.wav_seconds(tmp_path / "v1.wav") == pytest.approx(5.0)
    srt = tmp_path / "x.srt"
    narrate.write_srt([(1.0, 1.5, "Hello"), (61.25, 62.0, "World")], srt)
    text = srt.read_text()
    assert "1\n00:00:01,000 --> 00:00:01,500\nHello" in text
    assert "2\n00:01:01,250 --> 00:01:02,000\nWorld" in text


def test_street_labels_prefer_english_and_borrow_it_for_arabic_only_ways() -> None:
    from shapely.geometry import box

    def way(name: str, en: str | None, hw: str, coords: list[list[float]]) -> dict:
        props = {"highway": hw, "name": name, **({"name:en": en} if en else {})}
        return {"properties": props, "geometry": {"type": "LineString", "coordinates": coords}}

    feats = [
        way(
            "طريق الملك عبد العزيز",
            "King Abdulaziz Road",
            "primary",
            [[39.10, 21.70], [39.10, 21.71]],
        ),
        way("طريق الملك عبد العزيز", None, "primary", [[39.10, 21.71], [39.10, 21.73]]),
        way("شارع", None, "service", [[39.11, 21.70], [39.11, 21.72]]),  # not labelled
    ]
    out = street_labels(feats, box(39.0, 21.6, 39.2, 21.8))
    assert len(out) == 1
    road = out[0]
    assert (road["en"], road["ar"], road["cls"]) == (
        "King Abdulaziz Road",
        "طريق الملك عبد العزيز",
        1,
    )
    assert len(road["anchors"]) >= 4  # 3.3 km merged line, 550 m spacing
    assert all(abs(a[2] - 0.0) < 1.0 or abs(a[2] - 360.0) < 1.0 for a in road["anchors"])  # north


def test_anchor_bearing_east() -> None:
    from shapely.geometry import LineString

    pts = anchors(LineString([(39.10, 21.70), (39.12, 21.70)]), 500.0)
    assert pts and all(abs(p[2] - 90.0) < 0.5 for p in pts)


def test_landmarks_are_reviewed_and_include_obhur() -> None:
    data = yaml.safe_load((REPO_ROOT / "movies" / "landmarks.yaml").read_text())
    ids = {lm["id"] for lm in data["landmarks"]}
    assert {"kaia", "kau", "al_balad", "obhur_creek", "jeddah_tower", "corniche"} <= ids
    assert "obhur_creek_mouth" in ids
    assert all(lm.get("source") for lm in data["landmarks"])
    inside = landmark_labels((39.07, 21.68, 39.15, 21.75))
    assert {lm["id"] for lm in inside} == {"obhur_creek", "obhur_creek_mouth", "jeddah_tower"}


def test_callout_street_names() -> None:
    assert _is_edge_id("444402913#0") and _is_edge_id("82161453#0-AddedOffRampEdge")
    assert street_en("طريق الكورنيش الشمالي", {"طريق الكورنيش الشمالي": "Corniche Road"}) == (
        "Corniche Road"
    )
    assert street_en("444402913#0", {}) == ""


def test_obhur_replaces_hamra_in_the_public_demo_set() -> None:
    public = [
        SPECS_DIR / "evacuation.yaml",
        SPECS_DIR / "evacuation.narration.yaml",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "movies.md",
        REPO_ROOT / "web" / "scripts" / "integration-shots.json",
    ]
    for p in public:
        assert "hamra" not in p.read_text().lower(), p
    assert not (REPO_ROOT / "sim" / "scenarios" / "evac_corniche_hamra.yaml").exists()
    assert load_film("evacuation").fictional
    assert "obhur" in (SPECS_DIR / "evacuation.yaml").read_text().lower()


def _tts() -> Path | None:
    py = REPO_ROOT / ".venv-tts" / "bin" / "python"
    return py if py.exists() else None


@pytest.mark.skipif(_tts() is None, reason="TTS venv missing (make voice-setup)")
def test_tts_same_text_same_audio(tmp_path: Path) -> None:
    py = _tts()
    assert py is not None
    jobs = [{"text": "Synthetic demand, uncalibrated.", "out": str(tmp_path / f"{k}.wav")}
            for k in range(2)]  # fmt: skip
    env = narrate.tts_env()
    # run twice in separate processes: same samples
    for job in jobs:
        subprocess.run(
            [str(py), str(narrate.TTS_WORKER), "--voice", "af_heart", "--seed", "1"],
            input=json.dumps([job]), text=True, check=True, capture_output=True, env=env,
        )  # fmt: skip
    a, b = ((tmp_path / f"{k}.wav").read_bytes() for k in range(2))
    assert a == b and len(a) > 24000
    assert os.environ.get("HF_HUB_OFFLINE", "1")  # the worker runs offline by default


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_voice_mux_keeps_the_film_length(tmp_path: Path) -> None:
    """loudnorm pads to 100 ms blocks: the muxed AAC track must still end with the video."""
    import wave

    from scripts.movies.render import mux_voice, probe, probe_audio

    fps, frames = 30, 64  # 2.1333 s: not a whole number of 100 ms blocks
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=64x36:r={fps}",
         "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )  # fmt: skip
    rate = 24000
    wav = tmp_path / "voice.wav"
    t = np.arange(round(frames / fps * rate)) / rate
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2").tobytes())
    srt = tmp_path / "x.srt"
    narrate.write_srt([(0.1, 1.5, "Hello")], srt)
    out = tmp_path / "out.mp4"
    loud = mux_voice(video, wav, srt, out)
    audio = probe_audio(out)
    assert audio is not None and audio["codec"] == "aac"
    assert audio["duration_s"] == pytest.approx(frames / fps, abs=0.025)
    assert probe(out)["duration_s"] == pytest.approx(frames / fps, abs=0.025)
    assert abs(loud["output_lufs"] - narrate._settings()["lufs"]) < 2.0
