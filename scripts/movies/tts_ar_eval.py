"""Check Arabic TTS samples (RA-001, docs/movies-arabic.md): duration, rate, clipping, silence, ASR.

Runs in the Arabic TTS venv (`.venv-tts-ar`, which also holds mlx-whisper for this check only):

    .venv-tts-ar/bin/python scripts/movies/tts_ar_eval.py lines.json [--asr]

`lines.json` is the worker's job list ({text, out}). For each WAV: length, syllables per second
(syllables = short-vowel and tanween marks of the vowelised text, a fair count for fully vowelised
MSA), peak, clipped-sample share, the longest inner silence (20 ms RMS below -45 dBFS) and, with
`--asr`, Whisper large-v3-turbo's transcript (offline, MLX) with its character error rate against
the text stripped of diacritics. Prints one JSON line per WAV.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

VOWELS = set("ًٌٍَُِ")  # tanween x3, fatha, damma, kasra
ASR_MODEL = "mlx-community/whisper-large-v3-turbo"


def syllables(text: str) -> int:
    return sum(ch in VOWELS for ch in text)


def bare(text: str) -> str:
    """Arabic letters and digits only: diacritics, tatweel and punctuation removed, alef unified."""
    t = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    t = re.sub("[إأآٱ]", "ا", t).replace("ى", "ي").replace("ة", "ه").replace("ـ", "")
    return re.sub(r"[^\w]+", "", t)


def cer(ref: str, hyp: str) -> float:
    a, b = bare(ref), bare(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(a))


def stats(path: Path) -> dict[str, float]:
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(path, dtype="float32")
    win = int(0.02 * sr)
    n = len(x) // win
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    loud = np.flatnonzero(20 * np.log10(rms) > -45)
    gap = float((np.diff(loud) - 1).max(initial=0) * win / sr) if len(loud) else 0.0
    return {
        "seconds": round(len(x) / sr, 3),
        "rate_hz": sr,
        "peak": round(float(np.abs(x).max()), 4),
        "clipped_pct": round(float(np.mean(np.abs(x) >= 0.999) * 100), 4),
        "max_gap_s": round(gap, 3),
    }


def main() -> int:
    jobs = json.loads(Path(sys.argv[1]).read_text())
    asr = "--asr" in sys.argv
    if asr:
        import mlx_whisper
    for job in jobs:
        p = Path(job["out"])
        rec: dict[str, object] = {"wav": p.name, **stats(p)}
        syl = syllables(job["text"])
        rec["syllables"] = syl
        rec["syl_per_s"] = round(syl / float(rec["seconds"]), 2)  # type: ignore[arg-type]
        if asr:
            res = mlx_whisper.transcribe(str(p), path_or_hf_repo=ASR_MODEL, language="ar",
                                         temperature=0.0)  # fmt: skip
            rec["asr"] = res["text"].strip()
            rec["cer"] = round(cer(job["text"], res["text"]), 3)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
