"""Loop policy models: alignments (ordered stations) and the two transforms.

    loop_shuttle  station-to-station shuttles; a share alpha of car tours near two stations shifts
    loop_private  tunnel open to passenger cars with a toll; nearby cars re-route one-shot

`LoopPolicy` is Track A's `Policy` with the two Loop transforms added to the transform union, so a
Loop policy composes with every Track A transform and runs through `sim.policies.run.run_policy`
(sim/loop/run.py). Parameters left out fall back to sim/loop/config/loop.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, model_serializer, model_validator

from sim.common import load_yaml
from sim.schemas import (
    DayTypeChange,
    NetworkChange,
    Policy,
    PtLine,
    RemoteWork,
    RidehailShare,
    RoadPricing,
    Sourced,
    StaggeredHours,
    Strict,
)

CONFIG = Path(__file__).resolve().parent / "config" / "loop.yaml"


def loop_config(path: Path = CONFIG) -> dict:
    return load_yaml(path)


class Station(Strict):
    name: str
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class Alignment(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9]+$")
    name: str = ""
    stations: list[Station] = Field(min_length=2)


class LoopBase(Sourced):
    alignments: list[Alignment] = Field(min_length=1)
    speed_kmh: float | None = Field(None, gt=0, le=250)
    capacity: Literal["measured", "engineering"] | None = None
    occupancy: float | None = Field(None, gt=0)
    min_trip_km: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _unique_ids(self) -> LoopBase:
        ids = [a.id for a in self.alignments]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate alignment ids: {ids}")
        return self


class LoopShuttle(LoopBase):
    """Shuttle mode: car tours whose legs all run between two stations shift with share alpha."""

    type: Literal["loop_shuttle"]
    alpha: float | None = Field(None, ge=0, le=1)
    radius_o_m: float | None = Field(None, gt=0)
    radius_d_m: float | None = Field(None, gt=0)
    dwell_s: float | None = Field(None, ge=0)
    empty_reposition_factor: float | None = Field(None, ge=0)
    competitive_only: bool | None = None
    # Track H: path to a mode-choice YAML (sim/loop/config/mode_choice.yaml); replaces alpha
    mode_choice: str | None = None

    @model_serializer(mode="wrap")
    def _drop_unset_mode_choice(self, handler: Any) -> dict[str, Any]:
        """Leave `mode_choice` out when unset, so alpha-path policies keep their hashes."""
        d = handler(self)
        if isinstance(d, dict) and d.get("mode_choice") is None:
            d.pop("mode_choice", None)
        return d


class LoopPrivate(LoopBase):
    """Private-EV mode: tunnels open to passenger cars with a toll and a headway limit."""

    type: Literal["loop_private"]
    toll_sar: float | None = Field(None, ge=0)
    value_of_time_sar_h: float | None = Field(None, gt=0)
    reroute_radius_m: float | None = Field(None, gt=0)
    eligible_share: float | None = Field(None, ge=0, le=1)


LoopTransform = Annotated[
    RemoteWork
    | StaggeredHours
    | DayTypeChange
    | PtLine
    | RoadPricing
    | NetworkChange
    | RidehailShare
    | LoopShuttle
    | LoopPrivate,
    Field(discriminator="type"),
]


def register_loop_transforms() -> None:
    """Add the Loop transforms to Track A's `Policy` transform union (sim.schemas registers them
    with one appended import line, so `python -m sim.validate` and `load_policy` accept Loop
    policies). Idempotent."""
    from pydantic.fields import FieldInfo

    if getattr(Policy, "_loop_registered", False):
        return
    ann = list[LoopTransform]
    Policy.__annotations__["transforms"] = ann
    Policy.model_fields["transforms"] = FieldInfo.from_annotated_attribute(ann, Field(min_length=1))
    Policy.model_rebuild(force=True)
    Policy._loop_registered = True  # type: ignore[attr-defined]


register_loop_transforms()


class LoopPolicy(Policy):
    transforms: list[LoopTransform] = Field(min_length=1)  # type: ignore[assignment]

    @model_validator(mode="after")
    def _one_loop(self) -> LoopPolicy:
        kinds = [t.type for t in self.transforms]
        if kinds.count("loop_shuttle") + kinds.count("loop_private") > 1:
            raise ValueError("one loop transform per policy (list several alignments in it)")
        return self


def load_loop_policy(name_or_path: str | Path) -> LoopPolicy:
    path = Path(name_or_path)
    if not path.suffix:
        path = Path(__file__).resolve().parents[1] / "policies" / f"{name_or_path}.yaml"
    return LoopPolicy.model_validate(load_yaml(path))


def loop_transform(pol: Policy) -> LoopShuttle | LoopPrivate | None:
    for t in pol.transforms:
        if isinstance(t, LoopShuttle | LoopPrivate):
            return t
    return None
