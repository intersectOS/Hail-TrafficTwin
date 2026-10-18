"""Pydantic models for the behavioural YAML files (population config, day types, policies).

Every behavioural number sits in a block that carries `source:` (citation) or `assumption:`
(reasoning and plausible range); the models refuse blocks without one. Times of day are written
as "HH:MM" (may exceed 24:00 for after-midnight activity) and durations in minutes.

    python -m sim.schemas sim/daytypes/weekday.yaml      # validate one file
    python -m sim.validate sim/policies/remote_work_30.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sim.common import load_yaml


def hhmm_to_s(value: str | int | float) -> float:
    """'07:30' -> 27000.0; numbers are taken as seconds."""
    if isinstance(value, int | float):
        return float(value)
    hours, minutes = value.strip().split(":")
    return int(hours) * 3600.0 + int(minutes) * 60.0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sourced(Strict):
    """A behavioural block: must say where its numbers come from."""

    source: str | None = None
    assumption: str | None = None

    @model_validator(mode="after")
    def _has_provenance(self) -> Sourced:
        if not (self.source or self.assumption):
            raise ValueError(f"{type(self).__name__}: needs `source:` or `assumption:`")
        return self


class Component(Strict):
    w: float = Field(gt=0)
    mean: str
    sd_min: float = Field(ge=0)

    @property
    def mean_s(self) -> float:
        return hhmm_to_s(self.mean)


class TimeDist(Sourced):
    """Time-of-day distribution: a normal or a mixture of normals, truncated to [lo, hi]."""

    dist: Literal["normal", "mixture", "uniform"] = "normal"
    mean: str | None = None
    sd_min: float | None = None
    components: list[Component] | None = None
    lo: str
    hi: str

    @model_validator(mode="after")
    def _shape(self) -> TimeDist:
        if self.dist == "normal" and (self.mean is None or self.sd_min is None):
            raise ValueError("normal needs mean and sd_min")
        if self.dist == "mixture" and not self.components:
            raise ValueError("mixture needs components")
        if hhmm_to_s(self.lo) >= hhmm_to_s(self.hi):
            raise ValueError("lo must be before hi")
        return self

    def as_components(self) -> list[tuple[float, float, float]]:
        """[(weight, mean_s, sd_s)]; uniform -> one component with sd = -1 as a marker."""
        if self.dist == "normal":
            assert self.mean is not None and self.sd_min is not None
            return [(1.0, hhmm_to_s(self.mean), self.sd_min * 60.0)]
        if self.dist == "uniform":
            return [(1.0, 0.0, -1.0)]
        assert self.components is not None
        total = sum(c.w for c in self.components)
        return [(c.w / total, c.mean_s, c.sd_min * 60.0) for c in self.components]

    @property
    def lo_s(self) -> float:
        return hhmm_to_s(self.lo)

    @property
    def hi_s(self) -> float:
        return hhmm_to_s(self.hi)


class DurationDist(Sourced):
    """Activity duration in minutes, normal truncated to [lo_min, hi_min]."""

    mean_min: float = Field(gt=0)
    sd_min: float = Field(ge=0)
    lo_min: float = Field(ge=0)
    hi_min: float = Field(gt=0)


class Probability(Sourced):
    value: float = Field(ge=0, le=1)


class Rate(Sourced):
    """Tours per person per day (Poisson-like: integer part certain, fraction a probability)."""

    value: float = Field(ge=0)


class SplitShift(Sourced):
    """Share of workers who go home between two shifts (retail split shift)."""

    probability: float = Field(ge=0, le=1)
    break_start: TimeDist
    break_min: DurationDist


class MainTour(Strict):
    """The mandatory tour of a segment (work, school, university)."""

    participation: Probability
    start: TimeDist
    duration: DurationDist
    split_shift: SplitShift | None = None
    stop_on_return: Probability | None = None


class SecondaryTour(Strict):
    rate: Rate
    start: TimeDist
    duration: DurationDist


class Prayer(Sourced):
    """Mosque trips keyed to the computed adhan time of one prayer."""

    share_adult_males: float = Field(ge=0, le=1)
    share_adult_females: float = Field(ge=0, le=1)
    depart_offset_min: float
    duration_min: float = Field(gt=0)
    distance: Literal["local", "district"] = "local"


class AirportFlows(Sourced):
    trips_per_day: float = Field(ge=0)
    hourly_profile: list[float] = Field(min_length=24, max_length=24)
    to_makkah_share: float = Field(0.0, ge=0, le=1)


class SpecialFlags(Strict):
    ramadan: bool = False
    friday: bool = False
    umrah_season: bool = False
    school_day: bool = True


class DayType(Strict):
    """A Jeddah time-of-day profile (sim/daytypes/<id>.yaml)."""

    id: str
    kind: Literal["daytype"]
    title: str
    date: str = Field(description="simulated date (YYYY-MM-DD), drives prayer times")
    special: SpecialFlags = SpecialFlags()
    main_tours: dict[str, MainTour]
    secondary_tours: dict[str, dict[str, SecondaryTour]]
    prayers: dict[str, Prayer]
    airport: AirportFlows
    notes: str | None = None

    @field_validator("main_tours")
    @classmethod
    def _known_segments(cls, v: dict[str, MainTour]) -> dict[str, MainTour]:
        known = set(MAIN_SEGMENTS)
        unknown = set(v) - known
        if unknown:
            raise ValueError(f"unknown main-tour segments {sorted(unknown)}; known {sorted(known)}")
        return v

    @field_validator("secondary_tours")
    @classmethod
    def _known_groups(
        cls, v: dict[str, dict[str, SecondaryTour]]
    ) -> dict[str, dict[str, SecondaryTour]]:
        unknown = set(v) - set(STATUS_GROUPS)
        if unknown:
            raise ValueError(f"unknown status groups {sorted(unknown)}; known {STATUS_GROUPS}")
        for tours in v.values():
            bad = set(tours) - set(SECONDARY_PURPOSES)
            if bad:
                raise ValueError(f"unknown secondary purposes {sorted(bad)}")
        return v

    @field_validator("prayers")
    @classmethod
    def _known_prayers(cls, v: dict[str, Prayer]) -> dict[str, Prayer]:
        bad = set(v) - set(PRAYERS)
        if bad:
            raise ValueError(f"unknown prayers {sorted(bad)}; known {PRAYERS}")
        return v


# Segment vocabulary shared by the population, day types and policies.
WORK_SECTORS = (
    "government",
    "private_office",
    "retail_hospitality",
    "health",
    "education",
    "industrial_port",
    "logistics_ridehail",
)
MAIN_SEGMENTS = (*WORK_SECTORS, "school", "university")
STATUS_GROUPS = ("worker", "student", "homemaker", "other")
SECONDARY_PURPOSES = ("shopping", "leisure", "personal")
PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha", "jumuah")


# ---------------------------------------------------------------------------- policies (M4)
# A policy transforms the population, plans or network before a run (PROJECT.md section 7);
# it never acts through TraCI. Every transform carries `source:` or `assumption:`.

STAGGER_SEGMENTS = (*MAIN_SEGMENTS, "schools")  # "schools" is an alias of "school"


class RemoteWork(Sourced):
    """Remove the work tour of hybrid workers who stay home on the simulated day."""

    type: Literal["remote_work"]
    share: float | dict[str, float] = Field(
        description="share of eligible workers on a hybrid scheme (one value or per sector)"
    )
    days_per_week: float = Field(gt=0, le=5, description="remote days per 5-day work week")
    eligible_sectors: list[str]
    induced_trip_probability: float = Field(0.0, ge=0, le=1)
    induced_purposes: dict[str, float] = Field(
        default_factory=lambda: {"shopping": 0.4, "personal": 0.4, "leisure": 0.2}
    )

    @field_validator("eligible_sectors")
    @classmethod
    def _sectors(cls, v: list[str]) -> list[str]:
        bad = set(v) - set(WORK_SECTORS)
        if bad or not v:
            raise ValueError(f"unknown or empty sectors {sorted(bad)}; known {WORK_SECTORS}")
        return v

    @model_validator(mode="after")
    def _shares(self) -> RemoteWork:
        shares = self.share if isinstance(self.share, dict) else {"*": self.share}
        if any(not 0 <= x <= 1 for x in shares.values()):
            raise ValueError("share must lie in [0, 1]")
        if isinstance(self.share, dict) and set(self.share) - set(self.eligible_sectors):
            raise ValueError("per-sector share for a sector that is not eligible")
        if set(self.induced_purposes) - set(SECONDARY_PURPOSES):
            raise ValueError(f"induced_purposes must be among {SECONDARY_PURPOSES}")
        return self

    def share_for(self, sector: str) -> float:
        if isinstance(self.share, dict):
            return float(self.share.get(sector, 0.0))
        return float(self.share)


class StaggeredHours(Sourced):
    """Shift the main tours of one segment by a signed offset (whole institutions move)."""

    type: Literal["staggered_hours"]
    segment: str
    offset_minutes: float
    spread_minutes: float = Field(0.0, ge=0, description="sd of extra per-institution offset")
    share: float = Field(1.0, ge=0, le=1, description="share of institutions that shift")

    @field_validator("segment")
    @classmethod
    def _segment(cls, v: str) -> str:
        if v not in STAGGER_SEGMENTS:
            raise ValueError(f"unknown segment {v!r}; known {STAGGER_SEGMENTS}")
        return "school" if v == "schools" else v


class DayTypeChange(Strict):
    """Re-time the whole population with another day-type profile (Friday, Ramadan ...)."""

    type: Literal["daytype"]
    daytype: str
    source: str | None = None
    assumption: str | None = None

    @field_validator("daytype")
    @classmethod
    def _exists(cls, v: str) -> str:
        if not (Path(__file__).resolve().parent / "daytypes" / f"{v}.yaml").exists():
            raise ValueError(f"no day type file sim/daytypes/{v}.yaml")
        return v


class PtStop(Strict):
    name: str
    lon: float
    lat: float


class PtLine(Sourced):
    """A bus line through ptlines2flows.py plus a fixed car-to-bus shift within its catchment."""

    type: Literal["pt_line"]
    line_id: str
    stops: list[PtStop] = Field(min_length=2)
    both_directions: bool = True
    headway_s: float = Field(gt=0)
    hours: tuple[str, str] = ("06:00", "23:00")
    catchment_m: float = Field(500.0, gt=0)
    shift_share: float = Field(ge=0, le=1)
    shift_modes: list[str] = Field(default_factory=lambda: ["car", "chauffeured", "ridehail"])
    stop_duration_s: float = Field(20.0, ge=0)


class RoadPricing(Sourced):
    """Cordon charge: suppressed/re-timed crossing trips and a routing penalty on cordon edges."""

    type: Literal["road_pricing"]
    polygon: list[tuple[float, float]] = Field(min_length=3, description="(lon, lat) ring")
    charge_sar: float = Field(gt=0)
    hours: tuple[str, str]
    direction: Literal["both", "inbound"] = "both"
    elasticity: float = Field(le=0, description="demand elasticity w.r.t. generalised trip cost")
    base_trip_cost_sar: float = Field(gt=0, description="generalised cost of a crossing trip")
    retime_share: float = Field(0.0, ge=0, le=1, description="of suppressed trips: re-timed")
    value_of_time_sar_h: float = Field(gt=0, description="converts the charge to a time penalty")


class EdgeEdit(Strict):
    """One network edit; edges by id, or by street `name` (substring) within a `bbox`."""

    edges: list[str] | None = None
    name: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    closed: bool = False
    lanes: int | None = Field(None, ge=1)
    speed_kmh: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _select(self) -> EdgeEdit:
        if not self.edges and not self.name:
            raise ValueError("edge edit needs `edges` or `name`")
        if not (self.closed or self.lanes or self.speed_kmh):
            raise ValueError("edge edit changes nothing (closed, lanes or speed_kmh)")
        return self


class NewEdge(Strict):
    id: str
    from_node: str
    to_node: str
    lanes: int = Field(1, ge=1)
    speed_kmh: float = Field(50.0, gt=0)


class NetworkChange(Sourced):
    """Closure, lane or speed change, new link (netconvert) or signal plan (additional file)."""

    type: Literal["network_change"]
    edits: list[EdgeEdit] = Field(default_factory=list)
    new_edges: list[NewEdge] = Field(default_factory=list)
    tls_program: str | None = Field(None, description="additional file with <tlLogic> elements")

    @model_validator(mode="after")
    def _something(self) -> NetworkChange:
        if not (self.edits or self.new_edges or self.tls_program):
            raise ValueError("network_change needs edits, new_edges or tls_program")
        return self


class RidehailShare(Sourced):
    """Move a share of car-driver tours to ride-hail, with empty (deadhead) legs to each pickup."""

    type: Literal["ridehail_share"]
    convert_share: float = Field(ge=0, le=1, description="share of car-driver tours that switch")
    deadhead_factor: float = Field(ge=0, description="empty km per occupied km (new trips)")


Transform = Annotated[
    RemoteWork
    | StaggeredHours
    | DayTypeChange
    | PtLine
    | RoadPricing
    | NetworkChange
    | RidehailShare,
    Field(discriminator="type"),
]


class PolicyReportSpec(Strict):
    kpis: list[str] = Field(
        default_factory=lambda: [
            "mean_delay", "mean_speed", "vkt", "vht", "throughput", "peak_spreading", "co2", "nox"
        ]
    )  # fmt: skip
    by_district: bool = True
    top_corridors: int = Field(10, ge=1)


class Policy(Strict):
    """A policy (sim/policies/<id>.yaml): transforms applied before a Tier A run."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: Literal["policy"]
    title: str
    daytype: str = Field(description="baseline day type to compare against")
    transforms: list[Transform] = Field(min_length=1)
    report: PolicyReportSpec = PolicyReportSpec()
    notes: str | None = None

    @model_validator(mode="after")
    def _daytype_first(self) -> Policy:
        kinds = [t.type for t in self.transforms]
        if kinds.count("daytype") > 1:
            raise ValueError("at most one daytype transform")
        if "daytype" in kinds and kinds[0] != "daytype":
            raise ValueError("the daytype transform must come first (it re-times everyone)")
        if kinds.count("network_change") > 1:
            raise ValueError("combine network edits into one network_change transform")
        return self


def load_policy(name_or_path: str | Path) -> Policy:
    path = Path(name_or_path)
    if not path.suffix:
        path = Path(__file__).resolve().parent / "policies" / f"{name_or_path}.yaml"
    return Policy.model_validate(load_yaml(path))


def validate_file(path: Path) -> BaseModel:
    data: dict[str, Any] = load_yaml(path)
    kind = data.get("kind")
    if kind == "daytype":
        return DayType.model_validate(data)
    if kind == "policy":
        types = {t.get("type") for t in data.get("transforms") or [] if isinstance(t, dict)}
        if types & {"loop_shuttle", "loop_private"}:
            from sim.loop.schema import LoopPolicy  # Track D transforms

            return LoopPolicy.model_validate(data)
        nets = [t for t in data.get("transforms") or [] if isinstance(t, dict)]
        if any(t.get("type") == "network_change" and "bridges" in t for t in nets):
            from sim.bridge.schema import BridgePolicy  # Track J crossings

            return BridgePolicy.model_validate(data)
        return Policy.model_validate(data)
    raise ValueError(f"{path}: unknown kind {kind!r}")


def load_daytype(name_or_path: str | Path) -> DayType:
    path = Path(name_or_path)
    if not path.suffix:
        path = Path(__file__).resolve().parent / "daytypes" / f"{name_or_path}.yaml"
    return DayType.model_validate(load_yaml(path))


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(files: list[Path]) -> None:
    for f in files:
        validate_file(f)
        typer.echo(f"ok {f}")


if __name__ == "__main__":
    app()

import sim.loop.schema  # noqa: E402, F401  Track D: registers loop_shuttle / loop_private
