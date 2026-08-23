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


class ExecutionVenue(str, Enum):
    """执行 venue 类型"""
    POLYMARKET = "polymarket"
    BINANCE = "binance"
    HYPERLIQUID = "hyperliquid"
    PAPER = "paper"


class MarketStatus(str, Enum):
    """市场状态"""
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"
    SUSPENDED = "suspended"


class Market(BaseModel):
    """市场信息"""
    market_id: str
    gamma_market_id: str
    slug: str
    question: str
    category: Optional[str] = None
    status: MarketStatus
    end_time: Optional[datetime] = None
    liquidity_score: float = 0.0
    clob_token_ids: list[str] = Field(default_factory=list)
    primary_asset_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class OrderbookTick(BaseModel):
    """订单簿快照"""
    market_id: str
    asset_id: Optional[str] = None
    timestamp: datetime
    # A side that is not quoted is ``None``. It used to be ``0.0``, which is a
    # real price — a bid of zero — and downstream that made a one-sided book
    # look like a two-sided one with a free option on it.
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    bids: list[tuple[float, float]] = Field(default_factory=list)
    asks: list[tuple[float, float]] = Field(default_factory=list)
    # Order-book platform extensions (optional, backward compatible).
    # source_ts: provider/exchange timestamp; None when the feed omitted it
    # (never silently replaced by local time — check `quality`).
    source_ts: Optional[datetime] = None
    # receive_ts: local UTC receive time, always set by the ingestor.
    receive_ts: Optional[datetime] = None
    # quality: ok | stale | degraded | no_timestamp
    quality: str = "ok"
    # Polymarket CLOB exposes no monotonic sequence number.
    sequence_status: str = "no_sequence_available"


class TradeTick(BaseModel):
    """成交记录"""
    market_id: str
    asset_id: Optional[str] = None
    timestamp: datetime
    price: float
    size: float
    side: str


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
    UNAVAILABLE = "unavailable"
    RECONCILING = "reconciling"
    CANCEL_FAILED = "cancel_failed"
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


class InstrumentRef(BaseModel):
    """统一标的引用"""
    venue: ExecutionVenue
    symbol: str
    market_id: Optional[str] = None
    asset_id: Optional[str] = None


class TradeIntentLeg(BaseModel):
    """多腿交易意图中的一条腿"""
    leg_id: str
    instrument: InstrumentRef
    side: str
    quantity: float
    limit_price: Optional[float] = None
    role: str = "primary"


class TradeIntent(BaseModel):
    """组合级交易意图骨架"""
    intent_id: str
    strategy_id: str
    created_at: datetime
    rationale: str
    expected_edge_bps: float
    confidence: float
    legs: list[TradeIntentLeg] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class OrderLeg(BaseModel):
    """篮子订单中的执行腿"""
    leg_id: str
    venue: ExecutionVenue
    symbol: str
    side: str
    quantity: float
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING_SUBMIT
    client_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None
    filled_quantity: float = 0.0
    error: Optional[str] = None


class OrderBasket(BaseModel):
    """多腿订单篮子"""
    basket_id: str
    parent_intent_id: str
    created_at: datetime
    status: str
    legs: list[OrderLeg] = Field(default_factory=list)


class FillEvent(BaseModel):
    """标准化成交回报骨架"""
    fill_id: str
    basket_id: Optional[str] = None
    leg_id: Optional[str] = None
    venue: ExecutionVenue
    symbol: str
    side: str
    price: float
    quantity: float
    filled_at: datetime


class SpreadPairSnapshot(BaseModel):
    """价差对快照骨架"""
    snapshot_id: str
    pair_id: str
    timestamp: datetime
    left: InstrumentRef
    right: InstrumentRef
    left_bid: float
    left_ask: float
    right_bid: float
    right_ask: float
    left_mid: float
    right_mid: float
    spread_bps: float
    z_score: Optional[float] = None
    hedge_ratio: Optional[float] = None
    net_edge_bps: Optional[float] = None
    opportunity_side: Optional[str] = None


class OnchainEntityType(str, Enum):
    """链上地址/对手方实体类型"""
    DEPLOYER = "deployer"
    TREASURY = "treasury"
    TEAM = "team"
    MARKET_MAKER = "market_maker"
    CEX = "cex"
    DEX_ROUTER = "dex_router"
    DEX_POOL = "dex_pool"
    BRIDGE = "bridge"
    FRESH_WALLET = "fresh_wallet"
    UNKNOWN = "unknown"


class OnchainWatchAddress(BaseModel):
    """需要重点监控的链上地址"""
    watch_id: str
    chain: str
    token_symbol: str
    contract_address: str
    address: str
    label: str
    entity_type: OnchainEntityType = OnchainEntityType.UNKNOWN
    tags: list[str] = Field(default_factory=list)
    sell_threshold_usd: float = 25000.0
    cex_transfer_threshold_usd: float = 50000.0
    staging_transfer_threshold_usd: float = 40000.0


class OnchainTransferEvent(BaseModel):
    """标准化链上转账/卖出事件"""
    event_id: str
    chain: str
    tx_hash: str
    block_time: datetime
    token_symbol: str
    contract_address: str
    from_address: str
    to_address: str
    amount: float
    # None when the transfer could not be priced. A zero would be a claim that
    # the transfer was worthless, and the alert threshold would never see it.
    usd_value: Optional[float] = None
    from_label: Optional[str] = None
    to_label: Optional[str] = None
    to_entity_type: OnchainEntityType = OnchainEntityType.UNKNOWN
    action: Optional[str] = None
    source: str = "manual_ingest"


class DistributionAlert(BaseModel):
    """链上出货风险告警"""
    alert_id: str
    watch_id: str
    chain: str
    token_symbol: str
    contract_address: str
    address: str
    label: str
    alert_type: str
    severity: str
    title: str
    summary: str
    usd_value: float
    event_ids: list[str] = Field(default_factory=list)
    counterparty: Optional[str] = None
    created_at: datetime
    metadata: dict[str, str] = Field(default_factory=dict)
