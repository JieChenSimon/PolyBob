"""
Spread Reversion Strategy - 价差回归策略

数学原理:
- 价差 = ask_price - bid_price
- 当价差超过历史均值 + k*std 时,预期回归
- 使用 Bollinger Bands 思想
"""
from collections import deque
from datetime import datetime, timedelta
from typing import Optional
import math

from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side


class SpreadReversionStrategy(Strategy):
    """价差回归策略"""

    def __init__(self, config: dict = None):
        super().__init__("spread_reversion", config)

        # 参数
        self.lookback_window = self.config.get("lookback_window", 60)
        self.entry_threshold_std = self.config.get("entry_threshold_std", 2.0)
        self.min_spread_bps = self.config.get("min_spread_bps", 50.0)

        # 历史数据
        self.spread_history: dict[str, deque] = {}

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        market_id = features.get("market_id")
        spread_bps = features.get("spread_bps", 0)
        mid_price = features.get("mid_price", 0)

        if not market_id or spread_bps == 0 or mid_price == 0:
            return None

        # 初始化历史
        if market_id not in self.spread_history:
            self.spread_history[market_id] = deque(maxlen=self.lookback_window)

        history = self.spread_history[market_id]
        history.append(spread_bps)

        # 需要足够历史数据
        if len(history) < 20:
            return None

        # 计算统计量
        mean_spread = sum(history) / len(history)
        variance = sum((x - mean_spread) ** 2 for x in history) / len(history)
        std_spread = math.sqrt(variance)

        if std_spread == 0:
            return None

        # 计算 z-score
        z_score = (spread_bps - mean_spread) / std_spread

        # 价差异常扩大 -> 做市机会
        if z_score > self.entry_threshold_std and spread_bps > self.min_spread_bps:
            # 同时挂买卖单,赚取价差
            # 这里简化为买入信号(实际应该是做市策略)
            confidence = min(0.95, 0.5 + (z_score - self.entry_threshold_std) * 0.1)
            edge_bps = (spread_bps - mean_spread) / 2  # 预期赚取一半价差

            return StrategySignal(
                market_id=market_id,
                side=Side.BUY_YES,
                price=features.get("bid_price", mid_price * 0.99),
                size=10.0,
                confidence=confidence,
                expected_edge_bps=edge_bps,
                reason=f"spread_reversion:z={z_score:.2f},spread={spread_bps:.1f}bps"
            )

        return None
