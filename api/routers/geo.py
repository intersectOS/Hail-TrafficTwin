"""Static geo layers: districts and buildings (OpenStreetMap, ODbL)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from api.districts import districts_geojson_bytes
from api.geo import buildings_geojson
from api.runs import not_available

router = APIRouter(prefix="/api/geo", tags=["geo"])
GEOJSON = "application/geo+json"


@router.get("/districts")
def districts() -> Response:
    try:
        return Response(districts_geojson_bytes(), media_type=GEOJSON)
    except FileNotFoundError as exc:
        raise not_available("districts") from exc


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(v) for v in raw.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox must be w,s,e,n") from exc
    if not (w < e and s < n):
        raise HTTPException(status_code=422, detail="bbox must satisfy w < e and s < n")
    return w, s, e, n


@router.get("/buildings")
def buildings(bbox: str | None = None) -> Response:
    box = parse_bbox(bbox) if bbox else None
    try:
        body, count = buildings_geojson(box)
    except FileNotFoundError as exc:
        raise not_available("buildings") from exc
    return Response(body, media_type=GEOJSON, headers={"X-Feature-Count": str(count)})
