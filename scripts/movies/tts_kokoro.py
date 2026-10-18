"""Kokoro-82M text-to-speech worker for the film narration (runs in the TTS venv).

Started by scripts/movies/narrate.py with the interpreter of `.venv-tts` (see `make voice-setup`):

    .venv-tts/bin/python scripts/movies/tts_kokoro.py --versions
    echo '[{"text": "...", "out": "/tmp/a.wav"}]' | \
        .venv-tts/bin/python scripts/movies/tts_kokoro.py \
        --voice af_heart --speed 1.0 --seed 1

Reads a JSON list of {text, out} on stdin, writes 16-bit mono WAVs at 24 kHz and prints one JSON
line per file ({out, seconds}). Fully offline once the model is in the Hugging Face cache
(HF_HUB_OFFLINE=1 is set by the caller). Deterministic: torch is seeded before every line
(Kokoro's vocoder draws noise), deterministic algorithms and one thread are enforced, the
convolutions and linear layers run in float64 (`deterministic_cpu`), and the process runs with
PYTHONHASHSEED=0 (it re-executes itself otherwise: the G2P iterates over sets),
so the same text, voice, speed, seed and versions give the same samples in any process. Imports
nothing from the project on purpose.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ID = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000


def versions() -> dict[str, str]:
    from importlib.metadata import version

    from huggingface_hub import snapshot_download

    snap = Path(snapshot_download(REPO_ID, allow_patterns=["config.json"]))
    return {
        "engine": "kokoro",
        "kokoro": version("kokoro"),
        "misaki": version("misaki"),
        "torch": version("torch"),
        "model": REPO_ID,
        "model_revision": snap.name,
        "licence": "Apache-2.0 (code and weights)",
        "torch_threads": "1",
        "pythonhashseed": "0",
        "float64_kernels": "conv1d, conv_transpose1d, linear",
    }


def deterministic_cpu() -> None:
    """Run Kokoro's convolutions and linear layers in float64 and cast back to float32.

    On Apple Silicon the float32 CPU kernels can sum in a different order from one process to the
    next for identical inputs (found on the 1x1 Conv1d `predictor.F0_proj`): the F0 curve then
    differs in the last bits and the vocoder's sine phase turns that into audible differences.
    In float64 the order no longer shows after the cast, so every process gives the same samples.
    """
    import torch.nn as nn
    import torch.nn.functional as F

    def _b(bias):  # noqa: ANN001, ANN202
        return None if bias is None else bias.double()

    def conv1d(self, x, weight, bias):  # noqa: ANN001, ANN202
        y = F.conv1d(x.double(), weight.double(), _b(bias), self.stride, self.padding,
                     self.dilation, self.groups)  # fmt: skip
        return y.to(x.dtype)

    def conv_t1d(self, x, output_size=None):  # noqa: ANN001, ANN202
        op = self._output_padding(x, output_size, self.stride, self.padding, self.kernel_size, 1,
                                  self.dilation)  # fmt: skip
        y = F.conv_transpose1d(x.double(), self.weight.double(), _b(self.bias), self.stride,
                               self.padding, op, self.groups, self.dilation)  # fmt: skip
        return y.to(x.dtype)

    def linear(self, x):  # noqa: ANN001, ANN202
        return F.linear(x.double(), self.weight.double(), _b(self.bias)).to(x.dtype)

    nn.Conv1d._conv_forward = conv1d
    nn.ConvTranspose1d.forward = conv_t1d
    nn.Linear.forward = linear


def main() -> int:
    if os.environ.get("PYTHONHASHSEED") != "0":
        # the G2P iterates over sets: a fixed hash seed is needed for identical audio across runs
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        os.execve(sys.executable, [sys.executable, *sys.argv], env)
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", action="store_true")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--lang", default="a")  # a = American English
    a = ap.parse_args()
    if a.versions:
        print(json.dumps(versions()))
        return 0
    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KPipeline

    torch.use_deterministic_algorithms(True)
    deterministic_cpu()
    torch.set_num_threads(1)  # float sums in one fixed order: identical samples across processes
    pipe = KPipeline(lang_code=a.lang, repo_id=REPO_ID)
    for job in json.load(sys.stdin):
        torch.manual_seed(a.seed)
        chunks = [c.numpy() for _, _, c in pipe(job["text"], voice=a.voice, speed=a.speed)]
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, np.clip(audio, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16")
        print(json.dumps({"out": str(out), "seconds": len(audio) / SAMPLE_RATE}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
