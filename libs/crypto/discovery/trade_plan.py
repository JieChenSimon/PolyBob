"""Structural trade plans derived from observed market candles."""

from __future__ import annotations

import math

from .models import PositionSize, TradePlan


RISK_FRACTIONS = {
    "conservative": 0.005,
    "balanced": 0.01,
    "aggressive": 0.02,
}


def risk_quantity(
    equity: float,
    fraction: float,
    entry: float,
    stop: float,
) -> float:
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("entry and stop must differ")
    return equity * fraction / distance


def build_trade_plan(
    *,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    pump_potential: float,
    cashout_risk: float,
    coverage: float,
    account_equity: float | None,
    liquidity_usd: float | None,
    volume_24h_usd: float | None,
    quantity_step: float | None,
    min_pump_potential: float = 70.0,
    max_cashout_risk: float = 45.0,
    min_coverage: float = 0.70,
    min_liquidity_usd: float = 500_000.0,
    min_volume_24h_usd: float = 1_000_000.0,
) -> TradePlan:
    lengths = {len(closes), len(highs), len(lows), len(volumes)}
    if lengths != {len(closes)} or len(closes) < 15:
        return TradePlan(eligible=False, vetoes=["INSUFFICIENT_CANDLES"])

    vetoes: list[str] = []
    if pump_potential < min_pump_potential:
        vetoes.append("PUMP_POTENTIAL_BELOW_MINIMUM")
    if cashout_risk > max_cashout_risk:
        vetoes.append("CASHOUT_RISK_ABOVE_MAXIMUM")
    if coverage < min_coverage:
        vetoes.append("COVERAGE_BELOW_MINIMUM")
    if liquidity_usd is None or liquidity_usd < min_liquidity_usd:
        vetoes.append("LIQUIDITY_BELOW_MINIMUM")
    if volume_24h_usd is None or volume_24h_usd < min_volume_24h_usd:
        vetoes.append("VOLUME_BELOW_MINIMUM")

    atr = _average_true_range(highs, lows, closes, period=14)
    if atr <= 0:
        return TradePlan(eligible=False, vetoes=[*vetoes, "INVALID_VOLATILITY_STRUCTURE"])

    support = min(lows[-5:])
    anchored_vwap = _weighted_average(closes[-10:], volumes[-10:])
    support_band = (support, support + atr)
    vwap_band = (anchored_vwap - 0.75 * atr, anchored_vwap + 0.75 * atr)
    entry_low = max(support_band[0], vwap_band[0])
    entry_high = min(support_band[1], vwap_band[1])
    if entry_low >= entry_high:
        return TradePlan(eligible=False, vetoes=[*vetoes, "NO_STRUCTURAL_ENTRY"])

    if closes[-1] > entry_high + 1.5 * atr:
        vetoes.append("PRICE_OVEREXTENDED")

    stop = support - 0.25 * atr
    entry_mid = (entry_low + entry_high) / 2.0
    unit_risk = entry_mid - stop
    minimum_target = entry_mid + 2.0 * unit_risk
    resistance_candidates = sorted(level for level in highs if level >= minimum_target)
    target_1 = (
        min(resistance_candidates[0], entry_mid + 3.0 * unit_risk)
        if resistance_candidates
        else minimum_target
    )
    target_2 = max(
        target_1,
        min(max(highs), entry_mid + 4.0 * unit_risk),
        entry_mid + 3.0 * unit_risk,
    )
    reward_risk = (target_1 - entry_mid) / unit_risk if unit_risk > 0 else 0.0
    if reward_risk < 2.0:
        vetoes.append("REWARD_RISK_BELOW_MINIMUM")

    position_sizes = _position_sizes(
        account_equity=account_equity,
        entry=entry_mid,
        stop=stop,
        volume_24h_usd=volume_24h_usd,
        quantity_step=quantity_step,
    )
    return TradePlan(
        eligible=not vetoes,
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        reward_risk=reward_risk,
        vetoes=vetoes,
        position_sizes=position_sizes,
    )


def _average_true_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    period: int,
) -> float:
    ranges: list[float] = []
    for index in range(1, len(closes)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    window = ranges[-period:]
    return sum(window) / len(window) if window else 0.0


def _weighted_average(values: list[float], weights: list[float]) -> float:
    denominator = sum(max(weight, 0.0) for weight in weights)
    if denominator <= 0:
        return sum(values) / len(values)
    return sum(value * max(weight, 0.0) for value, weight in zip(values, weights)) / denominator


def _position_sizes(
    *,
    account_equity: float | None,
    entry: float,
    stop: float,
    volume_24h_usd: float | None,
    quantity_step: float | None,
) -> dict[str, PositionSize]:
    result: dict[str, PositionSize] = {}
    for name, fraction in RISK_FRACTIONS.items():
        if account_equity is None or account_equity <= 0:
            result[name] = PositionSize(risk_fraction=fraction)
            continue
        quantity = risk_quantity(account_equity, fraction, entry, stop)
        if volume_24h_usd is not None and volume_24h_usd > 0 and entry > 0:
            quantity = min(quantity, volume_24h_usd * 0.0005 / entry)
        quantity = _floor_to_step(quantity, quantity_step)
        result[name] = PositionSize(
            risk_fraction=fraction,
            quantity=quantity,
            notional_usd=quantity * entry,
            max_loss_usd=quantity * abs(entry - stop),
        )
    return result


def _floor_to_step(value: float, step: float | None) -> float:
    if step is None or step <= 0:
        return value
    return math.floor((value + 1e-12) / step) * step
