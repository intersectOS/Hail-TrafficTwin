"""scenario_report.json and scenario_report.md (baseline vs scenario)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KPI_ROWS = (
    ("vehicles_inserted", "vehicles inserted"),
    ("background_completed", "background trips completed"),
    ("vehicles_running_at_end", "running at end"),
    ("vehicles_waiting_at_end", "waiting to insert at end"),
    ("mean_travel_time_s", "mean travel time (s)"),
    ("mean_delay_s", "mean delay = timeLoss (s)"),
    ("mean_depart_delay_s", "mean insertion delay = departDelay (s)"),
    ("mean_speed_kmh", "mean speed (km/h)"),
    ("vkt", "VKT (veh-km)"),
    ("vht", "VHT (veh-h)"),
    ("queue_max_m", "longest queue, max (m)"),
    ("queue_p95_m", "longest queue, p95 over steps (m)"),
    ("queue_max_veh", "max halted on one edge (veh)"),
    ("halted_p95_veh", "halted in window, p95 (veh)"),
    ("teleports", "teleports"),
    ("teleports_jam", "jam teleports"),
    ("rerouted_vehicles", "vehicles rerouted by closures"),
)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _short(d: dict[str, Any], limit: int = 140) -> str:
    text = ", ".join(
        f"{k}={len(v) if isinstance(v, list | dict) and len(v) > 4 else v}"
        for k, v in d.items()
        if k not in ("t", "event", "action")
    )
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render_md(report: dict[str, Any], meta: dict[str, Any]) -> str:
    b, s = report["kpis"]["baseline"], report["kpis"]["scenario"]
    lines = [
        f"# Scenario report: {report['scenario']} on window `{report['window']}`",
        "",
        f"**{report['label']}**. "
        + ("Fictional scenario parameters (PROJECT.md section 11)." if report["fictional"] else ""),
        "",
        f"{report['title']}. Seed {report['seed']}, {report['begin']:.0f}-{report['end']:.0f} s, "
        f"Tier B (micro), {meta['sumo_version']}. Run `{meta['run_id']}`; config hash "
        f"`{meta['config_hash']}`, network hash `{meta['network_hash']}`, demand hash "
        f"`{meta['population_hash']}`.",
        "",
        f"Baseline: {report['baseline_definition']}.",
        "",
        "| KPI | baseline | scenario | delta | delta % |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, name in KPI_ROWS:
        d = report["delta"].get(key, {})
        lines.append(
            f"| {name} | {_fmt(b.get(key))} | {_fmt(s.get(key))} | {_fmt(d.get('delta'))} | "
            f"{_fmt(d.get('pct'))} |"
        )
    gb, gs = report["gridlock"]["baseline"], report["gridlock"]["scenario"]
    lines.append(
        f"| gridlock (onset s) | {gb['gridlock']} ({_fmt(gb['onset_s'])}) | "
        f"{gs['gridlock']} ({_fmt(gs['onset_s'])}) | | |"
    )
    if gs["rules_fired"]:
        lines.append("")
        lines.append(f"Gridlock rules fired in the scenario: {gs['rules_fired']}.")
    if report["emergency"]["scenario"]:
        lines += [
            "",
            "## Emergency trips",
            "",
            "| vehicle | free flow (s) | baseline TT (s) | scenario TT (s) | TT / free flow | "
            "TT / baseline | strategist |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for r in report["emergency"]["scenario"]:
            lines.append(
                f"| {r['vehicle']} | {_fmt(r['free_flow_s'])} | "
                f"{_fmt(r.get('baseline_travel_time_s'))} | {_fmt(r['travel_time_s'])} | "
                f"{_fmt(r['ratio_to_free_flow'])} | {_fmt(r.get('ratio_to_baseline'))} | "
                f"{'requested (M6, not applied)' if r['strategist'] else 'no'} |"
            )
    if report["convoy"]:
        lines += ["", "## Motorcade", ""]
        for c in report["convoy"]:
            summ = report["event_summaries"].get(c["event"], {})
            lines.append(
                f"- {c['event']}: {c['completed']}/{c['vehicles']} convoy vehicles completed, mean "
                f"travel time {_fmt(c['mean_travel_time_s'])} s (free flow {c['free_flow_s']} s); "
                f"{summ.get('junctions_held', 0)} junctions held, mean hold "
                f"{_fmt(summ.get('mean_hold_s'))} s, max {_fmt(summ.get('max_hold_s'))} s; "
                f"closures still active at end: {summ.get('closures_still_active', '-')}."
            )
    flows_b, flows_s = (
        report["event_edges_flow"]["baseline"],
        report["event_edges_flow"]["scenario"],
    )
    if flows_b:
        lines += [
            "",
            "## Vehicles entering event edges",
            "",
            "| edge | baseline | scenario |",
            "|---|---:|---:|",
        ]
        lines += [f"| `{e}` | {flows_b[e]:.0f} | {flows_s[e]:.0f} |" for e in flows_b]
    lines += [
        "",
        "## Top queued edges (scenario)",
        "",
        "| edge | max queue (m) | at (s) | max halted (veh) |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| `{q['edge']}` | {q['max_queue_m']} | {q['at_s']:.0f} | {q['max_halted_veh']} |"
        for q in s["top_queued_edges"]
    ]
    lines += [
        "",
        "## Event log (scenario)",
        "",
        "| t (s) | event | action | details |",
        "|---:|---|---|---|",
    ]
    lines += [
        f"| {e['t']:.0f} | {e['event']} | {e['action']} | {_short(e)} |"
        for e in report["event_log"]
    ]
    w = meta["wall_s"]
    lines += [
        "",
        f"Wall time: baseline {w['baseline_sim']} s + {w['baseline_post']} s post, scenario "
        f"{w['scenario_sim']} s + {w['scenario_post']} s post, total {w['total']} s "
        f"({'parallel' if w['parallel'] else 'serial'}).",
        "",
        f"Assumptions used ({len(report['assumption_ids'])}): "
        + ", ".join(report["assumption_ids"])
        + " (docs/assumptions-trackB.md, docs/assumptions.md).",
        "",
    ]
    return "\n".join(lines)


def write_reports(out: Path, report: dict[str, Any], meta: dict[str, Any]) -> None:
    (out / "scenario_report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "scenario_report.md").write_text(render_md(report, meta))
