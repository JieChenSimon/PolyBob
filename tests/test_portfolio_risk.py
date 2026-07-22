"""Portfolio-level risk checker tests."""
import asyncio
import json

from libs.db import fact_store
from libs.schemas import ExecutionVenue
from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
from services.execution_engine.basket_executor import BasketExecutor
from services.execution_engine.contract_executor import ContractExecutor
from services.execution_engine.intent_execution_service import IntentExecutionService
from services.risk_manager.risk_checker import (
    PortfolioRiskChecker,
    RiskChecker,
    RiskDecision,
    RiskLimits,
)


def _leg(market="mkt_a", quantity=10.0, price=100.0):
    return {"market_id": market, "quantity": quantity, "limit_price": price}


def test_unknown_positions_rejected():
    checker = PortfolioRiskChecker()
    decision = checker.evaluate_intent([_leg()], positions=None)
    assert isinstance(decision, RiskDecision)
    assert decision.allowed is False
    assert decision.reasons == ["position data unavailable"]


def test_flat_book_within_limits_allowed():
    checker = PortfolioRiskChecker()
    decision = checker.evaluate_intent([_leg()], positions={})
    assert decision.allowed is True
    assert decision.reasons == []
    assert decision.measurements["proposed_notional"] == 1000.0


def test_max_single_order_notional_triggers():
    checker = PortfolioRiskChecker(RiskLimits(max_order_notional=500.0))
    decision = checker.evaluate_intent([_leg(quantity=10.0, price=100.0)], positions={})
    assert decision.allowed is False
    assert any("order notional 1000.00" in r and "500.00" in r for r in decision.reasons)


def test_max_gross_notional_triggers_with_existing_positions():
    checker = PortfolioRiskChecker(RiskLimits(max_gross_notional=5000.0))
    decision = checker.evaluate_intent(
        [_leg(quantity=10.0, price=100.0)],
        positions={"mkt_b": 4500.0},
    )
    assert decision.allowed is False
    assert any("gross notional 5500.00" in r and "5000.00" in r for r in decision.reasons)
    assert decision.measurements["gross_notional"] == 5500.0


def test_max_per_market_notional_triggers():
    checker = PortfolioRiskChecker(RiskLimits(max_market_notional=1200.0))
    decision = checker.evaluate_intent(
        [_leg(market="mkt_a", quantity=10.0, price=100.0)],
        positions={"mkt_a": 300.0},
    )
    assert decision.allowed is False
    assert any("market notional 1300.00" in r and "mkt_a" in r for r in decision.reasons)


def test_max_basket_leg_count_triggers():
    checker = PortfolioRiskChecker(RiskLimits(max_basket_legs=2))
    legs = [_leg(market=f"mkt_{i}", quantity=1.0, price=1.0) for i in range(3)]
    decision = checker.evaluate_intent(legs, positions={})
    assert decision.allowed is False
    assert any("basket leg count 3 exceeds limit 2" in r for r in decision.reasons)


def test_min_cash_buffer_triggers():
    checker = PortfolioRiskChecker(RiskLimits(min_cash_buffer=500.0))
    decision = checker.evaluate_intent(
        [_leg(quantity=10.0, price=100.0)], positions={}, cash=1200.0
    )
    assert decision.allowed is False
    assert any("cash after trade 200.00" in r and "500.00" in r for r in decision.reasons)

    # Unknown cash with a buffer configured is also unsafe.
    unknown = checker.evaluate_intent([_leg()], positions={}, cash=None)
    assert unknown.allowed is False
    assert "cash balance unavailable" in unknown.reasons


def test_missing_leg_price_is_rejected():
    checker = PortfolioRiskChecker()
    decision = checker.evaluate_intent(
        [{"market_id": "mkt_a", "quantity": 5.0, "limit_price": None}], positions={}
    )
    assert decision.allowed is False
    assert any("leg notional unavailable" in r for r in decision.reasons)


def test_multiple_limits_report_all_reasons():
    checker = PortfolioRiskChecker(
        RiskLimits(max_order_notional=100.0, max_gross_notional=100.0, max_market_notional=100.0)
    )
    decision = checker.evaluate_intent([_leg(quantity=10.0, price=100.0)], positions={})
    assert decision.allowed is False
    assert len(decision.reasons) == 3


def test_decisions_persisted_as_audit_events(tmp_path):
    db_path = tmp_path / "audit.sqlite3"
    checker = PortfolioRiskChecker(audit_db_path=db_path)

    checker.evaluate_intent([_leg()], positions={}, subject_id="intent_x")
    checker.evaluate_intent([_leg()], positions=None, subject_id="intent_y")

    with fact_store.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT subject_id, payload_json FROM audit_events WHERE event_type = 'risk.decision' ORDER BY id"
        ).fetchall()
    assert len(rows) == 2
    allowed_payload = json.loads(rows[0]["payload_json"])
    denied_payload = json.loads(rows[1]["payload_json"])
    assert rows[0]["subject_id"] == "intent_x"
    assert allowed_payload["allowed"] is True
    assert denied_payload["allowed"] is False
    assert denied_payload["reasons"] == ["position data unavailable"]


def test_legacy_risk_checker_alias_still_works():
    legacy = RiskChecker(max_position=1000, max_order_size=100)
    allowed, _ = legacy.check_order(50)
    assert allowed is True
    blocked, reason = legacy.check_order(150)
    assert blocked is False
    assert reason


def _intent_service(risk_checker=None, position_provider=None):
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
    return IntentExecutionService(
        BasketExecutor(executors),
        risk_checker=risk_checker,
        position_provider=position_provider,
    )


def _create_intent(service):
    return asyncio.run(
        service.create_intent(
            strategy_id="spread_arbitrage_v1",
            rationale="risk wiring test",
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
            ],
        )
    )


def test_intent_service_with_portfolio_checker_and_positions_submits():
    service = _intent_service(
        risk_checker=PortfolioRiskChecker(),
        position_provider=lambda: {},
    )
    created = _create_intent(service)
    submitted = asyncio.run(service.submit_intent(created["intent_id"]))
    assert submitted["status"] == "submitted"


def test_intent_service_without_position_provider_rejects():
    service = _intent_service(risk_checker=PortfolioRiskChecker())
    created = _create_intent(service)
    result = asyncio.run(service.submit_intent(created["intent_id"]))
    assert result["status"] == "risk_rejected"
    assert "position data unavailable" in result["error"]


def test_intent_service_limit_breach_rejects_with_measured_value():
    service = _intent_service(
        risk_checker=PortfolioRiskChecker(RiskLimits(max_order_notional=100.0)),
        position_provider=lambda: {},
    )
    created = _create_intent(service)
    result = asyncio.run(service.submit_intent(created["intent_id"]))
    assert result["status"] == "risk_rejected"
    assert "order notional 650.00" in result["error"]
