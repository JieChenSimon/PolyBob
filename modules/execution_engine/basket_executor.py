"""篮子执行编排器 - 多腿订单骨架"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
import uuid

import structlog

from libs.db.repositories import BasketRepository
from libs.db.execution_ledger import ExecutionLedger, FillCommand
from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, OrderBasket, OrderLeg, OrderStatus
from .contract_executor import ContractExecutor

logger = structlog.get_logger()


class BasketPersistenceError(RuntimeError):
    """A basket state transition could not be durably recorded."""

_TERMINAL_LEG_STATUSES = {
    OrderStatus.FILLED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.REJECTED.value,
    OrderStatus.EXPIRED.value,
    OrderStatus.UNAVAILABLE.value,
}
_RECOVERABLE_LEG_STATUSES = {
    OrderStatus.PENDING_SUBMIT.value,
    OrderStatus.SUBMITTING.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.OPEN.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.PENDING_CANCEL.value,
    OrderStatus.CANCELLING.value,
    OrderStatus.CANCEL_FAILED.value,
    OrderStatus.UNKNOWN.value,
}


class BasketExecutor:
    def __init__(
        self,
        executors: dict[ExecutionVenue, ContractExecutor],
        basket_repository: BasketRepository | None = None,
        execution_ledger: ExecutionLedger | None = None,
        ledger_account_id: str = "paper-main",
    ):
        self.executors = executors
        self.event_bus = get_event_bus()
        self.basket_repository = basket_repository
        self.execution_ledger = execution_ledger
        self.ledger_account_id = ledger_account_id
        self.baskets: dict[str, OrderBasket] = {}

    async def _persist(self, operation, *args, **kwargs) -> None:
        """Run a repository write off the event loop and fail closed on error."""
        try:
            await asyncio.to_thread(operation, *args, **kwargs)
        except Exception as exc:
            logger.warning(
                "basket_persistence_failed",
                operation=getattr(operation, "__name__", str(operation)),
                error=str(exc) or exc.__class__.__name__,
            )
            raise BasketPersistenceError(
                f"basket persistence failed during {getattr(operation, '__name__', operation)}"
            ) from exc

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
            needs_reconciliation = False
            for leg_index, leg in enumerate(basket.legs):
                status = self._status_text(leg.status).lower()
                if status in _RECOVERABLE_LEG_STATUSES:
                    leg.status = OrderStatus.RECONCILING
                    leg.error = "process restarted; venue state must be reconciled"
                    needs_reconciliation = True
                    await self._persist_leg(record.basket_id, leg_index, leg)
            if needs_reconciliation:
                basket.status = OrderStatus.RECONCILING.value
                if self.basket_repository is not None:
                    await self._persist(
                        self.basket_repository.update_status,
                        record.basket_id,
                        basket.status,
                    )
            self.baskets[record.basket_id] = basket
            restored += 1

        logger.info("basket_state_restored", count=restored)
        return restored

    async def submit_basket(
        self,
        legs: list[dict[str, Any]],
        parent_intent_id: str = "manual",
    ) -> dict[str, Any]:
        if not legs:
            raise ValueError("basket must contain at least one leg")
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
                leg.status = OrderStatus.REJECTED
                leg.error = f"no executor registered for {leg.venue.value}"
                await self._persist_leg(basket_id, leg_index, leg)
                continue

            # An unavailable venue is a stub with no real order path. Reporting
            # its legs as "submitted"/"filled" would be a fake execution, so we
            # mark them explicitly "unavailable" and skip the executor entirely.
            if not getattr(executor, "available", True):
                leg.status = OrderStatus.UNAVAILABLE
                leg.error = f"venue {leg.venue.value} is unavailable"
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
            try:
                if executor.paper_trading:
                    order_id = execute(**order_kwargs)
                else:
                    # Live path performs sync network I/O; keep the event loop free.
                    order_id = await asyncio.to_thread(execute, **order_kwargs)
                order_state = executor.get_order_status(order_id)
                leg.client_order_id = order_id
                leg.status = (
                    OrderStatus(str(order_state["status"]))
                    if order_state
                    else OrderStatus.UNKNOWN
                )
                if order_state:
                    leg.exchange_order_id = order_state.get("exchange_order_id")
                    leg.filled_quantity = float(order_state.get("filled_size", 0.0) or 0.0)
                    leg.error = order_state.get("error")
            except Exception as exc:
                leg.status = OrderStatus.REJECTED
                leg.error = str(exc) or exc.__class__.__name__
                logger.warning(
                    "order_leg_submit_failed",
                    basket_id=basket_id,
                    leg_id=leg.leg_id,
                    venue=leg.venue.value,
                    error=leg.error,
                )
                await self._persist_leg(basket_id, leg_index, leg)
                continue
            fill = (
                order_state
                if order_state and "fill" in self._status_text(leg.status).lower()
                else None
            )
            await self._persist_leg(basket_id, leg_index, leg, fill=fill)
            await self._record_ledger_fill(basket_id, leg, order_state)

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
            current_status = self._status_text(leg.status).lower()
            if current_status in _TERMINAL_LEG_STATUSES:
                continue
            if not leg.client_order_id:
                leg.status = OrderStatus.CANCEL_FAILED
                leg.error = "cannot cancel leg without client_order_id"
                await self._persist_leg(basket_id, leg_index, leg)
                continue
            executor = self.executors.get(leg.venue)
            if executor is None or not getattr(executor, "available", True):
                leg.status = OrderStatus.CANCEL_FAILED
                leg.error = f"executor unavailable for {leg.venue.value}"
                await self._persist_leg(basket_id, leg_index, leg)
                continue
            try:
                if executor.paper_trading:
                    cancelled = executor.cancel_trade(leg.client_order_id)
                else:
                    cancelled = await asyncio.to_thread(
                        executor.cancel_trade, leg.client_order_id
                    )
            except Exception as exc:
                cancelled = False
                leg.error = str(exc) or exc.__class__.__name__
            if cancelled:
                leg.status = OrderStatus.CANCELLED
                leg.error = None
            else:
                leg.status = OrderStatus.CANCEL_FAILED
                leg.error = leg.error or "venue did not confirm cancellation"
            await self._persist_leg(basket_id, leg_index, leg)

        basket.status = self._derive_basket_status(basket)
        if self.basket_repository is not None:
            await self._persist(
                self.basket_repository.update_status, basket_id, basket.status
            )
        return self.serialize_basket(basket)

    async def reconcile_basket(self, basket_id: str) -> dict[str, Any]:
        """Refresh every non-terminal leg from local or venue order truth."""
        basket = self.baskets[basket_id]
        for leg_index, leg in enumerate(basket.legs):
            status = self._status_text(leg.status).lower()
            if status in _TERMINAL_LEG_STATUSES:
                continue
            executor = self.executors.get(leg.venue)
            if executor is None or not getattr(executor, "available", True):
                leg.status = OrderStatus.UNAVAILABLE
                leg.error = f"executor unavailable for {leg.venue.value}"
            elif not leg.client_order_id:
                leg.status = OrderStatus.UNKNOWN
                leg.error = "missing client_order_id during reconciliation"
            else:
                try:
                    state = await asyncio.to_thread(
                        executor.reconcile_trade,
                        leg.client_order_id,
                        exchange_order_id=leg.exchange_order_id,
                        symbol=leg.symbol,
                    )
                except Exception as exc:
                    state = None
                    leg.error = str(exc) or exc.__class__.__name__
                if state is None:
                    leg.status = OrderStatus.UNKNOWN
                    leg.error = "venue order state unavailable"
                else:
                    try:
                        leg.status = OrderStatus(str(state["status"]))
                    except ValueError:
                        leg.status = OrderStatus.UNKNOWN
                    leg.filled_quantity = float(
                        state.get("filled_size", leg.filled_quantity) or 0.0
                    )
                    leg.exchange_order_id = (
                        state.get("exchange_order_id") or leg.exchange_order_id
                    )
                    leg.error = state.get("error")
                    await self._record_ledger_fill(basket_id, leg, state)
            await self._persist_leg(basket_id, leg_index, leg)
        basket.status = self._derive_basket_status(basket)
        if self.basket_repository is not None:
            await self._persist(
                self.basket_repository.update_status, basket_id, basket.status
            )
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

    async def _record_ledger_fill(
        self,
        basket_id: str,
        leg: OrderLeg,
        order_state: dict[str, Any] | None,
    ) -> None:
        """Write only venue-confirmed, explicitly identified fills.

        A filled status alone is insufficient: without a stable fill id and
        execution price, a recovery pass could duplicate or misprice the
        canonical ledger. Such states remain visible on the basket but are
        deliberately not treated as accounted fills.
        """
        if self.execution_ledger is None or not order_state:
            return
        fill_id = order_state.get("fill_id")
        fill_price = order_state.get("fill_price")
        filled_quantity = order_state.get("filled_size")
        if not fill_id or fill_price is None or not filled_quantity or not leg.client_order_id:
            return
        try:
            command = FillCommand(
                fill_id=str(fill_id),
                account_id=self.ledger_account_id,
                order_id=str(leg.client_order_id),
                instrument_id=leg.symbol,
                side=leg.side,
                quantity=filled_quantity,
                price=fill_price,
                fee=order_state.get("fee", order_state.get("commission", 0)),
                currency=str(order_state.get("currency", "USD")),
                executed_at=order_state.get("filled_at") or order_state.get("executed_at"),
                metadata={
                    "basket_id": basket_id,
                    "leg_id": leg.leg_id,
                    "venue": leg.venue.value,
                    "exchange_order_id": leg.exchange_order_id,
                },
            )
            await asyncio.to_thread(self.execution_ledger.apply_fill, command)
        except Exception as exc:
            leg.error = f"execution ledger write failed: {exc}"
            logger.error(
                "execution_ledger_fill_write_failed",
                basket_id=basket_id,
                leg_id=leg.leg_id,
                error=str(exc) or exc.__class__.__name__,
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
                    "exchange_order_id": leg.exchange_order_id,
                    "filled_quantity": leg.filled_quantity,
                    "error": leg.error,
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
        if statuses and all(status == "filled" for status in statuses):
            return "filled"
        if any(status == "cancel_failed" for status in statuses):
            return "cancel_failed"
        if any(status == "reconciling" for status in statuses):
            return "reconciling"
        if any(status == "unknown" for status in statuses):
            return "unknown"
        if any(status == "partially_filled" for status in statuses):
            return "partially_filled"
        if any(status in {"rejected", "unavailable"} for status in statuses):
            return "partial_failure"
        if statuses and all(status in _TERMINAL_LEG_STATUSES for status in statuses):
            # Mixed filled/cancelled terminal legs leave a materially different
            # exposure than the requested basket and cannot be called complete.
            return "partial_failure"
        if statuses and all(status in {"submitted", "open", "filled"} for status in statuses):
            return "submitted"
        return "submitting"

    def _status_text(self, status: Any) -> str:
        return getattr(status, "value", str(status))
