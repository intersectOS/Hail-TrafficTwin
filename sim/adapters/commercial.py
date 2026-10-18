"""Commercial traffic-data adapters: INTERFACES ONLY (PROJECT.md 4 and 9.12).

Google, TomTom and HERE data cannot be redistributed. These stubs fix the interface a licensed user
would implement locally; nothing here calls an API. Rules for anyone implementing one:

- credentials come from the environment (`.env`, gitignored), never from the repo or a URL;
- fetched data is written outside the repo or under the gitignored `data/` tree and is never
  committed, published, or shipped in a release;
- output is converted to the open CSV formats (`sim.adapters.counts`, `sim.adapters.traveltimes`)
  so the calibration pipeline never depends on a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from sim.adapters.counts import CountRecord
from sim.adapters.traveltimes import TravelTimeRecord

NOT_IMPLEMENTED = (
    "{name} is an interface stub. Commercial traffic data is licensed and never committed; "
    "implement this adapter locally under your own licence, read the key from the environment "
    "variable {env}, and write its output under the gitignored data/ tree."
)


@dataclass(frozen=True)
class Segment:
    """A probe segment: ordered SUMO edges between two points the vendor can measure."""

    segment_id: str
    edge_ids: tuple[str, ...]


@runtime_checkable
class CountSource(Protocol):
    name: str

    def fetch_counts(self, edge_ids: list[str], day: date) -> list[CountRecord]: ...


@runtime_checkable
class TravelTimeSource(Protocol):
    name: str

    def fetch_travel_times(self, segments: list[Segment], day: date) -> list[TravelTimeRecord]: ...


class _Stub:
    name = "stub"
    env = "UNSET"

    def _refuse(self) -> NotImplementedError:
        return NotImplementedError(NOT_IMPLEMENTED.format(name=self.name, env=self.env))

    def fetch_travel_times(self, segments: list[Segment], day: date) -> list[TravelTimeRecord]:
        raise self._refuse()


class GoogleRoutesAdapter(_Stub):
    """Google Routes API (traffic-aware durations). Travel times only; no counts."""

    name = "google_routes"
    env = "GOOGLE_MAPS_API_KEY"


class TomTomAdapter(_Stub):
    """TomTom Traffic Stats / Move (historical segment speeds and sample sizes)."""

    name = "tomtom"
    env = "TOMTOM_API_KEY"


class HereAdapter(_Stub):
    """HERE Traffic (flow and historical speed patterns)."""

    name = "here"
    env = "HERE_API_KEY"


COMMERCIAL_ADAPTERS: dict[str, type[_Stub]] = {
    cls.name: cls for cls in (GoogleRoutesAdapter, TomTomAdapter, HereAdapter)
}
