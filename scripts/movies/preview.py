"""Serve built bundles and the viewer for previewing films in a normal browser.

    python -m scripts.movies.preview tahlia-street [--port 8765] [--rebuild]

Opens nothing by itself: visit http://127.0.0.1:<port>/?cinema=<film>&play=1 (real-time
playback) or drive frames from the console with window.__cinema.renderFrame(i).
"""

from __future__ import annotations

import functools
import http.server
import os

import typer

from scripts.movies.bundle import build_bundle, movies_runs_dir
from scripts.movies.render import DIST, _Handler, ensure_web_build
from scripts.movies.spec import load_film, load_settings

app = typer.Typer(add_completion=False)


@app.command()
def main(
    film: str = typer.Argument(..., help="film name"),
    port: int = typer.Option(8765, help="port on 127.0.0.1"),
    rebuild: bool = typer.Option(False, help="rebuild the bundle even if it exists"),
) -> None:
    os.environ.setdefault("TT_RUNS_READONLY", "1")
    r = load_settings()["render"]
    bundle = movies_runs_dir() / film / "bundle"
    if rebuild or not (bundle / "manifest.json").exists():
        build_bundle(
            load_film(film), int(r["fps"]), int(r["width"]), int(r["height"]), False, out=bundle
        )
    ensure_web_build()
    handler = functools.partial(_Handler, directory=str(DIST))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    typer.echo(f"http://127.0.0.1:{port}/?cinema={film}&play=1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    app()
