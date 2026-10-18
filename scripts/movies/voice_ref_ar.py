"""Reference voice for the Arabic narration (RA-001, docs/movies-arabic.md).

    uv run python -m scripts.movies.voice_ref_ar   # runs/movies/_voice_ar/ref/clartts-417-24k.wav

Chatterbox clones the voice of a short reference clip. The clip is utterance
`ch_02_arabic_tts_dataset_417.wav` (10.7 s, one male reader, Modern Standard / Classical Arabic) of
the ClArTTS test split (MBZUAI, CC-BY-4.0, https://huggingface.co/datasets/MBZUAI/ClArTTS; the
audio comes from a LibriVox recording). The parquet (69 MB) is downloaded once into its own
directory, the clip is written as 16-bit WAV and resampled to 24 kHz with ffmpeg. Nothing from it
is committed; the films credit ClArTTS.
"""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import typer

from sim.common import REPO_ROOT

URL = "https://huggingface.co/datasets/MBZUAI/ClArTTS/resolve/main/data/test-00000-of-00001.parquet"
CLIP = "ch_02_arabic_tts_dataset_417.wav"
REF_DIR = REPO_ROOT / "runs" / "movies" / "_voice_ar" / "ref"
OUT = REF_DIR / "clartts-417-24k.wav"
SHA16 = {"parquet": "544164c6a4d48d6f", "wav": "f471382fc258d3fc"}  # measured 2026-10-17


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(force: bool = False) -> Path:
    if OUT.exists() and not force:
        return OUT
    dl = REF_DIR / "download"
    dl.mkdir(parents=True, exist_ok=True)
    parquet = dl / "clartts-test.parquet"
    if not parquet.exists():
        urllib.request.urlretrieve(URL, parquet)  # noqa: S310 - fixed https URL
    if sha16(parquet) != SHA16["parquet"]:
        print(f"[voice_ref_ar] note: {parquet.name} sha {sha16(parquet)} != {SHA16['parquet']}")
    rows = pq.read_table(parquet, filters=[("file", "=", CLIP)]).to_pylist()
    if not rows:
        raise FileNotFoundError(f"{CLIP} not in {parquet}")
    r = rows[0]
    audio = np.asarray(r["audio"], dtype=np.float64)
    raw = REF_DIR / "clartts-417.wav"
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(r["sampling_rate"]))
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-ar", "24000", str(OUT)], check=True
    )
    if sha16(OUT) != SHA16["wav"]:
        print(f"[voice_ref_ar] note: {OUT.name} sha {sha16(OUT)} != {SHA16['wav']}")
    return OUT


def main(force: bool = typer.Option(False, help="rebuild the clip")) -> None:
    out = build(force)
    typer.echo(f"{out.relative_to(REPO_ROOT)} sha256[:16] {sha16(out)}")


if __name__ == "__main__":
    typer.run(main)
