"""P1: the rigorous PortfolioRiskChecker is wired into the LIVE execution path.

These tests exercise the exact wiring apps/api/main.py now uses:
``IntentExecutionService`` constructed with a ``PortfolioRiskChecker`` (notional
limits) plus a ``position_provider`` — and assert it (a) rejects intents that
exceed notional limits and (b) fails closed when positions are unavailable.
"""
import asyncio

from libs.crypto.binance_client import BinanceClient
from libs.schemas import ExecutionVenue
from services.execution_engine.basket_executor import BasketExecutor
from services.execution_engine.contract_executor import ContractExecutor
from services.execution_engine.intent_execution_service import IntentExecutionService
from services.risk_manager.risk_checker import PortfolioRiskChecker, RiskLimits


def _live_style_service(position_provider):
    executors = {
        ExecutionVenue.BINANCE: ContractExecutor(
            BinanceClient(paper_trading=True),
            paper_trading=True,
            venue=ExecutionVenue.BINANCE.value,
        ),
    }
    basket_executor = BasketExecutor(executors)
    checker = PortfolioRiskChecker(
        limits=RiskLimits(
            max_gross_notional=250_000.0,
            max_market_notional=100_000.0,
            max_order_notional=50_000.0,
            max_basket_legs=8,
        )
    )
    service = IntentExecutionService(
        basket_executor,
        risk_checker=checker,
        position_provider=position_provider,
        max_open_intents=5,
        dedupe_window_seconds=0.0,
    )
    return service


def _make_intent(service, *, quantity, limit_price):
    return asyncio.run(
        service.create_intent(
            strategy_id="spread_arbitrage_v1",
            rationale="risk gate test",
            expected_edge_bps=15.0,
            confidence=0.75,
            legs=[
                {
                    "venue": "binance",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "quantity": quantity,
                    "limit_price": limit_price,
                }
            ],
        )
    )


def test_live_intent_exceeding_order_notional_is_rejected():
    # Flat book (empty dict = genuinely flat) so only the proposed leg matters.
    service = _live_style_service(lambda: {})
    # 2 BTC * 65_000 = 130_000 > max_order_notional (50_000).
    created = _make_intent(service, quantity=2.0, limit_price=65_000)
    submitted = asyncio.run(service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "risk_rejected"
    assert "order notional" in (submitted["error"] or "")


def test_live_intent_exceeding_gross_with_existing_positions_is_rejected():
    # Existing exposure already near the gross cap; a small new leg pushes over.
    service = _live_style_service(lambda: {"BTCUSDT": 240_000.0})
    created = _make_intent(service, quantity=0.3, limit_price=65_000)  # +19_500
    submitted = asyncio.run(service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "risk_rejected"
    assert "gross notional" in (submitted["error"] or "")


def test_live_intent_within_limits_is_submitted():
    service = _live_style_service(lambda: {})
    created = _make_intent(service, quantity=0.1, limit_price=65_000)  # 6_500
    submitted = asyncio.run(service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "submitted"


def test_fails_closed_when_positions_unavailable():
    # position_provider returns None -> unknown positions -> must reject.
    service = _live_style_service(lambda: None)
    created = _make_intent(service, quantity=0.1, limit_price=65_000)
    submitted = asyncio.run(service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "risk_rejected"
    assert "position data unavailable" in (submitted["error"] or "")
