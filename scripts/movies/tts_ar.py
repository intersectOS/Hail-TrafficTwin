"""Arabic text-to-speech worker for the film narration (runs in the Arabic TTS venv).

Started by scripts/movies/narrate.py (`--lang ar`) with the interpreter of `.venv-tts-ar` (see
`make voice-setup-ar`):

    .venv-tts-ar/bin/python scripts/movies/tts_ar.py --versions
    echo '[{"text": "...", "out": "/tmp/a.wav"}]' | \
        .venv-tts-ar/bin/python scripts/movies/tts_ar.py --voice builtin --seed 1

Engine: Chatterbox Multilingual (Resemble AI, MIT code and weights, model `ResembleAI/chatterbox`,
language id `ar`), chosen in docs/movies-arabic.md (RA-001). `--voice builtin` uses the model's own
reference voice (conds.pt); a path to a WAV clones that voice instead. Reads a JSON list of
{text, out} on stdin, writes 16-bit mono WAVs at 24 kHz and prints one JSON line per file ({out,
seconds, max_gap_s, peak, clauses, retries}). Fully offline once the model is in the Hugging Face
cache (HF_HUB_OFFLINE=1 is set by the caller).

Long lines make the model run past the text (it babbles after the last word, seen on a 76-syllable
test line, docs/movies-arabic.md), so each line is spoken clause by clause: split after `،` `؛` `.`
`؟` `!` (clauses under `--min-syl` syllables join the next), each clause trimmed of silence and
joined with `--pause-comma` / `--pause-stop` seconds of silence. A clause longer than
`--max-s-per-syl` x its syllables + 1 s, or with a silence over `--max-gap` s inside it, is spoken
again with the next seed (up to `--retries`; the shortest take is kept if none passes).

Deterministic: torch, numpy and random are seeded before every line (the T3 decoder samples its
speech tokens) and the model runs on the CPU with one thread by default (`--device cpu`), so the
same text, voice, seed and versions give the same samples. Chatterbox adds Resemble's inaudible
Perth watermark to every output. Imports nothing from the project on purpose.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ID = "ResembleAI/chatterbox"
SAMPLE_RATE = 24000
FILES = ["ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json",
         "conds.pt", "Cangjie5_TC.json"]  # fmt: skip


def versions(device: str) -> dict[str, str]:
    from importlib.metadata import version

    from huggingface_hub import snapshot_download

    snap = Path(snapshot_download(REPO_ID, allow_patterns=FILES))
    return {
        "engine": "chatterbox-multilingual",
        "chatterbox-tts": version("chatterbox-tts"),
        "torch": version("torch"),
        "model": REPO_ID,
        "model_revision": snap.name,
        "licence": "MIT (code and weights)",
        "device": device,
        "torch_threads": "1" if device == "cpu" else "default",
    }


def trim(audio, pad: float, thresh_db: float = -45.0):  # noqa: ANN001, ANN201
    """Cut leading/trailing silence to `pad` seconds; report the longest inner gap."""
    import numpy as np

    win = int(0.02 * SAMPLE_RATE)
    n = len(audio) // win
    if n == 0:
        return audio, 0.0
    rms = np.sqrt(np.mean(audio[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    loud = 20 * np.log10(rms) > thresh_db
    if not loud.any():
        return audio, 0.0
    idx = np.flatnonzero(loud)
    a = max(0, idx[0] * win - int(pad * SAMPLE_RATE))
    b = min(len(audio), (idx[-1] + 1) * win + int(pad * SAMPLE_RATE))
    gaps = np.diff(idx) - 1
    return audio[a:b], float(gaps.max(initial=0) * win / SAMPLE_RATE)


VOWELS = set("\u064b\u064c\u064d\u064e\u064f\u0650")  # tanween x3, fatha, damma, kasra
CLAUSE_END = "،؛.؟!,"


def syllables(text: str) -> int:
    return sum(ch in VOWELS for ch in text)


def clauses(text: str, min_syl: int) -> list[str]:
    """The line cut after each clause mark; short clauses are joined to the next one."""
    parts, cur = [], ""
    for ch in text.strip():
        cur += ch
        if ch in CLAUSE_END:
            parts.append(cur.strip())
            cur = ""
    if cur.strip():
        parts.append(cur.strip())
    out: list[str] = []
    carry = ""
    for part in parts:
        carry = f"{carry} {part}".strip()
        if syllables(carry) >= min_syl:
            out.append(carry)
            carry = ""
    if carry:
        if out:
            out[-1] = f"{out[-1]} {carry}"
        else:
            out.append(carry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", action="store_true")
    ap.add_argument("--voice", default="builtin")  # builtin | path to a reference WAV
    ap.add_argument("--speed", type=float, default=1.0)  # 1 = as spoken (time-stretch otherwise)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--device", default="cpu")  # cpu (deterministic) | mps
    ap.add_argument("--cfg-weight", type=float, default=0.5)
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--pad", type=float, default=0.06)
    ap.add_argument("--min-syl", type=int, default=10)
    ap.add_argument("--pause-comma", type=float, default=0.22)
    ap.add_argument("--pause-stop", type=float, default=0.38)
    ap.add_argument("--max-s-per-syl", type=float, default=0.32)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--max-gap", type=float, default=1.0)  # longest silence inside a clause
    a = ap.parse_args()
    if a.versions:
        print(json.dumps(versions(a.device)))
        return 0
    import random

    import numpy as np
    import soundfile as sf
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if a.device == "cpu":
        torch.set_num_threads(1)
    model = ChatterboxMultilingualTTS.from_pretrained(device=a.device)
    ref = None if a.voice == "builtin" else a.voice

    def say(text: str, seed: int):  # noqa: ANN202
        torch.manual_seed(seed)
        np.random.seed(seed)
        random.seed(seed)
        wav = model.generate(
            text, language_id="ar", audio_prompt_path=ref, exaggeration=a.exaggeration,
            cfg_weight=a.cfg_weight, temperature=a.temperature,
        )  # fmt: skip
        audio = wav.squeeze(0).numpy().astype(np.float32)
        if a.speed != 1.0:
            import librosa

            audio = librosa.effects.time_stretch(audio, rate=a.speed)
        return trim(audio, a.pad)

    for job in json.load(sys.stdin):
        pieces, gap, retries = [], 0.0, 0
        parts = clauses(job["text"], a.min_syl)
        for k, part in enumerate(parts):
            limit = a.max_s_per_syl * syllables(part) + 1.0
            best = None
            for r in range(a.retries + 1):  # the first take within the limit, else the shortest
                audio, g = say(part, a.seed + r)
                if best is None or len(audio) < len(best[0]):
                    best = (audio, g)
                if len(audio) / SAMPLE_RATE <= limit and g <= a.max_gap:
                    break
                retries += 1
            audio, g = best
            gap = max(gap, g)
            pieces.append(audio)
            if k < len(parts) - 1:
                stop = part[-1] in ".؟!"
                pause = a.pause_stop if stop else a.pause_comma
                pieces.append(np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32))
        audio = np.concatenate(pieces)
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, np.clip(audio, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16")
        rec = {"out": str(out), "seconds": len(audio) / SAMPLE_RATE, "max_gap_s": round(gap, 3),
               "peak": round(float(np.abs(audio).max()), 4), "clauses": len(parts),
               "retries": retries}  # fmt: skip
        print(json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    raise SystemExit(main())
