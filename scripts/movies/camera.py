"""Keyframed camera paths: easing and interpolation, evaluated per frame (no wall clock).

Frame i of a film is at film time i / fps. Within a shot the camera between two keyframes moves
with the easing named on the later keyframe: position in Web Mercator (so a straight dolly stays
straight on screen), zoom linearly, bearing along the shorter arc. The simulated clock is
interpolated linearly in film time between keyframes that set `sim_t` and held outside them, so
"sim seconds per film second" is constant inside a segment.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scripts.movies.spec import Film, Keyframe, Shot

MERCATOR_MAX_LAT = 85.051129  # Web Mercator latitude limit


@dataclass(frozen=True)
class CameraState:
    lon: float
    lat: float
    zoom: float
    pitch: float
    bearing: float
    sim_t: float


@dataclass(frozen=True)
class FramePlan:
    index: int
    film_t: float
    shot: int  # index into film.shots
    shot_t: float
    camera: CameraState


def ease(u: float, kind: str) -> float:
    """Map u in [0, 1] to eased progress in [0, 1]."""
    u = min(1.0, max(0.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u * u
    if kind == "out":
        return 1 - (1 - u) ** 3
    if kind == "in_out":
        return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2
    if kind == "hold":
        return 1.0 if u >= 1.0 else 0.0
    raise ValueError(f"unknown easing {kind!r}")


def to_mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-MERCATOR_MAX_LAT, min(MERCATOR_MAX_LAT, lat))
    x = math.radians(lon)
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def from_mercator(x: float, y: float) -> tuple[float, float]:
    return math.degrees(x), math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def lerp_angle(a: float, b: float, f: float) -> float:
    """Interpolate bearings along the shorter arc; result in (-180, 180]."""
    d = ((b - a + 180.0) % 360.0) - 180.0
    out = (a + d * f + 180.0) % 360.0 - 180.0
    return 180.0 if out == -180.0 else out


def sim_time_at(keys: Sequence[Keyframe], t: float) -> float:
    """Simulated time at shot time t: linear between keyframes with sim_t, held outside them."""
    timed = [(k.t, float(k.sim_t)) for k in keys if k.sim_t is not None]
    if not timed:
        raise ValueError("no keyframe sets sim_t")
    if t <= timed[0][0]:
        return timed[0][1]
    for (t0, s0), (t1, s1) in zip(timed, timed[1:], strict=False):
        if t <= t1:
            return lerp(s0, s1, (t - t0) / (t1 - t0))
    return timed[-1][1]


def camera_at(keys: Sequence[Keyframe], t: float) -> CameraState:
    """Camera at shot time t (seconds); held after the last keyframe."""
    sim_t = sim_time_at(keys, t)
    if t <= keys[0].t or len(keys) == 1:
        k = keys[0]
        return CameraState(
            k.lon, k.lat, k.zoom, k.pitch, lerp_angle(k.bearing, k.bearing, 0), sim_t
        )
    for a, b in zip(keys, keys[1:], strict=False):
        if t <= b.t:
            f = ease((t - a.t) / (b.t - a.t), b.ease)
            ax, ay = to_mercator(a.lon, a.lat)
            bx, by = to_mercator(b.lon, b.lat)
            lon, lat = from_mercator(lerp(ax, bx, f), lerp(ay, by, f))
            return CameraState(
                lon,
                lat,
                lerp(a.zoom, b.zoom, f),
                lerp(a.pitch, b.pitch, f),
                lerp_angle(a.bearing, b.bearing, f),
                sim_t,
            )
    k = keys[-1]
    return CameraState(k.lon, k.lat, k.zoom, k.pitch, lerp_angle(k.bearing, k.bearing, 0), sim_t)


def frame_count(film: Film, fps: int) -> int:
    return round(film.duration_s * fps)


def shot_at(shots: Sequence[Shot], film_t: float) -> tuple[int, float]:
    """(shot index, time inside the shot) for a film time; the last shot holds its end."""
    start = 0.0
    for i, shot in enumerate(shots):
        if film_t < start + shot.duration_s or i == len(shots) - 1:
            return i, min(film_t - start, shot.duration_s)
        start += shot.duration_s
    raise ValueError("film has no shots")


def plan_frames(film: Film, fps: int) -> list[FramePlan]:
    """One FramePlan per output frame: frame i is at film time i / fps (bit-stable)."""
    plans = []
    for i in range(frame_count(film, fps)):
        film_t = i / fps
        s, shot_t = shot_at(film.shots, film_t)
        plans.append(FramePlan(i, film_t, s, shot_t, camera_at(film.shots[s].camera, shot_t)))
    return plans
