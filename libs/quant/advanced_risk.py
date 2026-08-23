"""Replayable advanced risk, TCA and venue-certification primitives.

These functions deliberately return ``unknown`` when evidence is too thin;
they never manufacture a calibrated cost or capacity estimate from a handful
of fills.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TCAReport:
    status: str
    samples: int
    mean_slippage_bps: float | None
    p95_slippage_bps: float | None
    mean_fee_bps: float | None
    capacity_notional: float | None
    reason: str | None = None


def analyze_tca(
    fills: Iterable[Mapping[str, float]], *, min_samples: int = 30,
    participation_limit: float = 0.10,
) -> TCAReport:
    rows = list(fills)
    if min_samples <= 0 or participation_limit <= 0:
        raise ValueError("min_samples and participation_limit must be positive")
    if len(rows) < min_samples:
        return TCAReport("unknown", len(rows), None, None, None, None, "insufficient_fill_samples")
    slippages = sorted(abs(float(row["execution_price"]) / float(row["reference_price"]) - 1.0) * 10_000 for row in rows)
    fees = [abs(float(row.get("fee", 0.0))) / abs(float(row["execution_price"]) * float(row["size"])) * 10_000 for row in rows]
    depths = [float(row["depth"]) for row in rows if float(row.get("depth", 0.0)) > 0]
    if len(depths) < min_samples:
        return TCAReport("unknown", len(rows), None, None, None, None, "insufficient_depth_samples")
    p95 = slippages[min(len(slippages) - 1, int(len(slippages) * 0.95))]
    return TCAReport(
        "calibrated", len(rows), mean(slippages), p95, mean(fees),
        mean(depths) * participation_limit,
    )


@dataclass(frozen=True)
class StressReport:
    status: str
    portfolio_return: float
    equal_weight_return: float
    worst_case_return: float
    attribution: dict[str, float]


def stress_portfolio(
    returns: Mapping[str, Iterable[float]], weights: Mapping[str, float],
    shocks: Mapping[str, float],
) -> StressReport:
    if not returns or set(weights) != set(returns):
        return StressReport("unknown", 0.0, 0.0, 0.0, {})
    means = {symbol: mean(list(series)) for symbol, series in returns.items()}
    if any(symbol not in shocks for symbol in returns):
        return StressReport("unknown", 0.0, 0.0, 0.0, {})
    total_weight = sum(abs(float(weight)) for weight in weights.values())
    if total_weight <= 0:
        return StressReport("unknown", 0.0, 0.0, 0.0, {})
    normalized = {symbol: float(weight) / total_weight for symbol, weight in weights.items()}
    attribution = {symbol: normalized[symbol] * (means[symbol] + float(shocks[symbol])) for symbol in returns}
    portfolio = sum(attribution.values())
    equal = mean(means[symbol] + float(shocks[symbol]) for symbol in returns)
    return StressReport("tested", portfolio, equal, portfolio, attribution)


@dataclass(frozen=True)
class AdapterCertification:
    status: str
    checks: dict[str, bool]
    missing: tuple[str, ...]


REQUIRED_ADAPTER_CHECKS = ("submit", "fill", "cancel", "disconnect", "reconnect", "idempotency")


def certify_adapter(checks: Mapping[str, bool]) -> AdapterCertification:
    missing = tuple(name for name in REQUIRED_ADAPTER_CHECKS if checks.get(name) is not True)
    return AdapterCertification("certified" if not missing else "blocked", dict(checks), missing)


__all__ = ["AdapterCertification", "TCAReport", "StressReport", "analyze_tca", "certify_adapter", "stress_portfolio"]
