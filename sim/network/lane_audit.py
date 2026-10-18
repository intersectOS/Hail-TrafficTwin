"""Lane audit from aerial imagery (Esri World Imagery) for untagged major roads.

The pipeline follows the `lane-audit-imagery` skill: inventory -> calibration on tagged ways ->
audit of untagged ways -> imagery fix list -> rebuilt network. Lane counts are read from the crops
by the `imagery-analyst` subagent (a vision pass outside this module); this module prepares the
crops, scores the calibration, applies the confidence threshold and writes the fix list.

    python -m sim.network.lane_audit inventory                  # untagged/tagged major ways
    python -m sim.network.lane_audit sample-calibration --n 40  # stratified tagged sample
    python -m sim.network.lane_audit sample-calibration --n 60 --seed 2 --set holdout \
        --exclude-set calibration                               # disjoint held-out check
    python -m sim.network.lane_audit crops --set calibration    # fetch tiles, write PNG crops
    python -m sim.network.lane_audit evaluate                   # -> fixes/imagery-eval.json
    python -m sim.network.lane_audit select-audit --cap 1500    # untagged ways by priority
    python -m sim.network.lane_audit crops --set audit
    python -m sim.network.lane_audit write-fixes                # -> fixes/imagery-lanes.yaml
    python -m sim.network.lane_audit rebuild                    # -> jeddah/jeddah.lanes.net.xml

Imaging needs Pillow, which is not yet a project dependency (pyproject.toml is outside this
track's ownership): run the `crops` command with `uv run --with pillow python -m ...`.
Working files (tiles, crops, analyst results) live under data/imagery/ (gitignored).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer
import yaml
from pyproj import Geod

from sim.common import REPO_ROOT, file_hash, rel, sumo_version

IMAGERY_DIR = REPO_ROOT / "data" / "imagery"
FIXES_DIR = REPO_ROOT / "data" / "osm" / "fixes"
EVAL_JSON = FIXES_DIR / "imagery-eval.json"
FIXES_YAML = FIXES_DIR / "imagery-lanes.yaml"
CLIP_PBF = REPO_ROOT / "data" / "osm" / "jeddah.osm.pbf"
RAW_NET = REPO_ROOT / "data" / "jeddah" / "jeddah.raw.net.xml"
LANES_NET = REPO_ROOT / "data" / "jeddah" / "jeddah.lanes.net.xml"

# Tool settings (how the audit runs, not how Jeddah behaves; see docs/lane-audit.md).
CLASSES = ("motorway", "trunk", "primary", "secondary")  # audit priority order
TILE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
TILE_SOURCE = "Esri World Imagery"
USER_AGENT = "TrafficTwinJeddah-lane-audit/0.1 (open-source traffic research; polite, cached)"
TILE_PX = 256
ZOOM = 19
CROP_PX = 512
OUT_SCALE = 2  # crops are upscaled 2x (lossless for counting, easier for the vision pass)
CAPTION_PX = 56
CAPTION_FONT_PX = 18
REQUEST_DELAY_S = 0.2
MIN_LENGTH_M = 60.0  # shorter ways are mostly junction stubs: no clean mid-segment sample
MIN_CALIBRATION_ACCEPTED = 15  # a threshold must keep at least this many calibration crops
TARGET_PRECISION = 0.80
EARTH_CIRCUMFERENCE_M = 40075016.686

GEOD = Geod(ellps="WGS84")


# ---------------------------------------------------------------- inventory


@dataclass
class Way:
    """One OSM major-road way with a mid-segment sample point."""

    way_id: int
    highway: str
    oneway: str  # "yes" | "no" | "-1"
    lanes_tag: str | None
    lanes_forward: str | None
    lanes_backward: str | None
    name: str | None
    length_m: float
    lon: float
    lat: float
    bearing: float  # degrees clockwise from north, direction of travel shown "up" in the crop

    @property
    def tagged(self) -> bool:
        return self.lanes_tag is not None

    def expected_lanes(self) -> int | None:
        """Lanes in the direction shown "up" in the crop, derived from the OSM tags.

        one-way (including oneway=-1): ``lanes``; two-way: ``lanes:forward``, else half of an
        even ``lanes``. Anything else is not comparable (None).
        """

        def as_int(v: str | None) -> int | None:
            try:
                return int(v) if v is not None else None
            except ValueError:
                return None

        total = as_int(self.lanes_tag)
        if self.oneway in ("yes", "-1"):
            return total
        fwd = as_int(self.lanes_forward)
        if fwd is not None:
            return fwd
        if total is not None and total % 2 == 0:
            return total // 2
        return None


def _norm_oneway(tags: dict[str, Any], highway: str) -> str:
    v = str(tags.get("oneway", "")).lower()
    if v in ("yes", "true", "1"):
        return "yes"
    if v in ("-1", "reverse"):
        return "-1"
    if v in ("no", "false", "0"):
        return "no"
    return "yes" if highway == "motorway" else "no"  # OSM implies oneway on motorways


def line_length_m(coords: list[tuple[float, float]]) -> float:
    lons, lats = zip(*coords, strict=True)
    return float(GEOD.line_length(lons, lats))


def midpoint_and_bearing(coords: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Point at half the geodesic length and the forward azimuth of that segment."""
    seg = []
    for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:], strict=True):
        az, _, d = GEOD.inv(lon1, lat1, lon2, lat2)
        seg.append((lon1, lat1, az, d))
    half = sum(s[3] for s in seg) / 2
    acc = 0.0
    for lon1, lat1, az, d in seg:
        if acc + d >= half and d > 0:
            lon, lat, _ = GEOD.fwd(lon1, lat1, az, half - acc)
            return float(lon), float(lat), float(az % 360)
        acc += d
    lon1, lat1, az, _ = seg[-1]
    return float(lon1), float(lat1), float(az % 360)


def sample_point(coords: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Midpoint and azimuth of the way's longest straight segment.

    OSM junctions, bridges and ramp gores sit at vertices, so the middle of the longest segment is
    the point farthest from them, and the road runs straight through the crop. (The calibration
    with the plain geodesic midpoint put a quarter of the samples on junctions or tunnels.)
    """
    best = (-1.0, 0.0, 0.0, 0.0)
    for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:], strict=True):
        az, _, d = GEOD.inv(lon1, lat1, lon2, lat2)
        if d > best[0]:
            best = (d, lon1, lat1, az)
    d, lon1, lat1, az = best
    lon, lat, _ = GEOD.fwd(lon1, lat1, az, d / 2)
    return float(lon), float(lat), float(az % 360)


def way_from_feature(feat: dict[str, Any]) -> Way | None:
    props = feat["properties"]
    highway = props.get("highway")
    if highway not in CLASSES or feat["geometry"]["type"] != "LineString":
        return None
    coords = [(float(x), float(y)) for x, y in feat["geometry"]["coordinates"]]
    if len(coords) < 2:
        return None
    oneway = _norm_oneway(props, highway)
    lon, lat, bearing = sample_point(coords)
    if oneway == "-1":
        bearing = (bearing + 180) % 360
    return Way(
        way_id=int(props["@id"]),
        highway=highway,
        oneway=oneway,
        lanes_tag=props.get("lanes"),
        lanes_forward=props.get("lanes:backward" if oneway == "-1" else "lanes:forward"),
        lanes_backward=props.get("lanes:forward" if oneway == "-1" else "lanes:backward"),
        name=props.get("name:en") or props.get("name"),
        length_m=round(line_length_m(coords), 1),
        lon=round(lon, 7),
        lat=round(lat, 7),
        bearing=round(bearing, 1),
    )


def read_geojsonseq(path: Path) -> list[Way]:
    ways = []
    with path.open() as fh:
        for line in fh:
            line = line.strip("\x1e \n")
            if line:
                way = way_from_feature(json.loads(line))
                if way is not None:
                    ways.append(way)
    return sorted(ways, key=lambda w: w.way_id)


def export_major_ways(pbf: Path, workdir: Path) -> Path:
    """osmium: keep major-road ways and export them as GeoJSON lines."""
    workdir.mkdir(parents=True, exist_ok=True)
    filtered = workdir / "major.osm.pbf"
    seq = workdir / "major.geojsonseq"
    filt = "w/highway=" + ",".join(CLASSES)
    subprocess.run(
        ["osmium", "tags-filter", str(pbf), filt, "-o", str(filtered), "--overwrite"], check=True
    )
    subprocess.run(
        [
            "osmium",
            "export",
            str(filtered),
            "-f",
            "geojsonseq",
            "-o",
            str(seq),
            "--overwrite",
            "--geometry-types=linestring",
            "-a",
            "type,id",
        ],
        check=True,
    )
    return seq


def inventory_summary(ways: list[Way]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cls in CLASSES:
        sel = [w for w in ways if w.highway == cls]
        untagged = [w for w in sel if not w.tagged]
        out[cls] = {
            "ways": len(sel),
            "untagged_ways": len(untagged),
            "untagged_ways_min_length": sum(w.length_m >= MIN_LENGTH_M for w in untagged),
            "km": round(sum(w.length_m for w in sel) / 1000, 1),
            "untagged_km": round(sum(w.length_m for w in untagged) / 1000, 1),
            "untagged_oneway_ways": sum(w.oneway != "no" for w in untagged),
        }
    return out


def load_inventory(path: Path | None = None) -> list[Way]:
    path = path or IMAGERY_DIR / "inventory.json"
    return [Way(**w) for w in json.loads(path.read_text())["ways"]]


# ---------------------------------------------------------------- selection


def stratified_calibration(
    ways: list[Way],
    n: int,
    seed: int,
    exclude: set[int],
    classes: tuple[str, ...] = CLASSES,
    max_per_road: int | None = None,
) -> list[Way]:
    """Tagged, comparable ways: n split evenly over classes (spare slots go to larger classes).

    ``max_per_road`` keeps at most that many ways of one named road per class (picked at random
    with the same seed), so one long, densely split road cannot dominate a set; unnamed ways are
    not capped.
    """
    pool = {
        cls: [
            w
            for w in ways
            if w.highway == cls
            and w.tagged
            and w.expected_lanes() is not None
            and w.length_m >= MIN_LENGTH_M
            and w.way_id not in exclude
        ]
        for cls in classes
    }
    rng = random.Random(seed)
    if max_per_road is not None:
        for cls in classes:
            shuffled = rng.sample(pool[cls], len(pool[cls]))
            seen: Counter[str] = Counter()
            capped = []
            for w in shuffled:
                if w.name is not None:
                    if seen[w.name] >= max_per_road:
                        continue
                    seen[w.name] += 1
                capped.append(w)
            pool[cls] = sorted(capped, key=lambda w: w.way_id)
    quota = dict.fromkeys(classes, 0)
    remaining = n
    while remaining > 0:
        open_cls = [c for c in classes if quota[c] < len(pool[c])]
        if not open_cls:
            break
        for c in sorted(open_cls, key=lambda c: (quota[c], -len(pool[c]))):
            if remaining == 0:
                break
            quota[c] += 1
            remaining -= 1
    picked: list[Way] = []
    for cls in classes:
        picked.extend(rng.sample(pool[cls], quota[cls]))
    return picked


def audit_priority(
    ways: list[Way], cap: int, exclude: set[int], classes: tuple[str, ...] = CLASSES
) -> list[Way]:
    """Untagged ways, motorway -> trunk -> primary -> secondary, longest first within a class."""
    order = {c: i for i, c in enumerate(CLASSES)}
    pool = [
        w
        for w in ways
        if not w.tagged
        and w.highway in classes
        and w.length_m >= MIN_LENGTH_M
        and w.way_id not in exclude
    ]
    pool.sort(key=lambda w: (order[w.highway], -w.length_m, w.way_id))
    return pool[:cap]


def human_fix_ways(fixes_dir: Path = FIXES_DIR) -> set[int]:
    """OSM ways already covered by reviewed (non-imagery) fixes: never audited over."""
    ways: set[int] = set()
    for path in sorted(fixes_dir.glob("*.yaml")):
        if path.name == FIXES_YAML.name:
            continue
        for fix in (yaml.safe_load(path.read_text()) or {}).get("fixes", []):
            if fix.get("osm_way_id") is not None:
                ways.add(int(fix["osm_way_id"]))
    return ways


# ---------------------------------------------------------------- tile maths


def global_pixel(lon: float, lat: float, z: int) -> tuple[float, float]:
    """Web Mercator pixel coordinates at zoom z (256 px tiles)."""
    n = TILE_PX * 2**z
    phi = math.radians(lat)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * n
    return x, y


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    x, y = global_pixel(lon, lat, z)
    return int(x // TILE_PX), int(y // TILE_PX)


def metres_per_pixel(lat: float, z: int) -> float:
    return EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / (TILE_PX * 2**z)


def tiles_for_crop(lon: float, lat: float, z: int, crop_px: int) -> tuple[range, range, int]:
    """Tile ranges covering a rotated crop of ``crop_px`` around the point, and its radius."""
    x, y = global_pixel(lon, lat, z)
    radius = math.ceil(crop_px / 2 * math.sqrt(2)) + 2
    xs = range(int((x - radius) // TILE_PX), int((x + radius) // TILE_PX) + 1)
    ys = range(int((y - radius) // TILE_PX), int((y + radius) // TILE_PX) + 1)
    return xs, ys, radius


def tile_source_string(z: int, x: int, y: int, date: str) -> str:
    return f"{TILE_SOURCE} tile z{z}/{x}/{y}, accessed {date}"


class TileCache:
    """One request at a time, cached under data/imagery/tiles/, polite delay, fixed User-Agent."""

    def __init__(self, root: Path = IMAGERY_DIR / "tiles", delay_s: float = REQUEST_DELAY_S):
        self.root = root
        self.delay_s = delay_s
        self.fetched = 0
        self._client: Any = None

    def path(self, z: int, x: int, y: int) -> Path:
        return self.root / str(z) / str(x) / f"{y}.jpg"

    def get(self, z: int, x: int, y: int) -> bytes:
        p = self.path(z, x, y)
        if p.exists():
            return p.read_bytes()
        import httpx

        if self._client is None:
            self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0)
        url = TILE_URL.format(z=z, x=x, y=y)
        for attempt in range(4):
            try:
                r = self._client.get(url)
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(2.0 * (attempt + 1))
        time.sleep(self.delay_s)
        self.fetched += 1
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        return r.content


# ---------------------------------------------------------------- crops


def caption_text(way: Way) -> list[str]:
    kind = "one-way carriageway" if way.oneway != "no" else "two-way road (count UP lanes only)"
    return [
        f"way {way.way_id} | {way.highway} | {kind} | bearing {way.bearing:.0f} deg",
        "count lanes travelling UP, on the carriageway under the red ticks only",
    ]


def make_crop(way: Way, cache: TileCache, out: Path, z: int = ZOOM, crop_px: int = CROP_PX) -> dict:
    """Stitch tiles, centre on the sample point, rotate travel direction to up, mark, caption."""
    from PIL import Image, ImageDraw, ImageFont

    xs, ys, radius = tiles_for_crop(way.lon, way.lat, z, crop_px)
    mosaic = Image.new("RGB", (len(xs) * TILE_PX, len(ys) * TILE_PX))
    import io

    for i, tx in enumerate(xs):
        for j, ty in enumerate(ys):
            tile = Image.open(io.BytesIO(cache.get(z, tx, ty))).convert("RGB")
            mosaic.paste(tile, (i * TILE_PX, j * TILE_PX))
    gx, gy = global_pixel(way.lon, way.lat, z)
    cx, cy = gx - xs.start * TILE_PX, gy - ys.start * TILE_PX
    box = (round(cx - radius), round(cy - radius), round(cx + radius), round(cy + radius))
    patch = mosaic.crop(box)
    # PIL rotates counter-clockwise; a road at bearing b (clockwise from north) then points up
    patch = patch.rotate(way.bearing, resample=Image.Resampling.BICUBIC)
    off = (patch.width - crop_px) // 2
    crop = patch.crop((off, off, off + crop_px, off + crop_px))
    crop = crop.resize((crop_px * OUT_SCALE, crop_px * OUT_SCALE), Image.Resampling.LANCZOS)
    size = crop_px * OUT_SCALE
    canvas = Image.new("RGB", (size, size + CAPTION_PX), "white")
    canvas.paste(crop, (0, 0))
    draw = ImageDraw.Draw(canvas)
    mid = size // 2
    tick = 34
    red = (255, 0, 0)
    for y0 in (0, size - tick):  # ticks on the sampled carriageway at the top and bottom edges
        draw.line([(mid, y0), (mid, y0 + tick)], fill=red, width=3)
    draw.polygon([(mid, 4), (mid - 10, 26), (mid + 10, 26)], outline=red)  # travel direction
    font = ImageFont.load_default(size=CAPTION_FONT_PX)
    for k, line in enumerate(caption_text(way)):
        draw.text((8, size + 4 + (CAPTION_FONT_PX + 6) * k), line, fill="black", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    tx, ty = tile_of(way.lon, way.lat, z)
    return {
        "file": out.name,
        "way_id": way.way_id,
        "z": z,
        "tile_x": tx,
        "tile_y": ty,
        "metres_per_px": round(metres_per_pixel(way.lat, z) / OUT_SCALE, 4),
    }


# ---------------------------------------------------------------- results and evaluation


def read_results(results_dir: Path) -> dict[int, dict[str, Any]]:
    """Analyst JSON lines (one object per crop) from every ``*.jsonl`` in the folder."""
    out: dict[int, dict[str, Any]] = {}
    for path in sorted(results_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("{"):
                rec = json.loads(line)
                out[int(rec["way_id"])] = rec
    return out


def precision_curve(pairs: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    """For each distinct confidence t: crops kept (conf >= t), precision and coverage."""
    n = len(pairs)
    curve = []
    for t in sorted({c for c, _ in pairs}):
        kept = [ok for c, ok in pairs if c >= t]
        curve.append(
            {
                "threshold": t,
                "kept": len(kept),
                "correct": sum(kept),
                "precision": round(sum(kept) / len(kept), 4),
                "coverage": round(len(kept) / n, 4) if n else 0.0,
            }
        )
    return curve


def choose_threshold(
    curve: list[dict[str, Any]],
    target: float = TARGET_PRECISION,
    min_kept: int = MIN_CALIBRATION_ACCEPTED,
) -> dict[str, Any] | None:
    """Lowest threshold (largest coverage) whose precision reaches the target with enough crops,
    and stays at or above it for every higher threshold that still keeps enough crops (so a
    lucky dip in the curve is not chosen)."""
    eligible = [r for r in curve if r["kept"] >= min_kept]
    for i, row in enumerate(eligible):  # ascending threshold = descending coverage
        if all(r["precision"] >= target for r in eligible[i:]):
            return row
    return None


def evaluate(
    ways: list[Way], results: dict[int, dict[str, Any]], target: float = TARGET_PRECISION
) -> dict[str, Any]:
    rows = []
    for w in ways:
        rec = results.get(w.way_id)
        truth = w.expected_lanes()
        pred = rec.get("lanes_marked_side") if rec else None
        conf = float(rec.get("confidence", 0.0)) if rec else 0.0
        rows.append(
            {
                "way_id": w.way_id,
                "highway": w.highway,
                "oneway": w.oneway,
                "truth": truth,
                "pred": pred,
                "confidence": conf,
                "correct": pred is not None and pred == truth,
                "within_one": pred is not None and truth is not None and abs(pred - truth) <= 1,
                "note": rec.get("note", "") if rec else "missing",
            }
        )
    pairs = [(r["confidence"], r["correct"]) for r in rows]
    curve = precision_curve(pairs)
    chosen = choose_threshold(curve, target)
    by_class: dict[str, Any] = {}
    for cls in CLASSES:
        sel = [r for r in rows if r["highway"] == cls]
        if not sel:
            continue
        kept = [r for r in sel if chosen and r["confidence"] >= chosen["threshold"]]
        confusion: dict[str, Counter[str]] = defaultdict(Counter)
        for r in sel:
            confusion[str(r["truth"])][str(r["pred"])] += 1
        by_class[cls] = {
            "n": len(sel),
            "agreement_all": round(sum(r["correct"] for r in sel) / len(sel), 4),
            "kept_at_threshold": len(kept),
            "agreement_at_threshold": (
                round(sum(r["correct"] for r in kept) / len(kept), 4) if kept else None
            ),
            "confusion_truth_to_pred": {t: dict(c) for t, c in sorted(confusion.items())},
        }
    n = len(rows)
    errors = Counter(
        (r["pred"] - r["truth"]) if r["pred"] is not None else "none"
        for r in rows
        if not r["correct"] and r["truth"] is not None
    )
    return {
        "n": n,
        "agreement_all": round(sum(r["correct"] for r in rows) / n, 4) if n else 0.0,
        "within_one_all": round(sum(r["within_one"] for r in rows) / n, 4) if n else 0.0,
        "target_precision": target,
        "min_kept": MIN_CALIBRATION_ACCEPTED,
        "threshold": chosen["threshold"] if chosen else None,
        "agreement_at_threshold": chosen["precision"] if chosen else None,
        "kept_at_threshold": chosen["kept"] if chosen else 0,
        "coverage_at_threshold": chosen["coverage"] if chosen else 0.0,
        "passed": chosen is not None,
        "error_pred_minus_truth": {str(k): v for k, v in sorted(errors.items(), key=str)},
        "by_class": by_class,
        "curve": curve,
        "rows": rows,
    }


def score_at(
    ways: list[Way], results: dict[int, dict[str, Any]], threshold: float
) -> dict[str, Any]:
    """Held-out check: precision and coverage of a threshold chosen on the calibration set."""
    rep = evaluate(ways, results)
    kept = [r for r in rep["rows"] if r["confidence"] >= threshold]
    correct = sum(r["correct"] for r in kept)
    return {
        "n": rep["n"],
        "threshold": threshold,
        "kept": len(kept),
        "correct": correct,
        "precision": round(correct / len(kept), 4) if kept else 0.0,
        "coverage": round(len(kept) / rep["n"], 4) if rep["n"] else 0.0,
        "agreement_all": rep["agreement_all"],
        "within_one_all": rep["within_one_all"],
        "by_class_kept": {
            cls: {
                "kept": sum(r["highway"] == cls for r in kept),
                "correct": sum(r["highway"] == cls and r["correct"] for r in kept),
            }
            for cls in CLASSES
        },
        "error_pred_minus_truth": rep["error_pred_minus_truth"],
        "curve": rep["curve"],
        "rows": rep["rows"],
    }


# ---------------------------------------------------------------- two independent reads (attempt 2)

READS = ("read-a", "read-b")  # independent analyst passes, different batch orderings
MIN_HOLDOUT_KEPT = 10  # the holdout must keep at least this many agreed crops to be scored


def combine_reads(a: dict[int, dict[str, Any]], b: dict[int, dict[str, Any]]) -> dict[int, dict]:
    """One record per way read in both passes. A count stands only if both reads give the same
    integer; its confidence is the lower of the two. Disagreements keep ``lanes_marked_side=None``
    and ``agree=False``."""
    out: dict[int, dict[str, Any]] = {}
    for way_id in sorted(set(a) & set(b)):
        la_, lb_ = a[way_id].get("lanes_marked_side"), b[way_id].get("lanes_marked_side")
        ca, cb = float(a[way_id].get("confidence", 0.0)), float(b[way_id].get("confidence", 0.0))
        agree = isinstance(la_, int) and la_ == lb_
        out[way_id] = {
            "way_id": way_id,
            "lanes_marked_side": la_ if agree else None,
            "confidence": min(ca, cb) if agree else 0.0,
            "agree": agree,
            "reads": [la_, lb_],
            "confidences": [ca, cb],
            "note": " | ".join(str(r.get("note", "")) for r in (a[way_id], b[way_id])),
        }
    return out


def evaluate_two_reads(
    ways: list[Way],
    a: dict[int, dict[str, Any]],
    b: dict[int, dict[str, Any]],
    threshold: float | None = None,
    target: float = TARGET_PRECISION,
    min_kept: int = MIN_CALIBRATION_ACCEPTED,
) -> dict[str, Any]:
    """Score agreed counts against the tags. Without ``threshold`` it is chosen on this set with
    the C-008 rule over agreed crops (confidence = the lower of the two reads); with one, the set
    is a holdout scored at that threshold."""
    combined = combine_reads(a, b)
    rows = []
    for w in ways:
        rec = combined.get(w.way_id)
        truth = w.expected_lanes()
        agree = bool(rec and rec["agree"])
        pred = rec["lanes_marked_side"] if rec else None
        rows.append(
            {
                "way_id": w.way_id,
                "highway": w.highway,
                "name": w.name,
                "truth": truth,
                "read_a": rec["reads"][0] if rec else None,
                "read_b": rec["reads"][1] if rec else None,
                "conf_a": rec["confidences"][0] if rec else None,
                "conf_b": rec["confidences"][1] if rec else None,
                "agree": agree,
                "pred": pred,
                "confidence": rec["confidence"] if rec else 0.0,
                "correct": agree and pred == truth,
                "note": rec["note"] if rec else "missing",
            }
        )
    agreed = [r for r in rows if r["agree"]]
    curve = precision_curve([(r["confidence"], r["correct"]) for r in agreed])
    single = {name: evaluate(ways, reads) for name, reads in zip(READS, (a, b), strict=True)}
    out: dict[str, Any] = {
        "n": len(rows),
        "read_agreement": round(len(agreed) / len(rows), 4) if rows else 0.0,
        "single_read_exact": {k: v["agreement_all"] for k, v in single.items()},
        "agreed_n": len(agreed),
        "agreed_precision_all": (
            round(sum(r["correct"] for r in agreed) / len(agreed), 4) if agreed else None
        ),
        "target_precision": target,
        "curve_agreed": curve,
    }
    if threshold is None:
        chosen = choose_threshold(curve, target, min_kept)
        out.update(
            {
                "min_kept": min_kept,
                "threshold": chosen["threshold"] if chosen else None,
                "precision_at_threshold": chosen["precision"] if chosen else None,
                "kept_at_threshold": chosen["kept"] if chosen else 0,
                "passed": chosen is not None,
            }
        )
        threshold = chosen["threshold"] if chosen else None
    else:
        kept = [r for r in agreed if r["confidence"] >= threshold]
        correct = sum(r["correct"] for r in kept)
        precision = round(correct / len(kept), 4) if kept else 0.0
        out.update(
            {
                "min_kept": MIN_HOLDOUT_KEPT,
                "threshold": threshold,
                "kept_at_threshold": len(kept),
                "correct_at_threshold": correct,
                "precision_at_threshold": precision,
                "passed": len(kept) >= MIN_HOLDOUT_KEPT and precision >= target,
            }
        )
    by_class: dict[str, Any] = {}
    for cls in CLASSES:
        sel = [r for r in rows if r["highway"] == cls]
        if not sel:
            continue
        kept = [
            r for r in sel if r["agree"] and threshold is not None and r["confidence"] >= threshold
        ]
        by_class[cls] = {
            "n": len(sel),
            "agreed": sum(r["agree"] for r in sel),
            "agreed_correct": sum(r["correct"] for r in sel),
            "kept_at_threshold": len(kept),
            "correct_at_threshold": sum(r["correct"] for r in kept),
        }
    out["by_class"] = by_class
    out["coverage_at_threshold"] = round(out["kept_at_threshold"] / len(rows), 4) if rows else 0.0
    out["rows"] = rows
    return out


def read_folders(
    set_dir: Path, way_ids: list[int], batch: int, seed: int
) -> dict[str, list[list[int]]]:
    """Copy the crops (PNG only, nothing else) into one folder tree per read: read-a in set
    order, read-b shuffled with ``seed``, so the two passes see different batch neighbours and
    the analyst cannot reach ways.json or earlier results from its folder."""
    import shutil

    src = {p.stem: p for p in (set_dir / "crops").rglob("*.png")}
    orders = {READS[0]: list(way_ids), READS[1]: random.Random(seed).sample(way_ids, len(way_ids))}
    layout: dict[str, list[list[int]]] = {}
    for name, order in orders.items():
        root = set_dir / "reads" / name
        if root.exists():
            shutil.rmtree(root)
        batches = [order[i : i + batch] for i in range(0, len(order), batch)]
        for k, ids in enumerate(batches):
            folder = root / f"batch-{k:03d}"
            folder.mkdir(parents=True)
            for way_id in ids:
                shutil.copy2(src[str(way_id)], folder / f"{way_id}.png")
        layout[name] = batches
    return layout


def analyst_records(text: str) -> list[dict[str, Any]]:
    """JSON objects (one per line) with a ``way_id`` from an analyst reply."""
    recs = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        if line.startswith("{") and '"way_id"' in line:
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


# ---------------------------------------------------------------- fix list


def way_default_lanes(net: Path, way_ids: set[int]) -> dict[int, int]:
    """Modal lane count of the SUMO edges built from each OSM way (streaming parse)."""
    import xml.etree.ElementTree as ET

    wanted = {str(w) for w in way_ids}
    counts: dict[int, Counter[int]] = defaultdict(Counter)
    current_lanes = 0
    current_ways: list[str] = []
    for event, elem in ET.iterparse(net, events=("start", "end")):
        if event == "start" and elem.tag == "edge":
            current_lanes, current_ways = 0, []
        elif event == "end" and elem.tag == "lane":
            current_lanes += 1
        elif event == "end" and elem.tag == "param" and elem.get("key") == "origId":
            if not current_ways:
                current_ways = [w for w in (elem.get("value") or "").split() if w in wanted]
        elif event == "end" and elem.tag == "edge":
            if elem.get("function") != "internal":
                for w in current_ways:
                    counts[int(w)][current_lanes] += 1
            elem.clear()
    return {w: c.most_common(1)[0][0] for w, c in counts.items()}


def fix_entries(
    ways: list[Way],
    results: dict[int, dict[str, Any]],
    manifest: dict[int, dict[str, Any]],
    threshold: float,
    defaults: dict[int, int],
    date: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Accepted imagery counts -> fix entries. ``lanes_min`` when the count raises the built
    default (keeps lanes netconvert adds at ramps), ``lanes`` when it lowers it, none if equal."""
    entries: list[dict[str, Any]] = []
    tally: Counter[str] = Counter()
    for w in ways:
        rec = results.get(w.way_id)
        if rec is None:
            tally["no_result"] += 1
            continue
        lanes = rec.get("lanes_marked_side")
        conf = float(rec.get("confidence", 0.0))
        if rec.get("agree") is False:
            tally["reads_disagree"] += 1
            continue
        if lanes is None or conf < threshold:
            tally["below_threshold"] += 1
            continue
        if not isinstance(lanes, int) or lanes < 1:
            tally["invalid"] += 1
            continue
        default = defaults.get(w.way_id)
        if default is None:
            tally["not_in_network"] += 1
            continue
        if lanes == default:
            tally["confirms_default"] += 1
            continue
        tally["raises" if lanes > default else "lowers"] += 1
        m = manifest[w.way_id]
        reads = f"; {len(rec['reads'])} independent reads agree" if "reads" in rec else ""
        entries.append(
            {
                "id": f"IMG-{w.way_id}",
                "osm_way_id": w.way_id,
                "field": "lanes_min" if lanes > default else "lanes",
                "value": lanes,
                "direction": "both",
                "reason": (
                    f"Untagged {w.highway} ({'one-way' if w.oneway != 'no' else 'two-way'}, "
                    f"{w.length_m:.0f} m); imagery shows {lanes} lane(s) per direction at the "
                    f"mid-segment sample, network default {default}{reads}"
                ),
                "date": date,
                "author": "lane-audit",
                "confidence": round(conf, 2),
                "method": "imagery-analyst",
                "source": tile_source_string(m["z"], m["tile_x"], m["tile_y"], m["accessed"]),
                "osm_note": "Imagery-derived; not upstreamed to OSM",
            }
        )
    return entries, dict(tally)


def write_fix_yaml(entries: list[dict[str, Any]], header: str, path: Path = FIXES_YAML) -> None:
    body = yaml.safe_dump({"fixes": entries}, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body)


# ---------------------------------------------------------------- CLI

app = typer.Typer(add_completion=False, help=__doc__)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _set_dir(name: str) -> Path:
    return IMAGERY_DIR / name


@app.command()
def inventory(
    pbf: Path = typer.Option(CLIP_PBF, help="Jeddah clip (osmium PBF)"),
    out: Path = typer.Option(IMAGERY_DIR / "inventory.json"),
) -> None:
    """List motorway/trunk/primary/secondary ways with length, sample point and bearing."""
    seq = export_major_ways(pbf, out.parent)
    ways = read_geojsonseq(seq)
    summary = inventory_summary(ways)
    _write_json(
        out,
        {
            "source": rel(pbf),
            "source_hash": file_hash(pbf),
            "min_length_m": MIN_LENGTH_M,
            "summary": summary,
            "ways": [asdict(w) for w in ways],
        },
    )
    typer.echo(json.dumps(summary, indent=2))


@app.command("sample-calibration")
def sample_calibration(
    n: int = typer.Option(40),
    seed: int = typer.Option(1),
    set_name: str = typer.Option("calibration", "--set", help="calibration or holdout"),
    exclude_set: list[str] = typer.Option([], help="sets whose ways must not be re-used"),
    classes: str = typer.Option(",".join(CLASSES), help="comma-separated highway classes"),
    max_per_road: int | None = typer.Option(None, help="cap ways per named road and class"),
    inv: Path | None = None,
) -> None:
    """Stratified sample of tagged ways for the blind calibration (or its disjoint holdout)."""
    exclude = human_fix_ways()
    for other in exclude_set:
        exclude |= {w.way_id for w in _set_ways(other)}
    cls = tuple(c for c in CLASSES if c in classes.split(","))
    ways = stratified_calibration(load_inventory(inv), n, seed, exclude, cls, max_per_road)
    _write_json(
        _set_dir(set_name) / "ways.json",
        {
            "seed": seed,
            "excluded_sets": exclude_set,
            "classes": list(cls),
            "max_per_road": max_per_road,
            "ways": [asdict(w) for w in ways],
        },
    )
    typer.echo(f"{len(ways)} {set_name} ways: {dict(Counter(w.highway for w in ways))}")


@app.command("select-audit")
def select_audit(
    cap: int = typer.Option(1500),
    set_name: str = typer.Option("audit", "--set"),
    classes: str = typer.Option(",".join(CLASSES), help="comma-separated highway classes"),
    inv: Path | None = None,
) -> None:
    """Untagged ways in priority order, capped."""
    cls = tuple(c for c in CLASSES if c in classes.split(","))
    ways = audit_priority(load_inventory(inv), cap, human_fix_ways(), cls)
    _write_json(
        _set_dir(set_name) / "ways.json",
        {"cap": cap, "classes": list(cls), "ways": [asdict(w) for w in ways]},
    )
    typer.echo(f"{len(ways)} audit ways: {dict(Counter(w.highway for w in ways))}")


def _set_ways(name: str) -> list[Way]:
    return [Way(**w) for w in json.loads((_set_dir(name) / "ways.json").read_text())["ways"]]


@app.command()
def crops(
    set_name: str = typer.Option("calibration", "--set"),
    batch: int = typer.Option(20, help="crops per analyst batch folder"),
    limit: int | None = typer.Option(None),
) -> None:
    """Fetch tiles and write captioned crops in batch folders (needs Pillow)."""
    ways = _set_ways(set_name)[:limit]
    cache = TileCache()
    manifest_path = _set_dir(set_name) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    today = dt.date.today().isoformat()
    t0 = time.perf_counter()
    for i, w in enumerate(ways):
        out = _set_dir(set_name) / "crops" / f"batch-{i // batch:03d}" / f"{w.way_id}.png"
        if str(w.way_id) in manifest and out.exists():
            continue
        rec = make_crop(w, cache, out)
        rec["accessed"] = today
        rec["batch"] = i // batch
        manifest[str(w.way_id)] = rec
        if i % 20 == 19:
            _write_json(manifest_path, manifest)
            typer.echo(f"{i + 1}/{len(ways)} crops, {cache.fetched} tiles fetched")
    _write_json(manifest_path, manifest)
    typer.echo(
        f"{len(ways)} crops in {time.perf_counter() - t0:.0f} s, {cache.fetched} tiles fetched"
    )


@app.command("evaluate")
def evaluate_cmd(out: Path = typer.Option(EVAL_JSON)) -> None:
    """Score the blind calibration counts against the OSM tags; choose the threshold."""
    ways = _set_ways("calibration")
    results = read_results(_set_dir("calibration") / "results")
    report = evaluate(ways, results)
    if (_set_dir("holdout") / "ways.json").exists() and report["threshold"] is not None:
        hold = score_at(
            _set_ways("holdout"), read_results(_set_dir("holdout") / "results"), report["threshold"]
        )
        report["holdout"] = hold
        report["passed"] = bool(report["passed"] and hold["precision"] >= TARGET_PRECISION)
        pooled = [(r["confidence"], r["correct"]) for r in report["rows"] + hold["rows"]]
        n_pooled = len(pooled)
        report["pooled"] = {
            "n": n_pooled,
            "agreement_all": round(sum(ok for _, ok in pooled) / n_pooled, 4),
            "within_one_all": round(
                sum(r["within_one"] for r in report["rows"] + hold["rows"]) / n_pooled, 4
            ),
            "threshold_if_chosen_on_pooled": (choose_threshold(precision_curve(pooled)) or {}).get(
                "threshold"
            ),
            "curve": precision_curve(pooled),
        }
    report = {
        "generated": dt.date.today().isoformat(),
        "imagery": f"{TILE_SOURCE}, zoom {ZOOM}, {CROP_PX} px crops upscaled {OUT_SCALE}x",
        "method": "imagery-analyst subagent, blind (caption has no lane tag)",
        "truth": "OSM lanes tags (oneway: lanes; two-way: lanes:forward or lanes/2)",
        **report,
    }
    _write_json(out, report)
    typer.echo(
        f"agreement {report['agreement_all']:.1%} over {report['n']} crops; threshold "
        f"{report['threshold']} -> precision {report['agreement_at_threshold']} on "
        f"{report['kept_at_threshold']} crops; passed={report['passed']}"
    )


@app.command("subset-set")
def subset_set(
    set_name: str = typer.Option(..., "--set"),
    from_set: list[str] = typer.Option(..., help="existing sets to take ways from"),
    classes: str = typer.Option("motorway,trunk"),
) -> None:
    """A new set from the ways of earlier sets, restricted to some classes (re-read afresh)."""
    cls = classes.split(",")
    ways = [w for name in from_set for w in _set_ways(name) if w.highway in cls]
    _write_json(
        _set_dir(set_name) / "ways.json",
        {"from_sets": from_set, "classes": cls, "ways": [asdict(w) for w in ways]},
    )
    typer.echo(f"{len(ways)} {set_name} ways: {dict(Counter(w.highway for w in ways))}")


@app.command("prepare-reads")
def prepare_reads(
    set_name: str = typer.Option(..., "--set"),
    batch: int = typer.Option(20),
    seed: int = typer.Option(7, help="shuffle seed for the second read's ordering"),
) -> None:
    """Copy crops into reads/read-a and reads/read-b batch folders (crops only)."""
    ids = [w.way_id for w in _set_ways(set_name)]
    layout = read_folders(_set_dir(set_name), ids, batch, seed)
    _write_json(_set_dir(set_name) / "reads" / "layout.json", {"seed": seed, **layout})
    typer.echo(f"{set_name}: {len(ids)} crops x {len(layout)} reads, {batch} per batch")


@app.command("collect-reads")
def collect_reads(
    transcripts: Path = typer.Option(..., help="folder of subagent transcript *.jsonl files"),
) -> None:
    """Save analyst replies as results/<read>/<batch>.jsonl. Each analyst prompt carries a line
    ``READ-TAG <set>/<read>/<batch>``; its final reply is one JSON object per crop."""
    saved = 0
    for path in sorted(transcripts.glob("*.jsonl")):
        tag, last_text = None, ""
        for line in path.read_text().splitlines():
            msg = json.loads(line).get("message") or {}
            content = msg.get("content")
            texts = (
                [content]
                if isinstance(content, str)
                else [c.get("text", "") for c in content or [] if c.get("type") == "text"]
            )
            for text in texts:
                if tag is None and msg.get("role") == "user" and "READ-TAG " in text:
                    tag = text.split("READ-TAG ", 1)[1].split()[0]
                elif msg.get("role") == "assistant" and analyst_records(text):
                    last_text = text
        if tag is None or not last_text:
            continue
        set_name, read, batch = tag.split("/")
        expected = {p.stem for p in (_set_dir(set_name) / "reads" / read / batch).glob("*.png")}
        recs = [r for r in analyst_records(last_text) if str(r["way_id"]) in expected]
        out = _set_dir(set_name) / "results" / read / f"{batch}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        saved += 1
        missing = len(expected) - len(recs)
        typer.echo(f"{tag}: {len(recs)} records" + (f", {missing} MISSING" if missing else ""))
    typer.echo(f"{saved} batches saved")


def _reads(set_name: str) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    a, b = (read_results(_set_dir(set_name) / "results" / r) for r in READS)
    return a, b


@app.command("evaluate-two-reads")
def evaluate_two_reads_cmd(
    calibration_set: str = typer.Option("v2-calibration"),
    holdout_set: str = typer.Option("v2-holdout"),
    audit_set: str = typer.Option("v2-audit"),
    sensitivity_exclude_road: str | None = typer.Option(
        None, help="also score the calibration without this road (information only)"
    ),
    out: Path = typer.Option(EVAL_JSON),
) -> None:
    """Attempt 2: threshold on agreed reads of the calibration set, checked on a fresh holdout."""
    cal = evaluate_two_reads(_set_ways(calibration_set), *_reads(calibration_set))
    report: dict[str, Any] = {
        "generated": dt.date.today().isoformat(),
        "protocol": "two-reads",
        "imagery": f"{TILE_SOURCE}, zoom {ZOOM}, {CROP_PX} px crops upscaled {OUT_SCALE}x",
        "method": (
            "imagery-analyst subagent, two independent blind reads per crop (different batch "
            "orderings, folders with crops only); a count is accepted only if both reads agree "
            "and the lower confidence is at or above the threshold"
        ),
        "truth": "OSM lanes tags (oneway: lanes; two-way: lanes:forward or lanes/2)",
        "calibration_set": calibration_set,
        "holdout_set": holdout_set,
        "audit_set": audit_set,
        "calibration": cal,
        "threshold": cal["threshold"],
    }
    hold = None
    if cal["threshold"] is not None and (_set_dir(holdout_set) / "ways.json").exists():
        hold = evaluate_two_reads(
            _set_ways(holdout_set), *_reads(holdout_set), threshold=cal["threshold"]
        )
        report["holdout"] = hold
    elif (_set_dir(holdout_set) / "results").exists():
        # No threshold from calibration: the gate has failed. The holdout is still scored on
        # every agreed count (threshold 0) and recorded for information; it cannot pass.
        info = evaluate_two_reads(_set_ways(holdout_set), *_reads(holdout_set), threshold=0.0)
        info["passed"] = False
        info["threshold"] = None  # no threshold was chosen; precision covers all agreed counts
        report["holdout_info_no_threshold"] = info
    if sensitivity_exclude_road:
        # Information only, never used for the gate: the calibration without one named road.
        keep = [w for w in _set_ways(calibration_set) if w.name != sensitivity_exclude_road]
        sens = evaluate_two_reads(keep, *_reads(calibration_set))
        sens.pop("rows")
        sens["excluded_road"] = sensitivity_exclude_road
        report["sensitivity_calibration_without_road"] = sens
    report["passed"] = bool(cal["passed"] and hold is not None and hold["passed"])
    report["agreement_at_threshold"] = hold["precision_at_threshold"] if hold else None
    report["kept_at_threshold"] = hold["kept_at_threshold"] if hold else 0
    _write_json(out, report)
    typer.echo(
        f"calibration: reads agree {cal['read_agreement']:.0%}, threshold {cal['threshold']} -> "
        f"{cal['precision_at_threshold']} on {cal['kept_at_threshold']}; holdout: "
        + (
            f"{hold['precision_at_threshold']} on {hold['kept_at_threshold']} "
            f"(agree {hold['read_agreement']:.0%})"
            if hold
            else "not scored"
        )
        + f"; passed={report['passed']}"
    )


@app.command("write-fixes")
def write_fixes(
    net: Path = typer.Option(RAW_NET, help="network giving the default lanes per way"),
    eval_json: Path = typer.Option(EVAL_JSON),
) -> None:
    """Accepted audit counts -> data/osm/fixes/imagery-lanes.yaml."""
    report = json.loads(eval_json.read_text())
    if not report.get("passed"):
        raise typer.BadParameter("calibration did not pass; no audit fixes are written")
    threshold = float(report["threshold"])
    audit_set = report.get("audit_set", "audit")
    ways = _set_ways(audit_set)
    if report.get("protocol") == "two-reads":
        results = combine_reads(*_reads(audit_set))
    else:
        results = read_results(_set_dir(audit_set) / "results")
    manifest = {
        int(k): v
        for k, v in json.loads((_set_dir(audit_set) / "manifest.json").read_text()).items()
    }
    defaults = way_default_lanes(net, {w.way_id for w in ways})
    entries, tally = fix_entries(
        ways, results, manifest, threshold, defaults, dt.date.today().isoformat()
    )
    header = (
        "# Imagery-derived lane counts (python -m sim.network.lane_audit write-fixes).\n"
        "# NOT human-reviewed: kept separate from the reviewed fix files. Counts are lanes per\n"
        f"# direction read by the imagery-analyst subagent from {TILE_SOURCE} crops"
        f" (zoom {ZOOM}),\n"
        f"# accepted at confidence >= {threshold} (calibration: data/osm/fixes/imagery-eval.json,\n"
        f"# precision {report['agreement_at_threshold']} on {report['kept_at_threshold']} tagged "
        "ways).\n"
        "# Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community.\n"
        f"# Audit tally: {json.dumps(tally, sort_keys=True)}\n"
    )
    write_fix_yaml(entries, header)
    typer.echo(f"{len(entries)} fixes -> {rel(FIXES_YAML)}; tally {tally}")


@app.command()
def rebuild(
    raw: Path = typer.Option(RAW_NET, help="netconvert output before any fix"),
    out: Path = typer.Option(LANES_NET),
    fixes_dir: Path = typer.Option(FIXES_DIR),
) -> None:
    """Apply every fix (reviewed + imagery) to the raw city net; write a new network name."""
    from sim.network.fixes import apply_fixes, load_fixes
    from sim.network.netinfo import net_stats

    if out.resolve() == (REPO_ROOT / "data" / "jeddah" / "jeddah.net.xml").resolve():
        raise typer.BadParameter("refusing to overwrite the shared jeddah.net.xml")
    t0 = time.perf_counter()
    log = REPO_ROOT / "logs" / f"lane_audit-rebuild-{out.stem.split('.')[1]}.log"
    resolved = apply_fixes(raw, out, fixes_dir, log=log)
    stats = net_stats(out)
    fixes = load_fixes(fixes_dir)
    meta = {
        "built_by": "python -m sim.network.lane_audit rebuild",
        "raw_net": rel(raw),
        "raw_net_hash": file_hash(raw),
        "fixes_dir": rel(fixes_dir),
        "fixes_total": len(fixes),
        "fixes_imagery": sum(f.method == "imagery-analyst" for f in fixes),
        "fixes_hash": file_hash(FIXES_YAML) if FIXES_YAML.exists() else None,
        "edges_changed": sum(len(v) for v in resolved.values()),
        "sumo_version": sumo_version(),
        "network": stats.as_dict(),
        "build_seconds": round(time.perf_counter() - t0, 1),
    }
    meta_path = out.with_name(out.name.replace(".net.xml", ".build.json"))
    _write_json(meta_path, meta)
    typer.echo(json.dumps(meta, indent=2))


if __name__ == "__main__":
    app()
