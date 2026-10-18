"""Showreel: every rendered film in order, each after a short title card, joined with crossfades.

    python -m scripts.movies.showreel            # movies/showreel.mp4 (+ .poster.png, .gif, .json)
    python -m scripts.movies.showreel --lang ar  # movies/showreel.ar.mp4 from movies/<film>.ar.mp4

Inputs are movies/<film>.mp4 in the order of movies/specs/order.yaml (stub specs and films not
rendered yet are skipped and listed), each cut to its spec's `showreel: [start, end]` excerpt so the
reel stays at 2-3 minutes. Title cards are drawn with Pillow (over the film's poster,
blurred and darkened) at the films' size and frame rate; transitions are ffmpeg
`xfade` crossfades, H.264 yuv420p CRF 18 like the films.

Voice-over (MOVIES_V2): `movies/specs/showreel.narration.yaml` holds one headline per film; each
is spoken over its film's title card (the films' own voice tracks are not cut up), the last line
is the caveat. The headlines are mixed, loudness-normalised and muxed like a film's voice track,
with movies/showreel.srt beside the MP4. Excerpts follow the narrated (stretched) films: they
start at the `showreel_excerpt` recorded in movies/<film>.json and keep the spec's length.

Arabic edition (`--lang ar`): the same reel from the Arabic films (movies/<film>.ar.mp4 and their
.ar.json excerpts and .ar.poster.png stills), with the headlines of showreel.narration.ar.yaml;
the title cards keep the films' English titles (the specs carry no Arabic titles).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import typer

from scripts.movies import narrate
from scripts.movies.render import MOVIES_DIR, ffmpeg, make_gif, mux_voice, probe, probe_audio
from scripts.movies.spec import film_names, load_film, load_settings
from sim.common import SYNTHETIC_LABEL

CARD_S = 2.5
XFADE_S = 0.6
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def font() -> str:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise FileNotFoundError("no TTF font found for the title cards")


def card_image(film: Any, poster: Path, out: Path, w: int, h: int) -> None:
    """Title card still: the film's poster blurred and darkened, title text centred (Pillow)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    u = h / 1080
    img = Image.open(poster).convert("RGB").resize((w, h))
    img = img.filter(ImageFilter.GaussianBlur(round(14 * u)))
    img = ImageEnhance.Brightness(img).enhance(0.35)
    draw = ImageDraw.Draw(img)
    lines = [
        ("TrafficTwin Jeddah", 22, (231, 183, 95), -110),
        (film.title, 72, (255, 255, 255), -60),
        (film.subtitle, 28, (207, 214, 226), 40),
        (SYNTHETIC_LABEL, 20, (240, 196, 106), 110),
    ]
    for text, size, color, dy in lines:
        f = ImageFont.truetype(font(), round(size * u))
        tw = draw.textlength(text, font=f)
        draw.text(((w - tw) / 2, h / 2 + dy * u), text, font=f, fill=color)
    img.save(out)


def title_card(
    film: Any, poster: Path, out: Path, w: int, h: int, fps: int, r: dict[str, Any]
) -> None:
    still = out.with_suffix(".png")
    card_image(film, poster, still, w, h)
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-t",
            str(CARD_S),
            "-i",
            str(still),
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            str(r["preset"]),
            "-crf",
            str(r["crf"]),
            "-pix_fmt",
            str(r["pix_fmt"]),
            "-r",
            str(fps),
            str(out),
        ],
        check=True,
    )


def excerpt(film: Any, mp4: Path, out: Path, fps: int, r: dict[str, Any]) -> Path:
    """The showreel excerpt of a film (frame-accurate re-encode, video only), or all of it."""
    meta_path = mp4.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    span = meta.get("showreel_excerpt") or film.showreel
    if span is None:
        return mp4
    a, b = span
    if film.showreel is not None:  # keep the spec's excerpt length so the reel stays 2-3 min
        b = min(b, a + film.showreel[1] - film.showreel[0])
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(mp4),
            "-an",
            "-sn",
            "-vf",
            f"trim=start_frame={round(a * fps)}:end_frame={round(b * fps)},setpts=PTS-STARTPTS",
            "-c:v",
            "libx264",
            "-preset",
            str(r["preset"]),
            "-crf",
            str(r["crf"]),
            "-pix_fmt",
            str(r["pix_fmt"]),
            "-r",
            str(fps),
            str(out),
        ],
        check=True,
    )
    return out


def headline_track(
    names: list[str],
    starts: list[float],
    total_s: float,
    work: Path,
    out_dir: Path,
    lang: str = "en",
) -> dict[str, Any] | None:
    """Voice WAV + SRT of the showreel headlines: each film's lines from its title card on."""
    nar = narrate.load_narration("showreel", lang)
    if nar is None:
        return None
    cfg = narrate._settings(lang)
    tag = "" if lang == "en" else f".{lang}"
    voice = nar.voice or str(cfg["voice"])
    lines = [ln for ln in nar.lines if ln.film in names]
    wavs = narrate.speak([narrate.spoken(ln) for ln in lines], voice, lang)
    placed: list[tuple[float, float, str, Path]] = []
    prev_end = -1.0
    for ln, wav in zip(lines, wavs, strict=True):
        start = max(
            starts[names.index(str(ln.film))] + float(cfg["lead_s"]), prev_end + float(cfg["gap_s"])
        )
        prev_end = start + narrate.wav_seconds(wav)
        placed.append((start, prev_end, ln.text, wav))
    if placed and placed[-1][1] > total_s:  # the caveat closes the reel: it must not be cut off
        raise ValueError(
            f"showreel headline {placed[-1][2][:40]!r} ends at {placed[-1][1]:.2f} s, after the "
            f"reel ({total_s:.2f} s): shorten it"
        )
    wav_out = work / "showreel.voice.wav"
    sha = narrate.voice_track([(a, w) for a, _, _, w in placed], total_s, wav_out, lang)
    srt = out_dir / f"showreel{tag}.srt"
    narrate.write_srt([(a, b, t) for a, b, t, _ in placed], srt)
    return {"wav": wav_out, "srt": srt, "voice_sha256_16": sha, "voice": voice,
            "lines": [{"text": t, "start_s": round(a, 3), "end_s": round(b, 3)}
                      for a, b, t, _ in placed]}  # fmt: skip


def build(out_dir: Path = MOVIES_DIR, voice: bool = True, lang: str = "en") -> dict[str, Any]:
    r = load_settings()["render"]
    tag = "" if lang == "en" else f".{lang}"
    clips: list[tuple[str, Path]] = []
    skipped = []
    for name in film_names():
        film = load_film(name)
        mp4 = out_dir / f"{name}{tag}.mp4"
        if film.stub or not mp4.exists():
            skipped.append(name)
            continue
        clips.append((name, mp4))
    if not clips:
        raise FileNotFoundError("no rendered films in movies/ (make movies first)")
    info0 = probe(clips[0][1])
    w, h, fps = info0["width"], info0["height"], round(info0["fps"])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts: list[Path] = []
        for name, mp4 in clips:
            info = probe(mp4)
            if (info["width"], info["height"], round(info["fps"])) != (w, h, fps):
                raise ValueError(f"{name}: size/fps differ from {clips[0][0]}; render all alike")
            film = load_film(name)
            card = tmp / f"{name}.card.mp4"
            title_card(film, out_dir / f"{name}{tag}.poster.png", card, w, h, fps, r)
            parts += [card, excerpt(film, mp4, tmp / f"{name}.cut.mp4", fps, r)]
        durations = [probe(p)["duration_s"] for p in parts]
        inputs: list[str] = []
        for p in parts:
            inputs += ["-i", str(p)]
        chain = []
        prev = "[0:v]"
        offset = 0.0
        for k in range(1, len(parts)):
            offset += durations[k - 1] - XFADE_S
            label = f"[v{k}]"
            chain.append(
                f"{prev}[{k}:v]xfade=transition=fade:duration={XFADE_S}:offset={offset:.3f}{label}"
            )
            prev = label
        out = out_dir / f"showreel{tag}.mp4"
        names = [n for n, _ in clips]
        starts = [sum(durations[: 2 * i]) - 2 * i * XFADE_S for i in range(len(clips))]
        total = sum(durations) - (len(parts) - 1) * XFADE_S
        voice_info = headline_track(names, starts, total, tmp, out_dir, lang) if voice else None
        silent = tmp / "showreel.video.mp4" if voice_info else out
        subprocess.run(
            [
                ffmpeg(),
                "-y",
                "-loglevel",
                "error",
                *inputs,
                "-filter_complex",
                ";".join(chain),
                "-map",
                prev,
                "-c:v",
                "libx264",
                "-preset",
                str(r["preset"]),
                "-crf",
                str(r["crf"]),
                "-pix_fmt",
                str(r["pix_fmt"]),
                "-r",
                str(fps),
                "-movflags",
                "+faststart",
                str(silent),
            ],
            check=True,
        )
        audio = None
        if voice_info:
            loud = mux_voice(silent, voice_info["wav"], voice_info["srt"], out, lang)
            audio = {k: v for k, v in voice_info.items() if k not in ("wav", "srt")}
            audio.update(
                {"loudness": loud, "srt": f"showreel{tag}.srt", "stream": probe_audio(out)}
            )
        else:
            (out_dir / f"showreel{tag}.srt").unlink(missing_ok=True)
    info = probe(out)
    poster = out_dir / f"showreel{tag}.poster.png"
    shutil.copyfile(out_dir / f"{clips[0][0]}{tag}.poster.png", poster)
    gif = make_gif(out, out_dir / f"showreel{tag}.gif", CARD_S + 4.0, r)
    meta = {
        "label": SYNTHETIC_LABEL,
        "lang": lang,
        "films": [n for n, _ in clips],
        "skipped": skipped,
        "card_s": CARD_S,
        "xfade_s": XFADE_S,
        "mp4": info,
        "audio": audio,
        "gif": gif,
    }
    (out_dir / f"showreel{tag}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return meta


app = typer.Typer(add_completion=False)


@app.command()
def main(
    out: Path = typer.Option(MOVIES_DIR, help="directory holding the films"),
    no_voice: bool = typer.Option(False, "--no-voice", help="silent showreel"),
    lang: str = typer.Option("en", help="edition: en | ar (movies/showreel.ar.mp4)"),
) -> None:
    """Build movies/showreel.mp4 (or showreel.<lang>.mp4) from the rendered films."""
    meta = build(out, voice=not no_voice, lang=lang)
    typer.echo(
        f"showreel: {len(meta['films'])} films, {meta['mp4']['duration_s']:.1f} s"
        f" (skipped: {', '.join(meta['skipped']) or 'none'})"
    )


if __name__ == "__main__":
    app()
