"""Convert run outputs for the viewer: edgedata.xml[.gz] -> edgedata.parquet,
fcd.xml -> fcd.parquet, and build the edge index and the bin arrays
(contract docs/contracts/run-outputs.md §10, §12).

A producer's own `edgedata.parquet` / `fcd.parquet` (SUMO column names) is never rewritten: edge
bins are read through `api.schema`, and producer FCD is copied once, sorted and renamed, into the
cache. Conversions from XML go into the run directory (v1) unless it is not writable or
TT_RUNS_READONLY=1, in which case they go to the cache.

    python -m api.ingest runs/<run_id>
    python -m api.ingest --all
    python -m api.ingest --all --force

XML is streamed with iterparse (elements cleared as they are consumed) and Parquet is written in
row groups, so memory stays flat whatever the file size.
"""

from __future__ import annotations

import gzip
import math
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import typer

from api import settings
from api.schema import fcd_select, is_contract_edgedata, is_contract_fcd, sql_path
from api.util import build_lock, is_stale, tmp_path_for

SECONDS_PER_HOUR = 3600  # unit conversion
EDGE_ROW_GROUP = 65_536  # rows buffered before a Parquet row group is written
FCD_ROW_GROUP = 131_072
DUCKDB_MEMORY_LIMIT = "1GB"  # external sort of FCD spills to disk beyond this

DICT_STR = pa.dictionary(pa.int32(), pa.string())
EDGE_SCHEMA = pa.schema(
    [
        ("bin_begin_s", pa.int32()),
        ("bin_end_s", pa.int32()),
        ("edge_id", DICT_STR),
        ("speed_ms", pa.float32()),
        ("speed_rel", pa.float32()),
        ("density_veh_km", pa.float32()),
        ("occupancy_pct", pa.float32()),
        ("flow_veh_h", pa.float32()),
        ("entered", pa.int32()),
        ("left", pa.int32()),
        ("sampled_s", pa.float32()),
        ("traveltime_s", pa.float32()),
        ("time_loss_s", pa.float32()),
        ("waiting_s", pa.float32()),
    ]
)
# parquet column -> SUMO edgeData attribute (floats; NaN when absent)
EDGE_FLOAT_ATTRS = {
    "speed_ms": "speed",
    "speed_rel": "speedRelative",
    "density_veh_km": "density",
    "occupancy_pct": "occupancy",
    "sampled_s": "sampledSeconds",
    "traveltime_s": "traveltime",
    "time_loss_s": "timeLoss",
    "waiting_s": "waitingTime",
}
FCD_SCHEMA = pa.schema(
    [
        ("time_s", pa.float32()),
        ("vehicle_id", DICT_STR),
        ("vtype", DICT_STR),
        ("lon", pa.float64()),
        ("lat", pa.float64()),
        ("speed_ms", pa.float32()),
        ("angle_deg", pa.float32()),
    ]
)

Log = Callable[[str], None]


def _open_xml(path: Path) -> Any:
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def _f(value: str | None) -> float:
    return float(value) if value not in (None, "") else math.nan


def _i(value: str | None) -> int:
    return int(float(value)) if value not in (None, "") else 0


def _edge_table(cols: dict[str, list[Any]]) -> pa.Table:
    arrays = []
    for field in EDGE_SCHEMA:
        if field.name == "edge_id":
            arrays.append(pa.array(cols["edge_id"], pa.string()).dictionary_encode())
        else:
            arrays.append(pa.array(cols[field.name], field.type))
    return pa.Table.from_arrays(arrays, schema=EDGE_SCHEMA)


def convert_edgedata(xml: Path, out: Path) -> int:
    """Stream SUMO edgeData XML to Parquet sorted by (bin_begin_s, edge_id); return row count."""
    tmp = tmp_path_for(out)
    rows = 0
    names = [f.name for f in EDGE_SCHEMA]
    buf: dict[str, list[Any]] = {n: [] for n in names}
    interval: list[tuple[str | None, ...]] = []
    wanted = ("id", *EDGE_FLOAT_ATTRS.values(), "entered", "left", "flow")
    begin = end = 0
    root: ET.Element | None = None

    def flush(writer: pq.ParquetWriter) -> None:
        if buf["edge_id"]:
            writer.write_table(_edge_table(buf), row_group_size=EDGE_ROW_GROUP)
            for v in buf.values():
                v.clear()

    with (
        _open_xml(xml) as src,
        pq.ParquetWriter(tmp, EDGE_SCHEMA, compression="zstd") as writer,
    ):
        for event, elem in ET.iterparse(src, events=("start", "end")):
            if root is None:
                root = elem
                continue
            if event == "start":
                if elem.tag == "interval":
                    begin, end = _i(elem.get("begin")), _i(elem.get("end"))
                continue
            if elem.tag == "edge":
                interval.append(tuple(elem.get(k) for k in wanted))
                elem.clear()
            elif elem.tag == "interval":
                width = end - begin
                interval.sort(key=lambda t: t[0] or "")
                for values in interval:
                    a = dict(zip(wanted, values, strict=True))
                    buf["bin_begin_s"].append(begin)
                    buf["bin_end_s"].append(end)
                    buf["edge_id"].append(a["id"] or "")
                    for col, attr in EDGE_FLOAT_ATTRS.items():
                        buf[col].append(_f(a[attr]))
                    entered = _i(a["entered"])
                    flow = a["flow"]
                    buf["flow_veh_h"].append(
                        _f(flow) if flow is not None else entered * SECONDS_PER_HOUR / width
                    )
                    buf["entered"].append(entered)
                    buf["left"].append(_i(a["left"]))
                    if len(buf["edge_id"]) >= EDGE_ROW_GROUP:
                        flush(writer)
                rows += len(interval)
                interval.clear()
                root.clear()
        flush(writer)
    os.replace(tmp, out)
    return rows


def _fcd_table(cols: dict[str, list[Any]]) -> pa.Table:
    arrays = []
    for field in FCD_SCHEMA:
        if field.type == DICT_STR:
            arrays.append(pa.array(cols[field.name], pa.string()))
        else:
            arrays.append(pa.array(cols[field.name], field.type))
    return pa.Table.from_arrays(arrays, names=FCD_SCHEMA.names)


def convert_fcd(xml: Path, out: Path) -> int:
    """Stream SUMO FCD XML (geo) to Parquet sorted by (vehicle_id, time_s); return row count.

    Pass 1 writes time-ordered row groups to a scratch file; pass 2 sorts them with DuckDB
    (which spills to disk under its memory limit) and streams the result into the final file.
    """
    scratch = out.with_name(f".{out.name}.unsorted.parquet")
    tmp = tmp_path_for(out)
    names = FCD_SCHEMA.names
    buf: dict[str, list[Any]] = {n: [] for n in names}
    plain = pa.schema([(f.name, pa.string() if f.type == DICT_STR else f.type) for f in FCD_SCHEMA])
    rows = 0
    t = math.nan
    root: ET.Element | None = None
    try:
        with _open_xml(xml) as src, pq.ParquetWriter(scratch, plain) as writer:
            for event, elem in ET.iterparse(src, events=("start", "end")):
                if root is None:
                    root = elem
                    continue
                if event == "start":
                    if elem.tag == "timestep":
                        t = _f(elem.get("time"))
                    continue
                if elem.tag == "vehicle":
                    buf["time_s"].append(t)
                    buf["vehicle_id"].append(elem.get("id", ""))
                    buf["vtype"].append(elem.get("type", ""))
                    buf["lon"].append(_f(elem.get("x")))
                    buf["lat"].append(_f(elem.get("y")))
                    buf["speed_ms"].append(_f(elem.get("speed")))
                    buf["angle_deg"].append(_f(elem.get("angle")))
                    rows += 1
                    elem.clear()
                    if len(buf["time_s"]) >= FCD_ROW_GROUP:
                        writer.write_table(_fcd_table(buf))
                        for v in buf.values():
                            v.clear()
                elif elem.tag == "timestep":
                    root.clear()
            if buf["time_s"]:
                writer.write_table(_fcd_table(buf))
        _sorted_fcd(f"SELECT * FROM read_parquet({sql_path(scratch)})", tmp)
        os.replace(tmp, out)
    finally:
        scratch.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return rows


def _sorted_fcd(select: str, out: Path) -> None:
    """Write `select` (contract FCD columns) sorted by (vehicle_id, time_s) to `out`."""
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute("SET preserve_insertion_order=false")
        reader = con.execute(f"{select} ORDER BY vehicle_id, time_s").to_arrow_reader(FCD_ROW_GROUP)
        with pq.ParquetWriter(out, FCD_SCHEMA, compression="zstd") as writer:
            for batch in reader:
                table = pa.Table.from_batches([batch]).select(FCD_SCHEMA.names)
                writer.write_table(table.cast(FCD_SCHEMA))
    finally:
        con.close()


def normalise_fcd(src: Path, out: Path) -> int:
    """Producer FCD Parquet (SUMO names) -> contract fcd.parquet, sorted; return row count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(out)
    try:
        _sorted_fcd(fcd_select(src), tmp)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return pq.ParquetFile(out).metadata.num_rows


def cache_run_dir(run_id: str) -> Path:
    return settings.cache_dir() / "runs" / run_id


def _writable(run: Path) -> bool:
    return not settings.runs_readonly() and os.access(run, os.W_OK)


def _xml(run: Path, stem: str) -> Path | None:
    for name in (f"{stem}.xml", f"{stem}.xml.gz"):
        if (run / name).is_file():
            return run / name
    return None


def ensure_edgedata(run: Path, force: bool = False, run_id: str | None = None) -> Path | None:
    """The run's edge bins as Parquet (contract or producer schema; see api.schema), or None.

    `run` is the directory holding the simulation outputs (for nested runs the sub-directory)."""
    run_id = run_id or run.name
    own, xml = run / "edgedata.parquet", _xml(run, "edgedata")
    if own.is_file() and not is_contract_edgedata(own):
        return own  # a producer's file: read through api.schema, never rewritten
    if xml is None:
        if own.is_file():
            return own
        cached = cache_run_dir(run_id) / "edgedata.parquet"
        return cached if cached.is_file() else None
    out = own if _writable(run) else cache_run_dir(run_id) / "edgedata.parquet"
    if not force and not is_stale(out, xml):
        return out
    with build_lock(f"edgedata:{out}"):
        if force or is_stale(out, xml):
            out.parent.mkdir(parents=True, exist_ok=True)
            convert_edgedata(xml, out)
    return out


def ensure_fcd(
    run: Path, force: bool = False, run_id: str | None = None, tier: str | None = None
) -> Path | None:
    """Contract-schema fcd.parquet for a Tier B run (converted or normalised), or None."""
    run_id = run_id or run.name
    if tier is None:
        tier = _tier(run)
    if tier == "A":  # trajectories are Tier B only (contract section 5)
        return None
    own, xml = run / "fcd.parquet", _xml(run, "fcd")
    cached = cache_run_dir(run_id) / "fcd.parquet"
    if own.is_file() and not is_contract_fcd(own):
        if force or is_stale(cached, own):
            with build_lock(f"fcd:{cached}"):
                if force or is_stale(cached, own):
                    normalise_fcd(own, cached)
        return cached
    if xml is None:
        if own.is_file():
            return own
        return cached if cached.is_file() else None
    out = own if _writable(run) else cached
    if not force and not is_stale(out, xml):
        return out
    with build_lock(f"fcd:{out}"):
        if force or is_stale(out, xml):
            out.parent.mkdir(parents=True, exist_ok=True)
            convert_fcd(xml, out)
    return out


def _tier(run: Path) -> str | None:
    from api.runs import read_meta

    meta = read_meta(run)
    return meta.get("tier") if meta else None


def _as_run(run: Any) -> Any:
    from api.runs import Run, get_run

    if isinstance(run, Run):
        return run
    return get_run(Path(run).name)


def ingest_run(run: Any, force: bool = False, log: Log = print) -> dict[str, Any]:
    """Everything the viewer needs for one run (a `Run`, run id or run path); timings and counts."""
    from api.bins import ensure_bins
    from api.edges import ensure_edge_index
    from api.runs import run_network

    r = _as_run(run)
    meta = r.meta
    report: dict[str, Any] = {"run_id": r.run_id}
    t0 = time.perf_counter()
    edp = ensure_edgedata(r.data_dir, force, run_id=r.run_id)
    report["edgedata_s"] = round(time.perf_counter() - t0, 2)
    if edp is not None:
        report["edgedata_rows"] = pq.ParquetFile(edp).metadata.num_rows
    log(f"ingest {r.run_id}: edgedata {report.get('edgedata_rows', 'n/a')} rows")
    if meta.get("tier") == "B":
        t0 = time.perf_counter()
        fcdp = ensure_fcd(r.data_dir, force, run_id=r.run_id, tier="B")
        report["fcd_s"] = round(time.perf_counter() - t0, 2)
        if fcdp is not None:
            report["fcd_rows"] = pq.ParquetFile(fcdp).metadata.num_rows
        log(f"ingest {r.run_id}: fcd {report.get('fcd_rows', 'n/a')} rows")
    nhash = meta.get("network_hash")
    if meta.get("network") and nhash:
        t0 = time.perf_counter()
        ensure_edge_index(run_network(r), str(nhash))
        report["edge_index_s"] = round(time.perf_counter() - t0, 2)
        log(f"ingest {r.run_id}: edge index {nhash} ready")
        if edp is not None:
            t0 = time.perf_counter()
            ensure_bins(r, force=force)
            report["bins_s"] = round(time.perf_counter() - t0, 2)
            log(f"ingest {r.run_id}: bins ready")
    return report


def _resolve_run(arg: str) -> Any:
    from fastapi import HTTPException

    from api.runs import get_run

    try:
        return get_run(Path(arg).name)
    except HTTPException as exc:
        raise typer.BadParameter(f"{arg}: not a run under {settings.runs_dir()}") from exc


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    run: str | None = typer.Argument(None, help="runs/<run_id> or a run id"),
    all_runs: bool = typer.Option(False, "--all", help="ingest every run under TT_RUNS_DIR"),
    force: bool = typer.Option(False, "--force", help="rebuild even when outputs are fresh"),
) -> None:
    if all_runs == (run is not None):
        raise typer.BadParameter("give exactly one of RUN or --all")
    from api.runs import registry

    targets = list(registry()[0].values()) if all_runs else [_resolve_run(str(run))]
    for target in targets:
        t0 = time.perf_counter()
        report = ingest_run(target, force=force, log=typer.echo)
        report["total_s"] = round(time.perf_counter() - t0, 2)
        typer.echo(f"  {report}")


if __name__ == "__main__":
    app()
