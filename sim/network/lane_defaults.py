"""Evidence-based lane and speed defaults for untagged Jeddah roads (network v2, A-net-301/302).

The SUMO typemap gives an OSM way without a `lanes` tag the class default (secondary 1 lane per
direction at 100 km/h). In Jeddah most major ways are untagged (docs/network-qa.md). This module
replaces those defaults with what the TAGGED ways of the same class and direction say, measured on
the same clip:

1. `stats`: for every highway class x oneway, the km-weighted distribution of lanes per direction
   (p25/p50/p75) and of `maxspeed` over the ways that carry the tag -> a JSON evidence file.
2. `tag`: a reproducible pre-pass over the clipped OSM XML that adds `lanes` (and `maxspeed`) to
   ways of the covered classes that lack them, using the class x oneway medians. Each added tag is
   marked with `traffictwin:defaults=<assumption id>`. Tagged ways are never changed.
3. `crosscheck`: agreement of the defaults with the lane-audit held-out ways (OSM tags as truth,
   plus the two blind imagery reads where they agree). Reads only the existing results; it makes
   no imagery calls.

    python -m sim.network.lane_defaults stats data/osm/jeddah.osm.pbf \
        --out sim/network/types/jeddah-lanes.json
    python -m sim.network.lane_defaults tag data/osm/jeddah.osm.gz data/osm/jeddah.v2.osm.gz \
        --stats sim/network/types/jeddah-lanes.json
    python -m sim.network.lane_defaults crosscheck --stats sim/network/types/jeddah-lanes.json \
        --imagery-dir ../trackC/data/imagery
"""

from __future__ import annotations

import gzip
import io
import json
import math
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import numpy as np
import typer
from pyproj import Geod

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, file_hash, rel, run_cmd

# classes whose untagged ways get the measured defaults; minor roads keep the SUMO typemap
APPLY_CLASSES = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
)
# classes measured (and reported) in the evidence file
STAT_CLASSES = (*APPLY_CLASSES, "unclassified", "residential")
# OSM: motorways and roundabouts are oneway unless tagged otherwise
IMPLIED_ONEWAY = {"motorway", "motorway_link"}
# Method threshold (not a behavioural value): a class x oneway median needs this much tagged
# evidence; recorded in the evidence file and overridable with `stats --min-tagged-km`.
MIN_TAGGED_KM = 5.0
ASSUMPTION_LANES = "A-net-301"
ASSUMPTION_SPEED = "A-net-302"

GEOD = Geod(ellps="WGS84")
_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph)?\s*$")


# ---------------------------------------------------------------------------- tag parsing


def parse_int(value: str | None) -> int | None:
    """`lanes`-style tag -> int; '2;3' takes the first value; anything else -> None."""
    if value is None:
        return None
    head = value.split(";")[0].strip()
    return int(head) if head.isdigit() and int(head) > 0 else None


def parse_speed_kmh(value: str | None) -> float | None:
    """`maxspeed` -> km/h ('60', '40 mph'); 'none', 'signals', 'SA:urban' -> None."""
    if value is None:
        return None
    m = _NUM.match(value.split(";")[0])
    if not m:
        return None
    v = float(m.group(1))
    return v * 1.609344 if m.group(2) else v


def is_oneway(tags: dict[str, str]) -> bool:
    ow = tags.get("oneway")
    if ow in ("yes", "1", "true", "-1", "reversible"):
        return True
    if ow in ("no", "0", "false"):
        return False
    return tags.get("highway") in IMPLIED_ONEWAY or tags.get("junction") in (
        "roundabout",
        "circular",
    )


def lanes_per_direction(tags: dict[str, str]) -> list[float]:
    """Lanes per travel direction from the tags ([] if untagged). Two-way: forward/backward if
    given, else lanes/2 for each direction (odd totals give x.5, kept as measured)."""
    if is_oneway(tags):
        n = parse_int(tags.get("lanes"))
        return [float(n)] if n else []
    fwd, bwd = parse_int(tags.get("lanes:forward")), parse_int(tags.get("lanes:backward"))
    if fwd and bwd:
        return [float(fwd), float(bwd)]
    n = parse_int(tags.get("lanes"))
    if not n:
        return []
    if fwd and n > fwd:
        return [float(fwd), float(n - fwd)]
    if bwd and n > bwd:
        return [float(n - bwd), float(bwd)]
    return [n / 2.0, n / 2.0]


def has_lanes_tag(tags: dict[str, str]) -> bool:
    return any(k in tags for k in ("lanes", "lanes:forward", "lanes:backward"))


# ---------------------------------------------------------------------------- statistics


@dataclass
class WayRecord:
    way_id: int
    highway: str
    oneway: bool
    km: float
    lanes_dir: list[float]
    speed_kmh: float | None


def _length_km(coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    lons, lats = zip(*coords, strict=True)
    return float(GEOD.line_length(lons, lats)) / 1000.0


def read_ways(seq: Path) -> Iterator[WayRecord]:
    """WayRecords from an osmium GeoJSONSeq export of highway ways."""
    with seq.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            props = feat.get("properties", {})
            hw = props.get("highway")
            if hw not in STAT_CLASSES or feat["geometry"]["type"] != "LineString":
                continue
            tags = {k: str(v) for k, v in props.items() if not k.startswith("@")}
            yield WayRecord(
                way_id=int(props.get("@id", 0)),
                highway=hw,
                oneway=is_oneway(tags),
                km=_length_km(feat["geometry"]["coordinates"]),
                lanes_dir=lanes_per_direction(tags),
                speed_kmh=parse_speed_kmh(tags.get("maxspeed")),
            )


def export_highways(pbf: Path, out: Path) -> None:
    """osmium: highway ways of the measured classes -> GeoJSONSeq with all tags."""
    with tempfile.TemporaryDirectory() as tmp:
        filtered = Path(tmp) / "highways.osm.pbf"
        run_cmd(
            [
                "osmium",
                "tags-filter",
                str(pbf),
                "w/highway=" + ",".join(STAT_CLASSES),
                "-o",
                str(filtered),
                "--overwrite",
            ]
        )
        run_cmd(
            [
                "osmium",
                "export",
                str(filtered),
                "-f",
                "geojsonseq",
                "--geometry-types",
                "linestring",
                "-a",
                "id",
                "-o",
                str(out),
                "--overwrite",
            ]
        )


def weighted_quantiles(values: Iterable[float], weights: Iterable[float], qs: Iterable[float]):
    """Weighted quantiles (lower interpolation: the value at which the cumulative weight first
    reaches q), so the result is always an observed value."""
    v = np.asarray(list(values), dtype=float)
    w = np.asarray(list(weights), dtype=float)
    order = np.argsort(v, kind="stable")
    v, w = v[order], w[order]
    cum = np.cumsum(w) / w.sum()
    return [float(v[min(np.searchsorted(cum, q - 1e-12), len(v) - 1)]) for q in qs]


def class_stats(records: Iterable[WayRecord]) -> dict[str, dict[str, Any]]:
    """Per '<class>|oneway' / '<class>|twoway': km, tagged km, lanes p25/p50/p75, speed p50."""
    groups: dict[str, list[WayRecord]] = {}
    for r in records:
        groups.setdefault(f"{r.highway}|{'oneway' if r.oneway else 'twoway'}", []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(groups):
        rs = groups[key]
        km = sum(r.km for r in rs)
        lane_vals: list[float] = []
        lane_w: list[float] = []
        for r in rs:
            for lpd in r.lanes_dir:
                lane_vals.append(lpd)
                lane_w.append(r.km)
        tagged_km = sum(r.km for r in rs if r.lanes_dir)
        sp = [(r.speed_kmh, r.km) for r in rs if r.speed_kmh]
        row: dict[str, Any] = {
            "ways": len(rs),
            "km": round(km, 1),
            "lanes_tagged_ways": sum(1 for r in rs if r.lanes_dir),
            "lanes_tagged_km": round(tagged_km, 1),
            "lanes_tagged_share": round(tagged_km / km, 3) if km else 0.0,
            "maxspeed_tagged_km": round(sum(w for _, w in sp), 1),
        }
        if lane_vals and sum(lane_w) > 0:
            p25, p50, p75 = weighted_quantiles(lane_vals, lane_w, (0.25, 0.5, 0.75))
            row.update(lanes_p25=p25, lanes_p50=p50, lanes_p75=p75)
        if sp and sum(w for _, w in sp) > 0:
            s25, s50, s75 = weighted_quantiles(
                [s for s, _ in sp], [w for _, w in sp], (0.25, 0.5, 0.75)
            )
            row.update(maxspeed_p25=round(s25), maxspeed_p50=round(s50), maxspeed_p75=round(s75))
        out[key] = row
    return out


def derive_defaults(
    stats: dict[str, dict[str, Any]], min_tagged_km: float = MIN_TAGGED_KM
) -> dict[str, dict[str, Any]]:
    """Default lanes per direction and maxspeed per '<class>|oneway|twoway' for APPLY_CLASSES.

    Median of the tagged ways of that class x direction if they cover >= min_tagged_km. Otherwise
    maxspeed falls back to the class's other direction; lanes do not (a two-way way is an undivided
    road, so the dual-carriageway median does not transfer): the SUMO typemap stays. Lanes round
    half up (1.5 -> 2), never below 1."""
    out: dict[str, dict[str, Any]] = {}
    for cls in APPLY_CLASSES:
        for d, other in (("oneway", "twoway"), ("twoway", "oneway")):
            key = f"{cls}|{d}"
            if key not in stats:
                continue
            row: dict[str, Any] = {}
            for field, val, km_field in (
                ("lanes", "lanes_p50", "lanes_tagged_km"),
                ("maxspeed", "maxspeed_p50", "maxspeed_tagged_km"),
            ):
                sources = [(key, "class x direction")]
                if field == "maxspeed":
                    sources.append((f"{cls}|{other}", "class"))
                for src_key, src in sources:
                    s = stats.get(src_key, {})
                    if s.get(km_field, 0.0) >= min_tagged_km and val in s:
                        v = s[val]
                        row[field] = max(1, math.floor(v + 0.5)) if field == "lanes" else int(v)
                        row[f"{field}_from"] = f"{src_key} ({src}, {s[km_field]} km tagged)"
                        break
            if row:
                out[key] = row
    return out


def _relpath(path: Path) -> str:
    """Repo-relative path without resolving symlinks (data/osm/* link to the main checkout)."""
    try:
        return str(Path(path).absolute().relative_to(REPO_ROOT))
    except ValueError:
        return rel(path)


def build_stats(pbf: Path, min_tagged_km: float = MIN_TAGGED_KM) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        seq = Path(tmp) / "highways.geojsonseq"
        export_highways(pbf, seq)
        records = list(read_ways(seq))
    stats = class_stats(records)
    return {
        "label": SYNTHETIC_LABEL,
        "source": _relpath(pbf),
        "source_hash": file_hash(pbf),
        "method": (
            "km-weighted quantiles of lanes per direction (oneway: lanes; two-way: "
            "lanes:forward/backward, else lanes/2) and maxspeed over OSM ways that carry the tag, "
            f"per class x oneway; defaults = median if >= {min_tagged_km} km tagged"
        ),
        "min_tagged_km": min_tagged_km,
        "assumptions": {"lanes": ASSUMPTION_LANES, "maxspeed": ASSUMPTION_SPEED},
        "stats": stats,
        "defaults": derive_defaults(stats, min_tagged_km),
    }


# ---------------------------------------------------------------------------- OSM pre-pass

_WAY_OPEN = re.compile(r"^\s*<way\b")
_WAY_SELF_CLOSED = re.compile(r"/>\s*$")
_TAG = re.compile(r'<tag k="([^"]*)" v="([^"]*)"\s*/>')


class _ClosingText(io.TextIOWrapper):
    """Text wrapper over a GzipFile that also closes the underlying file object."""

    def __init__(self, gzf: gzip.GzipFile, raw: IO[bytes]) -> None:
        super().__init__(gzf, encoding="utf-8")
        self._raw = raw

    def close(self) -> None:
        super().close()
        self._raw.close()


def _open_text(path: Path, mode: str, gz: bool | None = None) -> IO[str]:
    if path.suffix == ".gz" if gz is None else gz:
        if mode == "w":  # mtime 0 and no file name in the header: byte-identical reruns
            raw = path.open("wb")
            gzf = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
            return _ClosingText(gzf, raw)
        return gzip.open(path, mode + "t", encoding="utf-8")  # type: ignore[return-value]
    return path.open(mode, encoding="utf-8")


def added_tags(tags: dict[str, str], defaults: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The tags the pre-pass adds to one way (empty if none)."""
    hw = tags.get("highway")
    if hw not in APPLY_CLASSES:
        return {}
    oneway = is_oneway(tags)
    d = defaults.get(f"{hw}|{'oneway' if oneway else 'twoway'}")
    if not d:
        return {}
    add: dict[str, str] = {}
    marks = []
    if "lanes" in d and not has_lanes_tag(tags):
        add["lanes"] = str(d["lanes"] if oneway else 2 * d["lanes"])
        marks.append(ASSUMPTION_LANES)
    if "maxspeed" in d and "maxspeed" not in tags:
        add["maxspeed"] = str(d["maxspeed"])
        marks.append(ASSUMPTION_SPEED)
    if marks:
        add["traffictwin:defaults"] = ";".join(marks)
    return add


def tag_osm(src: Path, dst: Path, defaults: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Stream an osmium-written OSM XML file and add default tags to untagged ways.

    Relies on osmium's layout: one element per line, `<way ...>` ... `</way>`. Returns counts."""
    counts = {"ways": 0, "lanes_added": 0, "maxspeed_added": 0}
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    with _open_text(src, "r") as fin, _open_text(tmp, "w", gz=dst.suffix == ".gz") as fout:
        buf: list[str] | None = None
        for line in fin:
            if buf is None:
                if _WAY_OPEN.match(line) and not _WAY_SELF_CLOSED.search(line):
                    buf = [line]
                else:
                    fout.write(line)
                continue
            if line.strip() != "</way>":
                buf.append(line)
                continue
            counts["ways"] += 1
            tags = {m.group(1): m.group(2) for b in buf if (m := _TAG.search(b))}
            add = added_tags(tags, defaults)
            fout.writelines(buf)
            if add:
                indent = re.match(r"^(\s*)", buf[-1]).group(1) if len(buf) > 1 else "    "
                for k, v in add.items():
                    fout.write(f'{indent}<tag k="{k}" v="{v}"/>\n')
                counts["lanes_added"] += "lanes" in add
                counts["maxspeed_added"] += "maxspeed" in add
            fout.write(line)
            buf = None
    tmp.replace(dst)
    return counts


# ---------------------------------------------------------------------------- cross-check


def _reads(results: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for path in sorted(results.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip().startswith("{"):
                rec = json.loads(line)
                out[int(rec["way_id"])] = rec
    return out


def typemap_lanes(path: Path) -> dict[str, int]:
    """numLanes per highway class from a SUMO type file (`highway.<class>` ids)."""
    root = ET.parse(path).getroot()
    return {
        t.get("id", "").removeprefix("highway."): int(t.get("numLanes", 0))
        for t in root.iter("type")
        if t.get("id", "").startswith("highway.") and t.get("numLanes")
    }


def reference_lanes() -> dict[str, dict[str, int]]:
    """Lanes per direction that untagged ways got before v2, read from the v1 and m2 type files."""
    from sim.common import sumo_home

    v1 = typemap_lanes(sumo_home() / "data" / "typemap" / "osmNetconvert.typ.xml")
    m2 = {**v1, **typemap_lanes(REPO_ROOT / "sim" / "population" / "config" / "untagged.typ.xml")}
    return {"SUMO typemap (v1)": v1, "m2 overlay (A-net-201)": m2}


def _imagery_reads(set_dir: Path) -> tuple[str, dict[int, int]]:
    """Way -> imagery lane count: the agreed value of two blind reads (lane audit v2 sets), or
    the single read of the v1 sets."""
    res = set_dir / "results"
    if (res / "read-a").exists():
        ra, rb = _reads(res / "read-a"), _reads(res / "read-b")
        agreed = {
            w: a["lanes_marked_side"]
            for w, a in ra.items()
            if w in rb
            and a.get("lanes_marked_side") == rb[w].get("lanes_marked_side")
            and isinstance(a.get("lanes_marked_side"), int)
        }
        return "two agreeing reads", agreed
    single = {
        w: r["lanes_marked_side"]
        for w, r in _reads(res).items()
        if isinstance(r.get("lanes_marked_side"), int)
    }
    return "single read", single


def crosscheck(
    defaults: dict[str, dict[str, Any]], imagery_dir: Path, sets: Iterable[str]
) -> dict[str, Any]:
    """Per class: how often the class x direction default equals (a) the way's own OSM tag and
    (b) the imagery reading, next to the pre-v2 defaults. Uses existing lane-audit results only.

    The lane-audit ways are TAGGED ways (the tag is the truth the audit was scored against), so
    (a) asks: had this way been untagged, would the default have matched its tag?"""
    per: dict[str, dict[str, Any]] = {}
    ways_seen: set[int] = set()
    sets = list(sets)
    kinds: dict[str, str] = {}
    for name in sets:
        wfile = imagery_dir / name / "ways.json"
        if not wfile.exists():
            continue
        ways = json.loads(wfile.read_text())["ways"]
        kinds[name], img_reads = _imagery_reads(imagery_dir / name)
        for w in ways:
            wid = int(w["way_id"])
            if wid in ways_seen:
                continue
            ways_seen.add(wid)
            tags = {"highway": w["highway"]}
            for k_src, k_tag in (
                ("oneway", "oneway"),
                ("lanes_tag", "lanes"),
                ("lanes_forward", "lanes:forward"),
                ("lanes_backward", "lanes:backward"),
            ):
                if w.get(k_src) is not None:
                    tags[k_tag] = str(w[k_src])
            lpd = lanes_per_direction(tags)
            key = f"{w['highway']}|{'oneway' if is_oneway(tags) else 'twoway'}"
            d = defaults.get(key, {}).get("lanes")
            if d is None or not lpd:
                continue
            truth = round(max(lpd))  # the audited side
            c = per.setdefault(
                key,
                {"n": 0, "tag_eq": 0, "tag_within1": 0, "img_n": 0, "img_eq": 0, "tags": []},
            )
            c["n"] += 1
            c["tag_eq"] += int(truth == d)
            c["tag_within1"] += int(abs(truth - d) <= 1)
            c["tags"].append(truth)
            img = img_reads.get(wid)
            if img is not None:
                c["img_n"] += 1
                c["img_eq"] += int(img == d)
    rows = {}
    refs = reference_lanes()
    for key, c in sorted(per.items()):
        cls = key.split("|")[0]
        row: dict[str, Any] = {
            "default_lanes": defaults[key]["lanes"],
            "ways": c["n"],
            "agree_with_tag": round(c["tag_eq"] / c["n"], 3),
            "within_one_of_tag": round(c["tag_within1"] / c["n"], 3),
            "imagery_reads": c["img_n"],
            "agree_with_imagery": round(c["img_eq"] / c["img_n"], 3) if c["img_n"] else None,
        }
        for name, ref in refs.items():
            if cls in ref and key.endswith("oneway"):
                row[f"agree_with_tag[{name}]"] = round(
                    sum(t == ref[cls] for t in c["tags"]) / c["n"], 3
                )
        rows[key] = row
    return {"sets": sets, "read_kind": kinds, "ways": len(ways_seen), "per_class": rows}


# ---------------------------------------------------------------------------- CLI

app = typer.Typer(add_completion=False, help=__doc__)
DEFAULT_STATS = REPO_ROOT / "sim" / "network" / "types" / "jeddah-lanes.json"


@app.command("stats")
def stats_cmd(
    pbf: Path = typer.Argument(REPO_ROOT / "data" / "osm" / "jeddah.osm.pbf"),
    out: Path = typer.Option(DEFAULT_STATS),
    min_tagged_km: float = typer.Option(MIN_TAGGED_KM, help="evidence needed for a median"),
) -> None:
    """Measure lanes/maxspeed per class x oneway on the clip and derive the defaults."""
    res = build_stats(pbf, min_tagged_km)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    typer.echo(json.dumps(res["defaults"], indent=1))


@app.command("tag")
def tag_cmd(src: Path, dst: Path, stats: Path = typer.Option(DEFAULT_STATS)) -> None:
    """Pre-pass: add the default tags to untagged ways of an OSM XML file."""
    defaults = json.loads(stats.read_text())["defaults"]
    typer.echo(json.dumps(tag_osm(src, dst, defaults)))


@app.command("crosscheck")
def crosscheck_cmd(
    stats: Path = typer.Option(DEFAULT_STATS),
    imagery_dir: Path = typer.Option(REPO_ROOT / "data" / "imagery"),
    sets: str = typer.Option("v2-holdout,holdout", help="comma-separated lane-audit set names"),
    out: Path | None = typer.Option(None),
) -> None:
    """Agreement of the defaults with the lane-audit held-out ways (no imagery calls)."""
    defaults = json.loads(stats.read_text())["defaults"]
    res = crosscheck(defaults, imagery_dir, [s for s in sets.split(",") if s])
    if out:
        out.write_text(json.dumps(res, indent=2) + "\n")
    typer.echo(json.dumps(res, indent=1))


if __name__ == "__main__":
    app()
