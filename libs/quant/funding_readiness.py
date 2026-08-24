"""Research readiness gates for perpetual funding-rate history.

Funding is part of the return of a perpetual position.  A short recent window
can make a strategy look testable while providing no independent out-of-sample
evidence.  This module keeps that boundary explicit and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import pandas as pd


@dataclass(frozen=True)
class FundingReadiness:
    symbol: str
    status: str
    observations: int
    start: str | None
    end: str | None
    span_days: int
    oos_folds: int
    sources: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "observations": self.observations,
            "start": self.start,
            "end": self.end,
            "span_days": self.span_days,
            "oos_folds": self.oos_folds,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
        }


def assess_funding_frame(
    symbol: str,
    frame: pd.DataFrame,
    *,
    min_observations: int = 252,
    min_span_days: int = 365,
    min_fold_observations: int = 40,
    required_folds: int = 4,
) -> FundingReadiness:
    """Assess one symbol without filling gaps or treating missing funding as 0."""
    if frame.empty:
        return FundingReadiness(symbol, "BLOCKED", 0, None, None, 0, 0, (), ("no_rows",))

    dates = pd.to_datetime(frame["event_date"], errors="coerce").dt.date
    valid = dates.notna()
    if "rate" not in frame.columns or "source" not in frame.columns:
        return FundingReadiness(symbol, "UNKNOWN", int(valid.sum()), None, None, 0, 0, (), ("missing_required_columns",))

    frame = frame.loc[valid].copy()
    dates = dates.loc[valid]
    valid_rates = pd.to_numeric(frame["rate"], errors="coerce").notna()
    frame = frame.loc[valid_rates]
    dates = dates.loc[valid_rates]
    if frame.empty:
        return FundingReadiness(symbol, "UNKNOWN", 0, None, None, 0, 0, (), ("no_valid_rates",))

    unique_dates = sorted(set(dates.tolist()))
    start, end = unique_dates[0], unique_dates[-1]
    span_days = (end - start).days + 1
    observations = len(unique_dates)
    oos_folds = min(required_folds, observations // min_fold_observations)
    sources = tuple(sorted({str(v) for v in frame["source"].dropna().tolist()}))
    reasons: list[str] = []
    if observations < min_observations:
        reasons.append(f"observations<{min_observations}")
    if span_days < min_span_days:
        reasons.append(f"span_days<{min_span_days}")
    if oos_folds < required_folds:
        reasons.append(f"oos_folds<{required_folds}")
    return FundingReadiness(
        symbol,
        "READY" if not reasons else "BLOCKED",
        observations,
        start.isoformat(),
        end.isoformat(),
        span_days,
        oos_folds,
        sources,
        tuple(reasons),
    )


def assess_store(
    *,
    min_observations: int = 252,
    min_span_days: int = 365,
    min_fold_observations: int = 40,
    required_folds: int = 4,
) -> dict[str, Any]:
    """Return an auditable readiness report from the local bitemporal store."""
    from libs.data import store

    results = []
    for symbol in store.symbols(store.FUNDING_RATES):
        results.append(
            assess_funding_frame(
                symbol,
                store.read(store.FUNDING_RATES, symbol),
                min_observations=min_observations,
                min_span_days=min_span_days,
                min_fold_observations=min_fold_observations,
                required_folds=required_folds,
            )
        )
    ready = [r for r in results if r.ready]
    status = "READY" if ready else ("BLOCKED" if results else "UNKNOWN")
    return {
        "dataset": store.FUNDING_RATES.name,
        "status": status,
        "source_of_truth": "local_bitemporal_store",
        "coverage": store.coverage(store.FUNDING_RATES),
        "requirements": {
            "min_observations": min_observations,
            "min_span_days": min_span_days,
            "min_fold_observations": min_fold_observations,
            "required_folds": required_folds,
        },
        "ready_symbols": [r.symbol for r in ready],
        "blocked_symbols": [r.symbol for r in results if r.status == "BLOCKED"],
        "unknown_symbols": [r.symbol for r in results if r.status == "UNKNOWN"],
        "results": [r.as_dict() for r in results],
        "reason": "no symbol satisfies the minimum historical and OOS requirements" if not ready else None,
    }


def research_symbols(report: dict[str, Any]) -> tuple[str, ...]:
    """Return only symbols that are allowed into a funding research run."""
    return tuple(
        symbol for symbol in report.get("ready_symbols", [])
        if report.get("status") == "READY"
    )


__all__ = ["FundingReadiness", "assess_funding_frame", "assess_store", "research_symbols"]
