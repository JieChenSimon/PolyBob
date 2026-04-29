"""篮子执行编排器 - 多腿订单骨架"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, OrderBasket, OrderLeg
from .contract_executor import ContractExecutor


class BasketExecutor:
    def __init__(self, executors: dict[ExecutionVenue, ContractExecutor]):
        self.executors = executors
        self.event_bus = get_event_bus()
        self.baskets: dict[str, OrderBasket] = {}

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

        for leg in basket.legs:
            executor = self.executors.get(leg.venue)
            if executor is None:
                leg.status = "rejected"
                continue

            order_id = executor.execute_trade(
                symbol=leg.symbol,
                side=leg.side,
                price=leg.limit_price or 0.0,
                size=leg.quantity,
                order_type="LIMIT" if leg.limit_price is not None else "MARKET",
            )
            order_state = executor.get_order_status(order_id)
            leg.client_order_id = order_id
            leg.status = order_state["status"] if order_state else "submitted"

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
        for leg in basket.legs:
            if not leg.client_order_id:
                continue
            executor = self.executors.get(leg.venue)
            if executor is None:
                continue
            executor.cancel_trade(leg.client_order_id)
            leg.status = "cancelled"

        basket.status = "cancelled"
        return self.serialize_basket(basket)

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
