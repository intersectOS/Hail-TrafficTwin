"""Classify actions and options (PROJECT.md 9.9 step 5).

auto_eligible: reversible, low impact. Rerouting the ambulance (advisory, affects only the
ambulance) is always auto-eligible. Signal preemption and the rescue-lane proxy are reversible
and auto-eligible while the option's measured added background delay stays within A-strat-018
and (preemption) at most A-strat-019 signals are preempted. Action types listed in A-strat-020
(closures; contraflow and evacuation orders in M7) always need approval. An option is
approval_required if any of its actions is. Approval-required options are only applied through
`python -m strategist.approve`.
"""

from __future__ import annotations

from typing import Any

from strategist import config as C

AUTO = "auto_eligible"
APPROVAL = "approval_required"


def approval_types() -> set[str]:
    return set(str(C.value("classification", "approval_actions")).split("|"))


def classify_action(
    action: dict[str, Any], measured: dict[str, Any], added_veh_h: float
) -> dict[str, Any]:
    max_veh_h = float(C.value("classification", "auto_max_added_veh_h"))
    max_sig = int(C.value("classification", "auto_max_signals"))
    kind = action["type"]
    if kind in approval_types():
        return {"type": kind, "class": APPROVAL, "rule": "always needs approval (A-strat-020)"}
    if kind == "reroute":
        return {"type": kind, "class": AUTO, "rule": "advisory reroute of the ambulance"}
    if added_veh_h > max_veh_h:
        return {
            "type": kind,
            "class": APPROVAL,
            "rule": f"added delay {added_veh_h:.2f} veh-h > {max_veh_h} (A-strat-018)",
        }
    if kind == "preempt" and measured["signals_preempted"] > max_sig:
        return {
            "type": kind,
            "class": APPROVAL,
            "rule": f"{measured['signals_preempted']} signals > {max_sig} (A-strat-019)",
        }
    return {"type": kind, "class": AUTO, "rule": "reversible, within A-strat-018/019"}


def classify_option(
    actions: list[dict[str, Any]], measured: dict[str, Any], added_veh_h: float
) -> dict[str, Any]:
    per = [classify_action(a, measured, added_veh_h) for a in actions]
    cls = APPROVAL if any(a["class"] == APPROVAL for a in per) else AUTO
    return {"classification": cls, "actions": per}
