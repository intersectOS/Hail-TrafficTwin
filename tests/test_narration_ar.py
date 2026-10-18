"""Arabic edition of the film narration (pass 8, docs/movies-arabic.md)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.movies import narrate
from scripts.movies.spec import film_names, load_film
from sim.common import REPO_ROOT

CAVEAT = "طَلَبٌ اصْطِنَاعِيٌّ، غَيْرُ مُعَايَرْ."


def _nar(lines: list[dict[str, object]], film: str = "x") -> narrate.Narration:
    return narrate.Narration.model_validate({"film": film, "lines": lines})


def _worker():  # noqa: ANN202 - the TTS worker module (pure helpers only; no torch at import)
    spec = importlib.util.spec_from_file_location(
        "tts_ar", narrate.TTS_WORKER.with_name("tts_ar.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_film_has_a_valid_arabic_narration() -> None:
    for name in film_names():
        if load_film(name).stub:
            continue
        nar = narrate.load_narration(name, "ar")
        assert nar is not None, f"{name}: no {name}.narration.ar.yaml"
        assert narrate.check_ar(nar, narrate.load_narration(name), load_film(name)) == [], name
        assert all(ln.say for ln in nar.lines), f"{name}: every Arabic line needs `say`"
    reel = narrate.load_narration("showreel", "ar")
    assert reel is not None
    assert narrate.check_ar(reel, narrate.load_narration("showreel"), None) == []


def test_validate_covers_both_languages() -> None:
    names = [n for n, _ in narrate.validate_all()]
    assert "city-24h.narration.yaml" in names and "city-24h.narration.ar.yaml" in names
    assert len(names) == len(set(names))  # the .ar.yaml files are not read as English scripts
    assert all(errs == [] for _, errs in narrate.validate_all())


@pytest.mark.parametrize(
    ("words", "want"),
    [
        ("مِئَةٍ وَثَمَانِيَةٍ وَسَبْعِينَ أَلْفًا وَتِسْعِمِئَةٍ وَتِسْعِ سَاعَاتٍ", ["178909"]),
        ("ثَمَانِيَةً فَاصِلَةَ سَبْعَةٍ فِي المِئَةِ", ["8.7"]),
        ("اثْنَيْنِ فَاصِلَةَ خَمْسَةٍ وَثَمَانِينَ", ["2.85"]),
        ("نَحْوَ سِتِّمِئَةٍ وَأَرْبَعِمِئَةِ مَرْكَبَةٍ", ["600", "400"]),
        ("ثَلَاثَ عَشْرَةَ قِطْعَةً", ["13"]),
        ("ثَمَانِيَةٌ وَعِشْرُونَ إِلَى ثَلَاثِينَ", ["28", "30"]),
        ("ثَلَاثَةِ آلَافٍ وَسَبْعِمِئَةٍ وَخَمْسِينَ شَخْصًا فِي أَلْفٍ وَخَمْسِمِئَةِ سَيَّارَةٍ", ["3750", "1500"]),
        ("مِئَتَانِ وَثَمَانٍ وَثَلَاثُونَ أَلْفًا وَمِئَةٌ وَثَلَاثُونَ", ["238130"]),
        ("خَمْسًا وَثَمَانِينَ ثَانِيَةً، مُقَابِلَ سِتٍّ وَسِتِّينَ فَاصِلَةِ خَمْسَةٍ", ["85", "66.5"]),
        ("أَسْرَعُ بِمِئَةٍ وَخَمْسِ ثَوَانٍ", ["105"]),
        ("هَذِهِ جُدَّةُ فِي المِئَةِ", []),  # في المئة (per cent) is not a number
    ],
)  # fmt: skip
def test_arabic_number_words(words: str, want: list[str]) -> None:
    assert narrate.ar_numbers(words) == want


def test_digit_consistency_against_the_english_line() -> None:
    en = _nar([{"shot": "s1", "at": 0.6, "text": "Delay rises by 5.7 percent."},
               {"shot": "s1", "text": "Synthetic demand, uncalibrated."}])  # fmt: skip
    good = [
        {"shot": "s1", "at": 0.6, "text": "يرتفع التأخير 5.7 في المئة.",
         "say": "يَرْتَفِعُ التَّأْخِيرُ خَمْسَةً فَاصِلَةَ سَبْعَةٍ فِي المِئَةْ."},
        {"shot": "s1", "text": "طلب اصطناعي، غير معاير.", "say": CAVEAT},
    ]  # fmt: skip
    assert narrate.check_ar(_nar(good), en, None) == []

    def errs(k: int, **change: object) -> list[str]:
        lines = [dict(ln) for ln in good]
        lines[k].update(change)
        return narrate.check_ar(_nar(lines), en, None)

    assert any("subtitle numbers" in e for e in errs(0, text="يرتفع التأخير 7.5 في المئة."))
    assert any("not spoken" in e for e in errs(0, say="يَرْتَفِعُ التَّأْخِيرُ سَبْعَةً فَاصِلَةَ خَمْسَةٍ."))
    assert any("has digits" in e for e in errs(0, say="يَرْتَفِعُ التَّأْخِيرُ 5.7 فِي المِئَةْ."))
    assert any("anchor" in e for e in errs(0, at=2.0))
    assert any("caveat" in e for e in errs(1, text="انتهى.", say="انْتَهَى."))
    assert any("lines" in e for e in narrate.check_ar(_nar(good[:1]), en, None))


def test_settings_per_language_and_english_cache_keys_unchanged() -> None:
    en, ar = narrate._settings("en"), narrate._settings("ar")
    assert "ar" not in en and en["voice"] == "af_heart" and en.get("worker") is None
    assert ar["worker"] == "tts_ar.py" and ar["venv"] == ".venv-tts-ar"
    assert ar["lufs"] == en["lufs"] and ar["gap_s"] == en["gap_s"]  # inherited
    assert narrate.voice_dir("ar").name == "_voice_ar" and narrate.voice_dir().name == "_voice"
    assert narrate.narration_path("loop", "ar").name == "loop.narration.ar.yaml"
    # the English WAV cache key is the pre-pass-8 formula (no re-synthesis of English lines)
    import hashlib

    cfg, ver = {"speed": 0.95, "seed": 1}, {"engine": "kokoro"}
    old = hashlib.sha256(json.dumps(["Hi.", "af_heart", 0.95, 1, ver], sort_keys=True).encode())
    assert narrate.line_key("Hi.", "af_heart", cfg, ver) == old.hexdigest()[:16]
    assert narrate.line_key("Hi.", "af_heart", cfg, ver, ["--x"]) != old.hexdigest()[:16]


def test_spoken_text_is_say_when_given() -> None:
    ln = narrate.Line.model_validate({"shot": "s", "text": "نص 5", "say": "نَصٌّ خَمْسَةٌ"})
    assert narrate.spoken(ln) == "نَصٌّ خَمْسَةٌ"
    assert narrate.spoken(narrate.Line.model_validate({"shot": "s", "text": "Text"})) == "Text"


def test_worker_splits_long_lines_into_clauses() -> None:
    tts = _worker()
    assert tts.syllables("طَلَبٌ اصْطِنَاعِيٌّ") == 7  # ta-la-bun is-ti-naa-ʿiy-yun: 7 vowel marks
    line = ("تَبْدَأُ الرِّحْلَةُ عِنْدَ الكُورْنِيشِ الشَّمَالِيِّ، ثُمَّ تَرْتَفِعُ الكَامِيرَا فَوْقَ طَرِيقِ"
            " التَّحْلِيَةِ، حَتَّى تَظْهَرَ جُدَّةُ كُلُّهَا.")  # fmt: skip
    parts = tts.clauses(line, 10)
    assert len(parts) == 3 and " ".join(parts) == line
    assert tts.clauses("طَلَبٌ اصْطِنَاعِيٌّ، غَيْرُ مُعَايَرْ.", 10) == ["طَلَبٌ اصْطِنَاعِيٌّ، غَيْرُ مُعَايَرْ."]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_arabic_mux_tags_tracks_ara(tmp_path: Path) -> None:
    import wave

    import numpy as np

    from scripts.movies.render import mux_voice

    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=30",
         "-frames:v", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )  # fmt: skip
    wav = tmp_path / "voice.wav"
    t = np.arange(24000) / 24000
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes((np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2").tobytes())
    srt = tmp_path / "x.ar.srt"
    narrate.write_srt([(0.1, 0.9, "طلب اصطناعي، غير معاير.")], srt)
    out = tmp_path / "out.ar.mp4"
    mux_voice(video, wav, srt, out, "ar")
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name:stream_tags=language",
         "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    streams = {s["codec_type"]: s for s in json.loads(res.stdout)["streams"]}
    assert streams["audio"]["tags"]["language"] == "ara"
    assert streams["subtitle"]["codec_name"] == "mov_text"
    assert streams["subtitle"]["tags"]["language"] == "ara"
    assert "طلب اصطناعي" in srt.read_text(encoding="utf-8")  # logical order, not reversed


def _tts_ar() -> Path | None:
    py = REPO_ROOT / ".venv-tts-ar" / "bin" / "python"
    ref = REPO_ROOT / str(narrate._settings("ar")["voice"])
    return py if py.exists() and ref.exists() else None


@pytest.mark.skipif(_tts_ar() is None, reason="Arabic TTS venv missing (make voice-setup-ar)")
def test_arabic_tts_same_text_same_audio(tmp_path: Path) -> None:
    """Two separate worker processes, same line and seed: identical samples (about 1 min on CPU)."""
    py = _tts_ar()
    assert py is not None
    cfg = narrate._settings("ar")
    for k in range(2):
        job = [{"text": "غَيْرُ مُعَايَرْ.", "out": str(tmp_path / f"{k}.wav")}]
        subprocess.run(
            [str(py), str(narrate.tts_worker("ar")), "--voice", narrate.voice_ref(cfg["voice"]),
             "--seed", "1", *narrate._worker_args("ar")],
            input=json.dumps(job), text=True, check=True, capture_output=True,
            env=narrate.tts_env(),
        )  # fmt: skip
    a, b = ((tmp_path / f"{k}.wav").read_bytes() for k in range(2))
    assert a == b and len(a) > 12000


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_postprocess_caps_pauses_and_raises_tempo(tmp_path: Path) -> None:
    import wave

    import numpy as np

    rate = 24000
    tone = (np.sin(2 * np.pi * 220 * np.arange(rate) / rate) * 8000).astype("<i2")
    x = np.concatenate([tone, np.zeros(rate, dtype="<i2"), tone])  # 1 s, 1 s pause, 1 s
    capped = narrate._pause_cap(x, rate, 0.3)
    assert len(capped) == pytest.approx(2.3 * rate, abs=0.02 * rate)
    wav = tmp_path / "take.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())
    post = {"tempo": 1.12, "max_pause_s": 0.3}
    a = narrate.postprocess(wav, post)
    assert narrate.wav_seconds(a) == pytest.approx(2.3 / 1.12, abs=0.05)
    first = a.read_bytes()
    a.unlink()
    assert narrate.postprocess(wav, post).read_bytes() == first  # deterministic
    assert narrate._settings("ar")["post"] == post and "post" not in narrate._settings("en")
