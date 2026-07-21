"""Optimizer tests: spread-reversion & statistical-arbitrage improvements.

Covers the new causal z-score entry/stop logic, the OU half-life gate, the
time-alignment fix, and a look-ahead guard proving the reversion signal at bar
k does not change when future bars are appended.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from libs.quant.pit import assert_no_lookahead, find_lookahead
from strategies.spread_reversion import SpreadReversionStrategy
from strategies.statistical_arbitrage import StatisticalArbitrageStrategy


def _run(coro):
    return asyncio.run(coro)


# --- spread reversion -------------------------------------------------------


def _feed_reversion(strat, spreads, *, market="m1", mid=0.5):
    last = None
    for s in spreads:
        last = _run(
            strat.generate_signal(
                {"market_id": market, "spread_bps": s, "mid_price": mid,
                 "bid_price": mid * 0.99}
            )
        )
    return last


def test_reversion_needs_history_then_fires_on_wide_spread():
    strat = SpreadReversionStrategy(
        {"min_samples": 20, "min_spread_bps": 50.0, "zscore_stop_std": 6.0}
    )
    rng = np.random.default_rng(2)
    # 30 calm bars ~40bps with real dispersion (std ~15), staying below the
    # 50bps min-spread gate, then a moderate spike landing ~3 sigma out.
    calm = [40.0 + float(rng.normal(0, 15)) for _ in range(30)]
    _feed_reversion(strat, calm)  # priming; may or may not fire on calm noise
    signal = _feed_reversion(strat, [90.0])  # ~3 sigma above mean, wide enough
    assert signal is not None
    assert 0.5 <= signal.confidence <= 0.95
    assert "z=" in signal.reason


def test_reversion_zscore_stop_suppresses_extreme_dislocation():
    """A blow-out far beyond the stop band is treated as a structural break."""
    strat = SpreadReversionStrategy(
        {"min_samples": 20, "min_spread_bps": 50.0, "zscore_stop_std": 4.0}
    )
    calm = [40.0 + (i % 3) for i in range(30)]
    _feed_reversion(strat, calm)
    # Enormous spike -> z well beyond the 4-sigma stop -> no entry.
    signal = _feed_reversion(strat, [5000.0])
    assert signal is None


def test_reversion_confirm_bars_filters_single_spike():
    strat = SpreadReversionStrategy(
        {"min_samples": 20, "min_spread_bps": 50.0, "confirm_bars": 3}
    )
    calm = [40.0 + (i % 3) for i in range(30)]
    _feed_reversion(strat, calm)
    # One wide bar is not enough with confirm_bars=3.
    assert _feed_reversion(strat, [200.0]) is None
    # Two more sustained wide bars -> now confirmed.
    _feed_reversion(strat, [200.0])
    assert _feed_reversion(strat, [200.0]) is not None


def test_reversion_signal_is_causal():
    """assert_no_lookahead: the per-bar signal must not use future bars."""
    rng = np.random.default_rng(7)
    spreads = np.abs(50.0 + rng.normal(0, 20, 80))

    def signal_series(seq):
        strat = SpreadReversionStrategy({"min_samples": 20, "min_spread_bps": 30.0})
        out = []
        for s in seq:
            sig = _run(
                strat.generate_signal(
                    {"market_id": "m", "spread_bps": float(s), "mid_price": 0.5}
                )
            )
            out.append(None if sig is None else round(sig.confidence, 6))
        return out

    assert find_lookahead(signal_series, spreads) == []
    assert_no_lookahead(signal_series, spreads)


# --- statistical arbitrage --------------------------------------------------


def _feed_pair(strat, series_a, series_b):
    """Interleave two market price streams into the strategy."""
    last = None
    for a, b in zip(series_a, series_b):
        _run(strat.generate_signal({"market_id": "A", "mid_price": a,
                                     "ask_price": a * 1.01, "bid_price": a * 0.99}))
        last = _run(strat.generate_signal({"market_id": "B", "mid_price": b,
                                           "ask_price": b * 1.01, "bid_price": b * 0.99}))
    return last


def test_stat_arb_fires_on_mean_reverting_dislocation():
    """A cointegrated pair whose spread is a moderate AR(1) mean-reverter.

    Spread half-life ~2 bars (in the tradable band); the final spread is pushed
    to ~3 sigma so the z-score clears the entry band but not the 4-sigma stop.
    """
    strat = StatisticalArbitrageStrategy(
        {"min_samples": 30, "correlation_threshold": 0.6,
         "entry_threshold_std": 2.0, "min_half_life": 1.0, "max_half_life": 50.0}
    )
    rng = np.random.default_rng(3)
    n = 60
    a = 100.0 + np.cumsum(rng.normal(0, 0.5, n))  # common random-walk factor
    # AR(1) mean-reverting spread: phi=0.6 -> half-life = -ln2/ln(0.6) ~ 1.36.
    spread = np.zeros(n)
    for i in range(1, n):
        spread[i] = 0.6 * spread[i - 1] + rng.normal(0, 0.4)
    std = spread.std()
    spread[-1] = 3.0 * std  # deterministic ~3 sigma dislocation
    b = a + spread  # B tracks A plus the stationary spread
    # _feed_pair evaluates B (aligned with A) on the final bar and returns it.
    final = _feed_pair(strat, a, b)
    assert final is not None
    assert "hl=" in final.reason
    assert "SELL" in str(final.side)  # spread B-A stretched positive -> short B


def test_stat_arb_rejects_non_mean_reverting_pair():
    """Two independent random walks -> spread not mean-reverting -> no trade."""
    strat = StatisticalArbitrageStrategy(
        {"min_samples": 30, "correlation_threshold": 0.0,
         "entry_threshold_std": 1.0, "min_half_life": 1.0, "max_half_life": 20.0}
    )
    rng = np.random.default_rng(11)
    a = 100.0 + np.cumsum(rng.normal(0, 1.0, 60))
    b = 100.0 + np.cumsum(rng.normal(0, 1.0, 60))  # unrelated walk
    signal = _feed_pair(strat, a, b)
    assert signal is None


def test_half_life_estimator_positive_for_mean_reverting_series():
    strat = StatisticalArbitrageStrategy()
    # Strong mean reversion: s_t = 0.5*s_{t-1} around mean 0.
    rng = np.random.default_rng(1)
    s = [0.0]
    for _ in range(200):
        s.append(0.5 * s[-1] + rng.normal(0, 0.1))
    hl = strat._half_life(s, sum(s) / len(s))
    assert hl is not None and hl > 0
