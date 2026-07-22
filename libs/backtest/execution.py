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
    latency_ms: float = 0.0


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
            latency_ms=latency * 1000.0,
        )

        logger.info("order_executed",
                   order_id=order_id,
                   price=execution_price,
                   slippage=slippage)

        return execution
