"""Tests for the real-data layer contracts and the edge hypotheses.

Note the project constraint: real data drives every *result*. These tests use
small synthetic arrays only to verify code paths (causality, shape, direction),
never to judge whether an edge is profitable — that is what the real-data
scoreboard is for.
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.data.real_sources import DailyBars, DataUnavailable, _tencent_code
from libs.quant.edges import (
    OHLCV_EDGES,
    SINGLE_ASSET_EDGES,
    breakout,
    cross_sectional_momentum_positions,
    funding_contrarian,
    gap_continuation,
    gap_fade,
    range_contraction,
    range_expansion,
    trend_vol_scaled,
)
from libs.quant.pit import find_lookahead


def _bars(n=120, seed=0):
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 1, n))
    opens = closes + rng.normal(0, 0.5, n)
    highs = np.maximum(opens, closes) + abs(rng.normal(0, 0.5, n))
    lows = np.minimum(opens, closes) - abs(rng.normal(0, 0.5, n))
    return DailyBars(
        "TEST", "altcoin", [f"2026-01-{i%28+1:02d}" for i in range(n)],
        list(closes), "test", opens=list(opens), highs=list(highs),
        lows=list(lows), volumes=list(abs(rng.normal(1000, 200, n))),
    )


# --- data layer contracts --------------------------------------------------


def test_tencent_code_infers_exchange():
    assert _tencent_code("600519") == "sh600519"      # Shanghai
    assert _tencent_code("000001") == "sz000001"      # Shenzhen
    assert _tencent_code("300750") == "sz300750"      # ChiNext
    assert _tencent_code("159558.SZ") == "sz159558"   # ETF with suffix
    assert _tencent_code("920819") == "bj920819"      # Beijing


def test_tencent_code_rejects_invalid():
    with pytest.raises(DataUnavailable):
        _tencent_code("AAPL")


def test_daily_bars_usability_and_ohlc_flags():
    bars = _bars(250)
    assert bars.is_usable and bars.has_ohlc
    thin = DailyBars("X", "altcoin", ["2026-01-01"], [1.0], "test")
    assert not thin.is_usable and not thin.has_ohlc


# --- edge causality (the non-negotiable property) --------------------------


@pytest.mark.parametrize("name", sorted(SINGLE_ASSET_EDGES))
def test_close_only_edges_are_causal(name):
    prices = list(100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 90)))
    fn = SINGLE_ASSET_EDGES[name]
    assert find_lookahead(lambda p: list(fn(np.asarray(p, float))), prices) == []


def test_ohlcv_edges_produce_aligned_positions():
    bars = _bars()
    for name, fn in OHLCV_EDGES.items():
        pos = fn(bars)
        assert len(pos) == len(bars), name
        assert np.all(np.abs(pos) <= 1.0), name


# --- direction semantics ---------------------------------------------------


def test_gap_continuation_is_the_inverse_of_gap_fade():
    bars = _bars()
    assert np.allclose(gap_continuation(bars), -gap_fade(bars))


def test_range_contraction_is_the_inverse_of_range_expansion():
    bars = _bars()
    assert np.allclose(range_contraction(bars), -range_expansion(bars))


def test_breakout_goes_long_on_new_highs():
    prices = np.concatenate([np.full(60, 100.0), np.linspace(101, 130, 20)])
    assert breakout(prices, window=55)[-1] == 1.0


def test_trend_follows_direction():
    up = np.linspace(100, 200, 150)
    down = np.linspace(200, 100, 150)
    assert trend_vol_scaled(up)[-1] > 0
    assert trend_vol_scaled(down)[-1] < 0


def test_funding_contrarian_fades_crowded_longs():
    # Trailing window must be mostly low so today's spike clears the percentile.
    closes = np.full(80, 100.0)
    funding = np.full(80, 0.0001)
    funding[-1] = 0.01                       # today: crowded longs paying up
    pos = funding_contrarian(closes, funding)
    assert pos[-1] == -1.0


def test_funding_contrarian_buys_crowded_shorts():
    closes = np.full(80, 100.0)
    funding = np.full(80, -0.0001)
    funding[-1] = -0.01                      # today: crowded shorts paying up
    pos = funding_contrarian(closes, funding)
    assert pos[-1] == 1.0


def test_cross_sectional_momentum_is_dollar_neutral():
    rng = np.random.default_rng(5)
    matrix = 100 + np.cumsum(rng.normal(0, 1, (10, 80)), axis=1)
    pos = cross_sectional_momentum_positions(matrix, lookback=30)
    for day in range(40, 80):
        assert abs(pos[:, day].sum()) < 1e-9   # longs offset shorts
