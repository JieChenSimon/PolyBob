"""Tests for the calibrated digital-option probability in the BTC 5m workbench."""

from __future__ import annotations

from datetime import datetime, timezone

from libs.polymarket.btc_five_minute import (
    BtcFiveMinuteConfig,
    NormalizedBook,
    _digital_up_probability,
    _reference_return_volatility,
    _win_probability_up,
)


def _empty_book():
    return NormalizedBook(
        token_id="t", source="test", timestamp=None,
        received_at=datetime.now(timezone.utc), hash=None,
        bids=(), asks=(), is_real_orderbook=False,
    )


def test_digital_prob_direction_and_symmetry():
    # Above strike -> >0.5, below -> <0.5, at strike -> 0.5.
    up = _digital_up_probability(101.0, 100.0, remaining_s=120, return_volatility=0.001)
    dn = _digital_up_probability(99.0, 100.0, remaining_s=120, return_volatility=0.001)
    at = _digital_up_probability(100.0, 100.0, remaining_s=120, return_volatility=0.001)
    assert up > 0.5 > dn
    assert abs(at - 0.5) < 1e-9
    assert abs((up - 0.5) - (0.5 - dn)) < 0.02  # roughly symmetric


def test_digital_prob_higher_vol_less_confident():
    low = _digital_up_probability(101.0, 100.0, 120, 0.0005)
    high = _digital_up_probability(101.0, 100.0, 120, 0.005)
    # More volatility -> the same move is less decisive -> closer to 0.5.
    assert 0.5 < high < low


def test_digital_prob_bad_inputs_return_none():
    assert _digital_up_probability(101, 100, 120, 0.0) is None
    assert _digital_up_probability(101, 100, 0, 0.001) is None
    assert _digital_up_probability(101, 0, 120, 0.001) is None


def test_win_probability_uses_digital_when_vol_given_else_fallback():
    cfg = BtcFiveMinuteConfig()
    kw = dict(up_book=_empty_book(), down_book=_empty_book(), btc_price=100_500.0,
              target_price=100_000.0, seconds_to_expiry=120, config=cfg)
    with_vol = _win_probability_up(**kw, return_volatility=0.0009)
    without = _win_probability_up(**kw, return_volatility=None)
    # Both are valid probabilities; supplying real vol changes the estimate
    # (calibrated path) vs the legacy hand-tuned scale.
    assert 0.0 <= with_vol <= 1.0 and 0.0 <= without <= 1.0
    assert with_vol > 0.5  # price above strike -> bullish
    assert with_vol != without


def test_reference_return_volatility_parsing():
    assert _reference_return_volatility({"return_volatility": 0.0012}) == 0.0012
    assert _reference_return_volatility({"sigma_per_min": "0.002"}) == 0.002
    assert _reference_return_volatility({"return_volatility": 0}) is None
    assert _reference_return_volatility({"price": 100}) is None
    assert _reference_return_volatility({}) is None


def test_blend_defaults_reproduce_market_plus_digital():
    from libs.polymarket.btc_five_minute import (
        BTC5M_INDICATORS, DEFAULT_ENABLED_INDICATORS, blend_up_probability,
    )
    assert set(DEFAULT_ENABLED_INDICATORS) == {"market_implied", "digital_option"}
    assert {i["id"] for i in BTC5M_INDICATORS} == {
        "market_implied", "digital_option", "momentum_1m", "book_imbalance"}

    prob, breakdown = blend_up_probability(
        up_book=_empty_book(), down_book=_empty_book(), btc_price=100_500.0,
        target_price=100_000.0, seconds_to_expiry=120, config=BtcFiveMinuteConfig(),
        return_volatility=0.0009, enabled_indicators=None,
    )
    used = {b["id"] for b in breakdown if b["used"]}
    assert used == {"market_implied", "digital_option"}  # defaults
    assert 0.5 < prob <= 1.0


def test_blend_single_indicator_selection():
    from libs.polymarket.btc_five_minute import blend_up_probability
    prob, breakdown = blend_up_probability(
        up_book=_empty_book(), down_book=_empty_book(), btc_price=100_500.0,
        target_price=100_000.0, seconds_to_expiry=120, config=BtcFiveMinuteConfig(),
        return_volatility=0.0009, enabled_indicators=["digital_option"],
    )
    assert [b["used"] for b in breakdown if b["id"] == "digital_option"] == [True]
    assert [b["used"] for b in breakdown if b["id"] == "market_implied"] == [False]
    assert prob > 0.9  # confident up from digital model alone


def test_blend_falls_back_when_nothing_usable():
    from libs.polymarket.btc_five_minute import blend_up_probability
    prob, _ = blend_up_probability(
        up_book=_empty_book(), down_book=_empty_book(), btc_price=None,
        target_price=None, seconds_to_expiry=120, config=BtcFiveMinuteConfig(),
        enabled_indicators=["digital_option"],   # not computable without prices
    )
    assert prob == 0.5  # config.model_probability_up fallback
