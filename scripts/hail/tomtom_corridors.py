"""Typical (historical) travel times on Hail's main corridors from the TomTom Routing API.

1. `corridors`: split every named main road of the Hail v2 network into ~2 km pieces, both
   directions, each as a SUMO edge path (data/observed/corridors.json).
2. `fetch` (needs TOMTOM_KEY): for each corridor, day type and hour, ask TomTom for the route between
   the corridor's ends departing at that hour on a future date, with computeTravelTimeFor=all, and
   keep `historicTrafficTravelTimeInSeconds` (TomTom's historical speed profiles) and
   `noTrafficTravelTimeInSeconds`. Routes whose TomTom length differs from the corridor by more than
   15 % took another path and are dropped. Writes data/observed/tomtom_traveltimes.csv in the
   travel-time adapter format (segment_id, edge_ids, hour, travel_time_s, samples) plus a JSON with
   the full rows.

    python -m scripts.hail.tomtom_corridors corridors
    TOMTOM_KEY=... python -m scripts.hail.tomtom_corridors fetch --days weekday,thursday

Data: TomTom historical traffic, used under the TomTom Developer terms; attribution "© TomTom".
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import sumolib
import typer

from sim.common import REPO_ROOT

NET = REPO_ROOT / "data" / "hail" / "hail.v2.net.xml"
OUT = REPO_ROOT / "data" / "observed"
MAIN = {"highway.trunk", "highway.primary", "highway.secondary", "highway.tertiary"}
PIECE_M = 2000.0
MIN_PIECE_M = 900.0
LENGTH_TOL = 0.15
app = typer.Typer(add_completion=False, help=__doc__)


def _lonlat(net: Any, x: float, y: float) -> tuple[float, float]:
    lon, lat = net.convertXY2LonLat(x, y)
    return round(lon, 6), round(lat, 6)


def chains(net: Any) -> list[tuple[str, list[Any]]]:
    """Per named main road and direction: maximal chains of edges that continue the same street."""
    by_name: dict[str, list[Any]] = {}
    for e in net.getEdges():
        if e.getType() in MAIN and e.getName():
            by_name.setdefault(e.getName(), []).append(e)
    out: list[tuple[str, list[Any]]] = []
    for name, edges in by_name.items():
        ids = {e.getID() for e in edges}
        nxt: dict[str, Any] = {}
        has_prev: set[str] = set()
        for e in edges:
            cands = [o for o in e.getOutgoing() if o.getID() in ids and o.getID().lstrip("-") != e.getID().lstrip("-")]
            # continue straight: the candidate whose heading is closest
            if cands:
                (x0, y0), (x1, y1) = e.getShape()[-2], e.getShape()[-1]
                h = np.arctan2(y1 - y0, x1 - x0)

                def turn(o: Any) -> float:
                    (a0, b0), (a1, b1) = o.getShape()[0], o.getShape()[1]
                    d = np.arctan2(b1 - b0, a1 - a0) - h
                    return abs((d + np.pi) % (2 * np.pi) - np.pi)

                best = min(cands, key=turn)
                if turn(best) < np.radians(35):
                    nxt[e.getID()] = best
                    has_prev.add(best.getID())
        seen: set[str] = set()
        for e in edges:
            if e.getID() in has_prev or e.getID() in seen:
                continue
            ch = [e]
            seen.add(e.getID())
            while ch[-1].getID() in nxt and nxt[ch[-1].getID()].getID() not in seen:
                ch.append(nxt[ch[-1].getID()])
                seen.add(ch[-1].getID())
            if sum(x.getLength() for x in ch) >= MIN_PIECE_M:
                out.append((name, ch))
    return out


@app.command()
def corridors(net_file: Path = typer.Option(NET), out: Path = typer.Option(OUT / "corridors.json")) -> None:
    net = sumolib.net.readNet(str(net_file))
    rows = []
    for name, ch in chains(net):
        piece: list[Any] = []
        length = 0.0
        for e in ch:
            piece.append(e)
            length += e.getLength()
            if length >= PIECE_M:
                rows.append((name, piece, length))
                piece, length = [], 0.0
        if length >= MIN_PIECE_M:
            rows.append((name, piece, length))
    data = []
    for i, (name, piece, length) in enumerate(rows):
        a, b = piece[0].getShape()[0], piece[-1].getShape()[-1]
        data.append({"id": f"C{i:03d}", "name": name, "edges": [e.getID() for e in piece], "length_m": round(length),
                     "free_flow_s": round(sum(e.getLength() / e.getSpeed() for e in piece), 1),
                     "from": _lonlat(net, *a), "to": _lonlat(net, *b)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    typer.echo(f"{len(data)} corridors, {sum(d['length_m'] for d in data) / 1000:.0f} km -> {out}")


def next_day(weekday: int) -> dt.date:
    """The next date (at least 3 days ahead) with that ISO weekday (Mon=1 ... Sun=7)."""
    d = dt.date.today() + dt.timedelta(days=3)
    while d.isoweekday() != weekday:
        d += dt.timedelta(days=1)
    return d


DAYS = {"weekday": 7, "thursday": 4, "friday": 5, "saturday": 6}  # Sunday as the weekday


def route(key: str, a: list[float], b: list[float], depart: str) -> dict[str, Any] | None:
    loc = f"{a[1]},{a[0]}:{b[1]},{b[0]}"
    q = urllib.parse.urlencode({"key": key, "traffic": "true", "departAt": depart,
                                "computeTravelTimeFor": "all", "routeType": "fastest", "travelMode": "car"})
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{loc}/json?{q}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - fixed https host
                return json.loads(r.read())["routes"][0]["summary"]
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                time.sleep(2 + 3 * attempt)
                continue
            return None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError):
            time.sleep(1 + attempt)
    return None


@app.command()
def fetch(
    days: str = typer.Option("weekday,thursday"),
    hours: str = typer.Option("0-23"),
    corridors_file: Path = typer.Option(OUT / "corridors.json"),
    out_dir: Path = typer.Option(OUT),
    max_requests: int = typer.Option(6000),
    rps: float = typer.Option(4.0),
) -> None:
    key = os.environ.get("TOMTOM_KEY", "")
    if not key:
        raise typer.BadParameter("set TOMTOM_KEY")
    cors = json.loads(corridors_file.read_text())
    lo, hi = (int(x) for x in hours.split("-"))
    tz = dt.timezone(dt.timedelta(hours=3))
    rows: list[dict[str, Any]] = []
    n = dropped = failed = 0
    for day in days.split(","):
        date = next_day(DAYS[day])
        for c in cors:
            for h in range(lo, hi + 1):
                if n >= max_requests:
                    break
                depart = dt.datetime.combine(date, dt.time(h, 0), tz).isoformat()
                s = route(key, c["from"], c["to"], depart)
                n += 1
                time.sleep(1.0 / rps)
                if s is None:
                    failed += 1
                    continue
                if abs(s["lengthInMeters"] - c["length_m"]) > LENGTH_TOL * c["length_m"]:
                    dropped += 1
                    continue
                rows.append({"corridor": c["id"], "name": c["name"], "day": day, "date": str(date), "hour": h,
                             "length_m": s["lengthInMeters"], "historic_s": s.get("historicTrafficTravelTimeInSeconds"),
                             "no_traffic_s": s.get("noTrafficTravelTimeInSeconds"),
                             "live_s": s.get("liveTrafficIncidentsTravelTimeInSeconds"), "tt_s": s.get("travelTimeInSeconds")})
        typer.echo(f"{day} {date}: {n} requests, {len(rows)} kept, {dropped} other path, {failed} failed")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tomtom_traveltimes.json").write_text(json.dumps(
        {"source": "TomTom Routing API, historicTrafficTravelTimeInSeconds (© TomTom)", "fetched": dt.date.today().isoformat(),
         "requests": n, "kept": len(rows), "other_path": dropped, "failed": failed, "rows": rows}, ensure_ascii=False))
    edges = {c["id"]: " ".join(c["edges"]) for c in cors}
    with (out_dir / "tomtom_traveltimes.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["segment_id", "edge_ids", "hour", "travel_time_s", "samples"])
        for r in rows:
            if r["day"] == "weekday" and r["historic_s"]:
                w.writerow([r["corridor"], edges[r["corridor"]], r["hour"], r["historic_s"], 0])
    typer.echo(f"wrote {out_dir / 'tomtom_traveltimes.csv'}")


if __name__ == "__main__":
    app()
