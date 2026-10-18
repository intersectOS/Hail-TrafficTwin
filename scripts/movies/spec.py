"""Film spec schema (movies/specs/<film>.yaml) and loader.

A film is a sequence of shots. Each shot names the data sources it draws (edge heat, vehicle
trips, overlays), a camera path of keyframes (lon, lat, zoom, pitch, bearing, sim time) and the
HUD text. `python -m scripts.movies.spec validate movies/specs/*.yaml` checks every spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import typer
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sim.common import REPO_ROOT

SPECS_DIR = REPO_ROOT / "movies" / "specs"
SETTINGS_PATH = Path(__file__).with_name("settings.yaml")

Ease = Literal["linear", "in", "out", "in_out", "hold"]
Mode = Literal["single", "diff", "split"]
ColorBy = Literal["speed", "class"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Strict):
    """A run (as listed by the API registry, e.g. `<id>~baseline`) or a strategist candidate."""

    run: str | None = None
    strategist: str | None = None  # recommendation directory under runs/strategist/
    candidate: str | None = None  # candidate id, e.g. "A:reroute+rescue_lane"
    background: str | None = None  # run whose FCD is drawn behind a strategist candidate

    @model_validator(mode="after")
    def _one_kind(self) -> Source:
        if (self.run is None) == (self.strategist is None):
            raise ValueError("a source needs exactly one of `run` or `strategist`")
        if self.strategist is not None and self.candidate is None:
            raise ValueError("a strategist source needs `candidate` (or `no_strategy`)")
        return self


class Keyframe(Strict):
    t: float = Field(ge=0)  # seconds from the start of the shot
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    zoom: float = Field(ge=0, le=22)
    pitch: float = Field(default=0, ge=0, le=85)
    bearing: float = 0
    sim_t: float | None = None  # simulated seconds (run clock); None = carried from neighbours
    ease: Ease = "in_out"  # easing of the segment that ENDS at this keyframe


class Kpi(Strict):
    label: str
    value: float | None = None  # fixed value (counts up from `start`)
    start: float = 0.0
    unit: str = ""
    decimals: int = Field(default=0, ge=0, le=3)
    count_s: float = Field(default=3.0, ge=0)  # count-up duration from the shot start
    sign: bool = False  # show "+" on positive values
    series: (
        Literal[
            "running", "arrived", "halted", "mean_speed_kmh", "evacuees_running", "evacuees_out"
        ]
        | None
    ) = None
    source: str | None = None  # source id for a series or fact KPI
    fact: str | None = None  # dotted path into the source's facts, e.g. "mean_delay_s.delta_pct"
    scale: float = 1.0  # multiplies a fact (e.g. 1/60 for minutes)

    @model_validator(mode="after")
    def _one_kind(self) -> Kpi:
        kinds = [self.value is not None, self.series is not None, self.fact is not None]
        if sum(kinds) != 1:
            raise ValueError(f"KPI {self.label!r}: give exactly one of `value`, `series`, `fact`")
        if (self.series is not None or self.fact is not None) and self.source is None:
            raise ValueError(f"KPI {self.label!r}: a series or fact KPI needs `source`")
        return self


class Labels(Strict):
    """Map annotations drawn on a shot (when the film has labels): which kinds are shown."""

    streets: bool = True
    districts: bool = True
    landmarks: bool = True
    callouts: bool = True  # leader-line labels at events, closures, exits and contraflow


class Hud(Strict):
    caption: str = ""
    detail: str = ""  # second line (decision reasons, ETAs)
    kpis: list[Kpi] = Field(default_factory=list, max_length=3)
    legend: Literal["speed", "diff", "class", "none"] = "speed"
    split_labels: tuple[str, str] | None = None
    labels: Labels = Field(default_factory=Labels)


class Layers(Strict):
    heat: str | None = None  # source id coloured on the roads
    compare: str | None = None  # diff: heat - compare (blue = relief, red = worse)
    split: tuple[str, str] | None = None  # left / right source ids (heat + trips per side)
    mode: Mode = "single"
    metric: Literal["speed_rel", "delay_s_per_veh", "density_veh_km"] = "speed_rel"
    trips: str | None = None  # source id of vehicle trajectories
    color_by: ColorBy = "speed"
    overlays: list[
        Literal["events", "closures", "zone", "exits", "routes", "phases", "contraflow"]
    ] = Field(default_factory=list)
    route_source: str | None = None  # strategist source whose route is highlighted
    buildings: bool = True
    outline: list[tuple[float, float]] | None = None  # extra polygon (e.g. a policy cordon)
    outline_label: str = ""
    line: list[tuple[float, float]] | None = None  # open polyline (e.g. a Loop tunnel)
    stations: list[tuple[float, float]] | None = None  # points drawn on `line` (e.g. Loop stations)

    @model_validator(mode="after")
    def _mode(self) -> Layers:
        if self.mode == "diff" and (self.heat is None or self.compare is None):
            raise ValueError("mode diff needs `heat` and `compare`")
        if self.mode == "split" and self.split is None:
            raise ValueError("mode split needs `split: [left, right]`")
        return self


class Shot(Strict):
    id: str
    duration_s: float = Field(gt=0, le=120)
    layers: Layers
    camera: list[Keyframe] = Field(min_length=1)
    hud: Hud = Field(default_factory=Hud)

    @field_validator("camera")
    @classmethod
    def _sorted(cls, v: list[Keyframe]) -> list[Keyframe]:
        ts = [k.t for k in v]
        if ts != sorted(ts) or len(set(ts)) != len(ts):
            raise ValueError("camera keyframes need strictly increasing `t`")
        if ts[0] != 0:
            raise ValueError("the first camera keyframe must be at t = 0")
        if not any(k.sim_t is not None for k in v):
            raise ValueError("at least one camera keyframe needs `sim_t`")
        return v

    @model_validator(mode="after")
    def _within(self) -> Shot:
        if self.camera[-1].t > self.duration_s + 1e-9:
            raise ValueError(f"shot {self.id}: keyframe beyond duration_s")
        return self


class Basemap(Strict):
    bbox: tuple[float, float, float, float] | None = None  # w, s, e, n; None = from the cameras
    margin_deg: float = Field(default=0.01, ge=0, le=0.5)
    buildings: bool = True
    water: bool = True
    road_classes: Literal["all", "major"] = "all"


class Annotations(Strict):
    """Film-wide map annotations and HUD instruments (MOVIES_V2)."""

    labels: bool = True  # street, district and landmark labels (scripts/movies/labels.py)
    compass: bool = True  # north arrow rotating with the camera bearing
    scale_bar: bool = True  # scale bar at the camera centre


class Film(Strict):
    film: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    subtitle: str = ""
    duration_s: float = Field(ge=1, le=300)
    date: str = Field(default="2026-10-18", pattern=r"^\d{4}-\d{2}-\d{2}$")
    clock_t0: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")  # sim t=0 local time
    tier: Literal["A", "B"] = "B"
    sources: dict[str, Source] = Field(default_factory=dict)
    basemap: Basemap = Field(default_factory=Basemap)
    title_card_s: float = Field(default=2.5, ge=0, le=10)
    showreel: tuple[float, float] | None = None  # excerpt [start_s, end_s] used in the showreel
    fictional: bool = False  # fictional demo parameters (PROJECT.md section 11): footer says so
    annotations: Annotations = Field(default_factory=Annotations)
    stub: bool = False  # placeholder spec: validated but not rendered
    note: str = ""
    shots: list[Shot] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Film:
        if self.stub:
            return self
        if not self.shots:
            raise ValueError("a film needs at least one shot (or `stub: true`)")
        ids = [s.id for s in self.shots]
        if len(set(ids)) != len(ids):
            raise ValueError("shot ids must be unique")
        total = sum(s.duration_s for s in self.shots)
        if abs(total - self.duration_s) > 1e-6:
            raise ValueError(f"duration_s {self.duration_s} != sum of shot durations {total}")
        if self.showreel is not None:
            a, b = self.showreel
            if not 0 <= a < b <= self.duration_s:
                raise ValueError(
                    f"showreel excerpt {self.showreel} not within 0..{self.duration_s}"
                )
        for shot in self.shots:
            lay = shot.layers
            refs = [lay.heat, lay.compare, lay.trips, lay.route_source, *(lay.split or ())]
            refs += [k.source for k in shot.hud.kpis]
            for ref in refs:
                if ref is not None and ref not in self.sources:
                    raise ValueError(f"shot {shot.id}: unknown source {ref!r}")
        return self


def load_settings() -> dict[str, Any]:
    with SETTINGS_PATH.open() as fh:
        return yaml.safe_load(fh)


def spec_path(name_or_path: str) -> Path:
    path = Path(name_or_path)
    if path.suffix in (".yaml", ".yml") and path.exists():
        return path
    return SPECS_DIR / f"{name_or_path}.yaml"


def load_film(name_or_path: str) -> Film:
    path = spec_path(name_or_path)
    with path.open() as fh:
        data = yaml.safe_load(fh)
    film = Film.model_validate(data)
    if film.film != path.stem:
        raise ValueError(f"{path}: film id {film.film!r} must match the file name")
    return film


def film_names() -> list[str]:
    """Film specs in render order (the `order` list in movies/specs/order.yaml, then the rest)."""
    order_file = SPECS_DIR / "order.yaml"
    names = sorted(
        p.stem for p in SPECS_DIR.glob("*.yaml") if p.stem != "order" and "." not in p.stem
    )  # <film>.narration.yaml files are narration scripts, not films
    if order_file.exists():
        order = yaml.safe_load(order_file.read_text())["order"]
        return [n for n in order if n in names] + [n for n in names if n not in order]
    return names


app = typer.Typer(add_completion=False, help="Film specs: validate.")


@app.callback()
def _cli() -> None:
    """Film spec tools."""


@app.command()
def validate(paths: list[Path] = typer.Argument(None)) -> None:
    """Validate film specs (default: every movies/specs/*.yaml)."""
    targets = paths or [SPECS_DIR / f"{n}.yaml" for n in film_names()]
    bad = 0
    for path in targets:
        try:
            film = load_film(str(path))
            kind = "stub" if film.stub else f"{len(film.shots)} shots, {film.duration_s:g} s"
            typer.echo(f"OK   {path.name}: {film.film} ({kind})")
        except (ValueError, OSError) as exc:
            bad += 1
            typer.echo(f"FAIL {path.name}: {exc}")
    raise typer.Exit(1 if bad else 0)


if __name__ == "__main__":
    app()
