"""P2: an unavailable stub venue never reports a fill.

P14: the Hyperliquid market-data client degrades to None on upstream errors via
specific exception handling (no bare ``except``), instead of masking failures.
"""
import asyncio

import httpx

from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.data.http_client import HttpFetchError
from libs.schemas import ExecutionVenue
from modules.execution_engine.basket_executor import BasketExecutor
from modules.execution_engine.contract_executor import ContractExecutor


def _executors():
    return {
        ExecutionVenue.BINANCE: ContractExecutor(
            BinanceClient(paper_trading=True),
            paper_trading=True,
            venue=ExecutionVenue.BINANCE.value,
        ),
        # Wired exactly as apps/api/main.py now does: the stub venue is
        # explicitly unavailable.
        ExecutionVenue.HYPERLIQUID: ContractExecutor(
            HyperliquidClient(),
            paper_trading=True,
            venue=ExecutionVenue.HYPERLIQUID.value,
            available=False,
        ),
    }


def test_unavailable_venue_leg_is_not_submitted_or_filled():
    basket_executor = BasketExecutor(_executors())
    basket = asyncio.run(
        basket_executor.submit_basket(
            parent_intent_id="test_intent",
            legs=[
                {
                    "venue": "binance",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": 0.01,
                    "limit_price": 65000,
                },
                {
                    "venue": "hyperliquid",
                    "symbol": "BTC",
                    "side": "sell",
                    "quantity": 0.01,
                    "limit_price": 65010,
                },
            ],
        )
    )

    legs = {leg["venue"]: leg for leg in basket["legs"]}
    # The real (available) venue still submits.
    assert legs["binance"]["status"] == "submitted"
    assert legs["binance"]["client_order_id"] is not None
    # The unavailable stub venue must NOT be reported as submitted/filled.
    hl = legs["hyperliquid"]
    assert hl["status"] == "unavailable"
    assert hl["status"] not in ("submitted", "filled")
    assert hl["client_order_id"] is None

    # Basket-level metrics must not count the stub leg as a submission.
    assert basket["metrics"]["submitted_legs"] == 1
    # And the whole basket is not a clean "submitted".
    assert basket["status"] != "submitted"


def test_hyperliquid_market_data_degrades_to_none(monkeypatch):
    client = HyperliquidClient()

    def _boom(*args, **kwargs):
        raise HttpFetchError("upstream down")

    # The production client uses the bounded project transport rather than
    # httpx.post directly; patch the transport seam so this test never touches
    # the live provider during the default suite.
    monkeypatch.setattr("libs.crypto.hyperliquid_client.http_request_json", _boom)
    # Specific-exception handling: returns None (degraded), does not raise.
    assert client.get_ticker("BTC") is None
    assert client.get_orderbook("BTC") is None
