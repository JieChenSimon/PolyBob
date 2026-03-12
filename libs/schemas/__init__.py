"""
Schemas - 统一的数据模型定义
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    """交易方向"""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"


class MarketStatus(str, Enum):
    """市场状态"""
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"
    SUSPENDED = "suspended"


class Market(BaseModel):
    """市场信息"""
    market_id: str
    slug: str
    question: str
    category: Optional[str] = None
    status: MarketStatus
    end_time: Optional[datetime] = None
    liquidity_score: float = 0.0
    created_at: datetime
    updated_at: datetime


class OrderbookTick(BaseModel):
    """订单簿快照"""
    market_id: str
    timestamp: datetime
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    bids: list[tuple[float, float]] = Field(default_factory=list)
    asks: list[tuple[float, float]] = Field(default_factory=list)


class TradeTick(BaseModel):
    """成交记录"""
    market_id: str
    timestamp: datetime
    price: float
    size: float
    side: Side


class Signal(BaseModel):
    """交易信号"""
    signal_id: str
    market_id: str
    strategy_id: str
    timestamp: datetime
    side: Side
    price: float
    size: float
    expected_edge_bps: float
    confidence: float
    ttl_seconds: int
    reason_code: str
    explanation_ref: Optional[str] = None


class OrderRequest(BaseModel):
    """订单请求"""
    request_id: str
    market_id: str
    side: Side
    limit_price: float
    size: float
    time_in_force: str = "gtc"
    max_slippage_bps: float = 40.0
    source_signal_id: Optional[str] = None


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING_SUBMIT = "pending_submit"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    PENDING_CANCEL = "pending_cancel"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class Order(BaseModel):
    """订单"""
    order_id: str
    client_order_id: str
    market_id: str
    side: Side
    price: float
    size: float
    filled_size: float = 0.0
    status: OrderStatus
    exchange_order_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Position(BaseModel):
    """持仓"""
    position_id: str
    market_id: str
    net_qty: float
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    updated_at: datetime
