"""Tests for the multi-timeframe + moving-average trend classifier.

The fixtures here are *shaped* price paths, not claims about any market: they
exist to prove the classifier's arithmetic and its causality. Every real-data
claim in this project still comes from real data — see the verdict endpoint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from libs.quant.pit import LookaheadError, assert_no_lookahead
from libs.quant.trend_state import (
    HORIZONS, MIN_BARS, TrendClass, TrendState, classify_trend,
)


@dataclass
class FakeBars:
    """The minimal DailyBars shape the classifier consumes."""

    closes: list[float]
    dates: list[str]

    @classmethod
    def build(cls, closes: list[float]) -> "FakeBars":
        return cls(closes=closes, dates=[f"2024-{1 + i // 400:02d}-{1 + i % 28:02d}"
                                         for i in range(len(closes))])


def _drift(n: int, daily: float, start: float = 100.0, wobble: float = 0.0) -> list[float]:
    """A deterministic path with a fixed daily drift and an optional ripple."""
    out = []
    price = start
    for i in range(n):
        price *= 1.0 + daily
        out.append(price * (1.0 + wobble * math.sin(i / 7.0)))
    return out


def test_steady_rise_is_an_uptrend():
    state = classify_trend(FakeBars.build(_drift(400, 0.0015)))
    assert state.classification in (TrendClass.UPTREND, TrendClass.STRONG_UPTREND)
    assert state.aligned is True
    assert state.score > 0.5
    assert state.ma["price"] > state.ma["ma200"]


def test_strong_rise_is_a_strong_uptrend():
    state = classify_trend(FakeBars.build(_drift(400, 0.004)))
    assert state.classification is TrendClass.STRONG_UPTREND
    assert state.alignment == 1
    assert state.raw_score >= 0.5


def test_steady_decline_is_a_downtrend():
    state = classify_trend(FakeBars.build(_drift(400, -0.0015, start=400.0)))
    assert state.classification in (TrendClass.DOWNTREND, TrendClass.STRONG_DOWNTREND)
    assert state.score < 0.5
    assert state.ma["price"] < state.ma["ma200"]


def test_hard_decline_is_a_strong_downtrend():
    state = classify_trend(FakeBars.build(_drift(400, -0.004, start=2000.0)))
    assert state.classification is TrendClass.STRONG_DOWNTREND
    assert state.alignment == -1


def test_flat_choppy_market_is_neutral():
    # A sideways, genuinely noisy market drifting only ~5%/yr: the returns are
    # small relative to their own noise and price sits inside the MA band, so
    # neither block should commit to a direction.
    closes = [100.0 * (1.0002 ** i) * (1.0 + 0.012 * (-1) ** i) for i in range(400)]
    state = classify_trend(FakeBars.build(closes))
    assert state.classification is TrendClass.NEUTRAL
    assert 0.35 < state.score < 0.65


def test_hairline_ma_crossing_does_not_swing_the_score():
    """A price a whisker above its MA200 is not the same evidence as 15% above."""
    closes = [100.0 * (1.0002 ** i) * (1.0 + 0.012 * (-1) ** i) for i in range(400)]
    state = classify_trend(FakeBars.build(closes))
    # Banded, so the regime component is a fraction of its saturated value.
    assert abs(state.components["price_vs_ma200"]) < 0.5
    strong = classify_trend(FakeBars.build(_drift(400, 0.003, wobble=0.02)))
    assert strong.components["price_vs_ma200"] == pytest.approx(1.0)


def test_insufficient_history_is_unknown_never_neutral():
    state = classify_trend(FakeBars.build(_drift(MIN_BARS - 1, 0.002)))
    assert state.classification is TrendClass.UNKNOWN
    assert state.score == 0.5
    assert all(v is None for v in state.returns.values())
    assert "不足" in state.evidence_zh


def test_no_bars_at_all_is_unknown():
    assert classify_trend(None).classification is TrendClass.UNKNOWN
    assert classify_trend(FakeBars.build([])).classification is TrendClass.UNKNOWN


def test_missing_long_horizon_is_none_and_weight_is_redistributed():
    # 210 bars: MA200 exists, but the 1y (252-bar) return cannot.
    state = classify_trend(FakeBars.build(_drift(210, 0.002)))
    assert state.classification is not TrendClass.UNKNOWN
    assert state.returns["1y"] is None
    assert state.returns["6m"] is not None
    assert state.classification in (TrendClass.UPTREND, TrendClass.STRONG_UPTREND)


def test_returns_match_the_declared_lookbacks():
    closes = _drift(400, 0.0015)
    state = classify_trend(FakeBars.build(closes))
    for label, h in HORIZONS.items():
        expected = closes[-1] / closes[-1 - h] - 1.0
        assert state.returns[label] == pytest.approx(expected, rel=1e-9)


def test_volatility_normalisation_makes_markets_comparable():
    """The same drift at different vol should not read as wildly different trend."""
    calm = classify_trend(FakeBars.build(_drift(400, 0.0015, wobble=0.002)))
    wild = classify_trend(FakeBars.build(_drift(400, 0.0015, wobble=0.06)))
    # The noisy series is genuinely weaker evidence, but both stay on the same
    # side of neutral — normalisation must not flip the sign.
    assert calm.raw_score > 0 and wild.raw_score > 0
    assert calm.raw_score >= wild.raw_score


def test_classifier_is_causal():
    """Bar k's classification must not change when later bars are appended."""
    closes = _drift(320, 0.0015, wobble=0.02)

    def signal_fn(history):
        out = []
        for k in range(len(history)):
            prefix = FakeBars(closes=list(history[: k + 1]),
                              dates=[f"d{i}" for i in range(k + 1)])
            out.append(classify_trend(prefix).classification.value)
        return out

    # Spot-check across the usable region; the harness is O(n^2) in classify calls.
    assert_no_lookahead(signal_fn, closes,
                        check_indices=[199, 210, 240, 275, 300, 319])


def test_lookahead_harness_would_catch_a_leak():
    """Sanity: the guard above is a real test, not a tautology."""
    closes = _drift(60, 0.002, wobble=0.02)

    def leaky(history):
        # Peeks at the final bar of whatever window it is given.
        return [1.0 if history[-1] > h else -1.0 for h in history]

    with pytest.raises(LookaheadError):
        assert_no_lookahead(leaky, closes, check_indices=[10, 20, 30])


def test_wire_contract_shape():
    state = classify_trend(FakeBars.build(_drift(400, 0.0015)))
    d = state.to_dict()
    assert set(d) >= {"classification", "score", "returns", "ma", "aligned",
                      "evidence_zh", "evidence_en"}
    assert set(d["returns"]) == {"1w", "1m", "2m", "3m", "6m", "1y"}
    assert set(d["ma"]) == {"price", "ma20", "ma50", "ma200", "ma200_slope_20d"}
    assert isinstance(d["aligned"], bool)
    assert 0.0 <= d["score"] <= 1.0
    assert d["evidence_zh"] and d["evidence_en"]


def test_blocks_and_supports_act_flags():
    up = classify_trend(FakeBars.build(_drift(400, 0.003)))
    down = classify_trend(FakeBars.build(_drift(400, -0.003, start=2000.0)))
    unknown = classify_trend(None)
    assert up.supports_act and not up.blocks_act
    assert down.blocks_act and not down.supports_act
    assert not unknown.blocks_act and not unknown.supports_act
    assert isinstance(up, TrendState)
