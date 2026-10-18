"""Bridge policy models: a `network_change` transform that can also add whole crossings.

A crossing is a two-way road bridge between two landings (one per bank). Each landing has an
abutment (lon/lat at the shore, where the structure starts) and one or more `connect` points
that are snapped to existing arterial junctions; the builder (sim/bridge/network.py) adds new nodes
at the abutments, the span between them and an approach link each way between the abutment and every
snapped junction, with geometry in the network's own projection.

    transforms:
      - type: network_change
        bridges:
          - id: b1
            name: "Obhur Creek mouth bridge"
            lanes: 2                      # per direction (2+2)
            speed_kmh: 80                 # span
            approach_speed_kmh: 60
            south: {name: ..., abutment: [lon, lat], connect: [[lon, lat]]}
            north: {name: ..., abutment: [lon, lat], connect: [[lon, lat], [lon, lat]]}
        reroute: {...}
        assumption: "A-obh-0nn: ..."

`BridgePolicy` is Track A's `Policy` whose `network_change` transform also accepts `bridges` and
`reroute` (closures, lane and speed edits still work in the same transform, since a policy may hold
only one `network_change`). It runs through `sim.policies.run.run_policy` via sim/bridge/run.py,
the same run-time dispatch pattern as Track D's Loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from sim.common import REPO_ROOT, load_yaml
from sim.schemas import (
    DayTypeChange,
    NetworkChange,
    Policy,
    PtLine,
    RemoteWork,
    RidehailShare,
    RoadPricing,
    StaggeredHours,
    Strict,
)

CONFIG = Path(__file__).resolve().parent / "config" / "bridge.yaml"
POLICY_DIR = REPO_ROOT / "sim" / "policies"

LonLat = tuple[float, float]


def bridge_config(path: Path = CONFIG) -> dict:
    return load_yaml(path)


class Landing(Strict):
    name: str
    abutment: LonLat = Field(description="lon, lat where the structure meets the bank")
    connect: list[LonLat] = Field(
        min_length=1,
        description="lon, lat points snapped to existing arterial junctions; give one per "
        "carriageway on a divided road so both directions are reached",
    )

    @model_validator(mode="after")
    def _in_range(self) -> Landing:
        for lon, lat in [self.abutment, *self.connect]:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"{self.name}: lon/lat out of range ({lon}, {lat})")
        return self


class Crossing(Strict):
    id: str = Field(pattern=r"^[a-z0-9]+$")
    name: str
    lanes: int = Field(ge=1, le=6, description="lanes per direction")
    speed_kmh: float = Field(gt=0, le=130, description="design speed on the span")
    approach_speed_kmh: float = Field(gt=0, le=130)
    south: Landing
    north: Landing
    navigation: str = Field(description="navigable-span note (clearance or opening span)")
    source_note: str = Field(description="public plan this alignment follows, or 'analysis'")


class Reroute(Strict):
    """Which baseline vehicles get a one-shot route on the bridge network (and in the control)."""

    window: str | None = Field(
        "obhur_creek", description="route uses an edge inside this window polygon"
    )
    desire_crossing: bool = Field(True, description="or the O-D line crosses the creek polygon")


class BridgeNetworkChange(NetworkChange):
    """`network_change` with crossings: the bridge edges plus Track A's edits in one patch."""

    type: Literal["network_change"]
    bridges: list[Crossing] = Field(default_factory=list)
    reroute: Reroute = Reroute()

    @model_validator(mode="after")
    def _something(self) -> BridgeNetworkChange:  # overrides NetworkChange's check by name
        if not (self.edits or self.new_edges or self.tls_program or self.bridges):
            raise ValueError("network_change needs edits, new_edges, tls_program or bridges")
        return self

    @model_validator(mode="after")
    def _unique(self) -> BridgeNetworkChange:
        ids = [b.id for b in self.bridges]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate bridge ids: {ids}")
        return self


BridgeTransform = Annotated[
    RemoteWork
    | StaggeredHours
    | DayTypeChange
    | PtLine
    | RoadPricing
    | BridgeNetworkChange
    | RidehailShare,
    Field(discriminator="type"),
]


class BridgePolicy(Policy):
    transforms: list[BridgeTransform] = Field(min_length=1)  # type: ignore[assignment]


def load_bridge_policy(name_or_path: str | Path) -> BridgePolicy:
    path = Path(name_or_path)
    if not path.suffix:
        path = POLICY_DIR / f"{name_or_path}.yaml"
    return BridgePolicy.model_validate(load_yaml(path))


def bridge_transform(pol: Policy) -> BridgeNetworkChange | None:
    for t in pol.transforms:
        if isinstance(t, BridgeNetworkChange) and t.bridges:
            return t
    return None
