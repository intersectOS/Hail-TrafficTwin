"""Apply (or reject) a ranked option of a recommendation and log the human decision.

    python -m strategist.approve <recommendation_id> [--option 1] [--actor name] [--reject]
                                 [--to-end] [--db runs/strategist/decisions.sqlite]

Applying = re-running the option from the same saved state with the same seed (to the horizon,
or to the scenario end with --to-end), writing its outputs (tripinfo, statistics, SUMO log) to
runs/strategist/<recommendation id>/applied-option<k>/, checking the measured ambulance time
against the prediction (identical inputs and seed => identical, reported if not), and appending
a `decision` record linked to the recommendation. This call is the only path by which an option,
in particular an approval_required one, is applied. One decision per recommendation.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import typer

from sim.common import REPO_ROOT, SYNTHETIC_LABEL, rel
from strategist import config as C
from strategist import decision_log as L
from strategist.evaluate import run_candidate
from strategist.snapshot import state_matches


def _tripinfo_tt(path: Path, vid: str) -> float | None:
    if not path.exists():
        return None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo" and el.get("id") == vid:
            return float(el.get("duration", "nan"))
    return None


def approve(
    recommendation_id: str,
    option: int = 1,
    actor: str = "operator",
    reject: bool = False,
    to_end: bool = False,
    db: Path = C.DEFAULT_DB,
    quiet: bool = False,
) -> dict[str, Any]:
    problems = L.verify(db)
    if problems:
        raise RuntimeError(f"decision log {db} fails verification: {problems}")
    rec = L.get(db, recommendation_id)
    if rec is None or rec["kind"] != "recommendation":
        raise KeyError(f"no recommendation {recommendation_id!r} in {db}")
    if L.decisions_for(db, recommendation_id):
        raise RuntimeError(f"recommendation {recommendation_id} already has a decision")
    run_dir = REPO_ROOT / json.loads(rec["recommendation"])["run_dir"]
    if not run_dir.exists():
        run_dir = Path(json.loads(rec["recommendation"])["run_dir"])
    report = json.loads((run_dir / "recommendation.json").read_text())
    if report["log_hash"] != rec["hash"]:
        raise RuntimeError("recommendation.json does not match its decision-log record")
    opts = {o["rank"]: o for o in report["options"]}
    if option not in opts:
        raise ValueError(f"option {option} not in the ranked options {sorted(opts)}")
    chosen = opts[option]
    decision: dict[str, Any] = {
        "label": SYNTHETIC_LABEL,
        "recommendation_id": recommendation_id,
        "option_rank": option,
        "candidate_id": chosen["candidate_id"],
        "option_label": chosen["label"],
        "classification": chosen["classification"],
        "predicted_travel_time_s": chosen["travel_time_s"],
    }
    if reject:
        decision["decision"] = "rejected"
    else:
        fork = report["fork"]
        state = (
            REPO_ROOT / fork["state"]
            if not Path(fork["state"]).is_absolute()
            else Path(fork["state"])
        )
        if not state_matches(state, report["snapshot"]["state_hash"]):
            raise RuntimeError(
                f"saved state {state} changed since the recommendation (hash mismatch)"
            )
        cand = next(c for c in report["candidate_specs"] if c["id"] == chosen["candidate_id"])
        horizon = fork["horizon_s"]
        if to_end:
            horizon = max(horizon, float(fork["end"]) - float(fork["t"]))
        out = run_dir / f"applied-option{option}"
        res = run_candidate(
            {**fork, "horizon_s": horizon, "candidate": cand, "run_dir": str(out), "outputs": True}
        )
        vid = f"ev.{fork['trip']['id']}.0"
        tripinfo_tt = _tripinfo_tt(out / "tripinfo.xml", vid)
        match = res["travel_time_s"] == chosen["travel_time_s"]
        decision.update(
            {
                "decision": "approved",
                "applied_run_dir": rel(out),
                "horizon_s": horizon,
                "measured_travel_time_s": res["travel_time_s"],
                "tripinfo_travel_time_s": tripinfo_tt,
                "matches_prediction": match,
                "signals_preempted": res["signals_preempted"],
                "junctions_held": res["junctions_held"],
                "rescue_lane_edges": res["rescue_lane_edges"],
                "background_veh_h": res["background_veh_h"],
                "wall_s": res["wall_s"],
            }
        )
        (out / "applied.json").write_text(
            json.dumps({**decision, "measured": res}, indent=2, default=str)
        )
    entry = L.append(
        db,
        "decision",
        rec["snapshot_id"],
        [chosen["candidate_id"]],
        [{"candidate_id": chosen["candidate_id"], "score": chosen["score"]}],
        {"recommendation_id": recommendation_id, "recommendation_hash": rec["hash"]},
        decision,
        actor=actor,
    )
    decision["decision_id"] = entry["record_id"]
    decision["log_hash"] = entry["hash"]
    if not quiet:
        typer.echo(_render(decision))
    return decision


def _render(d: dict[str, Any]) -> str:
    lines = [
        f"Decision {d['decision_id']} [{d['label']}]: {d['decision'].upper()} "
        f"option {d['option_rank']} ({d['option_label']}, {d['classification']}) "
        f"of {d['recommendation_id']}",
    ]
    if d["decision"] == "approved":
        lines.append(
            f"  applied from the saved state to +{d['horizon_s']:.0f} s: ambulance "
            f"{d['measured_travel_time_s']} s (predicted {d['predicted_travel_time_s']} s, "
            f"tripinfo {d['tripinfo_travel_time_s']} s) -> "
            f"{'MATCHES' if d['matches_prediction'] else 'DIFFERS from'} prediction"
        )
        lines.append(f"  outputs: {d['applied_run_dir']}/")
    lines.append(f"  logged with hash {d['log_hash']}")
    return "\n".join(lines)


app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    recommendation_id: str,
    option: int = typer.Option(1, help="rank of the option to apply"),
    actor: str = typer.Option("operator", help="who decides (recorded in the log)"),
    reject: bool = typer.Option(False, help="reject the option instead of applying it"),
    to_end: bool = typer.Option(False, help="apply until the scenario end instead of the horizon"),
    db: Path = typer.Option(C.DEFAULT_DB, help="decision log (SQLite)"),
) -> None:
    d = approve(recommendation_id, option, actor, reject, to_end, db)
    if d["decision"] == "approved" and not d["matches_prediction"]:
        raise typer.Exit(code=3)


if __name__ == "__main__":
    app()
