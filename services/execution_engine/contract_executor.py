"""合约执行器 - 统一交易接口"""
from typing import Optional, Dict
from libs.crypto.base_client import CryptoExchangeClient
from .order_manager import OrderManager, OrderStatus

class ContractExecutor:
    def __init__(self, exchange_client: CryptoExchangeClient, paper_trading: bool = True, venue: str = "unknown"):
        self.client = exchange_client
        self.order_manager = OrderManager()
        self.paper_trading = paper_trading
        self.venue = venue

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
            "status": order.status.value,
            "created_at": order.created_at.isoformat()
        }

    def get_position(self, symbol: str) -> Optional[Dict]:
        """查询持仓"""
        return self.client.get_position(symbol)

    def get_all_orders(self) -> Dict:
        """获取所有订单"""
        return {oid: self.get_order_status(oid) for oid in self.order_manager.orders}

    def get_venue(self) -> str:
        return self.venue
