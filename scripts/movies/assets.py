"""Copy the README/doc previews of rendered films into docs/img/movies/.

    python -m scripts.movies.assets          # (make movies-docs)

For every rendered film: a light README GIF (the same 6 s as the render's preview, 10 fps, at
most 360 px wide, narrower when needed to stay <= 1.2 MB) and a 1280 px JPEG still from the
poster frame. movies/ stays git-ignored (with the full <= 3 MB GIFs); these small previews are
committed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from scripts.movies.render import MOVIES_DIR, ffmpeg, make_gif
from scripts.movies.spec import film_names, load_settings
from sim.common import REPO_ROOT

DOCS_IMG = REPO_ROOT / "docs" / "img" / "movies"
STILL_WIDTH = 1280
STILL_QSCALE = 4  # ffmpeg mjpeg quality (2 best .. 31 worst)
README_GIF = {"gif_width": 360, "gif_fps": 10, "gif_max_bytes": 1_200_000}


def export(out: Path = DOCS_IMG) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    done = []
    for name in [*film_names(), "showreel"]:
        poster = MOVIES_DIR / f"{name}.poster.png"
        gif = MOVIES_DIR / f"{name}.gif"
        if not poster.exists():
            continue
        subprocess.run(
            [
                ffmpeg(),
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(poster),
                "-vf",
                f"scale={STILL_WIDTH}:-2",
                "-q:v",
                str(STILL_QSCALE),
                str(out / f"{name}.jpg"),
            ],
            check=True,
        )
        meta = MOVIES_DIR / f"{name}.json"
        if gif.exists() and name != "showreel" and meta.exists():
            r = {**load_settings()["render"], **README_GIF}
            start = json.loads(meta.read_text()).get("gif", {}).get("start_s", 3.0)
            make_gif(MOVIES_DIR / f"{name}.mp4", out / f"{name}.gif", float(start), r)
        done.append(name)
    return done


app = typer.Typer(add_completion=False)


@app.command()
def main() -> None:
    """Export GIF previews and JPEG stills of the rendered films to docs/img/movies/."""
    typer.echo(f"exported: {', '.join(export()) or 'nothing (render first)'}")


if __name__ == "__main__":
    app()
