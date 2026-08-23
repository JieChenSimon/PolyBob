"""Small, explicit data/model SLO evaluation used by runtime status and alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable


@dataclass(frozen=True)
class SLOReport:
    status: str
    freshness_seconds: float | None
    coverage: float
    failure_rate: float
    duplicate_rate: float
    model_runs: int
    model_failures: int
    alerts: tuple[str, ...]


def evaluate_slo(
    records: Iterable[dict[str, Any]], *, now: datetime, expected_count: int,
    freshness_budget: timedelta, model_runs: int = 0, model_failures: int = 0,
) -> SLOReport:
    rows = list(records)
    if expected_count <= 0:
        raise ValueError("expected_count must be positive")
    timestamps = [row.get("timestamp") for row in rows if isinstance(row.get("timestamp"), datetime)]
    latest = max(timestamps) if timestamps else None
    age = (now - latest).total_seconds() if latest is not None else None
    failures = sum(1 for row in rows if row.get("status") in {"failed", "blocked", "unknown"})
    keys = [row.get("id") for row in rows if row.get("id") is not None]
    duplicate_rate = 1.0 - len(set(keys)) / len(keys) if keys else 0.0
    coverage = min(len(rows) / expected_count, 1.0)
    alerts: list[str] = []
    if age is None or age > freshness_budget.total_seconds():
        alerts.append("freshness_budget_exceeded")
    if coverage < 1.0:
        alerts.append("coverage_incomplete")
    if failures:
        alerts.append("source_failures_present")
    if duplicate_rate > 0:
        alerts.append("duplicate_records_present")
    if model_failures:
        alerts.append("model_runs_failed")
    return SLOReport(
        "alert" if alerts else "ok", age, coverage,
        failures / len(rows) if rows else 1.0, duplicate_rate,
        model_runs, model_failures, tuple(alerts),
    )


__all__ = ["SLOReport", "evaluate_slo"]
