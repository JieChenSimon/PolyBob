"""
Spread Reversion Strategy V1 - 价差回归策略

核心逻辑:
- 监控买卖价差异常扩大
- 当价差超过阈值且订单簿平衡时触发信号
- 在中间价附近挂单,赚取价差收益
"""
import asyncio
import structlog
from datetime import datetime
from typing import Dict
import uuid

from libs.events import get_event_bus, Topics
from libs.schemas import Signal, Side

logger = structlog.get_logger()


class SpreadReversionV1:
    """价差回归策略"""

    def __init__(self, config: dict):
        self.strategy_id = "spread_reversion_v1"
        self.event_bus = get_event_bus()

        # 配置参数
        self.spread_threshold_bps = config.get("spread_threshold_bps", 150.0)
        self.reversion_confidence = config.get("reversion_confidence", 0.7)
        self.min_depth_ratio = config.get("min_depth_ratio", 0.3)
        self.signal_ttl = config.get("signal_ttl_seconds", 180)

        self._running = False

    async def start(self):
        """启动策略"""
        logger.info("starting_strategy", strategy_id=self.strategy_id)
        self._running = True

        # 订阅特征快照
        await self.event_bus.subscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)

    async def stop(self):
        """停止策略"""
        logger.info("stopping_strategy", strategy_id=self.strategy_id)
        self._running = False

    async def _on_feature_snapshot(self, feature_data: dict):
        """处理特征快照"""
        spread_bps = feature_data.get("spread_bps", 0)
        depth_imbalance = abs(feature_data.get("depth_imbalance", 0))

        # 检查价差是否超过阈值
        if spread_bps < self.spread_threshold_bps:
            return

        # 检查订单簿是否相对平衡(深度不平衡小于阈值)
        if depth_imbalance > self.min_depth_ratio:
            return

        # 检查流动性
        bid_size = feature_data.get("bid_size", 0)
        ask_size = feature_data.get("ask_size", 0)
        if bid_size < 10 or ask_size < 10:
            return

        # 生成双向信号(做市)
        await self._generate_market_making_signals(feature_data, spread_bps)

    async def _generate_market_making_signals(self, features: dict, spread_bps: float):
        """生成做市信号"""
        market_id = features["market_id"]
        mid_price = features["mid_price"]
        bid_price = features["bid_price"]
        ask_price = features["ask_price"]

        # 计算预期优势(价差的一半)
        expected_edge_bps = spread_bps / 2

        # 买入信号(在 bid 上方挂单)
        buy_signal = Signal(
            signal_id=str(uuid.uuid4()),
            market_id=market_id,
            strategy_id=self.strategy_id,
            timestamp=datetime.utcnow(),
            side=Side.BUY_YES,
            price=bid_price + (mid_price - bid_price) * 0.3,  # 在价差 30% 位置
            size=50.0,
            expected_edge_bps=expected_edge_bps,
            confidence=self.reversion_confidence,
            ttl_seconds=self.signal_ttl,
            reason_code=f"spread_reversion_wide_spread_{spread_bps:.0f}bps",
        )

        # 卖出信号(在 ask 下方挂单)
        sell_signal = Signal(
            signal_id=str(uuid.uuid4()),
            market_id=market_id,
            strategy_id=self.strategy_id,
            timestamp=datetime.utcnow(),
            side=Side.SELL_YES,
            price=ask_price - (ask_price - mid_price) * 0.3,  # 在价差 30% 位置
            size=50.0,
            expected_edge_bps=expected_edge_bps,
            confidence=self.reversion_confidence,
            ttl_seconds=self.signal_ttl,
            reason_code=f"spread_reversion_wide_spread_{spread_bps:.0f}bps",
        )

        await self.event_bus.publish(Topics.SIGNAL_GENERATED, buy_signal)
        await self.event_bus.publish(Topics.SIGNAL_GENERATED, sell_signal)

        logger.info(
            "market_making_signals_generated",
            market_id=market_id,
            spread_bps=spread_bps,
            mid_price=mid_price,
        )
