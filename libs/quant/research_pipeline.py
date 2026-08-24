"""Reusable real-data parameter search with walk-forward and cost gates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np
from libs.backtest import simulate_position_series


@dataclass(frozen=True)
class CandidateResult:
    params: dict[str, int]
    train_sharpe: float
    test_return: float
    test_sharpe: float
    test_max_drawdown: float
    test_observations: int
    cost_bps: float


@dataclass(frozen=True)
class WalkForwardResult:
    symbol: str
    folds: tuple[CandidateResult, ...]
    selected_params: tuple[dict[str, int], ...]
    oos_return: float | None
    oos_sharpe: float | None
    oos_max_drawdown: float | None
    baseline_return: float | None
    status: str


def _returns(prices: np.ndarray, positions: np.ndarray, cost_bps: float) -> np.ndarray:
    if len(prices) < 2:
        return np.array([], dtype=float)
    returns, _ = simulate_position_series(
        prices, positions, cost_bps=cost_bps, allow_short=bool(np.min(positions) < 0)
    )
    return returns


def _metrics(returns: np.ndarray) -> tuple[float, float, float]:
    if len(returns) < 2:
        return 0.0, float(np.prod(1.0 + returns) - 1.0) if len(returns) else 0.0, 0.0
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    drawdown = float(np.max(1.0 - equity / peak[1:]))
    std = float(np.std(returns, ddof=1))
    sharpe = float(np.mean(returns) / std * math.sqrt(252.0)) if std > 0 else 0.0
    return sharpe, float(equity[-1] - 1.0), drawdown


def moving_average_positions(prices: Sequence[float], *, fast: int, slow: int) -> np.ndarray:
    """Causal long/flat MA signal; signal at i only uses prices through i."""
    values = np.asarray(prices, dtype=float)
    if fast <= 0 or slow <= fast or len(values) == 0:
        raise ValueError("require 0 < fast < slow")
    fast_ma = np.convolve(values, np.ones(fast) / fast, mode="valid")
    slow_ma = np.convolve(values, np.ones(slow) / slow, mode="valid")
    positions = np.zeros(len(values), dtype=float)
    for i in range(slow - 1, len(values)):
        positions[i] = 1.0 if fast_ma[i - fast + 1] > slow_ma[i - slow + 1] else 0.0
    return positions


def walk_forward_symbol(
    symbol: str,
    prices: Sequence[float],
    *,
    candidates: Sequence[Mapping[str, int]],
    cost_bps: float,
    train_size: int = 252,
    test_size: int = 63,
    step: int = 63,
    purge_bars: int = 0,
    embargo_bars: int = 0,
    position_builder: Callable[..., np.ndarray] = moving_average_positions,
) -> WalkForwardResult:
    """Select parameters only on each train window and score the following OOS window.

    ``purge_bars`` removes observations adjacent to the fit boundary and
    ``embargo_bars`` leaves a genuine unavailable-information gap before OOS.
    Both are expressed in bars so the contract works for crypto, equities and
    irregularly sampled data without assuming calendar-day spacing.
    """
    if min(train_size, test_size, step) <= 0 or min(purge_bars, embargo_bars) < 0:
        raise ValueError("window sizes must be positive and gaps non-negative")
    values = np.asarray(prices, dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        return WalkForwardResult(symbol, (), (), None, None, None, None, "unknown_bad_prices")
    fold_results: list[CandidateResult] = []
    oos_returns: list[np.ndarray] = []
    selected: list[dict[str, int]] = []
    start = 0
    while start + train_size + purge_bars + embargo_bars + test_size <= len(values):
        raw_train_end = start + train_size
        train = values[start:raw_train_end - purge_bars]
        test_start = raw_train_end + embargo_bars
        test = values[test_start:test_start + test_size]
        if len(train) < 2 or len(test) < 2:
            break
        scored: list[tuple[float, Mapping[str, int]]] = []
        for raw_params in candidates:
            params = {k: int(v) for k, v in raw_params.items()}
            positions = position_builder(train, **params)
            train_returns = _returns(train, positions, cost_bps)
            sharpe, _, _ = _metrics(train_returns)
            scored.append((sharpe, params))
        if not scored:
            break
        _, best = max(scored, key=lambda item: item[0])
        selected.append(dict(best))
        # Strategy builders may use different warm-up keys (e.g. ``lookback``
        # for mean reversion rather than ``slow`` for moving averages).
        warmup = max(int(best.get("slow", best.get("lookback", 2))), 2)
        test_prices = np.concatenate((train[-warmup:], test))
        test_positions = position_builder(test_prices, **best)[-len(test):]
        test_returns = _returns(test, test_positions, cost_bps)
        train_positions = position_builder(train, **best)
        train_sharpe, _, _ = _metrics(_returns(train, train_positions, cost_bps))
        test_sharpe, test_return, test_dd = _metrics(test_returns)
        fold_results.append(CandidateResult(dict(best), train_sharpe, test_return,
                                              test_sharpe, test_dd, len(test_returns), cost_bps))
        oos_returns.append(test_returns)
        start += step
    if not oos_returns:
        return WalkForwardResult(symbol, tuple(fold_results), tuple(selected), None, None, None, None,
                                 "unknown_insufficient_history")
    joined = np.concatenate(oos_returns)
    oos_sharpe, oos_return, oos_dd = _metrics(joined)
    baseline = values[-len(joined) - 1:]
    baseline_return = float(baseline[-1] / baseline[0] - 1.0) if len(baseline) > 1 else None
    status = "candidate_beats_baseline" if baseline_return is not None and oos_return > baseline_return else "tested_no_edge"
    return WalkForwardResult(symbol, tuple(fold_results), tuple(selected), oos_return,
                             oos_sharpe, oos_dd, baseline_return, status)


def aggregate_portfolio(results: Sequence[WalkForwardResult]) -> dict[str, float | int | str | None]:
    usable = [r for r in results if r.oos_return is not None]
    if not usable:
        return {"status": "unknown", "symbols": 0, "oos_return": None,
                "oos_sharpe": None, "oos_max_drawdown": None}
    returns = np.array([float(r.oos_return) for r in usable])
    paired = [(float(r.oos_return), float(r.baseline_return))
              for r in usable if r.baseline_return is not None]
    baseline = np.array([item[1] for item in paired])
    excess = np.array([item[0] - item[1] for item in paired])
    folds = [fold for result in usable for fold in result.folds]
    return {
        "status": (
            "tested_edge"
            if len(excess) and float(np.median(excess)) > 0 and float(np.median(returns)) > 0
            else "tested_no_edge"
        ),
        "symbols": len(usable),
        "oos_return": float(np.mean(returns)),
        "oos_sharpe": float(np.mean([r.oos_sharpe or 0.0 for r in usable])),
        "oos_max_drawdown": float(np.mean([r.oos_max_drawdown or 0.0 for r in usable])),
        "baseline_return": float(np.mean(baseline)) if len(baseline) else None,
        "excess_return": float(np.mean(excess)) if len(excess) else None,
        "median_excess_return": float(np.median(excess)) if len(excess) else None,
        "positive_excess_fraction": float(np.mean(excess > 0)) if len(excess) else None,
        "positive_symbol_fraction": float(np.mean(returns > 0)),
        "median_oos_return": float(np.median(returns)),
        "positive_fold_fraction": (
            float(np.mean([fold.test_return > 0 for fold in folds])) if folds else None
        ),
        "folds": len(folds),
    }


__all__ = ["CandidateResult", "WalkForwardResult", "aggregate_portfolio", "moving_average_positions", "walk_forward_symbol"]
