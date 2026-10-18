"""Render films: bundle -> headless Chrome frames -> H.264 MP4 + poster + GIF preview.

    python -m scripts.movies.render tahlia-street            # one film (make movie FILM=...)
    python -m scripts.movies.render --all                    # every spec (make movies)
    python -m scripts.movies.render tahlia-street --size 640x360 --frames 0:10 --out /tmp/x
    python -m scripts.movies.render tahlia-street --4k --fps 60 --letterbox

Per film: the data bundle is built (scripts.movies.bundle), the built viewer (web/dist) and the
bundle are served from 127.0.0.1 on a free port, web/scripts/cinema.mjs steps the frames in
headless Chrome and writes PNGs to runs/movies/<film>/frames/ in chunks; each chunk is encoded
(libx264, yuv420p, CRF 18) and its PNGs deleted, so at most one chunk sits on disk. The chunks are
joined without re-encoding into movies/<film>.mp4; then movies/<film>.poster.png (middle frame),
movies/<film>.gif (<= 6 s, <= 3 MB) and movies/<film>.json (sizes, hashes of the first, middle and
last frame, browser RSS, disk peak, timings). Frames are deleted after a successful encode.

Voice-over (MOVIES_V2): before the bundle, the film's narration script is spoken offline
(scripts/movies/narrate.py, Kokoro-82M) and the shots are stretched to fit the speech; the
subtitles are drawn by the HUD from the same lines. After the encode the lines are mixed into one
voice track, loudness-normalised (EBU R128, two-pass, linear) and muxed as AAC with a soft
subtitle track; movies/<film>.srt is written next to the MP4. `--no-voice` renders silently with
the spec's own timing; `--no-subtitles` keeps the voice but draws no subtitles.

Arabic edition (`--lang ar`, docs/movies-arabic.md): the same film with the Arabic narration
(`<film>.narration.ar.yaml`, Chatterbox Multilingual): movies/<film>.ar.mp4 (+ .ar.srt,
.ar.poster.png, .ar.gif, .ar.json), work files in runs/movies/<film>.ar/, subtitle and audio tracks
tagged `ara`. The English outputs are not touched.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import typer

from scripts.movies import narrate
from scripts.movies.bundle import build_bundle, movies_runs_dir, sha_file
from scripts.movies.spec import SPECS_DIR, film_names, load_film, load_settings, spec_path
from sim.common import REPO_ROOT, SYNTHETIC_LABEL

WEB = REPO_ROOT / "web"
DIST = WEB / "dist"
DRIVER = WEB / "scripts" / "cinema.mjs"
MOVIES_DIR = REPO_ROOT / "movies"


def log(msg: str) -> None:
    print(f"[movies] {msg}", flush=True)


# ----------------------------------------------------------------------------- web build


def _newest(paths: list[Path]) -> float:
    newest = 0.0
    for root in paths:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        newest = max([newest, *(p.stat().st_mtime for p in files)])
    return newest


def ensure_web_build(force: bool = False) -> None:
    """`npm run build` when web/dist is missing or older than web/src."""
    index = DIST / "index.html"
    srcs = [WEB / "src", WEB / "index.html", WEB / "package-lock.json", WEB / "vite.config.ts"]
    if not force and index.exists() and index.stat().st_mtime >= _newest(srcs):
        return
    log("building the viewer (npm run build)")
    subprocess.run(["npm", "run", "build"], cwd=WEB, check=True, stdout=subprocess.DEVNULL)


# ----------------------------------------------------------------------------- static server


class _Handler(http.server.SimpleHTTPRequestHandler):
    @property
    def bundles(self) -> Path:
        return movies_runs_dir()

    def translate_path(self, path: str) -> str:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/cinema-data/"):
            parts = [
                p for p in clean[len("/cinema-data/") :].split("/") if p not in ("", ".", "..")
            ]
            if not parts:
                return str(self.bundles / "_none")
            return str(self.bundles / parts[0] / "bundle" / "/".join(parts[1:]))
        rel = [p for p in clean.split("/") if p not in ("", ".", "..")]
        target = DIST.joinpath(*rel) if rel else DIST / "index.html"
        return str(target if target.exists() else DIST / "index.html")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        pass


def start_server() -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(_Handler, directory=str(DIST))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ----------------------------------------------------------------------------- driver


class Driver:
    """The node frame stepper (web/scripts/cinema.mjs) as a child process."""

    def __init__(self, url: str, film: str, width: int, height: int) -> None:
        self.proc = subprocess.Popen(
            [
                "node",
                str(DRIVER),
                "--url",
                url,
                "--film",
                film,
                "--width",
                str(width),
                "--height",
                str(height),
            ],
            cwd=WEB,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.ready = self._read()
        if self.ready.get("event") != "ready":
            raise RuntimeError(f"cinema driver failed: {self.ready}")
        self.browser_pid = self.ready.get("browser_pid")

    def _read(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("cinema driver exited")
        return json.loads(line)

    def render(self, a: int, b: int, out: Path) -> dict[str, Any]:
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"cmd": "render", "from": a, "to": b, "dir": str(out)}) + "\n"
        )
        self.proc.stdin.flush()
        msg = self._read()
        if msg.get("event") != "done":
            raise RuntimeError(f"render {a}:{b} failed: {msg}")
        return msg

    def browser_rss_mb(self) -> float:
        if not self.browser_pid:
            return 0.0
        try:
            root = psutil.Process(int(self.browser_pid))
            procs = [root, *root.children(recursive=True)]
            return sum(p.memory_info().rss for p in procs if p.is_running()) / 1e6
        except psutil.Error:
            return 0.0

    def close(self) -> None:
        if self.proc.poll() is None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()


# ----------------------------------------------------------------------------- ffmpeg


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found: brew install ffmpeg")
    return exe


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def encode_chunk(frames: Path, first: int, fps: int, out: Path, r: dict[str, Any]) -> None:
    _run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-start_number",
            str(first),
            "-i",
            str(frames / "f_%06d.png"),
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
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            str(out),
        ]
    )


def concat(segments: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{s}'\n" for s in segments))
    _run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    lst.unlink()


def probe(path: Path) -> dict[str, Any]:
    exe = shutil.which("ffprobe") or "ffprobe"
    res = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=width,height,nb_read_frames,r_frame_rate,pix_fmt,codec_name:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    s = data["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return {
        "width": s["width"],
        "height": s["height"],
        "frames": int(s.get("nb_read_frames") or 0),
        "fps": num / den,
        "pix_fmt": s.get("pix_fmt"),
        "codec": s.get("codec_name"),
        "duration_s": float(data["format"]["duration"]),
    }


def probe_audio(path: Path) -> dict[str, Any] | None:
    exe = shutil.which("ffprobe") or "ffprobe"
    res = subprocess.run(
        [exe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,sample_rate,channels,bit_rate,duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    streams = json.loads(res.stdout).get("streams") or []
    if not streams:
        return None
    a = streams[0]
    return {
        "codec": a.get("codec_name"),
        "sample_rate": int(a.get("sample_rate") or 0),
        "channels": a.get("channels"),
        "bit_rate": int(a.get("bit_rate") or 0),
        "duration_s": float(a.get("duration") or 0.0),
    }


def loudness(path: Path, extra: list[str] | None = None) -> dict[str, Any]:
    """EBU R128 measurement of the first audio stream (ffmpeg loudnorm, print_format json)."""
    v = load_settings()["voice"]
    res = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), *(extra or []), "-af",
         f"loudnorm=I={v['lufs']}:TP={v['true_peak_db']}:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    err = res.stderr
    return json.loads(err[err.rindex("{") : err.rindex("}") + 1])


ISO639_2 = {"en": "eng", "ar": "ara"}


def mux_voice(
    video: Path, wav: Path, srt: Path | None, out: Path, lang: str = "en"
) -> dict[str, Any]:
    """video + voice WAV (+ SRT) -> MP4 with AAC voice (loudness-normalised) and mov_text subs.

    loudnorm works in 100 ms blocks and pads its output to a whole block, so the track is trimmed
    back to the voice WAV's exact length (= the film's frames / fps)."""
    v = load_settings()["voice"]
    code = ISO639_2[lang]
    m = loudness(wav)
    dur = narrate.wav_seconds(wav)
    af = (
        f"loudnorm=I={v['lufs']}:TP={v['true_peak_db']}:LRA=11:measured_I={m['input_i']}:"
        f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
        f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
        f"aresample=48000,atrim=end={dur:.6f}"
    )
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav)]
    maps = ["-map", "0:v", "-map", "1:a"]
    if srt is not None:
        cmd += ["-i", str(srt)]
        maps += ["-map", "2:s", "-c:s", "mov_text", "-metadata:s:s:0", f"language={code}"]
    cmd += [*maps, "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", f"{v['aac_kbps']}k",
            "-ar", "48000", "-ac", "1", "-metadata:s:a:0", f"language={code}", "-fflags",
            "+bitexact", "-flags:a", "+bitexact", "-movflags", "+faststart", str(out)]  # fmt: skip
    _run(cmd)
    after = loudness(out)
    return {"input_lufs": float(m["input_i"]), "output_lufs": float(after["input_i"]),
            "output_true_peak_db": float(after["input_tp"]), "target_lufs": v["lufs"]}  # fmt: skip


def make_gif(mp4: Path, gif: Path, start: float, r: dict[str, Any]) -> dict[str, Any]:
    """Palette GIF of gif_seconds; shrinks the width until it is under gif_max_bytes.

    The frame rate stays fixed: GIF delays are whole hundredths of a second, so 10 fps (0.10 s per
    frame) gives exactly gif_seconds where 8 or 12 fps would round to a little more.
    """
    width, fps = int(r["gif_width"]), int(r["gif_fps"])
    for _ in range(6):
        vf = (
            f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
            f"[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
        )
        _run(
            [
                ffmpeg(),
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.3f}",
                "-t",
                str(r["gif_seconds"]),
                "-i",
                str(mp4),
                "-vf",
                vf,
                "-loop",
                "0",
                str(gif),
            ]
        )
        if gif.stat().st_size <= int(r["gif_max_bytes"]):
            break
        width = int(width * 0.85) // 2 * 2
    return {"bytes": gif.stat().st_size, "width": width, "fps": fps, "seconds": r["gif_seconds"]}


# ----------------------------------------------------------------------------- render


def sha_png(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def poster_frame(film: Any, fps: int, a: int, b: int) -> int:
    """Middle of the shot holding the film's midpoint (clear of title card and cut fades)."""
    mid = (a + b) / 2 / fps
    start = 0.0
    for shot in film.shots:
        if mid < start + shot.duration_s:
            k = round((start + shot.duration_s / 2) * fps)
            return k if a <= k < b else a + (b - a) // 2
        start += shot.duration_s
    return a + (b - a) // 2


def _dir_mb(path: Path) -> float:
    return (
        sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6
        if path.exists()
        else 0.0
    )


def render_film(
    name: str,
    fps: int | None = None,
    size: tuple[int, int] | None = None,
    k4: bool = False,
    letterbox: bool = False,
    frames: tuple[int, int] | None = None,
    out_dir: Path | None = None,
    keep_frames: bool = False,
    build_web: bool = True,
    voice: bool = True,
    subtitles: bool = True,
    lang: str = "en",
) -> dict[str, Any]:
    os.environ.setdefault("TT_RUNS_READONLY", "1")
    tag = "" if lang == "en" else f".{lang}"  # output and work-dir suffix of the edition
    settings = load_settings()
    r = settings["render"]
    film = load_film(name)
    out_dir = out_dir or MOVIES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if film.stub:
        log(f"{name}: stub spec ({film.note or 'no runs'}), not rendered")
        return {"film": name, "stub": True, "note": film.note}
    fps = fps or int(r["fps"])
    width, height = size or (
        (int(r["width_4k"]), int(r["height_4k"])) if k4 else (int(r["width"]), int(r["height"]))
    )
    t_start = time.time()
    work = movies_runs_dir() / f"{film.film}{tag}"
    timing = narrate.prepare(film, fps, lang) if voice else None
    if timing is not None:
        film = narrate.apply_timing(film, timing)
        log(f"{name}{tag}: narration {len(timing.lines)} lines, voice {timing.voice}, "
            f"stretch {timing.stretch}, {film.duration_s:.2f} s")  # fmt: skip
    lines = (
        [{"text": t.text, "start_s": round(t.start_s, 3), "end_s": round(t.end_s, 3)}
         for t in timing.lines]
        if timing is not None else None
    )  # fmt: skip
    log(f"{name}: bundle ({width}x{height}, {fps} fps)")
    bundle = build_bundle(
        film, fps, width, height, letterbox, out=work / "bundle", narration=lines,
        subtitles=subtitles,
    )  # fmt: skip
    manifest = json.loads((bundle / "manifest.json").read_text())
    n = int(manifest["n_frames"])
    a, b = frames or (0, n)
    b = min(b, n)
    if build_web:
        ensure_web_build()
    server, url = start_server()
    frames_dir = work / "frames"
    seg_dir = work / "segments"
    for d in (frames_dir, seg_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    poster_k = poster_frame(film, fps, a, b)
    # hash the first, middle and last frames free of any fade (real pictures, not black)
    fade = json.loads((bundle / "frames.json").read_text())["fade"]
    content = [k for k in range(a, b) if fade[k] == 0] or list(range(a, b))
    hash_ks = {content[0], content[len(content) // 2], content[-1]}
    picks = sorted(hash_ks | {poster_k})
    hashes: dict[str, str] = {}
    poster = out_dir / f"{film.film}{tag}.poster.png"
    rss_max = 0.0
    disk_max = 0.0
    segments: list[Path] = []
    chunk = int(r["chunk_frames"])
    driver = Driver(url, work.name, width, height)  # /cinema-data/<work dir>/ (bundle key)
    t_frames = 0.0
    try:
        gpu = driver.ready.get("gpu", {}).get("renderer")
        log(f"{name}: rendering frames {a}..{b - 1} on {gpu}")
        for c0 in range(a, b, chunk):
            c1 = min(b, c0 + chunk)
            t0 = time.time()
            msg = driver.render(c0, c1, frames_dir)
            t_frames += time.time() - t0
            if msg.get("errors"):
                log(f"page errors: {msg['errors'][:3]}")
            rss_max = max(rss_max, driver.browser_rss_mb())
            for k in picks:
                if c0 <= k < c1:
                    png = frames_dir / f"f_{k:06d}.png"
                    if k in hash_ks:
                        hashes[str(k)] = sha_png(png)
                    if k == poster_k:
                        shutil.copyfile(png, poster)
            disk_max = max(disk_max, _dir_mb(work))
            seg = seg_dir / f"seg_{c0:06d}.mp4"
            encode_chunk(frames_dir, c0, fps, seg, r)
            segments.append(seg)
            if keep_frames:
                keep = work / "frames-kept"
                keep.mkdir(exist_ok=True)
                for p in frames_dir.glob("*.png"):
                    shutil.move(str(p), keep / p.name)
            else:
                for p in frames_dir.glob("*.png"):
                    p.unlink()
            log(
                f"{name}: {c1 - a}/{b - a} frames ({(time.time() - t0) / (c1 - c0):.2f} s/frame, "
                f"browser {rss_max:.0f} MB, disk {disk_max:.0f} MB)"
            )
    finally:
        driver.close()
        server.shutdown()
    mp4 = out_dir / f"{film.film}{tag}.mp4"
    srt = out_dir / f"{film.film}{tag}.srt"
    audio: dict[str, Any] | None = None
    if timing is not None and (a, b) == (0, n):
        video = work / "video.mp4"
        concat(segments, video)
        wav = work / "voice.wav"
        voice_sha = narrate.voice_track(
            [(t.start_s, t.wav) for t in timing.lines], n / fps, wav, lang
        )
        narrate.write_srt([(t.start_s, t.end_s, t.text) for t in timing.lines], srt)
        loud = mux_voice(video, wav, srt, mp4, lang)
        video.unlink()
        audio = {"voice_sha256_16": voice_sha, "loudness": loud, "srt": srt.name,
                 "timing": timing.as_json()}  # fmt: skip
    else:
        concat(segments, mp4)
        srt.unlink(missing_ok=True)
    shutil.rmtree(seg_dir, ignore_errors=True)
    shutil.rmtree(frames_dir, ignore_errors=True)
    info = probe(mp4)
    gif_start = max(0.0, min(info["duration_s"] - float(r["gif_seconds"]), film.title_card_s + 0.5))
    try:
        gif: dict[str, Any] = make_gif(mp4, out_dir / f"{film.film}{tag}.gif", gif_start, r)
        gif["start_s"] = round(gif_start, 3)
    except subprocess.CalledProcessError as exc:  # e.g. a one-frame partial render
        gif = {"error": f"gif not made: {exc.returncode}"}
        log(f"{name}: GIF preview not made ({exc.returncode})")
    meta = {
        "film": film.film,
        "lang": lang,
        "label": SYNTHETIC_LABEL,
        "title": film.title,
        "spec": str(spec_path(name).relative_to(REPO_ROOT))
        if spec_path(name).is_relative_to(REPO_ROOT)
        else str(spec_path(name)),
        "spec_sha": sha_file(spec_path(name)),
        "bundle_hashes": json.loads((bundle / "hashes.json").read_text()),
        "sources": manifest["sources"],
        "width": width,
        "height": height,
        "fps": fps,
        "duration_s": film.duration_s,  # after the narration stretch
        "showreel_excerpt": list(film.showreel) if film.showreel else None,
        "frames_rendered": [a, b],
        "expected_duration_s": (b - a) / fps,
        "mp4": info,
        "audio": ({**audio, "stream": probe_audio(mp4)} if audio else None),
        "frame_sha256_16": hashes,
        "gif": gif,
        "browser_rss_max_mb": round(rss_max, 1),
        "disk_max_mb": round(disk_max, 1),
        "seconds": {"frames": round(t_frames, 1), "total": round(time.time() - t_start, 1)},
        "gpu": driver.ready.get("gpu"),
    }
    (out_dir / f"{film.film}{tag}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    log(
        f"{name}: {mp4.relative_to(REPO_ROOT) if mp4.is_relative_to(REPO_ROOT) else mp4} "
        f"{info['width']}x{info['height']} {info['duration_s']:.2f} s, "
        f"{mp4.stat().st_size / 1e6:.1f} MB, {meta['seconds']['total']} s"
    )
    if rss_max > float(r["max_browser_rss_mb"]) or disk_max > float(r["max_disk_mb"]):
        log(f"{name}: WARNING over budget (browser {rss_max:.0f} MB, disk {disk_max:.0f} MB)")
    return meta


def parse_size(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    w, h = v.lower().split("x")
    return int(w), int(h)


def parse_frames(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    a, b = v.split(":")
    return int(a), int(b)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    films: list[str] = typer.Argument(None, help="film names (movies/specs/<name>.yaml)"),
    all_: bool = typer.Option(False, "--all", help="render every spec in movies/specs/"),
    fps: int = typer.Option(0, help="frames per second (default 30)"),
    k4: bool = typer.Option(False, "--4k", help="3840x2160"),
    size: str = typer.Option("", help="WxH, overrides --4k"),
    letterbox: bool = typer.Option(False, help="2.39:1 letterbox bars"),
    frames: str = typer.Option("", help="render only frames A:B (smoke tests)"),
    out: Path = typer.Option(None, help="output directory (default movies/)"),
    keep_frames: bool = typer.Option(False, help="keep the PNG frames (debugging)"),
    no_voice: bool = typer.Option(False, "--no-voice", help="silent render, spec timing"),
    no_subtitles: bool = typer.Option(False, "--no-subtitles", help="voice without subtitles"),
    lang: str = typer.Option("en", help="narration language: en | ar (movies/<film>.ar.mp4)"),
) -> None:
    names = film_names() if all_ else list(films or [])
    if not names:
        raise typer.BadParameter("give film names or --all")
    for name in names:
        if not (SPECS_DIR / f"{name}.yaml").exists() and not Path(name).exists():
            raise typer.BadParameter(f"no spec {name}")
    failed = []
    for name in names:
        try:
            render_film(
                name,
                fps or None,
                parse_size(size),
                k4,
                letterbox,
                parse_frames(frames),
                out,
                keep_frames,
                voice=not no_voice,
                subtitles=not no_subtitles,
                lang=lang,
            )
        except Exception as exc:  # noqa: BLE001 - keep going with the other films
            log(f"{name}: FAILED {exc}")
            failed.append(name)
    if failed:
        log(f"failed: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    app()
