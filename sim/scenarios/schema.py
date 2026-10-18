"""Pydantic models for scenario (event) files, per the policy-yaml skill.

Times are simulation seconds since the window's time 0, written as a number (`600`) or as
"HH:MM[:SS]" (`"00:10:00"`). Window demand covers 0-3600 s, so demo scenarios use 0-3600.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from sim.vtypes.schema import check_mix

EVENTS_IMPLEMENTED = ("accident", "rain", "flood", "motorcade", "emergency_trip")


def _sim_time(v: Any) -> float:
    if isinstance(v, bool):
        raise ValueError("time must be seconds or 'HH:MM[:SS]'")
    if isinstance(v, int | float):
        if v < 0:
            raise ValueError("time must be >= 0")
        return float(v)
    if isinstance(v, str):
        parts = v.strip().split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            h, m, s = (int(p) for p in (parts + ["0"])[:3])
            if m < 60 and s < 60:
                return float(h * 3600 + m * 60 + s)
    raise ValueError(f"bad time {v!r}: use seconds or 'HH:MM[:SS]'")


SimTime = Annotated[float, BeforeValidator(_sim_time)]


class EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = None
    start: SimTime
    source: str | None = None
    assumption: str | None = None
    notes: str | None = None

    # fields that override a registered behavioural default; require source/assumption
    behavioural: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _overrides_need_provenance(self) -> EventBase:
        overridden = [f for f in self.behavioural if getattr(self, f, None) is not None]
        if overridden and not (self.source or self.assumption):
            raise ValueError(
                f"{self.type}: overriding behavioural defaults {overridden} needs "  # type: ignore[attr-defined]
                "`source:` or `assumption:` on the event"
            )
        return self


class TimedEvent(EventBase):
    duration_s: float | None = Field(default=None, gt=0)
    duration_min: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one_duration(self) -> TimedEvent:
        if (self.duration_s is None) == (self.duration_min is None):
            raise ValueError("give exactly one of duration_s / duration_min")
        return self

    @property
    def duration(self) -> float:
        return float(self.duration_s if self.duration_s is not None else self.duration_min * 60)

    @property
    def end(self) -> float:
        return self.start + self.duration


class Accident(TimedEvent):
    type: Literal["accident"]
    edge: str
    lanes_closed: int | Literal["all"] = 1
    side: Literal["left", "right"] | None = None
    include_split_parts: bool = True
    rubbernecking: bool = True
    rubbernecking_factor: float | None = Field(default=None, gt=0, le=1)
    reroute: bool | None = None
    behavioural: ClassVar[tuple[str, ...]] = ("rubbernecking_factor", "side", "reroute")

    @model_validator(mode="after")
    def _lanes(self) -> Accident:
        if isinstance(self.lanes_closed, int) and self.lanes_closed < 1:
            raise ValueError("lanes_closed must be >= 1 or 'all'")
        return self


class Rain(TimedEvent):
    type: Literal["rain"]
    preset: Literal["light", "heavy", "storm"]


class Flood(TimedEvent):
    type: Literal["flood"]
    preset: Literal["light", "heavy", "storm"] = "storm"
    sites_file: str | None = None
    site_ids: list[str] | None = None
    min_confidence: str | None = None
    closure_delay_s: float | None = Field(default=None, ge=0)
    reroute: bool | None = None
    behavioural: ClassVar[tuple[str, ...]] = ("closure_delay_s", "reroute")


class Motorcade(EventBase):
    type: Literal["motorcade"]
    route: list[str] | None = None
    from_edge: str | None = Field(default=None, alias="from")
    to_edge: str | None = Field(default=None, alias="to")
    vehicles: int = Field(default=5, ge=1, le=50)
    headway_s: float | None = Field(default=None, gt=0)
    lead_time_s: float | None = Field(default=None, ge=0)
    clear_time_s: float | None = Field(default=None, ge=0)
    hold: Literal["all_other_movements", "entering_only"] | None = None
    max_duration_s: float | None = Field(default=None, gt=0)
    behavioural: ClassVar[tuple[str, ...]] = ("headway_s", "lead_time_s", "clear_time_s", "hold")

    @model_validator(mode="after")
    def _route_or_ends(self) -> Motorcade:
        if self.route:
            if self.from_edge or self.to_edge:
                raise ValueError("motorcade: give `route` or `from`/`to`, not both")
        elif not (self.from_edge and self.to_edge):
            raise ValueError("motorcade: give `route` (edge list) or both `from` and `to`")
        return self


class EmergencyTrip(EventBase):
    type: Literal["emergency_trip"]
    from_edge: str = Field(alias="from")
    to_edge: str = Field(alias="to")
    vehicles: int = Field(default=1, ge=1, le=20)
    headway_s: float | None = Field(default=None, gt=0)
    strategist: bool = False
    max_duration_s: float | None = Field(default=None, gt=0)
    behavioural: ClassVar[tuple[str, ...]] = ("headway_s",)


class Evacuation(BaseModel):
    """Reserved for M7: accepted by the schema, rejected at run time."""

    model_config = ConfigDict(extra="allow")
    type: Literal["evacuation"]
    id: str | None = None
    start: SimTime


Event = Annotated[
    Accident | Rain | Flood | Motorcade | EmergencyTrip | Evacuation,
    Field(discriminator="type"),
]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: Literal["scenario"]
    window: str
    daytype: str
    label: str
    fictional: bool
    begin: SimTime = 0.0
    end: SimTime
    vtype_mix: dict[str, float] | None = None
    events: list[Event] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        if self.end <= self.begin:
            raise ValueError("end must be after begin")
        if self.vtype_mix is not None:
            check_mix(self.vtype_mix)
        seen: set[str] = set()
        for i, ev in enumerate(self.events):
            if ev.id is None:
                ev.id = f"{ev.type}_{i}"
            if ev.id in seen:
                raise ValueError(f"duplicate event id {ev.id!r}")
            seen.add(ev.id)
            if not self.begin <= ev.start < self.end:
                raise ValueError(f"event {ev.id} starts at {ev.start}, outside [begin, end)")
        return self


def strategist_requested(scenario: Scenario) -> bool:
    """True if any emergency trip asks for strategist support (read by Track B's M6)."""
    return any(isinstance(e, EmergencyTrip) and e.strategist for e in scenario.events)
