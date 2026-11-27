"""Cost rules over real Cost Explorer data.

Uses the per-day series that the daily cost summary already contains, so no
extra billed request is made. Today's partial day is excluded. Amounts are
what AWS reported; nothing is projected.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.governance_common import (
    CONFIRMED,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    Evaluation,
)

__all__ = ["THRESHOLDS", "evaluate_costs"]

THRESHOLDS = {
    "min_days": 14,
    "increase_ratio": 0.25,        # +25% week over week
    "increase_min_usd": 1.0,       # and at least $1 more
    "high_ratio": 1.0,             # +100%
    "high_min_usd": 5.0,           # and at least $5 more
}


def _ev(rule_id: str, title: str) -> Evaluation:
    return Evaluation("ACCOUNT", "aws-account", "global", rule_id, "COST", title, "aws:ce")


def _week_increase(daily: List[Dict[str, Any]]) -> Dict[str, Any]:
    ev = _ev("COST_WEEKLY_INCREASE", "Spend increased week over week")
    complete = daily[:-1]  # the last entry is today, which is still accruing
    if len(complete) < THRESHOLDS["min_days"]:
        ev.cite("ce:GetCostAndUsage", "Only %d complete day(s) of daily cost data." % len(complete))
        return ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Two full weeks of daily cost data are needed.",
                         confidence="low", missing_information=["14 complete days of cost data."])
    previous, recent = complete[-14:-7], complete[-7:]
    prev_total = sum(d["total"] for d in previous)
    recent_total = sum(d["total"] for d in recent)
    delta = recent_total - prev_total
    ev.cite("ce:GetCostAndUsage", "%s to %s: $%.2f." % (previous[0]["date"], previous[-1]["date"], prev_total))
    ev.cite("ce:GetCostAndUsage", "%s to %s: $%.2f." % (recent[0]["date"], recent[-1]["date"], recent_total))
    ratio = (delta / prev_total) if prev_total > 0 else (float("inf") if delta > 0 else 0.0)
    if delta < THRESHOLDS["increase_min_usd"] or ratio < THRESHOLDS["increase_ratio"]:
        return ev.result(NO_ISSUE)

    def by_service(days):
        totals: Dict[str, float] = {}
        for day in days:
            for name, value in (day.get("services") or {}).items():
                totals[name] = totals.get(name, 0.0) + value
        return totals

    before, after = by_service(previous), by_service(recent)
    drivers = sorted(((after.get(n, 0) - before.get(n, 0), n) for n in set(before) | set(after)), reverse=True)
    for change, name in drivers[:3]:
        if change > 0:
            ev.cite("ce:GetCostAndUsage", "%s: +$%.2f (from $%.2f to $%.2f)." % (name, change, before.get(name, 0), after.get(name, 0)))
    high = delta >= THRESHOLDS["high_min_usd"] and ratio >= THRESHOLDS["high_ratio"]
    pct = "%.0f%%" % (ratio * 100) if ratio != float("inf") else "from zero"
    result = ev.result(
        CONFIRMED, "HIGH" if high else "MEDIUM",
        "The last 7 complete days cost $%.2f more than the 7 days before (%s)." % (delta, pct),
        "Check whether the increase in the services listed was expected.",
        ["Open Cost Explorer filtered to the listed services and the last two weeks.",
         "Match the increase to deployments or usage changes.",
         "If unexpected, find the resources responsible before changing anything."],
        confidence="high",
        missing_information=["Whether the change was planned."],
    )
    result["measured_usd"] = round(delta, 2)
    return result


def evaluate_costs(daily_summary: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not daily_summary or not isinstance(daily_summary.get("daily"), list):
        ev = _ev("COST_WEEKLY_INCREASE", "Spend increased week over week")
        ev.cite("ce:GetCostAndUsage", "No per-day cost series is available yet (it is stored from the next daily refresh).")
        return [ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Daily cost data is not available.", confidence="low",
                          missing_information=["Daily cost series."])]
    return [_week_increase(daily_summary["daily"])]
