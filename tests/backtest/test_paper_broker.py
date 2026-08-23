import asyncio
from datetime import datetime

import pytest

from libs.backtest.execution import ExecutionConfig, MarketState, PaperBroker, TimeInForce
from libs.schemas import Side


def _state(depth=5.0):
    return MarketState(0.99, 1.01, depth, depth, datetime(2026, 1, 1))


def test_paper_broker_models_partial_gtc_fill():
    broker = PaperBroker(ExecutionConfig(base_latency_ms=0, latency_std_ms=0))
    order = broker.submit_order(
        order_id="o1", market_id="BTC", side=Side.BUY_YES, quantity=10,
        limit_price=1.02,
    )
    fills = asyncio.run(broker.on_market("BTC", _state(depth=4)))
    assert len(fills) == 1
    assert fills[0].size == 4
    assert order.status == "partial"
    assert order.remaining == pytest.approx(6)


def test_paper_broker_fok_and_ioc_do_not_leave_resting_orders():
    broker = PaperBroker(ExecutionConfig(base_latency_ms=0, latency_std_ms=0))
    fok = broker.submit_order(
        order_id="fok", market_id="BTC", side=Side.BUY_YES, quantity=10,
        limit_price=1.02, time_in_force=TimeInForce.FOK,
    )
    ioc = broker.submit_order(
        order_id="ioc", market_id="BTC", side=Side.BUY_YES, quantity=10,
        limit_price=1.02, time_in_force=TimeInForce.IOC,
    )
    asyncio.run(broker.on_market("BTC", _state(depth=4)))
    assert fok.status == "cancelled"
    assert ioc.status == "cancelled"
    assert ioc.filled_quantity == pytest.approx(4)


def test_cancel_race_is_idempotent():
    broker = PaperBroker(ExecutionConfig(base_latency_ms=0, latency_std_ms=0))
    order = broker.submit_order(
        order_id="o1", market_id="BTC", side=Side.BUY_YES, quantity=1,
    )
    asyncio.run(broker.cancel_order("o1"))
    asyncio.run(broker.cancel_order("o1"))
    asyncio.run(broker.on_market("BTC", _state()))
    assert order.status == "cancelled"
    assert broker.executions == []
