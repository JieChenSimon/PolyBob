"""TradeIntent 到 OrderBasket 的桥接服务"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid

import structlog

from libs.db.repositories import DecisionRepository, IntentRepository
from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, InstrumentRef, TradeIntent, TradeIntentLeg
from modules.risk_manager.risk_checker import (
    PortfolioRiskChecker,
    PositionProvider,
    RiskChecker,
    RiskDecision,
)
from .basket_executor import BasketExecutor

logger = structlog.get_logger()


class StrategyNotPromoted(PermissionError):
    """Raised when a strategy without a gate-approved edge tries to trade."""


class IntentExecutionService:
    def __init__(
        self,
        basket_executor: BasketExecutor,
        risk_checker: RiskChecker | PortfolioRiskChecker | None = None,
        max_open_intents: int = 3,
        dedupe_window_seconds: float = 30.0,
        intent_repository: IntentRepository | None = None,
        decision_repository: DecisionRepository | None = None,
        position_provider: PositionProvider | None = None,
    ):
        self.basket_executor = basket_executor
        self.event_bus = get_event_bus()
        self.risk_checker = risk_checker or RiskChecker(max_position=1000, max_order_size=100)
        # Supplies the current per-market notional exposure to a
        # PortfolioRiskChecker. When absent, positions are unknown and a
        # portfolio checker rejects the intent (unknown != safe).
        self.position_provider = position_provider
        self.max_open_intents = max_open_intents
        self.dedupe_window_seconds = dedupe_window_seconds
        self.intent_repository = intent_repository
        self.decision_repository = decision_repository
        self.intents: dict[str, TradeIntent] = {}
        self.intent_status: dict[str, str] = {}
        self.intent_baskets: dict[str, str] = {}
        self.intent_errors: dict[str, str] = {}
        self._recent_signatures: dict[str, datetime] = {}
        self._idempotency_keys: dict[str, str] = {}

    async def _persist(self, operation, *args, **kwargs) -> None:
        """Run a repository write off the event loop; never crash the hot path."""
        try:
            await asyncio.to_thread(operation, *args, **kwargs)
        except Exception as exc:
            logger.warning(
                "intent_persistence_failed",
                operation=getattr(operation, "__name__", str(operation)),
                error=str(exc) or exc.__class__.__name__,
            )

    async def restore_state(self) -> int:
        """Reload persisted intents into the in-memory hot cache.

        Degrades gracefully: a missing or corrupted DB leaves the service
        running with empty state.
        """
        if self.intent_repository is None:
            return 0
        try:
            records = await asyncio.to_thread(self.intent_repository.list_all)
        except Exception as exc:
            logger.warning(
                "intent_state_restore_failed",
                error=str(exc) or exc.__class__.__name__,
            )
            return 0

        restored = 0
        for record in records:
            try:
                intent = TradeIntent.model_validate(record.payload)
            except Exception as exc:
                logger.warning(
                    "intent_restore_skipped",
                    intent_id=record.intent_id,
                    error=str(exc) or exc.__class__.__name__,
                )
                continue
            self.intents[record.intent_id] = intent
            self.intent_status[record.intent_id] = record.status
            if record.basket_id:
                self.intent_baskets[record.intent_id] = record.basket_id
            if record.error:
                self.intent_errors[record.intent_id] = record.error
            if record.idempotency_key:
                self._idempotency_keys[record.intent_id] = record.idempotency_key
                if record.status == "submitted":
                    timestamp = self._parse_naive_utc(record.updated_at)
                    if timestamp is not None:
                        self._recent_signatures[record.idempotency_key] = timestamp
            restored += 1

        logger.info("intent_state_restored", count=restored)
        return restored

    @staticmethod
    def _parse_naive_utc(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            # Normalize to naive UTC to compare against datetime.utcnow().
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def _require_promoted(self, strategy_id: str) -> None:
        """Refuse to create an intent for a strategy that has no approved edge.

        Fail-closed and *not* configurable per call site: the setting decides
        whether the gate is enforced at all, and it defaults to on.
        """
        from libs.config import get_settings
        from libs.quant.promotion_registry import get_registry

        if not get_settings().require_strategy_promotion:
            return
        registry = get_registry()
        if registry.is_promoted(strategy_id):
            return
        reason = registry.reason_blocked(strategy_id)
        logger.warning("intent_blocked_unpromoted_strategy",
                       strategy_id=strategy_id, reason=reason)
        raise StrategyNotPromoted(
            f"策略 '{strategy_id}' 未过晋级门禁，不能创建交易意图：{reason}"
        )

    async def create_intent(
        self,
        strategy_id: str,
        rationale: str,
        expected_edge_bps: float,
        confidence: float,
        legs: list[dict[str, Any]],
        metadata: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        # The promotion gate lives here because this is the only place an intent
        # can be born. It used to live in the API route instead, which stopped
        # *you* from raising an intent by hand for an unvalidated strategy while
        # the process happily did it on your behalf: the lifespan auto-started
        # ``spread_arbitrage_v1``, which is not on the board at all, and that
        # path never passed through the route. A gate that only guards the door
        # humans use is not a gate.
        self._require_promoted(strategy_id)

        if idempotency_key is not None:
            existing = await self._find_existing_intent(idempotency_key)
            if existing is not None:
                return existing

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
        if idempotency_key is not None:
            self._idempotency_keys[intent_id] = idempotency_key

        if self.intent_repository is not None:
            await self._persist(
                self.intent_repository.save,
                intent_id,
                intent.model_dump(mode="json"),
                "created",
                idempotency_key=idempotency_key,
            )
        if self.decision_repository is not None:
            first_leg = intent.legs[0] if intent.legs else None
            market_id = None
            if first_leg is not None:
                market_id = first_leg.instrument.market_id or first_leg.instrument.symbol
            await self._persist(
                self.decision_repository.save,
                f"dec_{intent_id}",
                strategy_id=strategy_id,
                market_id=market_id,
                payload={
                    "intent_id": intent_id,
                    "rationale": rationale,
                    "expected_edge_bps": float(expected_edge_bps),
                    "confidence": float(confidence),
                    "leg_count": len(intent.legs),
                },
            )

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

    async def _find_existing_intent(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return the already-created intent for this key, if any (idempotent replay)."""
        for intent_id, intent in self.intents.items():
            if self._idempotency_keys.get(intent_id) == idempotency_key:
                return self.serialize_intent(intent)
        if self.intent_repository is None:
            return None
        try:
            record = await asyncio.to_thread(
                self.intent_repository.find_by_idempotency_key, idempotency_key
            )
        except Exception as exc:
            logger.warning(
                "intent_idempotency_lookup_failed",
                error=str(exc) or exc.__class__.__name__,
            )
            return None
        if record is None:
            return None
        if record.intent_id not in self.intents:
            try:
                intent = TradeIntent.model_validate(record.payload)
            except Exception:
                return None
            self.intents[record.intent_id] = intent
            self.intent_status[record.intent_id] = record.status
            if record.basket_id:
                self.intent_baskets[record.intent_id] = record.basket_id
            if record.error:
                self.intent_errors[record.intent_id] = record.error
        self._idempotency_keys[record.intent_id] = idempotency_key
        return self.serialize_intent(self.intents[record.intent_id])

    async def _persist_status(
        self,
        intent_id: str,
        status: str,
        *,
        error: str | None = None,
        basket_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        if self.intent_repository is None:
            return
        await self._persist(
            self.intent_repository.update_status,
            intent_id,
            status,
            error=error,
            basket_id=basket_id,
            idempotency_key=idempotency_key,
        )

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
            await self._persist_status(
                intent_id, "duplicate_blocked", error=self.intent_errors[intent_id]
            )
            return self.serialize_intent(intent)

        open_intents = sum(
            1 for value in self.intent_status.values() if value in {"created", "submitted"}
        )
        if open_intents > self.max_open_intents:
            self.intent_status[intent_id] = "risk_rejected"
            self.intent_errors[intent_id] = "max_open_intents exceeded"
            await self._persist_status(
                intent_id, "risk_rejected", error=self.intent_errors[intent_id]
            )
            return self.serialize_intent(intent)

        allowed, reason = self._evaluate_risk(intent)
        if not allowed:
            self.intent_status[intent_id] = "risk_rejected"
            self.intent_errors[intent_id] = reason
            await self._persist_status(intent_id, "risk_rejected", error=reason)
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
        self._idempotency_keys.setdefault(intent_id, signature)
        await self._persist_status(
            intent_id,
            "submitted",
            basket_id=basket["basket_id"],
            idempotency_key=signature,
        )
        return self.serialize_intent(intent)

    def _evaluate_risk(self, intent: TradeIntent) -> tuple[bool, str]:
        """Run pre-trade risk checks; returns (allowed, reason).

        A PortfolioRiskChecker evaluates the whole intent against current
        positions (from ``position_provider``; None = unknown = rejected).
        The legacy RiskChecker keeps its original per-leg unit checks.
        """
        checker = self.risk_checker
        if hasattr(checker, "evaluate_intent"):
            positions = self.position_provider() if self.position_provider is not None else None
            decision: RiskDecision = checker.evaluate_intent(
                intent.legs, positions, subject_id=intent.intent_id
            )
            if decision.allowed:
                return True, ""
            return False, "; ".join(decision.reasons) or "risk check failed"
        for leg in intent.legs:
            allowed, reason = checker.check_order(leg.quantity)
            if not allowed:
                return False, reason
        return True, ""

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
