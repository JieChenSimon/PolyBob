"""Leakage-resistant scoring primitives for forecast research.

These functions score already completed out-of-sample windows. They do not
select parameters or grant promotion; the existing promotion board remains the
only writer of trade permission.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TerminalForecastObservation:
    cluster: str
    last_close: float
    actual_close: float
    predicted_p10: float
    predicted_p50: float
    predicted_p90: float


@dataclass(frozen=True)
class ForecastEvaluation:
    n: int
    n_clusters: int
    mae: float
    naive_mae: float
    relative_mae: float
    direction_accuracy: float
    interval_80_coverage: float
    beats_naive: bool
    promotion_status: str = "lab_only"


def evaluate_terminal_forecasts(rows: Sequence[TerminalForecastObservation]) -> ForecastEvaluation:
    if not rows:
        raise ValueError("at least one completed out-of-sample forecast is required")
    errors = []
    naive_errors = []
    directions = []
    covered = []
    for row in rows:
        values = (row.last_close, row.actual_close, row.predicted_p10, row.predicted_p50, row.predicted_p90)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("forecast evaluation values must be finite and positive")
        if not row.predicted_p10 <= row.predicted_p50 <= row.predicted_p90:
            raise ValueError("forecast interval must satisfy p10 <= p50 <= p90")
        errors.append(abs(row.predicted_p50 - row.actual_close))
        naive_errors.append(abs(row.last_close - row.actual_close))
        predicted_direction = row.predicted_p50 - row.last_close
        actual_direction = row.actual_close - row.last_close
        directions.append((predicted_direction > 0) == (actual_direction > 0))
        covered.append(row.predicted_p10 <= row.actual_close <= row.predicted_p90)
    mae = sum(errors) / len(errors)
    naive_mae = sum(naive_errors) / len(naive_errors)
    relative = mae / naive_mae if naive_mae > 0 else math.inf
    return ForecastEvaluation(
        n=len(rows),
        n_clusters=len({row.cluster for row in rows}),
        mae=mae,
        naive_mae=naive_mae,
        relative_mae=relative,
        direction_accuracy=sum(directions) / len(directions),
        interval_80_coverage=sum(covered) / len(covered),
        beats_naive=relative < 1.0,
    )
