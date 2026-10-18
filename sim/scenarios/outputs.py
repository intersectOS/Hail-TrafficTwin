"""Streaming conversion of SUMO XML outputs to Parquet / aggregates (bounded memory)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

FCD_BATCH_ROWS = 200_000  # rows per Parquet row group (memory bound, not behavioural)

FCD_SCHEMA = pa.schema(
    [
        ("time", pa.float32()),
        ("id", pa.string()),
        ("type", pa.string()),
        ("lon", pa.float64()),
        ("lat", pa.float64()),
        ("angle", pa.float32()),
        ("speed", pa.float32()),
        ("pos", pa.float32()),
        ("lane", pa.string()),
    ]
)


def fcd_to_parquet(fcd_xml: Path, out: Path, delete_xml: bool = True) -> int:
    """iterparse the FCD (written with --fcd-output.geo: x = lon, y = lat), write row groups."""
    cols: dict[str, list[Any]] = {f.name: [] for f in FCD_SCHEMA}
    rows = 0
    writer = pq.ParquetWriter(out, FCD_SCHEMA, compression="zstd")

    def flush() -> None:
        nonlocal cols
        if cols["time"]:
            writer.write_table(pa.table(cols, schema=FCD_SCHEMA))
            cols = {f.name: [] for f in FCD_SCHEMA}

    try:
        t = 0.0
        for event, elem in ET.iterparse(fcd_xml, events=("start", "end")):
            if event == "start":
                if elem.tag == "timestep":
                    t = float(elem.get("time", 0))
                continue
            if elem.tag == "vehicle":
                a = elem.attrib
                cols["time"].append(t)
                cols["id"].append(a.get("id"))
                cols["type"].append(a.get("type"))
                cols["lon"].append(float(a.get("x", "nan")))
                cols["lat"].append(float(a.get("y", "nan")))
                cols["angle"].append(float(a.get("angle", "nan")))
                cols["speed"].append(float(a.get("speed", "nan")))
                cols["pos"].append(float(a.get("pos", "nan")))
                cols["lane"].append(a.get("lane"))
                rows += 1
                if len(cols["time"]) >= FCD_BATCH_ROWS:
                    flush()
            elif elem.tag == "timestep":
                elem.clear()
        flush()
    finally:
        writer.close()
    if delete_xml:
        fcd_xml.unlink()
    return rows


def queue_series(queue_xml: Path, delete_xml: bool = True) -> dict[str, Any]:
    """Per step: longest edge queue in the window (m). Per edge: max queue (m) and its time.

    Edge queue = longest lane queue of the edge (SUMO queue-output `queueing_length`)."""
    times: list[float] = []
    step_max: list[float] = []
    edge_max: dict[str, tuple[float, float]] = {}
    t = 0.0
    cur: dict[str, float] = {}
    for event, elem in ET.iterparse(queue_xml, events=("start", "end")):
        if event == "start":
            if elem.tag == "data":
                t = float(elem.get("timestep", 0))
                cur = {}
            continue
        if elem.tag == "lane":
            lid = elem.get("id", "")
            if not lid.startswith(":"):
                edge = lid.rsplit("_", 1)[0]
                q = float(elem.get("queueing_length", 0))
                if q > cur.get(edge, 0.0):
                    cur[edge] = q
        elif elem.tag == "data":
            times.append(t)
            step_max.append(max(cur.values()) if cur else 0.0)
            for e, q in cur.items():
                if q > edge_max.get(e, (0.0, 0.0))[0]:
                    edge_max[e] = (q, t)
            elem.clear()
    if delete_xml:
        queue_xml.unlink()
    return {"time": times, "max_queue_m": step_max, "edge_max": edge_max}


STRING_KEYS = {"id", "vType", "devices", "vaporized", "edge", "lane"}


def _num(key: str, v: str) -> Any:
    """Numbers as float; ids (edge ids like `1104788990` look numeric) and lanes stay text."""
    if key in STRING_KEYS or key.endswith("Lane"):
        return v
    try:
        return float(v)
    except ValueError:
        return v


def elements_to_parquet(xml: Path, tag: str, out: Path, parent_attrs: tuple[str, ...] = ()) -> int:
    """Flatten `<tag>` elements (plus selected attributes of their parent) into a Parquet table."""
    rows: list[dict[str, Any]] = []
    parent: dict[str, Any] = {}
    for event, elem in ET.iterparse(xml, events=("start", "end")):
        if event == "start":
            if parent_attrs and elem.tag != tag and any(a in elem.attrib for a in parent_attrs):
                parent = {a: _num(a, elem.get(a, "")) for a in parent_attrs}
            continue
        if elem.tag == tag:
            rows.append({**parent, **{k: _num(k, v) for k, v in elem.attrib.items()}})
            elem.clear()
    if rows:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        cols = {k: [r.get(k) for r in rows] for k in keys}
        for k, v in cols.items():
            if any(isinstance(x, str) for x in v):
                cols[k] = [None if x is None else str(x) for x in v]
        pq.write_table(pa.table(cols), out, compression="zstd")
    return len(rows)


TELEPORT_RE = re.compile(
    r"Teleporting vehicle '([^']+)'; waited too long \(([^)]+)\).*?time=([0-9]+(?:\.[0-9]+)?)"
)


def teleports_from_log(log: Path) -> list[dict[str, Any]]:
    out = []
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            m = TELEPORT_RE.search(line)
            if m:
                out.append({"vehicle": m.group(1), "reason": m.group(2), "t": float(m.group(3))})
    return out


def p95(values: list[float] | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.percentile(arr, 95)) if arr.size else 0.0
