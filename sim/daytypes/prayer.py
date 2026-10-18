"""Prayer times for a simulated date in Jeddah (adhanpy, Umm al-Qura method).

python -m sim.daytypes.prayer 2026-10-18
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import typer
from adhanpy.calculation import CalculationMethod
from adhanpy.PrayerTimes import PrayerTimes

JEDDAH = (21.5433, 39.1728)  # Al-Balad; prayer times vary by about a minute across the city
TZ = ZoneInfo("Asia/Riyadh")


def prayer_times(date: str, coords: tuple[float, float] = JEDDAH) -> dict[str, float]:
    """Seconds after local midnight of each adhan (fajr, sunrise, dhuhr, asr, maghrib, isha).

    `jumuah` equals dhuhr (the Friday sermon starts at the dhuhr adhan).
    """
    day = datetime.strptime(date, "%Y-%m-%d")
    pt = PrayerTimes(coords, day, CalculationMethod.UMM_AL_QURA, time_zone=TZ)
    out = {}
    for name in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"):
        t = getattr(pt, name).astimezone(TZ)
        out[name] = float(t.hour * 3600 + t.minute * 60 + t.second)
    out["jumuah"] = out["dhuhr"]
    return out


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(date: str) -> None:
    for name, s in prayer_times(date).items():
        typer.echo(f"{name:8s} {int(s // 3600):02d}:{int(s % 3600 // 60):02d}")


if __name__ == "__main__":
    app()
