"""Results table of policy runs (markdown) from their policy_report.json files.

python -m sim.policies.summary runs/remote_work_30 runs/friday ...      # prints the table
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sim.common import SYNTHETIC_LABEL

COLUMNS = [
    ("mean_delay_s", "mean delay"),
    ("am_peak_mean_delay_s", "AM-peak delay"),
    ("vkt", "VKT"),
    ("vht", "VHT"),
    ("co2_t", "CO2"),
    ("peak_spreading_top_hour_share", "top-hour share"),
    ("trips_completed", "trips"),
]


def row(report: dict) -> str:
    k = {r["kpi"]: r for r in report["kpis"]}

    def cell(key: str) -> str:
        r = k.get(key)
        if r is None or r["delta_pct"] is None:
            return "n/a"
        return f"{r['delta_pct']:+.1f} %"

    tele = k.get("teleport_share", {})
    tele_txt = f"{tele.get('baseline', 0):.2f} -> {tele.get('policy', 0):.2f}" if tele else "n/a"
    ctrl = report.get("control")
    ref = ctrl["raw_baseline"] if ctrl else report["compare_baseline"]
    base = ref.split("-f")[0].removeprefix("baseline-") + (" (matched control)" if ctrl else "")
    cells = [f"`{report['policy']}`", base, *[cell(c) for c, _ in COLUMNS], tele_txt]
    return "| " + " | ".join(cells) + " |"


def table(run_dirs: list[Path]) -> str:
    head = [
        "policy",
        "vs baseline",
        *[label for _, label in COLUMNS],
        "teleports/veh (base -> policy)",
    ]
    lines = [f"Changes vs the matching baseline, same seed ({SYNTHETIC_LABEL}).", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]  # fmt: skip
    for d in run_dirs:
        lines.append(row(json.loads((d / "policy_report.json").read_text())))
    return "\n".join(lines) + "\n"


def main(run_dirs: list[Path]) -> None:
    typer.echo(table(run_dirs))


if __name__ == "__main__":
    typer.run(main)
