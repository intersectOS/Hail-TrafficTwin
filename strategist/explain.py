"""Plain-language reasons built only from measured facts (PROJECT.md 9.9 step 4).

Every number in a sentence is a registered fact: {value, text, source}, where `source` names
the measured field it comes from (what-if results, the snapshot at T, the horizon setting) or
the arithmetic on measured fields. Edge and junction ids are written in backticks so the test
can tell them from numbers. Nothing is estimated or invented here.
"""

from __future__ import annotations

from typing import Any


class Facts:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, name: str, value: float | int, fmt: str, source: str) -> str:
        text = format(value, fmt)
        self.items[name] = {"value": value, "text": text, "source": source}
        return text


def _plural(n: int | float, word: str) -> str:
    return word if n == 1 else f"{word}s"


def explain(
    cand: dict[str, Any],
    res: dict[str, Any],
    ns_cand: dict[str, Any],
    ns_res: dict[str, Any],
    added_veh_h: float,
    horizon_s: float,
    halted_at_t: dict[str, int],
    without: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """`without[action type]` = measured result of the same route with that action removed
    (None if that run does not exist). An action is named as a cause only if that run was
    measured slower; otherwise it is stated as a plain fact."""
    f = Facts()
    without = without or {}
    label = cand["label"]
    faster = False
    hz = f.add("horizon_s", horizon_s, ".0f", "settings.evaluation.horizon_s")
    if res["arrived"]:
        tt = f.add("tt_s", res["travel_time_s"], ".0f", "option.travel_time_s")
        if ns_res["arrived"]:
            gain = ns_res["travel_time_s"] - res["travel_time_s"]
            g = f.add(
                "gain_s", abs(gain), ".0f", "abs(no_strategy.travel_time_s - option.travel_time_s)"
            )
            ns = f.add("ns_tt_s", ns_res["travel_time_s"], ".0f", "no_strategy.travel_time_s")
            faster = gain > 0
            if gain > 0:
                cmp = f"{g} s faster than no strategy ({ns} s)"
            elif gain < 0:
                cmp = f"{g} s slower than no strategy ({ns} s)"
            else:
                cmp = f"as fast as no strategy ({ns} s)"
        else:
            faster = True
            cmp = f"while without a strategy the ambulance had not arrived after {hz} s"
        s1 = f"{label} gets the ambulance there in {tt} s, {cmp}"
    else:
        s1 = f"{label} does not get the ambulance there within the {hz} s horizon"
    reasons = []
    ns_edges = ns_res["ambulance_edge_s"]
    if ns_edges:
        # edge where the no-strategy ambulance lost most time against free flow (measured)
        lost = {e: s - ns_cand["edge_ff_s"].get(e, 0.0) for e, s in ns_edges.items()}
        e = max(sorted(lost), key=lambda k: lost[k])
        if lost[e] > 0 and cand["route"] != ns_cand["route"]:
            se = f.add("ns_edge_s", ns_edges[e], ".0f", f"no_strategy.ambulance_edge_s[{e}]")
            if e not in set(cand["route"]):
                r = f"it avoids `{e}`, where the no-strategy ambulance spent {se} s"
                n = halted_at_t.get(e, 0)
                if n:
                    nh = f.add("ns_edge_halted", n, "d", f"snapshot.halted_by_edge[{e}]")
                    r += f" with {nh} {_plural(n, 'vehicle')} halted there at dispatch"
            else:
                oe = f.add(
                    "opt_edge_s",
                    res["ambulance_edge_s"].get(e, 0.0),
                    ".0f",
                    f"option.ambulance_edge_s[{e}]",
                )
                r = f"it also uses `{e}` but spends {oe} s there instead of {se} s"
            reasons.append(r)
        elif lost[e] > 0 and e in res["ambulance_edge_s"]:
            se = f.add("ns_edge_s", ns_edges[e], ".0f", f"no_strategy.ambulance_edge_s[{e}]")
            oe = f.add(
                "opt_edge_s", res["ambulance_edge_s"][e], ".0f", f"option.ambulance_edge_s[{e}]"
            )
            reasons.append(f"it spends {oe} s on `{e}` instead of {se} s")
    side_facts = []
    for kind, field, key, what in (
        ("preempt", "signals_preempted", "signals", "signal"),
        ("rescue_lane", "rescue_lane_edges", "rescue_edges", "edge"),
    ):
        if not res[field]:
            continue
        n = f.add(key, res[field], "d", f"option.{field}")
        noun = f"{n} {_plural(res[field], what)}"
        if kind == "preempt":
            phrase, fact = f"preempting {noun}", f"preempts {noun}"
        else:
            phrase, fact = f"the rescue lane on {noun}", f"reserves a rescue lane on {noun}"
        alt = without.get(kind)
        own = (
            alt["travel_time_s"] - res["travel_time_s"]
            if alt and alt["arrived"] and res["arrived"]
            else None
        )
        if own is not None and own > 0:
            o = f.add(
                f"{key}_own_s", own, ".0f", f"without[{kind}].travel_time_s - option.travel_time_s"
            )
            reasons.append(f"{phrase} saves {o} s against the same route without it")
        else:
            side_facts.append(fact)
    if reasons:
        joined = (
            reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + " and " + reasons[-1]
        )
        # causal wording only when the option is measured faster; otherwise facts only
        s1 += f" because {joined}" if faster else f"; {joined}"
    if side_facts:
        # no measured gain of its own (or no run without it): stated, not claimed as a cause
        s1 += "; it also " + " and ".join(side_facts)
    d = f.add(
        "added_veh_h",
        abs(added_veh_h),
        ".2f",
        "abs(option.background_veh_h - no_strategy.background_veh_h)",
    )
    if d == format(0.0, ".2f"):
        s2 = f"Over the {hz} s horizon background delay is unchanged ({d} vehicle-hours difference)"
    else:
        verb = "adds" if added_veh_h > 0 else "saves"
        s2 = (
            f"Over the {hz} s horizon it {verb} {d} vehicle-hours of background delay "
            "versus no strategy"
        )
    if res["junctions_held"]:
        j = f.add("junctions_held", res["junctions_held"], "d", "option.junctions_held")
        hs = f.add("hold_s", res["hold_s_total"], ".0f", "option.hold_s_total")
        entries = "entry" if res["junctions_held"] == 1 else "entries"
        s2 += f" and holds {j} side {entries} for {hs} s in total"
    if res["route_halted_max"]:
        w = res["route_halted_max"][0]
        nh = f.add("worst_halted", w["halted"], "d", f"option.route_halted_max[0] ({w['edge']})")
        veh = _plural(w["halted"], "vehicle")
        s2 += f"; the longest queue on its route was {nh} halted {veh} on `{w['edge']}`"
    return {"text": f"{s1}. {s2}.", "facts": f.items}
