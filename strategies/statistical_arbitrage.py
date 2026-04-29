"""
Statistical Arbitrage Strategy - 统计套利策略

数学原理:
- 寻找相关市场的定价偏差
- 协整关系: Y = β*X + ε, 其中 ε 均值回归
- 当偏差超过阈值时,做多低估/做空高估
"""
from typing import Optional
from collections import defaultdict, deque
import math

from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side


class StatisticalArbitrageStrategy(Strategy):
    """统计套利策略"""

    def __init__(self, config: dict = None):
        super().__init__("stat_arb", config)

        # 参数
        self.correlation_threshold = self.config.get("correlation_threshold", 0.7)
        self.entry_threshold_std = self.config.get("entry_threshold_std", 2.5)

        # 市场对价格历史
        self.price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.last_check_time = None

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        market_id = features.get("market_id")
        mid_price = features.get("mid_price", 0)

        if not market_id or mid_price == 0:
            return None

        # 记录价格
        self.price_history[market_id].append(mid_price)

        # 每个市场只检查一次(避免重复信号)
        if len(self.price_history[market_id]) < 30:
            return None

        # 寻找相关市场
        for other_id, other_prices in self.price_history.items():
            if other_id == market_id or len(other_prices) < 30:
                continue

            # 计算相关性
            corr = self._calculate_correlation(
                list(self.price_history[market_id]),
                list(other_prices)
            )

            if abs(corr) < self.correlation_threshold:
                continue

            # 计算价差
            current_spread = mid_price - other_prices[-1]
            spreads = [
                self.price_history[market_id][i] - other_prices[i]
                for i in range(min(len(self.price_history[market_id]), len(other_prices)))
            ]

            mean_spread = sum(spreads) / len(spreads)
            variance = sum((s - mean_spread) ** 2 for s in spreads) / len(spreads)
            std_spread = math.sqrt(variance)

            if std_spread == 0:
                continue

            z_score = (current_spread - mean_spread) / std_spread

            # 价差过大 -> 做空当前市场
            if z_score > self.entry_threshold_std:
                confidence = min(0.9, 0.5 + (z_score - self.entry_threshold_std) * 0.08)
                edge_bps = abs(z_score) * std_spread / mid_price * 10000

                return StrategySignal(
                    market_id=market_id,
                    side=Side.SELL_YES,
                    price=features.get("ask_price", mid_price * 1.01),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"stat_arb:pair={other_id[:8]},z={z_score:.2f},corr={corr:.2f}"
                )

            # 价差过小 -> 做多当前市场
            elif z_score < -self.entry_threshold_std:
                confidence = min(0.9, 0.5 + (abs(z_score) - self.entry_threshold_std) * 0.08)
                edge_bps = abs(z_score) * std_spread / mid_price * 10000

                return StrategySignal(
                    market_id=market_id,
                    side=Side.BUY_YES,
                    price=features.get("bid_price", mid_price * 0.99),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"stat_arb:pair={other_id[:8]},z={z_score:.2f},corr={corr:.2f}"
                )

        return None

    def _calculate_correlation(self, x: list, y: list) -> float:
        """计算皮尔逊相关系数"""
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        x = x[-n:]
        y = y[-n:]

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)
