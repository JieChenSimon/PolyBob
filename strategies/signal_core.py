"""Shared causal signal cores — the single source of truth a strategy uses in
*both* research (backtest) and live trading (P7).

The problem this solves
-----------------------
Look-ahead bias and research/live skew are the two errors that most reliably
turn a great backtest into a losing live strategy. They share a root cause:
the backtest and the live loop compute the signal with *different code*, so a
subtly non-causal (or simply divergent) backtest can never be trusted to
predict live behaviour. The only durable fix is architectural — one pure,
causal function that both paths import and call.

The pattern (follow this for every strategy)
--------------------------------------------
1. Put the decision logic in a **pure function of a price/feature window whose
   last element is the current bar** — no I/O, no clock, no future access. A
   function that can only see ``window[: current + 1]`` is causal *by
   construction*.
2. Expose a **``*_signals(series, params)`` companion** that maps a whole series
   to per-bar signals by replaying the pure function over expanding (and, where
   a strategy uses a rolling lookback, bounded) windows. This is what a
   vectorless backtest calls, and what :func:`libs.quant.pit.assert_no_lookahead`
   proves causal.
3. Have the **live strategy call the same pure function** on its rolling buffer.
   Because both paths share the function, ``research == live`` is guaranteed,
   not hoped for — and provable with an equivalence test.

This module currently hosts the spread-reversion core; ``SpreadReversionStrategy``
(live/research strategy) and the backtest/lookahead tests both route through it.
New strategies should add their core here and follow the same three steps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SpreadReversionParams:
    """Parameters for the spread mean-reversion entry core.

    Mirrors :class:`strategies.spread_reversion.SpreadReversionStrategy` config so
    the live strategy and a backtest can be driven from identical settings.
    """

    entry_threshold_std: float = 2.0
    min_spread_bps: float = 50.0
    zscore_stop_std: float = 4.0
    min_samples: int = 20
    lookback_window: int = 60


@dataclass(frozen=True)
class ReversionSignal:
    """Outcome of the entry core for one bar.

    ``enter`` is the causal decision; ``z_score`` / ``mean`` / ``std`` are
    surfaced so a caller can size / annotate without recomputing.
    """

    enter: bool
    z_score: float
    mean: float
    std: float


def mean_std(window: Sequence[float]) -> tuple[float, float]:
    """Unbiased sample mean/std (ddof=1); std is 0.0 for < 2 samples."""
    n = len(window)
    if n == 0:
        return 0.0, 0.0
    mean = sum(window) / n
    if n < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in window) / (n - 1)
    return mean, math.sqrt(variance)


def spread_reversion_entry(
    window: Sequence[float], params: SpreadReversionParams | None = None
) -> ReversionSignal:
    """Causal spread-reversion entry decision for the *last* bar of ``window``.

    ``window`` is the spread (bps) history whose final element is the current
    observation. Only values in ``window`` are ever read, so the decision cannot
    depend on the future. An entry fires when the current spread is an unusually
    wide (> ``entry_threshold_std`` σ) yet not *structurally broken*
    (>= ``zscore_stop_std`` σ ⇒ stand aside, don't catch a falling knife) and
    the absolute spread clears ``min_spread_bps``.
    """
    params = params or SpreadReversionParams()
    n = len(window)
    if n < params.min_samples:
        return ReversionSignal(False, 0.0, 0.0, 0.0)
    mean, std = mean_std(window)
    if std == 0:
        return ReversionSignal(False, 0.0, mean, 0.0)
    current = window[-1]
    z_score = (current - mean) / std
    if z_score >= params.zscore_stop_std:
        return ReversionSignal(False, z_score, mean, std)
    enter = z_score > params.entry_threshold_std and current > params.min_spread_bps
    return ReversionSignal(bool(enter), z_score, mean, std)


def spread_reversion_signals(
    spreads: Sequence[float], params: SpreadReversionParams | None = None
) -> list[int]:
    """Per-bar entry signals (1 = enter, 0 = flat) over a whole spread series.

    Replays :func:`spread_reversion_entry` over bounded rolling windows that end
    at each bar, exactly reproducing the live strategy's ``deque(maxlen=lookback)``
    behaviour. Aligned 1:1 with ``spreads`` and causal, so it is both the
    backtest signal generator and the subject of ``assert_no_lookahead``.
    """
    params = params or SpreadReversionParams()
    lookback = max(1, params.lookback_window)
    out: list[int] = []
    for k in range(len(spreads)):
        start = max(0, k + 1 - lookback)
        window = spreads[start : k + 1]
        out.append(1 if spread_reversion_entry(window, params).enter else 0)
    return out


__all__ = [
    "ReversionSignal",
    "SpreadReversionParams",
    "mean_std",
    "spread_reversion_entry",
    "spread_reversion_signals",
]
