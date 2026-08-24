"""Strict audit rules for crypto TSMOM sensitivity reports."""

from __future__ import annotations

from typing import Any


def audit_candidate(folds: list[dict[str, Any]], *, min_trades: float = 5.0) -> dict[str, Any]:
    """Reject negative, unstable, or degenerate candidates.

    A lower drawdown is not an improvement when it comes from never trading.
    This is deliberately a screening gate, not a promotion gate: passing it
    would still require the full multiple-testing and portfolio checks.
    """
    reasons: list[str] = []
    if len(folds) < 4:
        reasons.append("oos_folds<4")
    if any((fold.get("median_oos_return") or 0.0) <= 0.0 for fold in folds):
        reasons.append("nonpositive_median_oos_return")
    if any((fold.get("positive_oos_fraction") or 0.0) < 0.5 for fold in folds):
        reasons.append("positive_oos_fraction<0.5")
    if any((fold.get("median_oos_closed_trades") or 0.0) < min_trades for fold in folds):
        reasons.append("median_oos_closed_trades<5")
    if any((fold.get("median_full_max_drawdown") or 0.0) > 0.30 for fold in folds):
        reasons.append("max_drawdown>0.30")
    return {"approved_for_next_stage": not reasons, "reasons": reasons}


__all__ = ["audit_candidate"]
