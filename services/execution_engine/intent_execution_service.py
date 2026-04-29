"""TradeIntent 到 OrderBasket 的桥接服务"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, InstrumentRef, TradeIntent, TradeIntentLeg
from services.risk_manager.risk_checker import RiskChecker
from .basket_executor import BasketExecutor


class IntentExecutionService:
    def __init__(
        self,
        basket_executor: BasketExecutor,
        risk_checker: RiskChecker | None = None,
        max_open_intents: int = 3,
        dedupe_window_seconds: float = 30.0,
    ):
        self.basket_executor = basket_executor
        self.event_bus = get_event_bus()
        self.risk_checker = risk_checker or RiskChecker(max_position=1000, max_order_size=100)
        self.max_open_intents = max_open_intents
        self.dedupe_window_seconds = dedupe_window_seconds
        self.intents: dict[str, TradeIntent] = {}
        self.intent_status: dict[str, str] = {}
        self.intent_baskets: dict[str, str] = {}
        self.intent_errors: dict[str, str] = {}
        self._recent_signatures: dict[str, datetime] = {}

    async def create_intent(
        self,
        strategy_id: str,
        rationale: str,
        expected_edge_bps: float,
        confidence: float,
        legs: list[dict[str, Any]],
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        intent_id = f"intent_{uuid.uuid4().hex[:10]}"
        intent_legs: list[TradeIntentLeg] = []

        for index, leg in enumerate(legs, start=1):
            intent_legs.append(
                TradeIntentLeg(
                    leg_id=str(leg.get("leg_id") or f"{intent_id}:leg{index}"),
                    instrument=InstrumentRef(
                        venue=ExecutionVenue(str(leg["venue"])),
                        symbol=str(leg["symbol"]),
                        market_id=leg.get("market_id"),
                        asset_id=leg.get("asset_id"),
                    ),
                    side=str(leg["side"]),
                    quantity=float(leg["quantity"]),
                    limit_price=float(leg["limit_price"]) if leg.get("limit_price") is not None else None,
                    role=str(leg.get("role", "primary")),
                )
            )

        intent = TradeIntent(
            intent_id=intent_id,
            strategy_id=strategy_id,
            created_at=datetime.utcnow(),
            rationale=rationale,
            expected_edge_bps=float(expected_edge_bps),
            confidence=float(confidence),
            legs=intent_legs,
            metadata=metadata or {},
        )
        self.intents[intent_id] = intent
        self.intent_status[intent_id] = "created"

        await self.event_bus.publish(
            Topics.STRATEGY_INTENT_CREATED,
            {
                "intent_id": intent_id,
                "strategy_id": strategy_id,
                "leg_count": len(intent_legs),
                "expected_edge_bps": expected_edge_bps,
            },
        )
        return self.serialize_intent(intent)

    async def submit_intent(self, intent_id: str) -> dict[str, Any]:
        intent = self.intents[intent_id]
        status = self.intent_status.get(intent_id, "created")
        if status == "submitted":
            return self.serialize_intent(intent)

        signature = self._intent_signature(intent)
        now = datetime.utcnow()
        recent = self._recent_signatures.get(signature)
        if recent and (now - recent).total_seconds() < self.dedupe_window_seconds:
            self.intent_status[intent_id] = "duplicate_blocked"
            self.intent_errors[intent_id] = "duplicate intent blocked by dedupe window"
            return self.serialize_intent(intent)

        open_intents = sum(
            1 for value in self.intent_status.values() if value in {"created", "submitted"}
        )
        if open_intents > self.max_open_intents:
            self.intent_status[intent_id] = "risk_rejected"
            self.intent_errors[intent_id] = "max_open_intents exceeded"
            return self.serialize_intent(intent)

        for leg in intent.legs:
            allowed, reason = self.risk_checker.check_order(leg.quantity)
            if not allowed:
                self.intent_status[intent_id] = "risk_rejected"
                self.intent_errors[intent_id] = reason
                return self.serialize_intent(intent)

        basket = await self.basket_executor.submit_basket(
            parent_intent_id=intent.intent_id,
            legs=[
                {
                    "leg_id": leg.leg_id,
                    "venue": leg.instrument.venue.value,
                    "symbol": leg.instrument.symbol,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "limit_price": leg.limit_price,
                }
                for leg in intent.legs
            ],
        )
        self.intent_status[intent_id] = "submitted"
        self.intent_baskets[intent_id] = basket["basket_id"]
        self.intent_errors.pop(intent_id, None)
        self._recent_signatures[signature] = now
        return self.serialize_intent(intent)

    def list_intents(self) -> list[dict[str, Any]]:
        return [self.serialize_intent(intent) for intent in self.intents.values()]

    def get_intent(self, intent_id: str) -> dict[str, Any] | None:
        intent = self.intents.get(intent_id)
        if intent is None:
            return None
        return self.serialize_intent(intent)

    def serialize_intent(self, intent: TradeIntent) -> dict[str, Any]:
        intent_id = intent.intent_id
        return {
            "intent_id": intent.intent_id,
            "strategy_id": intent.strategy_id,
            "created_at": intent.created_at.isoformat(),
            "rationale": intent.rationale,
            "expected_edge_bps": intent.expected_edge_bps,
            "confidence": intent.confidence,
            "status": self.intent_status.get(intent_id, "unknown"),
            "basket_id": self.intent_baskets.get(intent_id),
            "error": self.intent_errors.get(intent_id),
            "legs": [
                {
                    "leg_id": leg.leg_id,
                    "venue": leg.instrument.venue.value,
                    "symbol": leg.instrument.symbol,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "limit_price": leg.limit_price,
                    "role": leg.role,
                }
                for leg in intent.legs
            ],
            "metadata": intent.metadata,
        }

    def _intent_signature(self, intent: TradeIntent) -> str:
        pair_id = intent.metadata.get("pair_id", "manual")
        legs = "|".join(
            f"{leg.instrument.venue.value}:{leg.instrument.symbol}:{leg.side}:{leg.quantity}"
            for leg in intent.legs
        )
        return f"{intent.strategy_id}:{pair_id}:{legs}"
