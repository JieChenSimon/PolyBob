"""Fail-closed evaluation of the user's per-instrument return targets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class ReturnTargetDecision:
    status: str
    annualized_return: float | None
    monthly_returns: dict[str, float]
    failed_months: tuple[str, ...]
    min_complete_months: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "annualized_return": self.annualized_return,
            "monthly_returns": self.monthly_returns,
            "failed_months": list(self.failed_months),
            "min_complete_months": self.min_complete_months,
            "reason": self.reason,
        }


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed


def _equity(value: Any) -> float:
    return float(value.equity if hasattr(value, "equity") else value["equity"])


def monthly_returns(points: Iterable[Any]) -> dict[str, float]:
    """Return calendar-month returns from chronological equity observations."""
    ordered = sorted(((_timestamp(p.ts if hasattr(p, "ts") else p["ts"]), _equity(p))
                      for p in points), key=lambda item: item[0])
    if len(ordered) < 2:
        return {}
    first_by_month: dict[str, tuple[datetime, float]] = {}
    last_by_month: dict[str, tuple[datetime, float]] = {}
    for stamp, equity in ordered:
        month = stamp.strftime("%Y-%m")
        first_by_month.setdefault(month, (stamp, equity))
        last_by_month[month] = (stamp, equity)
    result: dict[str, float] = {}
    previous_end: float | None = None
    for month in sorted(last_by_month):
        start = first_by_month[month][1]
        end = last_by_month[month][1]
        base = previous_end if previous_end is not None else start
        if base > 0:
            result[month] = end / base - 1.0
        previous_end = end
    return result


def evaluate_return_target(
    points: Iterable[Any], *, min_annualized_return: float = 0.50,
    min_monthly_return: float = 0.15, min_complete_months: int = 12,
) -> ReturnTargetDecision:
    """Evaluate both targets; insufficient history is UNKNOWN, never PASS."""
    ordered = sorted(((_timestamp(p.ts if hasattr(p, "ts") else p["ts"]), _equity(p))
                      for p in points), key=lambda item: item[0])
    months = monthly_returns(points)
    if len(ordered) < 2 or len(months) < min_complete_months:
        return ReturnTargetDecision(
            status="UNKNOWN", annualized_return=None, monthly_returns=months,
            failed_months=(), min_complete_months=min_complete_months,
            reason=f"need {min_complete_months} complete calendar months; observed {len(months)}",
        )
    start_stamp, start_equity = ordered[0]
    end_stamp, end_equity = ordered[-1]
    years = max((end_stamp - start_stamp).total_seconds() / (365.25 * 86400), 1 / 365.25)
    annualized = (end_equity / start_equity) ** (1.0 / years) - 1.0 if start_equity > 0 else None
    failed = tuple(month for month, value in months.items() if value < min_monthly_return)
    passed = annualized is not None and annualized >= min_annualized_return and not failed
    return ReturnTargetDecision(
        status="PASS" if passed else "FAIL", annualized_return=annualized,
        monthly_returns=months, failed_months=failed,
        min_complete_months=min_complete_months,
        reason="both annualized and monthly targets passed" if passed else "annualized or monthly target failed",
    )


__all__ = ["ReturnTargetDecision", "evaluate_return_target", "monthly_returns"]
