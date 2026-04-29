"""
Kelly Position Strategy - Kelly 公式仓位管理

数学原理:
Kelly Criterion: f* = (p*b - q) / b
其中:
- f* = 最优仓位比例
- p = 胜率
- q = 1-p (败率)
- b = 赔率 (盈利/亏损比)

应用:
- 根据市场特征估计胜率和赔率
- 计算最优仓位大小
- 使用 fractional Kelly (如 0.25x) 降低风险
"""
from typing import Optional
import math

from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side


class KellyPositionStrategy(Strategy):
    """Kelly 仓位管理策略"""

    def __init__(self, config: dict = None):
        super().__init__("kelly_position", config)

        # 参数
        self.kelly_fraction = self.config.get("kelly_fraction", 0.25)  # 使用 1/4 Kelly
        self.min_edge_bps = self.config.get("min_edge_bps", 30.0)
        self.max_position_size = self.config.get("max_position_size", 100.0)
        self.depth_imbalance_threshold = self.config.get("depth_imbalance_threshold", 0.3)

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        market_id = features.get("market_id")
        mid_price = features.get("mid_price", 0)
        depth_imbalance = features.get("depth_imbalance", 0)
        spread_bps = features.get("spread_bps", 0)

        if not market_id or mid_price == 0:
            return None

        # 深度不平衡显著 -> 价格可能向买方移动
        if abs(depth_imbalance) < self.depth_imbalance_threshold:
            return None

        # 估计胜率 (基于深度不平衡)
        # 深度不平衡越大,胜率越高
        win_prob = 0.5 + depth_imbalance * 0.3  # 0.5 ± 0.3
        win_prob = max(0.1, min(0.9, win_prob))

        # 估计赔率 (基于价差)
        # 价差越小,赔率越好
        odds_ratio = 1.0 + (100.0 - spread_bps) / 100.0  # 价差小 -> 赔率高
        odds_ratio = max(1.0, odds_ratio)

        # Kelly 公式
        kelly_fraction_optimal = (win_prob * odds_ratio - (1 - win_prob)) / odds_ratio

        if kelly_fraction_optimal <= 0:
            return None

        # 使用 fractional Kelly
        position_fraction = kelly_fraction_optimal * self.kelly_fraction
        position_size = min(position_fraction * self.max_position_size, self.max_position_size)

        if position_size < 1.0:
            return None

        # 计算预期优势
        expected_edge_bps = (win_prob * odds_ratio - 1) * 10000 / odds_ratio

        if expected_edge_bps < self.min_edge_bps:
            return None

        # 生成信号
        side = Side.BUY_YES if depth_imbalance > 0 else Side.SELL_YES
        price = features.get("bid_price" if side == Side.BUY_YES else "ask_price", mid_price)

        confidence = win_prob

        return StrategySignal(
            market_id=market_id,
            side=side,
            price=price,
            size=position_size,
            confidence=confidence,
            expected_edge_bps=expected_edge_bps,
            reason=f"kelly:imb={depth_imbalance:.2f},p={win_prob:.2f},kelly={kelly_fraction_optimal:.3f}"
        )
