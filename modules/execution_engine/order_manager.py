"""最小执行层 - 订单管理。

订单状态统一使用 ``libs.schemas.OrderStatus``，避免执行腿与 venue order
各自维护一套含义冲突的枚举。
"""
from dataclasses import dataclass
from datetime import datetime
import uuid

from libs.schemas import OrderStatus

@dataclass
class Order:
    order_id: str
    market_id: str
    side: str  # "buy" or "sell"
    price: float
    size: float
    status: OrderStatus
    created_at: datetime
    filled_at: datetime = None
    exchange_order_id: str = None
    filled_size: float = 0.0
    error: str = None

class OrderManager:
    def __init__(self):
        self.orders = {}

    def create_order(self, market_id, side, price, size):
        """创建订单"""
        order_id = f"order_{uuid.uuid4().hex[:16]}"

        order = Order(
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            status=OrderStatus.PENDING_SUBMIT,
            created_at=datetime.now()
        )

        self.orders[order_id] = order
        return order_id

    def submit_order(self, order_id):
        """提交订单（模拟）"""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.SUBMITTED
            return True
        return False

    def fill_order(self, order_id):
        """成交订单（模拟）"""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.FILLED
            self.orders[order_id].filled_size = self.orders[order_id].size
            self.orders[order_id].filled_at = datetime.now()
            return True
        return False

    def get_order(self, order_id):
        """获取订单"""
        return self.orders.get(order_id)

    def reject_order(self, order_id, error: str):
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.REJECTED
            self.orders[order_id].error = error
