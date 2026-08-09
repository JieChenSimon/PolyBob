"""最小执行层 - 订单管理"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"

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

class OrderManager:
    def __init__(self):
        self.orders = {}
        self.order_counter = 0

    def create_order(self, market_id, side, price, size):
        """创建订单"""
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"

        order = Order(
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            status=OrderStatus.PENDING,
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
            self.orders[order_id].filled_at = datetime.now()
            return True
        return False

    def get_order(self, order_id):
        """获取订单"""
        return self.orders.get(order_id)
