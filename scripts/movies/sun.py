"""Sun position (NOAA equations) and the film lighting derived from it (A-mov-003, A-mov-004).

`sun_position(date, local_seconds)` gives the compass azimuth (degrees from north, clockwise) and
the elevation of the sun's centre above the horizon for Jeddah on that date, with the simulated
clock read as local time (AST, UTC+3). `lighting(elevation)` turns it into the values the cinema
renderer needs: a light direction for deck.gl's DirectionalLight (x east, y north, z up; the
direction the light travels), intensities and a night factor (0 day .. 1 night).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as Date
from typing import Any

from scripts.movies.spec import load_settings

DAY_S = 86400


@dataclass(frozen=True)
class Sun:
    azimuth_deg: float
    elevation_deg: float


def _julian_day(d: Date) -> float:
    """Julian day number at 00:00 UTC of a Gregorian date."""
    y, m = d.year, d.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d.day + b - 1524.5


def sun_position(d: Date, local_s: float, lat: float, lon: float, utc_offset_h: float) -> Sun:
    """NOAA solar position for local clock seconds `local_s` (may exceed one day)."""
    utc_s = local_s - utc_offset_h * 3600.0
    jd = _julian_day(d) + utc_s / DAY_S
    t = (jd - 2451545.0) / 36525.0  # Julian centuries since J2000.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0  # geometric mean longitude
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)  # mean anomaly
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)  # orbit eccentricity
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long)))
    y = math.tan(math.radians(eps / 2)) ** 2
    l0r = math.radians(l0)
    eq_time = 4 * math.degrees(  # minutes
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    utc_min = utc_s / 60.0
    true_solar_min = (utc_min + eq_time + 4 * lon) % 1440.0
    hour_angle = true_solar_min / 4 - 180.0
    latr = math.radians(lat)
    cos_zen = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(
        math.radians(hour_angle)
    )
    zen = math.acos(max(-1.0, min(1.0, cos_zen)))
    elevation = 90.0 - math.degrees(zen)
    denom = math.cos(latr) * math.sin(zen)
    if abs(denom) < 1e-12:
        azimuth = 180.0
    else:
        cos_az = (math.sin(latr) * math.cos(zen) - math.sin(decl)) / denom
        az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
        azimuth = (az + 180.0) % 360.0 if hour_angle > 0 else (540.0 - az) % 360.0
    return Sun(azimuth, elevation)


def sun_for_film(date_iso: str, local_s: float, settings: dict[str, Any] | None = None) -> Sun:
    s = (settings or load_settings())["sun"]
    return sun_position(
        Date.fromisoformat(date_iso), local_s, s["latitude"], s["longitude"], s["utc_offset_h"]
    )


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def light_direction(sun: Sun) -> tuple[float, float, float]:
    """Direction the sunlight travels (x east, y north, z up), unit length."""
    az, el = math.radians(sun.azimuth_deg), math.radians(max(sun.elevation_deg, 2.0))
    return (-math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), -math.sin(el))


def lighting(sun: Sun, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Light set for one frame: night factor, sun and ambient intensity/colour, direction."""
    twilight = float((settings or load_settings())["sun"]["twilight_deg"]["value"])
    el = sun.elevation_deg
    night = 1.0 - smoothstep(twilight, 0.0, el)  # 1 below civil twilight, 0 above the horizon
    golden = 1.0 - smoothstep(0.0, 20.0, el)  # warm light near the horizon
    day = 1.0 - night
    sun_rgb = [255, round(255 - 75 * golden), round(255 - 150 * golden)]
    ambient_rgb = [round(255 - 150 * night), round(255 - 140 * night), round(255 - 70 * night)]
    return {
        "night": round(night, 4),
        "sun_intensity": round(2.2 * day * smoothstep(-2.0, 8.0, el), 4),
        "sun_color": sun_rgb,
        "ambient_intensity": round(0.35 + 0.65 * day, 4),
        "ambient_color": ambient_rgb,
        "direction": [round(v, 5) for v in light_direction(sun)],
        "azimuth_deg": round(sun.azimuth_deg, 3),
        "elevation_deg": round(el, 3),
    }
