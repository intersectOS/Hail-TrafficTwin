"""Voice-over for the films: narration scripts -> speech -> timing, voice track and subtitles.

    uv run python -m scripts.movies.narrate validate          # movies/specs/*.narration.yaml
    uv run python -m scripts.movies.narrate speak evacuation  # WAVs + timing for one film
    uv run python -m scripts.movies.narrate speak evacuation --lang ar   # the Arabic edition
    make voice-setup                                          # the offline TTS venv (.venv-tts)
    make voice-setup-ar                                       # the Arabic TTS venv (.venv-tts-ar)

A narration script (`movies/specs/<film>.narration.yaml`) has 4-8 plain-English lines, each tied to
a shot of the film: `at` (seconds into the shot, i.e. a camera moment) or `sim_t` (the moment the
shot's sim clock reaches it), or neither (straight after the line before). The last line is the
caveat. Every number spoken must already be in the docs (`NUMBER_DOCS`); `validate` checks that.

Each line is spoken by Kokoro-82M (scripts/movies/tts_kokoro.py, run in `.venv-tts`; cached per
text + voice + versions under runs/movies/_voice/). The measured durations set the timing: a line
starts at its anchor, never before the previous line has ended (+ gap), and the shot is slowed down
(camera keyframes stretched, the sim time-lapse rate drops) until its last line ends inside it:
shots stretch to fit speech, never the reverse. `apply_timing` returns the stretched film;
`voice_track` mixes the lines into one WAV of the film's length; `write_srt` writes the subtitles.
Same script + model + settings => same samples (seeded TTS), so the voice track hash is stable.

Arabic edition (`--lang ar`, docs/movies-arabic.md): `<film>.narration.ar.yaml` has the same lines
and anchors in Modern Standard Arabic. Each line's `text` is the subtitle (Western digits, the same
figures as the English line) and `say` the fully vowelised text the TTS speaks, numbers in words.
`check` compares the subtitle's numbers with the English line's and reads the spoken number words
back (`ar_numbers`) so the voice says the same figures. The Arabic voice is Chatterbox
Multilingual (scripts/movies/tts_ar.py in `.venv-tts-ar`, settings `voice.ar`), cached in
runs/movies/_voice_ar/.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import typer
import yaml
from pydantic import Field, model_validator

from scripts.movies.spec import SPECS_DIR, Film, Strict, film_names, load_film, load_settings
from sim.common import REPO_ROOT

NARRATION_SUFFIX = ".narration.yaml"
LANGS = ("en", "ar")
TTS_WORKER = Path(__file__).with_name("tts_kokoro.py")
# numbers spoken in a narration must appear in one of these (MOVIES_V2: never invent a number)
NUMBER_DOCS = [
    "docs/policies.md",
    "docs/loop.md",
    "docs/evacuation.md",
    "docs/strategist.md",
    "docs/events.md",
    "docs/obhur-bridge.md",
    "docs/movies.md",
]
CAVEAT_WORDS = ("synthetic", "uncalibrated")
CAVEAT_AR = "طلب اصطناعي، غير معاير"


class Line(Strict):
    text: str = Field(min_length=3)  # what is spoken, and the subtitle
    say: str | None = None  # Arabic edition: the vowelised text spoken instead (numbers in words)
    shot: str | None = None  # film narration: shot id the line belongs to
    film: str | None = None  # showreel narration: film whose excerpt the line belongs to
    at: float | None = Field(default=None, ge=0)  # seconds into the shot (camera moment)
    sim_t: float | None = None  # or: when the shot's sim clock reaches this

    @model_validator(mode="after")
    def _anchor(self) -> Line:
        if (self.shot is None) == (self.film is None):
            raise ValueError(f"line {self.text[:30]!r}: give exactly one of `shot` or `film`")
        if self.at is not None and self.sim_t is not None:
            raise ValueError(f"line {self.text[:30]!r}: give `at` or `sim_t`, not both")
        return self


class Narration(Strict):
    film: str
    voice: str | None = None  # default: settings voice.voice (one voice for every film)
    lines: list[Line] = Field(min_length=1, max_length=12)


def suffix(lang: str = "en") -> str:
    if lang not in LANGS:
        raise ValueError(f"language {lang!r}: one of {LANGS}")
    return NARRATION_SUFFIX if lang == "en" else f".narration.{lang}.yaml"


def narration_path(film: str, lang: str = "en") -> Path:
    return SPECS_DIR / f"{film}{suffix(lang)}"


def load_narration(film: str, lang: str = "en") -> Narration | None:
    path = narration_path(film, lang)
    if not path.exists():
        return None
    nar = Narration.model_validate(yaml.safe_load(path.read_text()))
    if nar.film != film:
        raise ValueError(f"{path.name}: film {nar.film!r} must be {film!r}")
    return nar


# ----------------------------------------------------------------------------- checks


NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[str]:
    return [m.group(0).rstrip(",").replace(",", "") for m in NUM_RE.finditer(text)]


def doc_numbers() -> set[str]:
    nums: set[str] = set()
    for d in NUMBER_DOCS:
        p = REPO_ROOT / d
        if p.exists():
            nums.update(_numbers(p.read_text()))
    return nums


DIACRITICS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
AR_UNITS = {
    "واحد": 1, "واحده": 1, "احد": 1, "احدى": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2,
    "اثنتين": 2, "ثلاثه": 3, "ثلاث": 3, "اربعه": 4, "اربع": 4, "خمسه": 5, "خمس": 5, "سته": 6,
    "ست": 6, "سبعه": 7, "سبع": 7, "ثمانيه": 8, "ثماني": 8, "ثمان": 8, "تسعه": 9, "تسع": 9,
    "عشره": 10, "عشر": 10, "اثني": 2, "اثنا": 2, "اثنتي": 2, "اثنتا": 2,
}  # fmt: skip
for _w in ("واحد", "ثلاث", "اربع", "خمس", "ست", "سبع", "ثماني", "تسع", "عشر"):
    AR_UNITS[f"{_w}ا"] = AR_UNITS[_w]  # accusative with tanween: خمسًا، واحدًا
AR_TENS = {
    "عشرون": 20, "عشرين": 20, "ثلاثون": 30, "ثلاثين": 30, "اربعون": 40, "اربعين": 40,
    "خمسون": 50, "خمسين": 50, "ستون": 60, "ستين": 60, "سبعون": 70, "سبعين": 70, "ثمانون": 80,
    "ثمانين": 80, "تسعون": 90, "تسعين": 90,
}  # fmt: skip
AR_HUNDREDS = {"مئه": 100, "مائه": 100, "مئتان": 200, "مئتين": 200, "مائتان": 200, "مائتين": 200}
for _w, _v in (("ثلاث", 3), ("اربع", 4), ("خمس", 5), ("ست", 6), ("سبع", 7), ("ثمان", 8),
               ("تسع", 9)):  # fmt: skip
    AR_HUNDREDS[f"{_w}مئه"] = AR_HUNDREDS[f"{_w}مائه"] = _v * 100
AR_THOUSAND = {"الف": 1, "الفا": 1, "الاف": 1, "الفان": 2, "الفين": 2}
AR_POINT = "فاصله"


def ar_bare(text: str) -> str:
    """Arabic without diacritics or tatweel; alef forms unified, ة as ه, ى as ي."""
    t = DIACRITICS.sub("", text)
    return re.sub("[إأآٱ]", "ا", t).replace("ة", "ه").replace("ى", "ي")


def _ar_word(w: str) -> tuple[str, int] | None:
    """(kind, value) of an Arabic number word, with an optional و / ب prefix; None otherwise."""
    for cand in (w, w[1:] if w[:1] in "وب" else ""):
        if cand in AR_UNITS:
            return "unit", AR_UNITS[cand]
        if cand in AR_TENS:
            return "ten", AR_TENS[cand]
        if cand in AR_HUNDREDS:
            return "hundred", AR_HUNDREDS[cand]
        if cand in AR_THOUSAND:
            return "thousand", AR_THOUSAND[cand]
        if cand == AR_POINT:
            return "point", 0
    return None


def _ar_int(toks: list[tuple[str, int] | None], j: int) -> tuple[int, int]:
    """One integer read greedily from toks[j]; returns (value, index after it)."""
    rank = {"hundred": 3, "unit": 2, "ten": 1}
    total = group = 0
    last = 9  # rank of the last part of the current group (9 = group empty)
    teen = thousands = False
    while j < len(toks) and toks[j] is not None:
        kind, v = toks[j]  # type: ignore[misc]
        if kind == "point":
            break
        if kind == "thousand":
            if thousands:
                break
            total += (group or v) * 1000 if group else v * 1000
            group, last, thousands = 0, 9, True
        elif kind == "unit" and v == 10 and last == 2 and not teen and group % 10:
            group += 10  # ثلاثة عشر = 13
            teen = True
        else:
            r = rank[kind]
            if last != 9 and r >= last:
                break  # cannot follow the part before: a new number starts here
            group += v
            last, teen = r, False
        j += 1
    return total + group, j


def ar_numbers(text: str) -> list[str]:
    """The numbers spoken in Arabic words, as digit strings ('مئة وثمانية وسبعون ألفًا وتسعمئة
    وتسع' -> '178909', 'ثمانية فاصلة سبعة' -> '8.7'). Within a number the parts come hundreds,
    units, tens, and ألف multiplies the group before it; a part that cannot follow the one before
    starts a new number ('ستمئة وأربعمئة' = 600 and 400)."""
    toks = [_ar_word(w) for w in re.findall(r"[\u0621-\u064a]+", ar_bare(text))]
    out: list[str] = []
    j = 0
    while j < len(toks):
        if toks[j] is None or toks[j][0] == "point":  # type: ignore[index]
            j += 1
            continue
        v, j = _ar_int(toks, j)
        num = str(v)
        if j + 1 < len(toks) and toks[j] == ("point", 0) and toks[j + 1] is not None:
            f, j = _ar_int(toks, j + 1)
            num = f"{v}.{f}"
        out.append(num)
    return out


def _num_key(n: str) -> str:
    return n.rstrip("0").rstrip(".") if "." in n else n


def check_ar(nar: Narration, en: Narration | None, film: Film | None) -> list[str]:
    """Problems with an Arabic narration: anchors and figures against its English counterpart."""
    errs = []
    if en is None:
        return ["no English narration to compare with"]
    if len(nar.lines) != len(en.lines):
        errs.append(f"{len(nar.lines)} lines, the English script has {len(en.lines)}")
    if film is not None:
        ids = [s.id for s in film.shots]
        bad = [ln.shot for ln in nar.lines if ln.shot not in ids]
        if bad:
            errs.append(f"unknown shot in {bad}")
    if CAVEAT_AR not in ar_bare(nar.lines[-1].text).replace("معايره", "معاير"):
        errs.append(f"the last line must carry the caveat «{CAVEAT_AR}»")
    for k, (ar, e) in enumerate(zip(nar.lines, en.lines, strict=False), start=1):
        where = f"line {k}"
        if (ar.shot, ar.film, ar.at, ar.sim_t) != (e.shot, e.film, e.at, e.sim_t):
            errs.append(f"{where}: anchor differs from the English line")
        want = sorted(_numbers(e.text))
        got = sorted(_numbers(ar.text))
        if got != want:
            errs.append(f"{where}: subtitle numbers {got} != English {want}")
        if ar.say is None:
            continue
        if re.search(r"[0-9\u0660-\u0669]", ar.say):
            errs.append(f"{where}: `say` has digits (write numbers in words)")
        spoken = [_num_key(n) for n in ar_numbers(ar.say)]
        for n in want:
            if _num_key(n) not in spoken:
                errs.append(f"{where}: {n} is not spoken in `say` (read {spoken})")
                continue
            spoken.remove(_num_key(n))
    return errs


def check(nar: Narration, film: Film | None, known: set[str]) -> list[str]:
    """Problems with a narration script (empty list = OK)."""
    errs = []
    if film is not None:
        if not 4 <= len(nar.lines) <= 8:
            errs.append(f"{len(nar.lines)} lines (want 4-8)")
        ids = [s.id for s in film.shots]
        order = [ids.index(ln.shot) if ln.shot in ids else -1 for ln in nar.lines]
        if -1 in order:
            errs.append(f"unknown shot in {[ln.shot for ln in nar.lines if ln.shot not in ids]}")
        elif order != sorted(order):
            errs.append("lines must follow the shot order")
    last = nar.lines[-1].text.lower()
    if not all(w in last for w in CAVEAT_WORDS):
        errs.append("the last line must be the caveat (synthetic demand, uncalibrated)")
    for ln in nar.lines:
        for n in _numbers(ln.text):
            if n not in known:
                errs.append(f"number {n} in {ln.text[:40]!r} is not in {', '.join(NUMBER_DOCS)}")
    return errs


# ----------------------------------------------------------------------------- speech


def _settings(lang: str = "en") -> dict[str, Any]:
    """Voice settings for a language: `voice` (English), `voice.ar` overriding it for Arabic."""
    v = dict(load_settings()["voice"])
    per_lang = {k: v.pop(k) for k in LANGS if isinstance(v.get(k), dict)}
    return {**v, **per_lang.get(lang, {})}


def tts_worker(lang: str = "en") -> Path:
    return Path(__file__).with_name(str(_settings(lang).get("worker", TTS_WORKER.name)))


def tts_python(lang: str = "en") -> Path:
    py = REPO_ROOT / str(_settings(lang)["venv"]) / "bin" / "python"
    if not py.exists():
        target = "voice-setup" if lang == "en" else f"voice-setup-{lang}"
        raise FileNotFoundError(f"{py} missing: run `make {target}` (offline TTS venv)")
    return py


def tts_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("HF_HUB_OFFLINE", "1")  # the model is in the HF cache after voice-setup
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.pop("VIRTUAL_ENV", None)
    return env


_VERSIONS: dict[str, dict[str, str]] = {}


def _worker_args(lang: str) -> list[str]:
    """Worker options beyond voice/speed/seed (settings `voice.<lang>.args`, e.g. Chatterbox's)."""
    return [str(x) for x in _settings(lang).get("args", [])]


def tts_versions(lang: str = "en") -> dict[str, str]:
    if lang not in _VERSIONS:
        res = subprocess.run(
            [str(tts_python(lang)), str(tts_worker(lang)), "--versions", *_worker_args(lang)],
            capture_output=True, text=True, check=True, env=tts_env(),
        )  # fmt: skip
        _VERSIONS[lang] = json.loads(res.stdout.strip().splitlines()[-1])
    return _VERSIONS[lang]


def voice_dir(lang: str = "en") -> Path:
    return REPO_ROOT / "runs" / "movies" / ("_voice" if lang == "en" else f"_voice_{lang}")


def voice_ref(voice: str) -> str:
    """A voice that names a file (Arabic reference clip) as an absolute path; others unchanged."""
    p = REPO_ROOT / voice
    return str(p) if "/" in voice and p.exists() else voice


def line_key(
    text: str, voice: str, cfg: dict[str, Any], ver: dict[str, str], extra: list[str] | None = None
) -> str:
    items: list[Any] = [text, voice, cfg["speed"], cfg["seed"], ver]
    if extra:  # the Arabic worker's options (English keys stay as they were)
        items.append(extra)
    raw = json.dumps(items, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def speak(texts: list[str], voice: str, lang: str = "en") -> list[Path]:
    """WAV per text (cached); missing ones are synthesised in `workers` TTS processes."""
    cfg = _settings(lang)
    ver = tts_versions(lang)
    extra = _worker_args(lang) or None
    paths = [voice_dir(lang) / f"{line_key(t, voice, cfg, ver, extra)}.wav" for t in texts]
    jobs = [{"text": t, "out": str(p)} for t, p in zip(texts, paths, strict=True) if not p.exists()]
    if jobs:
        cmd = [str(tts_python(lang)), str(tts_worker(lang)), "--voice", voice_ref(voice),
               "--speed", str(cfg["speed"]), "--seed", str(cfg["seed"])]  # fmt: skip
        cmd += extra or []
        n = max(1, min(int(cfg.get("workers", 1)), len(jobs)))
        logs = voice_dir(lang) / "_logs"
        logs.mkdir(parents=True, exist_ok=True)
        procs = []
        for k in range(n):  # start every worker first, so they run in parallel
            err = (logs / f"worker-{k}.log").open("w")  # stderr; stdout in .out
            out = (logs / f"worker-{k}.out").open("a")
            pr = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True, env=tts_env()
            )  # fmt: skip
            out.close()
            assert pr.stdin is not None
            pr.stdin.write(json.dumps(jobs[k::n]))
            pr.stdin.close()
            procs.append((pr, err, logs / f"worker-{k}.log"))
        for pr, err, log in procs:
            pr.wait()
            err.close()
            if pr.returncode != 0:
                raise RuntimeError(f"TTS failed: {log.read_text()[-2000:]}")
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise RuntimeError(f"TTS wrote no audio for {missing}")
    post = cfg.get("post")
    return [postprocess(p, post) for p in paths] if post else paths


def _pause_cap(x: np.ndarray, rate: int, max_pause_s: float, thresh_db: float = -45) -> np.ndarray:
    """Shorten every pause (20 ms frames below thresh_db) longer than max_pause_s to max_pause_s."""
    win = int(0.02 * rate)
    n = len(x) // win
    if n == 0:
        return x
    frames = x[: n * win].astype(np.float64).reshape(n, win) / 32768.0
    quiet = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-12) < thresh_db
    keep = np.ones(n, dtype=bool)
    cap = max(1, int(round(max_pause_s / 0.02)))
    k = 0
    while k < n:
        if quiet[k]:
            j = k
            while j < n and quiet[j]:
                j += 1
            if j - k > cap:  # keep the pause's two ends, drop its middle
                keep[k + cap // 2 : j - (cap - cap // 2)] = False
            k = j
        else:
            k += 1
    return np.concatenate([x[: n * win].reshape(n, win)[keep].ravel(), x[n * win :]])


def postprocess(wav: Path, post: dict[str, Any]) -> Path:
    """The cached take with long pauses capped and the tempo raised (ffmpeg atempo, pitch kept).

    Settings `voice.<lang>.post` ({tempo, max_pause_s}); the raw take stays cached, so changing the
    post-processing never re-runs the TTS. Deterministic: same take + settings => same samples."""
    tag = hashlib.sha256(json.dumps(post, sort_keys=True).encode()).hexdigest()[:8]
    out = wav.with_name(f"{wav.stem}.post-{tag}.wav")
    if out.exists():
        return out
    with wave.open(str(wav)) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if post.get("max_pause_s"):
        x = _pause_cap(x, rate, float(post["max_pause_s"]))
    tmp = out.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.astype("<i2").tobytes())
    tempo = float(post.get("tempo", 1.0))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", f"atempo={tempo}",
         "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le", "-fflags", "+bitexact",
         "-flags:a", "+bitexact", str(out)],
        check=True,
    )  # fmt: skip
    tmp.unlink()
    return out


# ----------------------------------------------------------------------------- timing


@dataclass
class Timed:
    text: str
    wav: Path
    seconds: float
    start_s: float = 0.0
    shot: str = ""

    @property
    def end_s(self) -> float:
        return self.start_s + self.seconds


@dataclass
class Timing:
    film: str
    voice: str
    lines: list[Timed]
    stretch: dict[str, float]  # shot id -> factor (1 = unchanged)
    duration_s: float
    versions: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "film": self.film,
            "voice": self.voice,
            "duration_s": round(self.duration_s, 4),
            "stretch": {k: round(v, 5) for k, v in self.stretch.items()},
            "lines": [
                {
                    "text": t.text,
                    "shot": t.shot,
                    "start_s": round(t.start_s, 3),
                    "end_s": round(t.end_s, 3),
                    "seconds": round(t.seconds, 3),
                    "wav": t.wav.name,
                }
                for t in self.lines
            ],  # fmt: skip
            "versions": self.versions,
        }


def _sim_anchor(shot: Any, sim_t: float) -> float:
    """Shot-local time when the shot's sim clock reaches sim_t (keyframes, linear between)."""
    keys = [(k.t, k.sim_t) for k in shot.camera if k.sim_t is not None]
    if len(keys) == 1 or sim_t <= keys[0][1]:
        return keys[0][0] if sim_t <= keys[0][1] else keys[-1][0]
    for (t0, s0), (t1, s1) in zip(keys, keys[1:], strict=False):
        if s0 <= sim_t <= s1 and s1 > s0:
            return t0 + (sim_t - s0) / (s1 - s0) * (t1 - t0)
    return keys[-1][0]


def plan_timing(
    film: Film,
    nar: Narration,
    seconds: list[float],
    wavs: list[Path],
    fps: int | None = None,
    lang: str = "en",
) -> Timing:
    """Place the lines, find each shot's stretch (with `fps`: stretched shots last whole frames)."""
    cfg = _settings(lang)
    gap, lead, tail = float(cfg["gap_s"]), float(cfg["lead_s"]), float(cfg["tail_s"])
    by_shot: dict[str, list[int]] = {}
    for i, ln in enumerate(nar.lines):
        by_shot.setdefault(str(ln.shot), []).append(i)
    timed = [Timed(ln.text, w, s, shot=str(ln.shot)) for ln, w, s in zip(nar.lines, wavs, seconds,
                                                                        strict=True)]  # fmt: skip
    stretch: dict[str, float] = {}
    shot_start = 0.0
    prev_end = film.title_card_s + float(cfg["after_title_s"]) - gap
    for shot in film.shots:
        idx = by_shot.get(shot.id, [])
        base = []
        for i in idx:
            ln = nar.lines[i]
            if ln.at is not None:
                base.append(ln.at)
            elif ln.sim_t is not None:
                base.append(_sim_anchor(shot, ln.sim_t))
            else:
                base.append(None)
        k = 1.0
        for _ in range(50):
            p = prev_end
            for j, i in enumerate(idx):
                anchor = shot_start + max(lead, (base[j] or 0.0) * k) if base[j] is not None else 0
                timed[i].start_s = max(p + gap, anchor, shot_start + lead)
                p = timed[i].end_s
            need = (p + tail - shot_start) if idx else 0.0
            if need <= shot.duration_s * k + 1e-6:
                break
            k = need / shot.duration_s
            if fps:  # a whole number of frames, so the film's length is exact
                k = math.ceil(shot.duration_s * k * fps - 1e-6) / (fps * shot.duration_s)
        stretch[shot.id] = k
        if idx:
            prev_end = timed[idx[-1]].end_s
        shot_start += shot.duration_s * k
    return Timing(film.film, "", timed, stretch, shot_start)


def apply_timing(film: Film, timing: Timing) -> Film:
    """The film with every shot (camera keyframes, duration) stretched by its factor."""
    data = film.model_dump()
    old_bounds, new_bounds = [], []
    o = n = 0.0
    for shot in data["shots"]:
        k = timing.stretch.get(shot["id"], 1.0)
        old_bounds.append((o, o + shot["duration_s"], k))
        new_bounds.append(n)
        o += shot["duration_s"]
        shot["duration_s"] = round(shot["duration_s"] * k, 6)
        for key in shot["camera"]:
            key["t"] = round(key["t"] * k, 6)
        n += shot["duration_s"]
    data["duration_s"] = round(sum(s["duration_s"] for s in data["shots"]), 6)

    def remap(t: float) -> float:
        for (a, b, k), s0 in zip(old_bounds, new_bounds, strict=True):
            if t <= b + 1e-9:
                return round(s0 + (t - a) * k, 3)
        return data["duration_s"]

    if data.get("showreel"):
        data["showreel"] = [remap(data["showreel"][0]), remap(data["showreel"][1])]
    return Film.model_validate(data)


def spoken(ln: Line) -> str:
    """What the voice says: `say` (Arabic edition) or the subtitle text."""
    return ln.say or ln.text


def prepare(film: Film, fps: int | None = None, lang: str = "en") -> Timing | None:
    """Speak a film's narration (cached) and plan its timing; None when the film has none."""
    nar = load_narration(film.film, lang)
    if nar is None:
        return None
    cfg = _settings(lang)
    voice = nar.voice or str(cfg["voice"])
    wavs = speak([spoken(ln) for ln in nar.lines], voice, lang)
    timing = plan_timing(film, nar, [wav_seconds(w) for w in wavs], wavs, fps, lang)
    timing.voice = voice
    timing.versions = tts_versions(lang)
    k_max = max(timing.stretch.values(), default=1.0)
    if k_max > float(cfg["max_stretch"]):
        print(f"[narrate] {film.film}: a shot is stretched x{k_max:.2f} to fit its speech")
    return timing


# ----------------------------------------------------------------------------- audio + subtitles


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.int32)


def voice_track(
    lines: list[tuple[float, Path]], duration_s: float, out: Path, lang: str = "en"
) -> str:
    """Mix (start_s, wav) lines into one 16-bit mono WAV of duration_s; return its sha256[:16]."""
    rate = int(_settings(lang)["sample_rate"])
    n = int(round(duration_s * rate))
    mix = np.zeros(n, dtype=np.int32)
    for start, wav in lines:
        a = _read_wav(wav)
        i = int(round(start * rate))
        j = min(n, i + len(a))
        if i < n:
            mix[i:j] += a[: j - i]
    pcm = np.clip(mix, -32768, 32767).astype("<i2").tobytes()
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return hashlib.sha256(pcm).hexdigest()[:16]


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(lines: list[tuple[float, float, str]], out: Path) -> None:
    blocks = [
        f"{k}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n"
        for k, (a, b, text) in enumerate(lines, start=1)
    ]
    out.write_text("\n".join(blocks), encoding="utf-8")


# ----------------------------------------------------------------------------- CLI

app = typer.Typer(add_completion=False, help=__doc__)


@app.callback()
def _cli() -> None:
    """Film narration tools."""


def validate_all() -> list[tuple[str, list[str]]]:
    """(file name, problems) for every narration script, English and Arabic."""
    known = doc_numbers()
    out = []
    for lang in LANGS:
        suf = suffix(lang)
        paths = sorted(p for p in SPECS_DIR.glob(f"*{suf}") if lang != "en" or
                       not any(p.name.endswith(suffix(o)) for o in LANGS if o != "en"))  # fmt: skip
        for path in paths:
            name = path.name[: -len(suf)]
            try:
                nar = load_narration(name, lang)
                assert nar is not None
                film = load_film(name) if name in film_names() else None
                if lang == "en":
                    errs = check(nar, film, known)
                else:
                    errs = check_ar(nar, load_narration(name), film)
            except (ValueError, OSError) as exc:
                errs = [str(exc)]
            out.append((path.name, errs))
    return out


@app.command()
def validate() -> None:
    """Check every narration script: anchors, 4-8 lines, caveat last, numbers from the docs; the
    Arabic scripts against their English counterparts (anchors, figures, spoken number words)."""
    results = validate_all()
    bad = 0
    for name, errs in results:
        bad += bool(errs)
        detail = "".join(f"\n     {e}" for e in errs)
        typer.echo(f"{'FAIL' if errs else 'OK  '} {name}{detail}")
    for lang in LANGS:
        for n in film_names():
            if not narration_path(n, lang).exists() and not load_film(n).stub:
                typer.echo(f"WARN {n}: no {suffix(lang)[1:]} narration script")
    raise typer.Exit(1 if bad else 0)


@app.command("speak")
def speak_cmd(film: str, lang: str = typer.Option("en", help="en | ar")) -> None:
    """Synthesise one film's narration and print the timing (shot stretch factors)."""
    timing = prepare(load_film(film), lang=lang)
    if timing is None:
        raise typer.BadParameter(f"no {narration_path(film, lang).name}")
    typer.echo(json.dumps(timing.as_json(), indent=1, ensure_ascii=False))


@app.command("speak-all")
def speak_all_cmd(lang: str = typer.Option("en", help="en | ar")) -> None:
    """Synthesise every narration line of a language at once (all TTS workers busy; cached)."""
    texts = []
    for name in [*film_names(), "showreel"]:
        nar = load_narration(name, lang)
        texts += [spoken(ln) for ln in nar.lines] if nar else []
    voice = str(_settings(lang)["voice"])
    typer.echo(f"{len(speak(texts, voice, lang))} lines in {voice_dir(lang)}")


if __name__ == "__main__":
    app()
