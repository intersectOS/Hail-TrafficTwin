"""Pydantic models for vType libraries, vType mixes and registered behavioural parameters.

Every behavioural number is a `Param`: value + unit + plausible range + `source:` or `assumption:`
+ an assumption-register id (`A-<area>-<nnn>`, listed in docs/assumptions-trackB.md).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ASSUMPTION_ID = r"^A-[a-z]+-[a-z0-9-]+$"
MIX_TOLERANCE = 1e-6  # numerical tolerance for "shares sum to 1" (not behavioural)


class Param(BaseModel):
    """A registered behavioural parameter."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ASSUMPTION_ID)
    value: float | int | bool | str
    unit: str = ""
    range: list[float | int | str] | str | None = None
    source: str | None = None
    assumption: str | None = None
    status: Literal["assumed", "sourced", "calibrated"] | None = None

    @model_validator(mode="after")
    def _needs_provenance(self) -> Param:
        if not (self.source or self.assumption):
            raise ValueError(f"{self.id}: needs `source:` or `assumption:`")
        if self.status is None:
            self.status = "sourced" if self.source and not self.assumption else "assumed"
        return self

    def range_text(self) -> str:
        if self.range is None:
            return ""
        if isinstance(self.range, str):
            return self.range
        return "-".join(str(x) for x in self.range)


# vType attributes we allow (SUMO names). Car-following and lane-change params are attributes too.
VTYPE_ATTRS = {
    "length",
    "width",
    "minGap",
    "accel",
    "decel",
    "emergencyDecel",
    "apparentDecel",
    "sigma",
    "tau",
    "maxSpeed",
    "speedFactor",
    "speedDev",
    "lcStrategic",
    "lcCooperative",
    "lcSpeedGain",
    "lcKeepRight",
    "lcAssertive",
    "lcImpatience",
    "jmIgnoreFoeProb",
    "jmDriveAfterRedTime",
}


class VTypeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    vClass: str
    guiShape: str
    color: str
    carFollowModel: Literal["Krauss"] = "Krauss"
    laneChangeModel: Literal["LC2013"] = "LC2013"
    tier_b_only: bool = False
    devices: list[Literal["bluelight"]] = Field(default_factory=list)
    params: dict[str, Param]

    @field_validator("params")
    @classmethod
    def _known_attrs(cls, v: dict[str, Param]) -> dict[str, Param]:
        unknown = set(v) - VTYPE_ATTRS
        if unknown:
            raise ValueError(f"unknown vType attributes: {sorted(unknown)}")
        return v

    @model_validator(mode="after")
    def _bluelight_is_tier_b(self) -> VTypeDef:
        if "bluelight" in self.devices and not self.tier_b_only:
            raise ValueError("the bluelight device is micro-only: set tier_b_only: true")
        return self


class VTypeLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vtype_library"]
    distribution_id: str
    step_length_s: float  # tau below the step length risks collisions (SUMO docs); checked
    types: dict[str, VTypeDef]

    @model_validator(mode="after")
    def _tau_floor(self) -> VTypeLibrary:
        for name, t in self.types.items():
            tau = t.params.get("tau")
            if tau is not None and float(tau.value) < self.step_length_s:
                raise ValueError(
                    f"{name}: tau {tau.value} < step length {self.step_length_s} "
                    "(Krauss collisions)"
                )
        return self


def check_mix(mix: dict[str, float], known: set[str] | None = None) -> dict[str, float]:
    """Shares must be in [0, 1], sum to 1 and (if `known` given) name known vTypes."""
    if not mix:
        raise ValueError("vtype_mix is empty")
    bad = {k: v for k, v in mix.items() if not 0.0 <= float(v) <= 1.0}
    if bad:
        raise ValueError(f"vtype_mix shares outside [0, 1]: {bad}")
    total = sum(float(v) for v in mix.values())
    if abs(total - 1.0) > MIX_TOLERANCE:
        raise ValueError(f"vtype_mix shares sum to {total:.6f}, expected 1")
    if known is not None:
        unknown = set(mix) - known
        if unknown:
            raise ValueError(f"vtype_mix names unknown vTypes: {sorted(unknown)}")
    return {k: float(v) for k, v in mix.items()}


class MixFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vtype_mix"]
    id: str
    title: str
    shares: dict[str, Param]

    def as_mix(self) -> dict[str, float]:
        return check_mix({k: float(p.value) for k, p in self.shares.items()})

    def assumption_ids(self) -> list[str]:
        return [p.id for p in self.shares.values()]


def params_in(obj: Any, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Find registered parameters (dicts with `id` and `value`) anywhere in a YAML tree."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(obj, dict):
        if "id" in obj and "value" in obj and str(obj["id"]).startswith("A-"):
            return [(prefix, obj)]
        for k, v in obj.items():
            found.extend(params_in(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(params_in(v, f"{prefix}[{i}]"))
    return found
