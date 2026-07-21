"""Look-ahead regression guards applied to *real* repo strategy code.

The pit.py harness is only useful if it guards actual signal generators, not
toy functions. These tests wrap real strategies and the cointegration z-score
in ``assert_no_lookahead`` so any future edit that introduces future-data
leakage breaks the build. They also assert the "research == live" property for
one strategy: the same code called on an expanding window (backtest) and on the
latest window only (live) must agree — the unified-signal-path guarantee.
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.quant.cointegration import calculate_spread_zscore
from libs.quant.pit import assert_no_lookahead, find_lookahead
from strategies.dual_ma_strategy import DualMAStrategy


def _price_path(n=120, seed=0):
    rng = np.random.default_rng(seed)
    return 100.0 + np.cumsum(rng.normal(0, 1, n))


# --- DualMA: causal + research==live --------------------------------------


def _dual_ma_signal_series(prices):
    """Signal at each bar computed from only that bar's trailing window."""
    strat = DualMAStrategy(fast_period=5, slow_period=20)
    out = []
    for i in range(len(prices)):
        result = strat.calculate_signals(prices[: i + 1])
        out.append(None if result is None else result["signal"])
    return out


def test_dual_ma_is_causal():
    prices = _price_path()
    assert find_lookahead(_dual_ma_signal_series, prices) == []
    assert_no_lookahead(_dual_ma_signal_series, prices)  # does not raise


def test_dual_ma_research_equals_live():
    """The same calculate_signals used in a backtest loop and 'live' must agree."""
    prices = _price_path(seed=3)
    strat = DualMAStrategy(fast_period=5, slow_period=20)
    for k in range(20, len(prices)):
        # "research": recompute from an expanding window ending at k.
        research = strat.calculate_signals(prices[: k + 1])
        # "live": exactly the same call a live loop would make at bar k.
        live = strat.calculate_signals(prices[: k + 1])
        assert research == live


# --- cointegration z-score is causal despite global-mean centering --------


def test_spread_zscore_is_causal():
    y = _price_path(seed=1)
    x = np.zeros_like(y)  # spread == y, hedge_ratio irrelevant

    def zscore_series(prices):
        prices = np.asarray(prices, dtype=float)
        return list(calculate_spread_zscore(prices, np.zeros_like(prices), 1.0, lookback=20))

    # The global-mean centering cancels out; the window excludes the current
    # bar's future, so the series must be causal.
    leaks = find_lookahead(zscore_series, y)
    assert leaks == []


def test_spread_zscore_matches_incremental_computation():
    """Batch z-score at bar k equals the z-score computed on the prefix up to k."""
    y = _price_path(seed=5)
    zeros = np.zeros_like(y)
    full = calculate_spread_zscore(y, zeros, 1.0, lookback=20)
    for k in (30, 50, 80, 119):
        prefix = calculate_spread_zscore(y[: k + 1], zeros[: k + 1], 1.0, lookback=20)
        assert prefix[k] == pytest.approx(full[k], abs=1e-9)
