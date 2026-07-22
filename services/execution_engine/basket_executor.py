"""篮子执行编排器 - 多腿订单骨架"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
import uuid

import structlog

from libs.db.repositories import BasketRepository
from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, OrderBasket, OrderLeg
from .contract_executor import ContractExecutor

logger = structlog.get_logger()


class BasketExecutor:
    def __init__(
        self,
        executors: dict[ExecutionVenue, ContractExecutor],
        basket_repository: BasketRepository | None = None,
    ):
        self.executors = executors
        self.event_bus = get_event_bus()
        self.basket_repository = basket_repository
        self.baskets: dict[str, OrderBasket] = {}

    async def _persist(self, operation, *args, **kwargs) -> None:
        """Run a repository write off the event loop; never crash the hot path."""
        try:
            await asyncio.to_thread(operation, *args, **kwargs)
        except Exception as exc:
            logger.warning(
                "basket_persistence_failed",
                operation=getattr(operation, "__name__", str(operation)),
                error=str(exc) or exc.__class__.__name__,
            )

    async def restore_state(self) -> int:
        """Reload persisted baskets (with leg statuses/fills) into memory.

        Degrades gracefully: a missing or corrupted DB leaves the executor
        running with empty state.
        """
        if self.basket_repository is None:
            return 0
        try:
            records = await asyncio.to_thread(self.basket_repository.list_all)
        except Exception as exc:
            logger.warning(
                "basket_state_restore_failed",
                error=str(exc) or exc.__class__.__name__,
            )
            return 0

        restored = 0
        for record in records:
            try:
                basket = OrderBasket.model_validate(record.payload)
            except Exception as exc:
                logger.warning(
                    "basket_restore_skipped",
                    basket_id=record.basket_id,
                    error=str(exc) or exc.__class__.__name__,
                )
                continue
            basket.status = record.status
            for leg_record in record.legs:
                if leg_record.leg_index >= len(basket.legs):
                    continue
                try:
                    basket.legs[leg_record.leg_index] = OrderLeg.model_validate(leg_record.payload)
                except Exception:
                    basket.legs[leg_record.leg_index].status = leg_record.status
            self.baskets[record.basket_id] = basket
            restored += 1

        logger.info("basket_state_restored", count=restored)
        return restored

    async def submit_basket(
        self,
        legs: list[dict[str, Any]],
        parent_intent_id: str = "manual",
    ) -> dict[str, Any]:
        basket_id = f"basket_{uuid.uuid4().hex[:10]}"
        basket_legs: list[OrderLeg] = []

        for index, leg in enumerate(legs, start=1):
            venue = ExecutionVenue(str(leg["venue"]))
            basket_legs.append(
                OrderLeg(
                    leg_id=str(leg.get("leg_id") or f"{basket_id}:leg{index}"),
                    venue=venue,
                    symbol=str(leg["symbol"]),
                    side=str(leg["side"]),
                    quantity=float(leg["quantity"]),
                    limit_price=float(leg["limit_price"]) if leg.get("limit_price") is not None else None,
                )
            )

        basket = OrderBasket(
            basket_id=basket_id,
            parent_intent_id=parent_intent_id,
            created_at=datetime.utcnow(),
            status="submitting",
            legs=basket_legs,
        )
        self.baskets[basket_id] = basket

        if self.basket_repository is not None:
            await self._persist(
                self.basket_repository.save,
                basket_id,
                intent_id=parent_intent_id,
                status=basket.status,
                payload=basket.model_dump(mode="json"),
                legs=[leg.model_dump(mode="json") for leg in basket.legs],
            )

        for leg_index, leg in enumerate(basket.legs):
            executor = self.executors.get(leg.venue)
            if executor is None:
                leg.status = "rejected"
                await self._persist_leg(basket_id, leg_index, leg)
                continue

            # An unavailable venue is a stub with no real order path. Reporting
            # its legs as "submitted"/"filled" would be a fake execution, so we
            # mark them explicitly "unavailable" and skip the executor entirely.
            if not getattr(executor, "available", True):
                leg.status = "unavailable"
                logger.warning(
                    "order_leg_venue_unavailable",
                    basket_id=basket_id,
                    leg_id=leg.leg_id,
                    venue=leg.venue.value,
                )
                await self._persist_leg(basket_id, leg_index, leg)
                await self.event_bus.publish(
                    Topics.ORDER_LEG_UPDATED,
                    {
                        "basket_id": basket_id,
                        "leg_id": leg.leg_id,
                        "venue": leg.venue.value,
                        "status": leg.status,
                        "client_order_id": leg.client_order_id,
                    },
                )
                continue

            execute = executor.execute_trade
            order_kwargs = {
                "symbol": leg.symbol,
                "side": leg.side,
                "price": leg.limit_price or 0.0,
                "size": leg.quantity,
                "order_type": "LIMIT" if leg.limit_price is not None else "MARKET",
            }
            if executor.paper_trading:
                order_id = execute(**order_kwargs)
            else:
                # Live path performs sync network I/O; keep the event loop free.
                order_id = await asyncio.to_thread(execute, **order_kwargs)
            order_state = executor.get_order_status(order_id)
            leg.client_order_id = order_id
            leg.status = order_state["status"] if order_state else "submitted"
            fill = (
                order_state
                if order_state and "fill" in self._status_text(leg.status).lower()
                else None
            )
            await self._persist_leg(basket_id, leg_index, leg, fill=fill)

            await self.event_bus.publish(
                Topics.ORDER_LEG_UPDATED,
                {
                    "basket_id": basket_id,
                    "leg_id": leg.leg_id,
                    "venue": leg.venue.value,
                    "status": leg.status,
                    "client_order_id": leg.client_order_id,
                },
            )

        basket.status = self._derive_basket_status(basket)
        if self.basket_repository is not None:
            await self._persist(self.basket_repository.update_status, basket_id, basket.status)
        await self.event_bus.publish(
            Topics.ORDER_BASKET_SUBMITTED,
            {
                "basket_id": basket.basket_id,
                "parent_intent_id": basket.parent_intent_id,
                "status": basket.status,
                "leg_count": len(basket.legs),
            },
        )
        return self.serialize_basket(basket)

    async def cancel_basket(self, basket_id: str) -> dict[str, Any]:
        basket = self.baskets[basket_id]
        for leg_index, leg in enumerate(basket.legs):
            if not leg.client_order_id:
                continue
            executor = self.executors.get(leg.venue)
            if executor is None:
                continue
            executor.cancel_trade(leg.client_order_id)
            leg.status = "cancelled"
            await self._persist_leg(basket_id, leg_index, leg)

        basket.status = "cancelled"
        if self.basket_repository is not None:
            await self._persist(self.basket_repository.update_status, basket_id, "cancelled")
        return self.serialize_basket(basket)

    async def _persist_leg(
        self,
        basket_id: str,
        leg_index: int,
        leg: OrderLeg,
        fill: dict[str, Any] | None = None,
    ) -> None:
        if self.basket_repository is None:
            return
        await self._persist(
            self.basket_repository.update_leg,
            basket_id,
            leg_index,
            status=self._status_text(leg.status),
            payload=leg.model_dump(mode="json"),
            fill=fill,
        )

    def list_baskets(self) -> list[dict[str, Any]]:
        return [self.serialize_basket(basket) for basket in self.baskets.values()]

    def get_basket(self, basket_id: str) -> dict[str, Any] | None:
        basket = self.baskets.get(basket_id)
        if basket is None:
            return None
        return self.serialize_basket(basket)

    def serialize_basket(self, basket: OrderBasket) -> dict[str, Any]:
        statuses = [self._status_text(leg.status) for leg in basket.legs]
        submitted_count = sum(1 for status in statuses if "submitted" in status.lower())
        cancelled_count = sum(1 for status in statuses if "cancelled" in status.lower())
        rejected_count = sum(1 for status in statuses if "reject" in status.lower())
        residual_legs = sum(1 for status in statuses if status.lower() not in {"submitted", "cancelled", "filled"})

        return {
            "basket_id": basket.basket_id,
            "parent_intent_id": basket.parent_intent_id,
            "created_at": basket.created_at.isoformat(),
            "status": basket.status,
            "legs": [
                {
                    "leg_id": leg.leg_id,
                    "venue": leg.venue.value,
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "limit_price": leg.limit_price,
                    "status": self._status_text(leg.status),
                    "client_order_id": leg.client_order_id,
                }
                for leg in basket.legs
            ],
            "metrics": {
                "submitted_legs": submitted_count,
                "cancelled_legs": cancelled_count,
                "rejected_legs": rejected_count,
                "residual_legs": residual_legs,
            },
        }

    def _derive_basket_status(self, basket: OrderBasket) -> str:
        statuses = [self._status_text(leg.status).lower() for leg in basket.legs]
        if statuses and all(status == "cancelled" for status in statuses):
            return "cancelled"
        if any("reject" in status for status in statuses):
            return "partial_failure"
        if statuses and all("submitted" in status or "filled" in status for status in statuses):
            return "submitted"
        return "partial"

    def _status_text(self, status: Any) -> str:
        return getattr(status, "value", str(status))
