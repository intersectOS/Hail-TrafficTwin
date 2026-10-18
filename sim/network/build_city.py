"""Build the Tier A (city, mesoscopic) Jeddah network from OpenStreetMap.

Pipeline (each step is skipped when its output is newer than its input, unless --force):
  1. download the Geofabrik extract (only with --download, or if missing and allowed)
  2. clip it to data/osm/jeddah.poly with osmium
  3. convert the clip to OSM XML (netconvert does not read PBF)
  3b. (network v2) pre-pass: tag untagged major ways with the measured Jeddah lane/speed defaults
     (sim/network/lane_defaults.py, A-net-301/302) -> a separate OSM XML
  4. netconvert with the options in sim/network/config/city.yaml -> <net>.raw.net.xml
  5. apply the reviewed fix list (data/osm/fixes/*.yaml) -> data/jeddah/jeddah.net.xml
  6. side outputs: districts.geojson, buildings.geojson, viewer edges, build.json

    python -m sim.network.build_city                       # full city build, profile v2 (default)
    python -m sim.network.build_city --network-profile v1 --out /tmp/v1.net.xml   # M1 settings
    python -m sim.network.build_city --osm data/demo/demo.osm.xml.gz --out /tmp/demo.net.xml \
        --no-side-outputs                                  # same builder on a small extract
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

import typer

from sim.common import (
    REPO_ROOT,
    file_hash,
    load_yaml,
    rel,
    run_cmd,
    sumo_bin,
    sumo_home,
    sumo_version,
)
from sim.network import geo
from sim.network.fixes import apply_fixes, load_fixes
from sim.network.lane_defaults import tag_osm
from sim.network.netinfo import edges_geojson, net_stats

# Network profiles: v1 = M1 build (data/jeddah/jeddah.net.xml), m2 = Track A variant with the
# judgement overlay (A-net-201), v2 = measured lane defaults + junction/ramp settings (Track F).
PROFILES = {
    "v1": REPO_ROOT / "sim" / "network" / "config" / "city.yaml",
    "m2": REPO_ROOT / "sim" / "population" / "config" / "network-m2.yaml",
    "v2": REPO_ROOT / "sim" / "network" / "config" / "city-v2.yaml",
}
DEFAULT_PROFILE = "v2"
DEFAULT_CONFIG = PROFILES[DEFAULT_PROFILE]


def _p(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _fresh(out: Path, *inputs: Path) -> bool:
    return out.exists() and all(out.stat().st_mtime >= i.stat().st_mtime for i in inputs)


def netconvert_args(cfg: dict[str, Any]) -> list[str]:
    """Flatten the configured netconvert options and type files into an argument list."""
    args: list[str] = []
    for opt in cfg["netconvert_options"]:
        args.extend([opt] if isinstance(opt, str) else [str(o) for o in opt])
    type_files = [str(_p(t.replace("${SUMO_HOME}", str(sumo_home())))) for t in cfg["type_files"]]
    args.extend(["--type-files", ",".join(type_files)])
    return args


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    typer.echo(f"downloading {url} -> {rel(dest)}")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL from config
    tmp.rename(dest)


def osm_timestamp(pbf: Path) -> str:
    out = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(pbf)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out or "unknown"


def build_net(
    osm_xml: Path,
    net_out: Path,
    cfg: dict[str, Any],
    fixes_dir: Path,
    log: Path,
    strict_fixes: bool = True,
) -> dict[str, list[str]]:
    """netconvert + fix list. Returns the edges each fix resolved to."""
    net_out.parent.mkdir(parents=True, exist_ok=True)
    raw = net_out.with_name(net_out.name.replace(".net.xml", ".raw.net.xml"))
    cmd = [
        sumo_bin("netconvert"),
        "--osm-files",
        str(osm_xml),
        "-o",
        str(raw),
        *netconvert_args(cfg),
    ]
    run_cmd(cmd, log=log)
    resolved = apply_fixes(raw, net_out, fixes_dir, log=log, strict=strict_fixes)
    return resolved


app = typer.Typer(add_completion=False, help=__doc__)


def profile_of(config: Path) -> str | None:
    """Profile name of a config file, or None for a custom config."""
    return next((k for k, v in PROFILES.items() if v.resolve() == Path(config).resolve()), None)


def lane_prepass(
    osm: Path, cfg: dict[str, Any], log: Path, force: bool, out: Path | None = None
) -> tuple[Path, dict]:
    """Network v2 pre-pass: OSM XML with measured default tags on untagged ways (if configured).

    The config's `osm_out` is used only for the city build (input = the config's clip and default
    output); a build from `--osm` or to `--out` writes `<output stem>.lanes.osm.gz` beside its own
    output, so a test or experiment can never replace the city's pre-pass file. The file is
    rewritten unless its sidecar records the same input and stats hashes."""
    pre = cfg.get("lane_defaults")
    if not pre:
        return osm, {}
    stats = _p(pre["stats"])
    city = out is None and osm.absolute() == _p(cfg["osm_xml"]).absolute()
    if city and "osm_out" in pre:
        dst = _p(pre["osm_out"])
    else:
        base = out if out is not None else osm
        dst = base.with_name(base.name.removesuffix(".net.xml").split(".osm")[0] + ".lanes.osm.gz")
    key = {"input_hash": file_hash(osm), "stats_hash": file_hash(stats)}
    side = dst.with_name(dst.name + ".json")
    counts: dict[str, Any] = {}
    if force or not dst.exists() or not side.exists() or json.loads(side.read_text()) != key:
        counts = tag_osm(osm, dst, json.loads(stats.read_text())["defaults"])
        side.write_text(json.dumps(key))
        with log.open("a") as fh:
            fh.write(f"lane_defaults pre-pass {rel(osm)} -> {rel(dst)}: {json.dumps(counts)}\n")
    return dst, {
        "stats": rel(stats),
        **key,
        "osm_out": rel(dst),
        "osm_out_hash": file_hash(dst),
        **({"counts": counts} if counts else {}),
    }


@app.command()
def main(
    config: Path | None = typer.Option(
        None, help="build configuration YAML (overrides --network-profile)"
    ),
    network_profile: str = typer.Option(
        DEFAULT_PROFILE, help=f"one of {', '.join(PROFILES)} (default {DEFAULT_PROFILE})"
    ),
    osm: Path | None = typer.Option(None, help="use this OSM XML instead of the city clip"),
    out: Path | None = typer.Option(None, help="output .net.xml (default from config)"),
    fixes_dir: Path | None = typer.Option(None, help="fix list directory (default from config)"),
    download_extract: bool = typer.Option(False, "--download", help="(re)download the extract"),
    side_outputs: bool = typer.Option(True, help="write districts/buildings/viewer GeoJSON"),
    force: bool = typer.Option(False, help="rebuild every step"),
    strict_fixes: bool = typer.Option(True, help="fail if a fix matches no edge"),
) -> None:
    if config is None:
        if network_profile not in PROFILES:
            raise typer.BadParameter(f"unknown profile {network_profile!r}; use {list(PROFILES)}")
        config = PROFILES[network_profile]
    cfg = load_yaml(config)
    net = out or _p(cfg["net"])
    fixes = fixes_dir or _p(cfg["fixes_dir"])
    # custom outputs (tests, experiments) log next to the output; the city build logs to logs/
    # (named after the full output stem, so a variant never appends to another network's log)
    log_dir = net.parent if out is not None else REPO_ROOT / "logs"
    log = log_dir / f"build_city-{net.name.removesuffix('.net.xml')}.log"
    t0 = time.perf_counter()
    meta: dict[str, Any] = {
        "config": rel(config),
        "profile": profile_of(config),
        "sumo_version": sumo_version(),
        "sumo_home": str(sumo_home()),
    }

    if osm is None:
        extract = _p(cfg["extract"]["file"])
        if download_extract or not extract.exists():
            download(cfg["extract"]["url"], extract)
        poly = _p(cfg["polygon"])
        clip = _p(cfg["clip_pbf"])
        osm = _p(cfg["osm_xml"])
        if force or not _fresh(clip, extract, poly):
            run_cmd(
                [
                    "osmium",
                    "extract",
                    "-p",
                    str(poly),
                    str(extract),
                    "-o",
                    str(clip),
                    "--overwrite",
                ],
                log=log,
            )
        if force or not _fresh(osm, clip):
            run_cmd(["osmium", "cat", str(clip), "-o", str(osm), "--overwrite"], log=log)
        meta.update(
            extract=rel(extract),
            extract_timestamp=osm_timestamp(extract),
            polygon=rel(poly),
            polygon_hash=file_hash(poly),
        )
    meta["osm_input"] = rel(osm)
    meta["osm_hash"] = file_hash(osm)
    log.parent.mkdir(parents=True, exist_ok=True)
    osm, pre_meta = lane_prepass(osm, cfg, log, force, out)
    if pre_meta:
        meta["lane_defaults"] = pre_meta

    resolved = build_net(osm, net, cfg, fixes, log, strict_fixes=strict_fixes)
    meta["fixes"] = {f.id: resolved.get(f.id, []) for f in load_fixes(fixes)}
    stats = net_stats(net)
    meta["network"] = stats.as_dict()
    typer.echo(f"network {rel(net)}: {json.dumps(stats.as_dict())}")

    if side_outputs:
        clip_pbf = _p(cfg["clip_pbf"])
        districts = _p(cfg["districts"]["out"])
        n_d = geo.write_districts(clip_pbf, _p(cfg["polygon"]), districts, cfg["districts"])
        buildings = _p(cfg["buildings"]["out"])
        heights = load_yaml(_p(cfg["buildings"]["heights"]))
        n_b = geo.write_buildings(clip_pbf, buildings, heights)
        edges_out = _p(cfg["viewer"]["edges_out"])
        n_e = edges_geojson(net, edges_out)
        shutil.copyfile(districts, _p(cfg["viewer"]["districts_out"]))
        meta["side_outputs"] = {
            "districts": {"file": rel(districts), "features": n_d},
            "buildings": {
                "file": rel(buildings),
                "features": n_b,
                "mb": round(buildings.stat().st_size / 1e6, 1),
            },
            "viewer_edges": {"file": rel(edges_out), "features": n_e},
        }
    meta["build_seconds"] = round(time.perf_counter() - t0, 1)
    meta_path = net.with_name(net.name.replace(".net.xml", ".build.json"))
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    typer.echo(f"build metadata -> {rel(meta_path)} ({meta['build_seconds']} s)")


if __name__ == "__main__":
    os.environ.setdefault("LC_ALL", "C")
    app()
