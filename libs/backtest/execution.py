"""
模拟订单执行器
"""
import asyncio
import math
import random
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import structlog
import numpy as np
from enum import StrEnum

from libs.schemas import Side

logger = structlog.get_logger()


@dataclass
class ExecutionConfig:
    """执行配置

    ``seed`` controls the latency RNG so backtest runs are reproducible.
    The default (42) makes every default-configured run deterministic;
    set ``seed=None`` explicitly to opt into nondeterministic latencies.
    A dedicated ``random.Random`` instance is always used — the global
    ``random`` module state is never touched.
    """
    base_latency_ms: float = 50.0
    latency_std_ms: float = 20.0
    slippage_model: str = "sqrt"  # "linear", "sqrt", "almgren_chriss"
    impact_coefficient: float = 0.1
    permanent_impact_factor: float = 0.5  # 永久冲击占比
    seed: int | None = 42  # None = nondeterministic latency
    fee_bps: float = 0.0


@dataclass
class MarketState:
    """市场状态"""
    best_bid: float
    best_ask: float
    bid_depth: float
    ask_depth: float
    timestamp: datetime


@dataclass
class Execution:
    """成交记录"""
    order_id: str
    market_id: str
    side: Side
    price: float
    size: float
    timestamp: datetime
    slippage: float
    fee: float = 0.0
    latency_ms: float = 0.0


class TimeInForce(StrEnum):
    """Supported paper order lifecycles."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass
class PaperOrder:
    order_id: str
    market_id: str
    side: Side
    quantity: float
    limit_price: float | None
    time_in_force: TimeInForce
    remaining: float
    status: str = "open"
    filled_quantity: float = 0.0


class PaperBroker:
    """Deterministic order lifecycle model for real-market paper feeds.

    ``on_market`` must be called with the latest real BBO/depth snapshot. It
    models limit crossing, partial fills, IOC/FOK behavior, fees/slippage via
    :class:`SimulatedExecutor`, and cancel-vs-fill ordering. It never submits to
    a venue; callers may pass resulting executions to the authoritative ledger.
    """

    def __init__(self, config: ExecutionConfig | None = None):
        self.executor = SimulatedExecutor(config)
        self.orders: dict[str, PaperOrder] = {}
        self.executions: list[Execution] = []

    def submit_order(
        self, *, order_id: str, market_id: str, side: Side, quantity: float,
        limit_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ) -> PaperOrder:
        if order_id in self.orders:
            raise ValueError(f"duplicate order_id: {order_id}")
        if quantity <= 0 or (limit_price is not None and limit_price <= 0):
            raise ValueError("quantity and limit_price must be positive")
        order = PaperOrder(order_id, market_id, side, float(quantity), limit_price,
                           TimeInForce(time_in_force), float(quantity))
        self.orders[order_id] = order
        return order

    async def cancel_order(self, order_id: str) -> PaperOrder:
        order = self.orders[order_id]
        if order.status == "open":
            order.status = "cancelled"
        return order

    async def on_market(self, market_id: str, state: MarketState) -> list[Execution]:
        """Match all eligible orders against one real snapshot."""
        fills: list[Execution] = []
        for order in list(self.orders.values()):
            if order.market_id != market_id or order.status != "open":
                continue
            buying = "buy" in order.side.value.lower()
            touch = state.best_ask if buying else state.best_bid
            depth = state.ask_depth if buying else state.bid_depth
            crosses = order.limit_price is None or (
                touch <= order.limit_price if buying else touch >= order.limit_price
            )
            if not crosses or depth <= 0:
                if order.time_in_force in (TimeInForce.IOC, TimeInForce.FOK):
                    order.status = "cancelled"
                continue
            if order.time_in_force is TimeInForce.FOK and depth < order.remaining:
                order.status = "cancelled"
                continue
            fill_size = min(order.remaining, depth)
            execution = await self.executor.execute_order(
                order.order_id, order.market_id, order.side, touch, fill_size, state
            )
            if execution is None:
                continue
            order.remaining -= execution.size
            order.filled_quantity += execution.size
            order.status = "filled" if order.remaining <= 1e-12 else (
                "cancelled" if order.time_in_force is TimeInForce.IOC else "partial"
            )
            self.executions.append(execution)
            fills.append(execution)
        return fills


class SlippageModel:
    """滑点模型 - 优化版本"""

    @staticmethod
    def linear_impact(order_size: float, available_depth: float, impact_coef: float = 0.1) -> float:
        """线性市场冲击模型"""
        if available_depth <= 0:
            return 0.0
        return impact_coef * (order_size / available_depth)

    @staticmethod
    def sqrt_impact(order_size: float, available_depth: float, impact_coef: float = 0.1) -> float:
        """平方根市场冲击模型 (更真实)"""
        if available_depth <= 0:
            return 0.0
        return impact_coef * np.sqrt(order_size / available_depth)

    @staticmethod
    def almgren_chriss_impact(order_size: float, available_depth: float,
                              volatility: float, impact_coef: float = 0.1,
                              permanent_factor: float = 0.5) -> tuple[float, float]:
        """Almgren-Chriss市场冲击模型 (分离临时和永久冲击)"""
        if available_depth <= 0:
            return 0.0, 0.0

        participation_rate = order_size / available_depth
        temporary_impact = impact_coef * volatility * np.sqrt(participation_rate)
        permanent_impact = permanent_factor * temporary_impact

        return temporary_impact, permanent_impact


class SimulatedExecutor:
    """模拟订单执行器"""

    def __init__(self, config: ExecutionConfig = None):
        self.config = config or ExecutionConfig()
        # Dedicated RNG instance: reproducible when seeded, and immune to
        # anything else in the process reseeding the global random module.
        self._rng = random.Random(self.config.seed)

    async def execute_order(
        self,
        order_id: str,
        market_id: str,
        side: Side,
        price: float,
        size: float,
        market_state: MarketState
    ) -> Optional[Execution]:
        """模拟订单执行"""

        # 1. 模拟延迟
        latency = max(0, self._rng.gauss(
            self.config.base_latency_ms,
            self.config.latency_std_ms
        )) / 1000.0
        await asyncio.sleep(latency)

        # 2. 检查流动性
        if "buy" in side.value.lower():
            available_liquidity = market_state.ask_depth
            base_price = market_state.best_ask
        else:
            available_liquidity = market_state.bid_depth
            base_price = market_state.best_bid

        if available_liquidity <= 0:
            logger.warning("no_liquidity", market_id=market_id, side=side)
            return None

        # 3. 计算滑点
        if self.config.slippage_model == "linear":
            slippage_pct = SlippageModel.linear_impact(
                size, available_liquidity, self.config.impact_coefficient
            )
        else:
            slippage_pct = SlippageModel.sqrt_impact(
                size, available_liquidity, self.config.impact_coefficient
            )

        slippage = base_price * slippage_pct
        if "buy" in side.value.lower():
            execution_price = base_price + slippage
        else:
            execution_price = base_price - slippage

        # 4. 生成成交
        execution = Execution(
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=execution_price,
            size=size,
            timestamp=datetime.utcnow(),
            slippage=slippage,
            fee=execution_price * size * self.config.fee_bps / 10_000.0,
            latency_ms=latency * 1000.0,
        )

        logger.info("order_executed",
                   order_id=order_id,
                   price=execution_price,
                   slippage=slippage)

        return execution
