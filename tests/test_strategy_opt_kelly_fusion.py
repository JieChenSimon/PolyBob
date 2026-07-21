"""Optimizer tests: Kelly sizing + SignalFusion softmax weighting.

Covers the fractional-Kelly hard cap, volatility scaling, drawdown throttle,
and the softmax/recency/floor weight-learning in SignalFusion (while asserting
the normalization + monotonicity contract downstream feedback relies on).
"""
from __future__ import annotations

import asyncio

import pytest

from strategies.kelly_position import KellyPositionStrategy
from strategies.signal_fusion import SignalFusion


def _run(coro):
    return asyncio.run(coro)


def _kelly_features(**over):
    base = {
        "market_id": "m1",
        "mid_price": 0.5,
        "depth_imbalance": 0.6,
        "spread_bps": 20.0,
        "bid_price": 0.49,
        "ask_price": 0.51,
    }
    base.update(over)
    return base


# --- Kelly ------------------------------------------------------------------


def test_kelly_volatility_scaling_shrinks_size():
    strat = KellyPositionStrategy({"target_volatility_bps": 100.0})
    calm = _run(strat.generate_signal(_kelly_features(volatility_bps=50.0)))
    wild = _run(strat.generate_signal(_kelly_features(volatility_bps=400.0)))
    assert calm is not None and wild is not None
    # Higher realized vol -> strictly smaller position.
    assert wild.size < calm.size


def test_kelly_drawdown_throttle_reduces_size():
    strat = KellyPositionStrategy({"max_drawdown_throttle": 0.5})
    flat = _run(strat.generate_signal(_kelly_features(current_drawdown=0.0)))
    drawn = _run(strat.generate_signal(_kelly_features(current_drawdown=0.4)))
    assert flat is not None and drawn is not None
    assert drawn.size < flat.size


def test_kelly_hard_cap_bounds_optimal_fraction():
    """Even with an extreme edge, f* is capped so size never explodes."""
    capped = KellyPositionStrategy({"max_kelly_fraction": 0.1, "kelly_fraction": 1.0})
    uncapped = KellyPositionStrategy({"max_kelly_fraction": 1.0, "kelly_fraction": 1.0})
    f = _kelly_features(depth_imbalance=0.9, spread_bps=1.0)
    c = _run(capped.generate_signal(f))
    u = _run(uncapped.generate_signal(f))
    assert c is not None and u is not None
    assert c.size < u.size


def test_kelly_rejects_negative_edge():
    strat = KellyPositionStrategy()
    # Negative imbalance below threshold magnitude -> no signal path anyway;
    # use a tiny imbalance that yields sub-threshold edge.
    sig = _run(strat.generate_signal(_kelly_features(depth_imbalance=0.0)))
    assert sig is None


def test_update_equity_tracks_drawdown():
    strat = KellyPositionStrategy()
    assert strat.update_equity(100.0) == 0.0
    assert strat.update_equity(120.0) == 0.0  # new peak
    assert strat.update_equity(90.0) == pytest.approx(0.25)  # (120-90)/120


# --- SignalFusion weighting -------------------------------------------------


def test_fusion_weights_stay_normalized_and_reward_winner():
    fusion = SignalFusion()
    before = dict(fusion.weights)
    for _ in range(15):
        fusion.update_performance("rsi", 1.0)   # wins
        fusion.update_performance("macd", -1.0)  # losses
    after = fusion.weights
    assert sum(after.values()) == pytest.approx(1.0)
    assert after["rsi"] > before["rsi"]
    assert after["macd"] < before["macd"]
    # Winner should beat the loser after learning.
    assert after["rsi"] > after["macd"]


def test_fusion_weight_floor_keeps_signals_alive():
    fusion = SignalFusion({"weight_floor": 0.05, "weight_temperature": 0.1})
    # Punish one signal relentlessly; it must not collapse below the floor.
    for _ in range(40):
        fusion.update_performance("bollinger", -1.0)
        fusion.update_performance("rsi", 1.0)
    assert fusion.weights["bollinger"] >= 0.05 - 1e-9
    assert sum(fusion.weights.values()) == pytest.approx(1.0)


def test_fusion_softmax_sharper_than_linear():
    """Lower temperature concentrates weight more on the winning signal."""
    sharp = SignalFusion({"weight_temperature": 0.2})
    soft = SignalFusion({"weight_temperature": 1.5})
    for _ in range(15):
        for f in (sharp, soft):
            f.update_performance("rsi", 1.0)
            f.update_performance("macd", -1.0)
    assert sharp.weights["rsi"] > soft.weights["rsi"]


def test_fusion_recency_mean_helper():
    fusion = SignalFusion({"recency_decay": 0.5})
    # Recent wins should dominate older losses.
    recent_win = fusion._recency_weighted_mean([0.0, 0.0, 1.0])
    recent_loss = fusion._recency_weighted_mean([1.0, 1.0, 0.0])
    assert recent_win > 0.5
    assert recent_loss < 0.5
    assert fusion._recency_weighted_mean([]) == 0.5
