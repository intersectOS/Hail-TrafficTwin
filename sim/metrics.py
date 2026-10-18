"""City KPIs for a Tier A run (PROJECT.md 9.8): delay, speed, VKT, VHT, throughput, peak
spreading, CO2/NOx, per-district and top corridors. Reads SUMO outputs in `runs/<id>/`, converts
them to Parquet (streaming; the big XML files are deleted afterwards) and writes `metrics.json`,
`metrics_hourly.parquet`, `metrics_district.parquet`, `report.md` and validation plots.

Totals (VKT, VHT, trips, emissions) are divided by the population sample fraction, so a 10 % run
reports full-city figures; means (delay, speed) are unaffected.

    python -m sim.metrics runs/<id>            # recompute from the Parquet/XML in a run dir
"""

from __future__ import annotations

import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL

FIDELITY_DOC = REPO_ROOT / "docs" / "fidelity.md"
DEFAULT_CAVEATS = (
    "- Tier A runs SUMO's mesoscopic model, which tends to underestimate congestion and models "
    "queue spill-back incompletely; trust baseline-versus-policy deltas more than absolute "
    "values.\n"
    "- Demand is synthetic and uncalibrated (no Jeddah counts or travel survey).\n"
)


# ---------------------------------------------------------------------------- parsing


def xml_content_hash(path: Path, length: int = 16) -> str:
    """sha256 of a (gzipped) XML file ignoring comment lines (headers carry dates and paths)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    digest = hashlib.sha256()
    in_comment = False
    with opener(path, "rb") as fh:
        for line in fh:
            s = line.strip()
            if not in_comment and s.startswith(b"<!--"):
                in_comment = True
            if in_comment:
                if s.endswith(b"-->"):
                    in_comment = False
                continue
            digest.update(line)
    return digest.hexdigest()[:length]


def _xml_source(path: Path):  # noqa: ANN202 - path or binary file object for iterparse
    return gzip.open(path, "rb") if str(path).endswith(".gz") else path


def find_output(out: Path, name: str) -> Path | None:
    """`<name>.xml` or `<name>.xml.gz` in a run dir (policy runs write gzipped outputs)."""
    for cand in (out / f"{name}.xml", out / f"{name}.xml.gz"):
        if cand.exists():
            return cand
    return None


def parse_tripinfo(path: Path) -> pd.DataFrame:
    cols: dict[str, list] = {
        k: []
        for k in (
            "veh_id",
            "depart",
            "arrival",
            "duration",
            "route_m",
            "time_loss",
            "waiting",
            "depart_delay",
            "vtype",
            "co2_g",
            "nox_g",
        )
    }
    for _, el in ET.iterparse(_xml_source(path), events=("end",)):
        if el.tag != "tripinfo":
            continue
        cols["veh_id"].append(el.get("id"))
        cols["depart"].append(float(el.get("depart", "nan")))
        cols["arrival"].append(float(el.get("arrival", "nan")))
        cols["duration"].append(float(el.get("duration", "nan")))
        cols["route_m"].append(float(el.get("routeLength", "nan")))
        cols["time_loss"].append(float(el.get("timeLoss", "nan")))
        cols["waiting"].append(float(el.get("waitingTime", "nan")))
        cols["depart_delay"].append(float(el.get("departDelay", "0")))
        cols["vtype"].append(el.get("vType"))
        em = el.find("emissions")
        cols["co2_g"].append(float(em.get("CO2_abs", "nan")) / 1000.0 if em is not None else np.nan)
        cols["nox_g"].append(float(em.get("NOx_abs", "nan")) / 1000.0 if em is not None else np.nan)
        el.clear()
    return pd.DataFrame(cols)


EDGE_FIELDS = ("entered", "left", "sampledSeconds", "speed", "density", "timeLoss", "traveltime")


def edgedata_to_parquet(xml: Path, out: Path, fields: tuple[str, ...] = EDGE_FIELDS) -> int:
    """Stream <interval><edge .../></interval> into Parquet (one row group per interval)."""
    schema = pa.schema(
        [("begin", pa.float32()), ("end", pa.float32()), ("edge_id", pa.string())]
        + [(f, pa.float32()) for f in fields]
    )
    writer = pq.ParquetWriter(out, schema, compression="zstd")
    rows = 0
    begin = end = 0.0
    buf: dict[str, list] = {k: [] for k in schema.names}
    try:
        for ev, el in ET.iterparse(_xml_source(xml), events=("start", "end")):
            if ev == "start":
                if el.tag == "interval":
                    begin, end = float(el.get("begin", 0)), float(el.get("end", 0))
                continue
            if el.tag == "edge":
                buf["begin"].append(begin)
                buf["end"].append(end)
                buf["edge_id"].append(el.get("id"))
                for f in fields:
                    v = el.get(f)
                    buf[f].append(float(v) if v not in (None, "") else np.nan)
                el.clear()
            elif el.tag == "interval":
                if buf["edge_id"]:
                    writer.write_table(pa.table(buf, schema=schema))
                    rows += len(buf["edge_id"])
                    buf = {k: [] for k in schema.names}
                el.clear()
    finally:
        writer.close()
    return rows


def parse_stats(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    return {child.tag: dict(child.attrib) for child in root}


# ---------------------------------------------------------------------------- KPIs


def city_kpis(
    trips: pd.DataFrame, sample: float, sim_end: float, stats: dict[str, Any]
) -> dict[str, Any]:
    """Trip-based city KPIs; `trips` = tripinfo joined to vehicles (only departures < sim_end)."""
    f = 1.0 / sample
    done = trips[trips["depart"] < sim_end]
    loaded = int(stats.get("vehicles", {}).get("loaded", len(done)))
    tele = stats.get("teleports", {})
    delay = done["time_loss"] + done["depart_delay"]
    hours = np.floor(done["depart"] / 3600.0).astype(int)
    by_hour = done.groupby(hours).size()
    peak_hour = int(by_hour.idxmax()) if len(by_hour) else -1
    peak_share = float(by_hour.max() / by_hour.sum()) if len(by_hour) else 0.0
    am = done[(done["depart"] >= 6 * 3600) & (done["depart"] < 9 * 3600)]
    return {
        "trips_completed": int(round(len(done) * f)),
        "trips_completed_sampled": len(done),
        "vehicles_loaded_sampled": loaded,
        "teleports": int(tele.get("total", 0)),
        "teleport_share": round(int(tele.get("total", 0)) / loaded, 6) if loaded else 0.0,
        "mean_delay_s": round(float(delay.mean()), 1),
        "mean_time_loss_s": round(float(done["time_loss"].mean()), 1),
        "mean_depart_delay_s": round(float(done["depart_delay"].mean()), 1),
        "mean_duration_s": round(float(done["duration"].mean()), 1),
        "mean_trip_km": round(float(done["route_m"].mean() / 1000.0), 2),
        "mean_speed_kmh": round(float(done["route_m"].sum() / done["duration"].sum() * 3.6), 2),
        "vkt": round(float(done["route_m"].sum() / 1000.0 * f)),
        "vht": round(float(done["duration"].sum() / 3600.0 * f)),
        "vht_delay": round(float(delay.sum() / 3600.0 * f)),
        "throughput_peak_hour_trips": int(round(by_hour.max() * f)) if len(by_hour) else 0,
        "peak_hour": peak_hour,
        "peak_spreading_top_hour_share": round(peak_share, 4),
        "am_peak_mean_delay_s": round(float((am["time_loss"] + am["depart_delay"]).mean()), 1)
        if len(am)
        else None,
        "co2_t": round(float(done["co2_g"].sum() / 1e6 * f), 1),
        "nox_kg": round(float(done["nox_g"].sum() / 1e3 * f), 1),
        "co2_peak_hour_t": round(float(done.loc[hours == peak_hour, "co2_g"].sum() / 1e6 * f), 1),
    }


def hourly_kpis(trips: pd.DataFrame, sample: float, sim_end: float) -> pd.DataFrame:
    f = 1.0 / sample
    done = trips[trips["depart"] < sim_end].copy()
    done["hour"] = np.floor(done["depart"] / 3600.0).astype(int)
    done["delay"] = done["time_loss"] + done["depart_delay"]
    g = done.groupby("hour")
    out = pd.DataFrame(
        {
            "departures": g.size() * f,
            "mean_delay_s": g["delay"].mean(),
            "mean_speed_kmh": g["route_m"].sum() / g["duration"].sum() * 3.6,
            "vkt": g["route_m"].sum() / 1000.0 * f,
            "co2_t": g["co2_g"].sum() / 1e6 * f,
            "nox_kg": g["nox_g"].sum() / 1e3 * f,
        }
    ).reindex(range(int(np.ceil(sim_end / 3600.0))), fill_value=0.0)
    out.index.name = "hour"
    return out.reset_index()


def district_kpis(
    trips: pd.DataFrame, zones: pd.DataFrame | None, sample: float, sim_end: float
) -> pd.DataFrame:
    """Per origin district: trips, mean delay, mean speed, VKT (equity view)."""
    f = 1.0 / sample
    done = trips[(trips["depart"] < sim_end) & (trips["o_zone"] >= 0)].copy()
    done["delay"] = done["time_loss"] + done["depart_delay"]
    g = done.groupby("o_zone")
    out = pd.DataFrame(
        {
            "trips": g.size() * f,
            "mean_delay_s": g["delay"].mean(),
            "mean_speed_kmh": g["route_m"].sum() / g["duration"].sum() * 3.6,
            "mean_trip_km": g["route_m"].mean() / 1000.0,
            "vkt": g["route_m"].sum() / 1000.0 * f,
        }
    )
    out.index.name = "zone_id"
    out = out.reset_index()
    if zones is not None:
        out = out.merge(zones[["zone_id", "name_en", "name_ar", "population"]], on="zone_id")
    return out


def top_corridors(edgedata: Path, n: int = 10, peak_hour: int | None = None) -> list[dict]:
    """Edges with the largest total time loss (vehicle-hours) over the day."""
    if not edgedata.exists():
        return []
    tbl = pq.read_table(edgedata, columns=["begin", "edge_id", "timeLoss", "speed"])
    df = tbl.to_pandas()
    if peak_hour is not None:
        df = df[(df["begin"] >= peak_hour * 3600) & (df["begin"] < (peak_hour + 1) * 3600)]
    agg = df.groupby("edge_id").agg(time_loss_s=("timeLoss", "sum"), speed=("speed", "mean"))
    agg = agg.sort_values("time_loss_s", ascending=False).head(n)
    return [
        {
            "edge_id": e,
            "time_loss_veh_h_sampled": round(float(r.time_loss_s) / 3600.0, 2),
            "mean_speed_kmh": round(float(r.speed) * 3.6, 1),
        }
        for e, r in agg.iterrows()
    ]


# ---------------------------------------------------------------------------- report


def caveats() -> str:
    """Caveats section of docs/fidelity.md (written by sim.fidelity), else defaults."""
    if FIDELITY_DOC.exists():
        text = FIDELITY_DOC.read_text()
        if "## Caveats" in text:
            section = text.split("## Caveats", 1)[1]
            return section.split("\n## ", 1)[0].strip() + "\n"
    return DEFAULT_CAVEATS


REPORT_TEMPLATE = """# {title}

> **{label}.** Tier {tier} ({mode}), day type `{daytype}` ({date}), seed {seed}, population sample
> {sample_pct} % with capacity scaling x{scale:g}. Totals are scaled to the full city.

| KPI | value |
|---|---|
{kpi_rows}

## Per district (top 10 by mean delay)
{district_rows}

## Most delayed edges (sampled vehicle-hours of time loss)
{corridor_rows}

## Provenance
seed {seed} | config {config_hash} | population {population_hash} | network {network_hash} |
{sumo_version}

## Caveats (meso fidelity, PROJECT.md 9.4)
{caveats}
"""


def md_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(none)"
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def write_report(out: Path, meta: dict[str, Any], report: dict[str, Any]) -> Path:
    s = report["summary"]
    kpi_rows = "\n".join(f"| {k} | {v} |" for k, v in s.items())
    district_rows = md_table(report.get("districts_top", []))
    corridor_rows = md_table(report.get("top_corridors", []))
    text = REPORT_TEMPLATE.format(
        title=f"Run {meta['run_id']}",
        label=SYNTHETIC_LABEL,
        tier=meta.get("tier", "A"),
        mode=meta.get("mode", "meso"),
        daytype=meta.get("daytype"),
        date=meta.get("date"),
        seed=meta.get("seed"),
        sample_pct=round(100 * float(meta.get("sample", 1.0)), 1),
        scale=float(meta.get("capacity_scale", 1.0)),
        kpi_rows=kpi_rows,
        district_rows=district_rows,
        corridor_rows=corridor_rows,
        config_hash=meta.get("config_hash"),
        population_hash=meta.get("population_hash"),
        network_hash=meta.get("network_hash"),
        sumo_version=meta.get("sumo_version"),
        caveats=caveats(),
    )
    path = out / "report.md"
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------- driver


def load_zone_table(meta: dict[str, Any]) -> pd.DataFrame | None:
    from sim.population.zones import default_zone_dir

    path = default_zone_dir() / "zones.parquet"
    return pd.read_parquet(path) if path.exists() else None


def process_run(out: Path, meta: dict[str, Any], keep_xml: bool = False) -> dict[str, Any]:
    """Convert outputs to Parquet, compute KPIs, write metrics.json, report.md and plots."""
    out = Path(out)
    sample = float(meta.get("sample", 1.0))
    sim_end = float(meta.get("sim_end_s", 86400))
    ti_xml = find_output(out, "tripinfo")
    if ti_xml is not None:
        ti = parse_tripinfo(ti_xml)
        ti.to_parquet(out / "tripinfo.parquet", index=False)
    else:
        ti = pd.read_parquet(out / "tripinfo.parquet")
    for name in ("edgedata", "emissions"):
        xml = find_output(out, name)
        if xml is not None:
            fields = EDGE_FIELDS if name == "edgedata" else ("CO2_abs", "NOx_abs")
            edgedata_to_parquet(xml, out / f"{name}.parquet", fields)
    veh = pd.read_parquet(out / "vehicles.parquet")
    trips = ti.merge(veh, on="veh_id", how="left", suffixes=("", "_plan"))
    trips["o_zone"] = trips["o_zone"].fillna(-1).astype(int)
    stats = parse_stats(out / "stats.xml") if (out / "stats.xml").exists() else {}
    summary = city_kpis(trips, sample, sim_end, stats)
    summary["vehicles_planned"] = int(round(len(veh) / sample))
    summary["completion_share"] = round(len(ti) / max(len(veh), 1), 4)
    hourly = hourly_kpis(trips, sample, sim_end)
    hourly.to_parquet(out / "metrics_hourly.parquet", index=False)
    zones = load_zone_table(meta)
    districts = district_kpis(trips, zones, sample, sim_end)
    districts.to_parquet(out / "metrics_district.parquet", index=False)
    top_d = districts.sort_values("mean_delay_s", ascending=False).head(10)
    cols = [c for c in ("name_en", "trips", "mean_delay_s", "mean_speed_kmh") if c in top_d]
    report = {
        "label": SYNTHETIC_LABEL,
        "run_id": meta.get("run_id"),
        "summary": summary,
        "hourly": hourly.round(3).to_dict("records"),
        "districts_top": top_d[cols].round(1).to_dict("records"),
        "top_corridors": top_corridors(out / "edgedata.parquet", 10),
        "tripinfo_hash": hashlib.sha256(
            pd.util.hash_pandas_object(ti, index=False).to_numpy().tobytes()
        ).hexdigest()[:16],
        "provenance": {
            k: meta.get(k)
            for k in (
                "seed",
                "sample",
                "config_hash",
                "population_hash",
                "network_hash",
                "sumo_version",
                "daytype",
            )
        },
    }
    (out / "metrics.json").write_text(json.dumps(report, indent=2, default=float))
    write_report(out, meta, report)
    from sim.population.plots import validation_plots

    validation_plots(out, trips, sample)
    if not keep_xml:
        for name in ("tripinfo", "edgedata", "emissions"):
            for sfx in (".xml", ".xml.gz"):
                (out / f"{name}{sfx}").unlink(missing_ok=True)
    return report


def format_summary(meta: dict[str, Any], report: dict[str, Any]) -> str:
    s = report["summary"]
    t = meta.get("timings", {})
    a = t.get("assignment", {})
    sim = t.get("simulation", {})
    return "\n".join(
        [
            f"TrafficTwin baseline {meta['run_id']}  [{SYNTHETIC_LABEL}]",
            f"  {meta['daytype']} {meta['date']}, sample {meta['sample']:g} (capacity x"
            f"{meta['capacity_scale']:g}), seed {meta['seed']}, {meta['sumo_version']}",
            f"  persons {meta['persons']:,}, vehicle trips {meta['vehicles']:,} "
            f"(full city {s['vehicles_planned']:,}); completed {s['completion_share']:.1%}",
            f"  mean delay {s['mean_delay_s']} s, mean speed {s['mean_speed_kmh']} km/h, "
            f"VKT {s['vkt']:,}, VHT {s['vht']:,}, peak hour {s['peak_hour']}:00 "
            f"({s['peak_spreading_top_hour_share']:.1%} of trips)",
            f"  CO2 {s['co2_t']:,} t, NOx {s['nox_kg']:,} kg; teleports {s['teleports']} "
            f"({100 * s['teleport_share']:.3f} %)",
            f"  runtime: demand {t.get('demand_s')} s, assignment {a.get('wall_s', 'cached')} s "
            f"(peak {a.get('peak_rss_mb', '-')} MB), simulation {sim.get('wall_s')} s "
            f"(peak {sim.get('peak_rss_mb')} MB)",
            f"  outputs runs/{meta['run_id']}/",
        ]
    )


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(run_dir: Path) -> None:
    meta = json.loads((run_dir / "meta.json").read_text())
    report = process_run(run_dir, meta)
    typer.echo(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    app()
