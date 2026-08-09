from datetime import datetime, timedelta

import pytest

from libs.schemas import OrderbookTick, TradeTick
from modules.feature_engine.service import MarketFeatures


def test_price_window_keeps_exact_running_statistics():
    features = MarketFeatures("test-market")
    start = datetime(2026, 1, 1)

    for index in range(75):
        mid = 100.0 + index
        features.update_from_orderbook(
            OrderbookTick(
                market_id="test-market",
                timestamp=start + timedelta(seconds=index),
                bid_price=mid - 0.5,
                ask_price=mid + 0.5,
                bid_size=100.0,
                ask_size=100.0,
            )
        )

    retained = [100.0 + index for index in range(15, 75)]
    assert len(features.price_history) == 60
    assert features._price_count == 60
    assert features._running_sum == pytest.approx(sum(retained))
    assert features._running_sum_sq == pytest.approx(sum(value * value for value in retained))


def test_trade_window_updates_count_and_volume_incrementally():
    features = MarketFeatures("test-market")
    start = datetime(2026, 1, 1)

    for index in range(5):
        features.update_from_trade(
            TradeTick(
                market_id="test-market",
                timestamp=start + timedelta(seconds=index * 10),
                price=100.0,
                size=float(index + 1),
                side="buy",
            )
        )

    assert features.trade_intensity_1m == 5
    assert features.volume_1m == pytest.approx(15.0)

    features.update_from_trade(
        TradeTick(
            market_id="test-market",
            timestamp=start + timedelta(seconds=75),
            price=101.0,
            size=10.0,
            side="sell",
        )
    )

    assert features.trade_intensity_1m == 4
    assert features.volume_1m == pytest.approx(22.0)
