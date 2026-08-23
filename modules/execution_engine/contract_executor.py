"""合约执行器 - 统一交易接口"""
from typing import Optional, Dict
from libs.crypto.base_client import CryptoExchangeClient
from .order_manager import OrderManager, OrderStatus

class ContractExecutor:
    def __init__(
        self,
        exchange_client: CryptoExchangeClient,
        paper_trading: bool = True,
        venue: str = "unknown",
        available: bool = True,
    ):
        self.client = exchange_client
        self.order_manager = OrderManager()
        self.paper_trading = paper_trading
        self.venue = venue
        # When False, this venue is a non-functional stub (e.g. an unsigned
        # client). BasketExecutor must not route orders here or report fills —
        # a no-op is never an execution.
        self.available = available

    def execute_trade(self, symbol: str, side: str, price: float, size: float,
                     order_type: str = "LIMIT") -> str:
        """执行交易"""
        order_id = self.order_manager.create_order(symbol, side, price, size)

        try:
            exchange_order_id = self.client.place_order(symbol, side, price, size, order_type)
            order = self.order_manager.get_order(order_id)
            order.exchange_order_id = exchange_order_id
            self.order_manager.submit_order(order_id)
            return order_id
        except Exception as e:
            self.order_manager.reject_order(order_id, str(e))
            raise Exception(f"交易执行失败: {e}")

    def cancel_trade(self, order_id: str) -> bool:
        """取消交易"""
        order = self.order_manager.get_order(order_id)
        if not order or not order.exchange_order_id:
            return False

        success = self.client.cancel_order(order.exchange_order_id, order.market_id)
        if success:
            order.status = OrderStatus.CANCELLED
        return success

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """查询订单状态"""
        order = self.order_manager.get_order(order_id)
        if not order:
            return None

        return {
            "order_id": order.order_id,
            "symbol": order.market_id,
            "side": order.side,
            "price": order.price,
            "size": order.size,
            "filled_size": order.filled_size,
            "status": order.status.value,
            "exchange_order_id": order.exchange_order_id,
            "error": order.error,
            "created_at": order.created_at.isoformat()
        }

    def reconcile_trade(
        self,
        order_id: str,
        *,
        exchange_order_id: str | None = None,
        symbol: str | None = None,
    ) -> Optional[Dict]:
        """Query local/venue truth after recovery; return None when unknowable."""
        local = self.get_order_status(order_id)
        if local is not None:
            return local
        if not exchange_order_id:
            return None
        venue_order = self.client.get_order(exchange_order_id, symbol)
        if not venue_order:
            return None
        raw_status = str(venue_order.get("status", "UNKNOWN")).upper()
        status_map = {
            "NEW": OrderStatus.OPEN,
            "OPEN": OrderStatus.OPEN,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        status = status_map.get(raw_status, OrderStatus.UNKNOWN)
        return {
            "order_id": order_id,
            "exchange_order_id": exchange_order_id,
            "symbol": symbol,
            "status": status.value,
            "filled_size": float(
                venue_order.get("executedQty", venue_order.get("filled_size", 0.0)) or 0.0
            ),
        }

    def get_position(self, symbol: str) -> Optional[Dict]:
        """查询持仓"""
        return self.client.get_position(symbol)

    def get_all_orders(self) -> Dict:
        """获取所有订单"""
        return {oid: self.get_order_status(oid) for oid in self.order_manager.orders}

    def get_venue(self) -> str:
        return self.venue
