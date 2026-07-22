"""Explainable horizon scoring for altcoin discovery candidates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .models import Evidence, HorizonScore


PUMP_WEIGHTS: dict[str, dict[str, float]] = {
    "7d": {
        "floor": 0.10,
        "washout": 0.15,
        "control": 0.20,
        "accumulation": 0.20,
        "historical_operator_strength": 0.10,
        "futures_squeeze": 0.25,
    },
    "30d": {
        "floor": 0.20,
        "washout": 0.20,
        "control": 0.15,
        "accumulation": 0.25,
        "historical_operator_strength": 0.15,
        "futures_squeeze": 0.05,
    },
    "90d": {
        "floor": 0.25,
        "washout": 0.15,
        "control": 0.15,
        "accumulation": 0.25,
        "historical_operator_strength": 0.20,
        "futures_squeeze": 0.00,
    },
}

CASHOUT_WEIGHTS: dict[str, dict[str, float]] = {
    "7d": {
        "dev_concentration": 0.20,
        "insider_concentration": 0.15,
        "adverse_flow": 0.20,
        "audit_risk": 0.15,
        "liquidity_risk": 0.10,
        "abnormal_turnover": 0.05,
        "crowded_longs": 0.15,
        "unlock_risk": 0.00,
    },
    "30d": {
        "dev_concentration": 0.20,
        "insider_concentration": 0.15,
        "adverse_flow": 0.15,
        "audit_risk": 0.15,
        "liquidity_risk": 0.10,
        "abnormal_turnover": 0.05,
        "crowded_longs": 0.10,
        "unlock_risk": 0.10,
    },
    "90d": {
        "dev_concentration": 0.20,
        "insider_concentration": 0.15,
        "adverse_flow": 0.10,
        "audit_risk": 0.15,
        "liquidity_risk": 0.10,
        "abnormal_turnover": 0.05,
        "crowded_longs": 0.05,
        "unlock_risk": 0.20,
    },
}


@dataclass(frozen=True)
class CandidateScores:
    pump_potential: dict[str, HorizonScore]
    cashout_risk: dict[str, HorizonScore]
    coverage: float


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def weighted_score(values: dict[str, float], weights: dict[str, float]) -> HorizonScore:
    present = [
        (name, values[name], weight)
        for name, weight in weights.items()
        if weight > 0 and name in values
    ]
    expected_weight = sum(weight for weight in weights.values() if weight > 0)
    present_weight = sum(weight for _, _, weight in present)
    if present_weight <= 0:
        return HorizonScore(value=None, coverage=0.0)

    contributions = {
        name: 100.0 * value * weight / present_weight
        for name, value, weight in present
    }
    return HorizonScore(
        value=sum(contributions.values()),
        coverage=present_weight / expected_weight if expected_weight else 0.0,
        contributions=contributions,
    )


def score_candidate(evidence: Iterable[Evidence]) -> CandidateScores:
    observed: dict[str, float] = {}
    confidence: dict[str, float] = {}
    unsupported: set[str] = set()
    for item in evidence:
        if item.status == "unsupported":
            unsupported.add(item.name)
            continue
        if item.status != "observed" or isinstance(item.value, bool):
            continue
        if not isinstance(item.value, (int, float)) or not math.isfinite(float(item.value)):
            continue
        observed[item.name] = clamp(float(item.value))
        confidence[item.name] = clamp(item.confidence)

    pump = {
        horizon: weighted_score(observed, weights)
        for horizon, weights in PUMP_WEIGHTS.items()
    }
    cashout = {
        horizon: weighted_score(observed, weights)
        for horizon, weights in CASHOUT_WEIGHTS.items()
    }

    expected_importance: dict[str, float] = {}
    for matrix in (PUMP_WEIGHTS, CASHOUT_WEIGHTS):
        for weights in matrix.values():
            for name, weight in weights.items():
                expected_importance[name] = max(expected_importance.get(name, 0.0), weight)
    denominator = sum(
        weight
        for name, weight in expected_importance.items()
        if name in observed or name not in unsupported
    )
    numerator = sum(
        weight * confidence.get(name, 0.0)
        for name, weight in expected_importance.items()
        if name in observed
    )
    coverage = numerator / denominator if denominator else 0.0
    return CandidateScores(pump_potential=pump, cashout_risk=cashout, coverage=coverage)


def derive_market_features(
    *,
    closes: list[float],
    volumes: list[float],
    market_cap_percentile: float | None,
    top10_holder_percent: float | None,
    smart_money_inflow_percentile: float | None,
    buy_volume: float | None,
    sell_volume: float | None,
    holder_growth: float | None = None,
    concentration_change: float | None = None,
    negative_funding_score: float | None = None,
    open_interest_price_divergence: float | None = None,
    short_crowding_score: float | None = None,
) -> dict[str, float]:
    if not closes or len(closes) != len(volumes):
        raise ValueError("closes and volumes must be non-empty and have equal length")

    current = closes[-1]
    peak = max(closes)
    low = min(closes)
    drawdown = clamp((peak - current) / peak) if peak > 0 else 0.0
    proximity_to_low = (
        clamp(1.0 - (current - low) / (peak - low)) if peak > low else 0.5
    )
    inverse_cap = (
        clamp(1.0 - market_cap_percentile)
        if market_cap_percentile is not None
        else None
    )

    features: dict[str, float] = {}
    floor_parts = _renormalized(
        [(inverse_cap, 0.45), (drawdown, 0.35), (proximity_to_low, 0.20)]
    )
    if floor_parts is not None:
        features["floor"] = floor_parts

    recent_volumes = volumes[-3:]
    peak_volume = max(volumes)
    volume_contraction = (
        clamp(1.0 - (sum(recent_volumes) / len(recent_volumes)) / peak_volume)
        if peak_volume > 0
        else 0.0
    )
    recent_closes = closes[-5:]
    stability = (
        clamp(1.0 - (max(recent_closes) - min(recent_closes)) / abs(current))
        if current != 0
        else 0.0
    )
    features["washout"] = _renormalized(
        [(drawdown, 0.50), (volume_contraction, 0.30), (stability, 0.20)]
    ) or 0.0

    if top10_holder_percent is not None:
        features["control"] = clamp((top10_holder_percent - 20.0) / 70.0)

    total_volume = (buy_volume or 0.0) + (sell_volume or 0.0)
    buy_ratio = buy_volume / total_volume if buy_volume is not None and total_volume > 0 else None
    accumulation = _renormalized(
        [
            (smart_money_inflow_percentile, 0.40),
            (buy_ratio, 0.30),
            (holder_growth, 0.20),
            (concentration_change, 0.10),
        ]
    )
    if accumulation is not None:
        features["accumulation"] = accumulation

    max_rally = 0.0
    for start in range(len(closes)):
        start_price = closes[start]
        if start_price <= 0:
            continue
        window_peak = max(closes[start : min(len(closes), start + 8)])
        max_rally = max(max_rally, window_peak / start_price - 1.0)
    rally_score = clamp(max_rally / 2.0)
    repeat_rallies = sum(
        1
        for previous, following in zip(closes, closes[1:])
        if previous > 0 and following / previous - 1.0 >= 0.30
    )
    repeat_score = clamp(repeat_rallies / 3.0)
    features["historical_operator_strength"] = 0.60 * rally_score + 0.40 * repeat_score

    squeeze = _renormalized(
        [
            (negative_funding_score, 0.35),
            (open_interest_price_divergence, 0.35),
            (short_crowding_score, 0.30),
        ]
    )
    if squeeze is not None:
        features["futures_squeeze"] = squeeze
    return features


def _renormalized(parts: list[tuple[float | None, float]]) -> float | None:
    present = [(clamp(value), weight) for value, weight in parts if value is not None]
    denominator = sum(weight for _, weight in present)
    if denominator <= 0:
        return None
    return sum(value * weight for value, weight in present) / denominator
