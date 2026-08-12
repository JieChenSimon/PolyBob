from __future__ import annotations

import datetime as dt

import pytest

from libs.forecasting.contracts import AssetClass, BarInterval, CanonicalBar, CanonicalBarFrame


def bar(day: int, *, low: float = 9.0, high: float = 12.0) -> CanonicalBar:
    return CanonicalBar(
        timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=day - 1),
        open=10.0,
        high=high,
        low=low,
        close=11.0,
        volume=100.0,
    )


def test_frame_preserves_explicit_amount_derivation_state():
    frame = CanonicalBarFrame(
        instrument_id="BTC-USDT",
        asset_class=AssetClass.CRYPTO_SPOT,
        venue="OKX",
        interval=BarInterval.ONE_DAY,
        source="okx",
        fetched_at=dt.datetime.now(dt.UTC),
        bars=tuple(bar(index) for index in range(1, 33)),
    )
    frame.validate()
    assert frame.feature_mode == "ohlcv_amount_derived"


def test_invalid_ohlc_is_rejected():
    with pytest.raises(ValueError, match="low <="):
        bar(1, low=10.5).validate()


def test_short_context_is_rejected():
    frame = CanonicalBarFrame(
        instrument_id="AAPL",
        asset_class=AssetClass.US_EQUITY,
        venue="US",
        interval=BarInterval.ONE_DAY,
        source="test",
        fetched_at=dt.datetime.now(dt.UTC),
        bars=(bar(1),),
    )
    with pytest.raises(ValueError, match="at least 32"):
        frame.validate()
