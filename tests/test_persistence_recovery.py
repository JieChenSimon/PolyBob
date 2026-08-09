"""Restart-recovery, idempotency, and audit-trail tests for execution persistence."""
import asyncio
import json

from libs.crypto.binance_client import BinanceClient
from libs.crypto.hyperliquid_client import HyperliquidClient
from libs.db import connect
from libs.db.repositories import BasketRepository, DecisionRepository, IntentRepository
from libs.schemas import ExecutionVenue
from modules.execution_engine.basket_executor import BasketExecutor
from modules.execution_engine.contract_executor import ContractExecutor
from modules.execution_engine.intent_execution_service import IntentExecutionService


def build_executors() -> dict[ExecutionVenue, ContractExecutor]:
    return {
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


def build_services(db_path, **intent_kwargs):
    basket_executor = BasketExecutor(
        build_executors(),
        basket_repository=BasketRepository(db_path),
    )
    intent_service = IntentExecutionService(
        basket_executor,
        intent_repository=IntentRepository(db_path),
        decision_repository=DecisionRepository(db_path),
        **intent_kwargs,
    )
    return basket_executor, intent_service


SPREAD_LEGS = [
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
]


def create_spread_intent(intent_service, **overrides):
    kwargs = {
        "strategy_id": "spread_arbitrage_v1",
        "rationale": "persistence test spread",
        "expected_edge_bps": 15.0,
        "confidence": 0.75,
        "legs": SPREAD_LEGS,
        "metadata": {"pair_id": "btc_pair"},
    }
    kwargs.update(overrides)
    return asyncio.run(intent_service.create_intent(**kwargs))


def test_restart_recovers_intents_baskets_and_errors(tmp_path, promoted_strategy):
    db_path = tmp_path / "polybob.sqlite3"
    _, intent_service = build_services(db_path)

    submitted = create_spread_intent(intent_service)
    submitted = asyncio.run(intent_service.submit_intent(submitted["intent_id"]))
    assert submitted["status"] == "submitted"
    assert submitted["basket_id"] is not None

    rejected = create_spread_intent(
        intent_service,
        rationale="oversized order",
        legs=[
            {
                "venue": "binance",
                "symbol": "BTCUSDT",
                "side": "buy",
                "quantity": 500.0,
                "limit_price": 65000,
            }
        ],
        metadata={"pair_id": "oversize"},
    )
    rejected = asyncio.run(intent_service.submit_intent(rejected["intent_id"]))
    assert rejected["status"] == "risk_rejected"
    assert rejected["error"] is not None

    # Fresh service instances against the same DB simulate a process restart.
    fresh_basket_executor, fresh_intent_service = build_services(db_path)
    assert asyncio.run(fresh_basket_executor.restore_state()) == 1
    assert asyncio.run(fresh_intent_service.restore_state()) == 2

    recovered_submitted = fresh_intent_service.get_intent(submitted["intent_id"])
    assert recovered_submitted is not None
    assert recovered_submitted["status"] == "submitted"
    assert recovered_submitted["basket_id"] == submitted["basket_id"]
    assert [leg["symbol"] for leg in recovered_submitted["legs"]] == ["BTCUSDT", "BTC"]

    recovered_rejected = fresh_intent_service.get_intent(rejected["intent_id"])
    assert recovered_rejected is not None
    assert recovered_rejected["status"] == "risk_rejected"
    assert recovered_rejected["error"] == rejected["error"]

    recovered_basket = fresh_basket_executor.get_basket(submitted["basket_id"])
    assert recovered_basket is not None
    assert recovered_basket["status"] == "submitted"
    assert recovered_basket["parent_intent_id"] == submitted["intent_id"]
    assert len(recovered_basket["legs"]) == 2
    for leg in recovered_basket["legs"]:
        assert leg["status"] == "submitted"
        assert leg["client_order_id"] is not None


def test_duplicate_idempotency_key_returns_original_intent(tmp_path, promoted_strategy):
    db_path = tmp_path / "polybob.sqlite3"
    _, intent_service = build_services(db_path)

    first = create_spread_intent(intent_service, idempotency_key="client-key-1")
    replay = create_spread_intent(intent_service, idempotency_key="client-key-1")
    assert replay["intent_id"] == first["intent_id"]

    # Replay also survives a restart into a fresh service instance.
    _, fresh_intent_service = build_services(db_path)
    asyncio.run(fresh_intent_service.restore_state())
    replay_after_restart = create_spread_intent(
        fresh_intent_service, idempotency_key="client-key-1"
    )
    assert replay_after_restart["intent_id"] == first["intent_id"]

    with connect(db_path) as connection:
        rows = connection.execute("SELECT COUNT(*) AS n FROM intents").fetchone()
    assert rows["n"] == 1


def test_signature_dedupe_survives_restart(tmp_path, promoted_strategy):
    db_path = tmp_path / "polybob.sqlite3"
    _, intent_service = build_services(db_path, dedupe_window_seconds=300.0)

    first = create_spread_intent(intent_service)
    assert asyncio.run(intent_service.submit_intent(first["intent_id"]))["status"] == "submitted"

    _, fresh_intent_service = build_services(db_path, dedupe_window_seconds=300.0)
    asyncio.run(fresh_intent_service.restore_state())

    duplicate = create_spread_intent(fresh_intent_service)
    blocked = asyncio.run(fresh_intent_service.submit_intent(duplicate["intent_id"]))
    assert blocked["status"] == "duplicate_blocked"
    assert blocked["error"] is not None


def test_audit_trail_records_full_intent_history(tmp_path, promoted_strategy):
    db_path = tmp_path / "polybob.sqlite3"
    _, intent_service = build_services(db_path)

    intent = create_spread_intent(intent_service)
    submitted = asyncio.run(intent_service.submit_intent(intent["intent_id"]))
    assert submitted["status"] == "submitted"

    with connect(db_path) as connection:
        events = connection.execute(
            """
            SELECT event_type, payload_json FROM audit_events
            WHERE subject_type = 'intent' AND subject_id = ?
            ORDER BY id
            """,
            (intent["intent_id"],),
        ).fetchall()
        decision_rows = connection.execute(
            "SELECT strategy_id, market_id, payload_json FROM strategy_decisions"
        ).fetchall()
        basket_events = connection.execute(
            """
            SELECT event_type FROM audit_events
            WHERE subject_type = 'basket' AND subject_id = ?
            ORDER BY id
            """,
            (submitted["basket_id"],),
        ).fetchall()

    event_types = [row["event_type"] for row in events]
    assert event_types == ["intent.created", "intent.status_changed"]
    assert json.loads(events[0]["payload_json"])["status"] == "created"
    final = json.loads(events[1]["payload_json"])
    assert final["status"] == "submitted"
    assert final["basket_id"] == submitted["basket_id"]

    assert len(decision_rows) == 1
    assert decision_rows[0]["strategy_id"] == "spread_arbitrage_v1"
    assert json.loads(decision_rows[0]["payload_json"])["intent_id"] == intent["intent_id"]

    basket_event_types = [row["event_type"] for row in basket_events]
    assert basket_event_types[0] == "basket.created"
    assert basket_event_types.count("basket_leg.updated") == 2
    assert basket_event_types[-1] == "basket.status_changed"


def test_corrupted_db_degrades_to_empty_state(tmp_path, promoted_strategy):
    db_path = tmp_path / "corrupted.sqlite3"
    db_path.write_bytes(b"this is not a sqlite database, not even close")

    basket_executor, intent_service = build_services(db_path)
    assert asyncio.run(basket_executor.restore_state()) == 0
    assert asyncio.run(intent_service.restore_state()) == 0
    assert intent_service.list_intents() == []
    assert basket_executor.list_baskets() == []

    # The service keeps working in memory even though persistence fails.
    intent = create_spread_intent(intent_service)
    submitted = asyncio.run(intent_service.submit_intent(intent["intent_id"]))
    assert submitted["status"] == "submitted"


def test_missing_db_starts_empty_and_bootstraps_schema(tmp_path, promoted_strategy):
    db_path = tmp_path / "brand-new.sqlite3"
    basket_executor, intent_service = build_services(db_path)
    assert asyncio.run(intent_service.restore_state()) == 0
    assert asyncio.run(basket_executor.restore_state()) == 0

    intent = create_spread_intent(intent_service)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM intents WHERE intent_id = ?", (intent["intent_id"],)
        ).fetchone()
    assert row["status"] == "created"
