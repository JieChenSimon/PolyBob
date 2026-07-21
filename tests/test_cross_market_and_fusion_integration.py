"""Tests for the cross-market hedge OLS fix and proven-signal fusion wiring."""

from __future__ import annotations

import asyncio

import numpy as np

from strategies.cross_market_hedge import CrossMarketHedge, compute_hedge_ratio
from strategies.signal_fusion import SignalFusion


# --- cross-market hedge: OLS-derived hedge ratio --------------------------


def test_compute_hedge_ratio_recovers_known_beta():
    rng = np.random.default_rng(0)
    crypto = rng.normal(100, 5, 200)
    pm = 0.3 + 1.8 * crypto + rng.normal(0, 0.5, 200)  # true beta = 1.8
    ratio = compute_hedge_ratio(pm, crypto)
    assert abs(ratio - 1.8) < 0.1


def test_compute_hedge_ratio_falls_back_when_insufficient_data():
    assert compute_hedge_ratio([1.0], [1.0], default=0.42) == 0.42


def test_analyze_hedge_uses_ols_when_series_given():
    rng = np.random.default_rng(1)
    crypto = rng.normal(100, 5, 100)
    pm = 0.1 + 0.7 * crypto + rng.normal(0, 0.3, 100)
    hedge = CrossMarketHedge(None, None)
    result = hedge.analyze_hedge_opportunity(
        "SEC regulation ruling", "BTC", pm_series=pm, crypto_series=crypto
    )
    assert result is not None
    assert result["ratio_source"] == "ols_beta"
    assert abs(result["hedge_ratio"] - 0.7) < 0.1  # not the hardcoded 0.5


def test_analyze_hedge_defaults_without_series():
    hedge = CrossMarketHedge(None, None, default_hedge_ratio=0.5)
    result = hedge.analyze_hedge_opportunity("SEC regulation news", "ETH")
    assert result["ratio_source"] == "default"
    assert result["hedge_ratio"] == 0.5


def test_analyze_hedge_none_for_unrelated_event():
    hedge = CrossMarketHedge(None, None)
    assert hedge.analyze_hedge_opportunity("weather forecast", "BTC") is None


# --- proven signals wired into SignalFusion -------------------------------


def _fuse(features):
    return asyncio.run(SignalFusion().generate_signal(features))


def test_injected_tsmom_signal_participates_in_fusion():
    # A strong positive time-series-momentum score injected as a feature should
    # drive a bullish fused signal (BUY_YES).
    from libs.schemas import Side

    signal = _fuse({"market_id": "m1", "tsmom_signal": 0.9})
    assert signal is not None
    assert signal.side is Side.BUY_YES


def test_injected_reversal_signal_can_flip_direction():
    from libs.schemas import Side

    signal = _fuse({"market_id": "m1", "reversal_signal": -0.8})
    assert signal is not None
    assert signal.side is Side.SELL_YES


def test_fusion_ignores_absent_proven_signals():
    # No proven-signal features -> behaves exactly as before (no crash, no signal).
    assert _fuse({"market_id": "m1"}) is None
