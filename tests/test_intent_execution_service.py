import asyncio

from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.schemas import ExecutionVenue
from modules.execution_engine.basket_executor import BasketExecutor
from modules.execution_engine.contract_executor import ContractExecutor
from modules.execution_engine.intent_execution_service import IntentExecutionService


def test_intent_execution_service_creates_and_submits_intent(promoted_strategy):
    executors = {
        ExecutionVenue.BINANCE: ContractExecutor(
            BinanceClient(paper_trading=True),
            paper_trading=True,
            venue=ExecutionVenue.BINANCE.value,
        ),
        ExecutionVenue.HYPERLIQUID: ContractExecutor(
            HyperliquidClient(),
            paper_trading=True,
            venue=ExecutionVenue.HYPERLIQUID.value,
        ),
    }

    basket_executor = BasketExecutor(executors)
    intent_service = IntentExecutionService(basket_executor)

    created = asyncio.run(
        intent_service.create_intent(
            strategy_id="spread_arbitrage_v1",
            rationale="manual spread",
            expected_edge_bps=15.0,
            confidence=0.75,
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

    assert created["status"] == "created"
    assert created["basket_id"] is None

    submitted = asyncio.run(intent_service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "submitted"
    assert submitted["basket_id"] is not None


def test_intent_execution_service_blocks_duplicate_submission(promoted_strategy):
    executors = {
        ExecutionVenue.BINANCE: ContractExecutor(
            BinanceClient(paper_trading=True),
            paper_trading=True,
            venue=ExecutionVenue.BINANCE.value,
        ),
        ExecutionVenue.HYPERLIQUID: ContractExecutor(
            HyperliquidClient(),
            paper_trading=True,
            venue=ExecutionVenue.HYPERLIQUID.value,
        ),
    }

    basket_executor = BasketExecutor(executors)
    intent_service = IntentExecutionService(
        basket_executor,
        max_open_intents=5,
        dedupe_window_seconds=60.0,
    )

    first = asyncio.run(
        intent_service.create_intent(
            strategy_id="spread_arbitrage_v1",
            rationale="manual spread",
            expected_edge_bps=15.0,
            confidence=0.75,
            metadata={"pair_id": "btc_pair"},
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
    asyncio.run(intent_service.submit_intent(first["intent_id"]))

    second = asyncio.run(
        intent_service.create_intent(
            strategy_id="spread_arbitrage_v1",
            rationale="manual spread",
            expected_edge_bps=15.0,
            confidence=0.75,
            metadata={"pair_id": "btc_pair"},
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
    blocked = asyncio.run(intent_service.submit_intent(second["intent_id"]))

    assert blocked["status"] == "duplicate_blocked"
    assert blocked["error"] is not None
