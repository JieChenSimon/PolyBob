"""
Cross Market Dislocation Strategy - 跨市场错位套利
"""
from typing import Optional
from collections import deque
import math
from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side


class CrossMarketStrategy(Strategy):
    """跨市场错位套利策略"""

    def __init__(self, config: dict = None):
        super().__init__("cross_market_dislocation", config)

        self.z_score_threshold = self.config.get("z_score_threshold", 2.0)
        self.min_spread_bps = self.config.get("min_spread_bps", 50.0)
        self.lookback_window = self.config.get("lookback_window", 100)

        # 市场对价差历史
        self.spread_history: dict[tuple, deque] = {}
        self.market_prices: dict[str, float] = {}

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        market_id = features.get("market_id")
        mid_price = features.get("mid_price", 0)

        if not market_id or mid_price == 0:
            return None

        # 更新价格缓存
        self.market_prices[market_id] = mid_price

        # 需要至少两个市场才能比较
        if len(self.market_prices) < 2:
            return None

        # 寻找最大价差
        best_signal = None
        max_z_score = 0

        for other_id, other_price in self.market_prices.items():
            if other_id == market_id:
                continue

            pair_key = tuple(sorted([market_id, other_id]))
            spread = abs(mid_price - other_price) * 10000  # bps

            if pair_key not in self.spread_history:
                self.spread_history[pair_key] = deque(maxlen=self.lookback_window)

            history = self.spread_history[pair_key]
            history.append(spread)

            if len(history) < 20:
                continue

            mean = sum(history) / len(history)
            std = math.sqrt(sum((x - mean) ** 2 for x in history) / len(history))

            if std == 0:
                continue

            z_score = abs((spread - mean) / std)

            if z_score > self.z_score_threshold and spread > self.min_spread_bps:
                if z_score > max_z_score:
                    max_z_score = z_score
                    side = Side.SELL_YES if mid_price > other_price else Side.BUY_YES
                    confidence = min(0.9, 0.5 + (z_score - self.z_score_threshold) * 0.1)

                    best_signal = StrategySignal(
                        market_id=market_id,
                        side=side,
                        price=mid_price,
                        size=10.0,
                        confidence=confidence,
                        expected_edge_bps=spread - mean,
                        reason=f"cross_market:z={z_score:.2f},pair={other_id[:8]}"
                    )

        return best_signal
