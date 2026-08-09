"""
Kelly Position Strategy - Kelly 公式仓位管理

数学原理:
Kelly Criterion: f* = (p*b - q) / b
其中:
- f* = 最优仓位比例
- p = 胜率
- q = 1-p (败率)
- b = 赔率 (盈利/亏损比)

应用与稳健化 (grounded in fractional-Kelly best practice):
- **fractional Kelly (0.25x–0.5x)**: 全 Kelly 长期增长最优但回撤惊人 (常见 60%+);
  半 Kelly 保留 ~75% 增长却把波动/回撤砍掉约一半。默认用 1/4 Kelly。
- **hard cap on f***: 输入 (胜率/赔率) 都是噪声估计,对最优比例本身设上限,避免
  过度下注 (overbetting 会导致必然破产,而 underbetting 是安全的)。
- **volatility scaling**: 仓位与波动率成反比——高波动标的自动获得更小仓位。
- **drawdown throttle**: 处于回撤中时线性缩减仓位,控制连亏放大。
- **negative-edge rejection**: f* <= 0 表示负期望,直接不交易 (这是策略问题,不是
  仓位问题)。
"""
from typing import Optional
import math

from modules.strategy_engine.base import Strategy, StrategySignal
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
        # 对"最优 Kelly 比例"本身设上限,防止噪声输入导致过度下注。
        self.max_kelly_fraction = self.config.get("max_kelly_fraction", 0.5)
        # 波动率归一化的参考值 (bps);实际波动越高,仓位越小。
        self.target_volatility_bps = self.config.get("target_volatility_bps", 100.0)

        # 回撤节流:跟踪权益峰值,回撤时缩减仓位。
        self.equity_peak: Optional[float] = None
        self.max_drawdown_throttle = self.config.get("max_drawdown_throttle", 0.5)

    def update_equity(self, equity: float) -> float:
        """更新权益峰值,返回当前回撤比例 (0=在峰值)。外部可选调用。"""
        if self.equity_peak is None or equity > self.equity_peak:
            self.equity_peak = equity
        if not self.equity_peak:
            return 0.0
        return max(0.0, (self.equity_peak - equity) / self.equity_peak)

    def _drawdown_scale(self, features: dict) -> float:
        """回撤越深,仓位缩放系数越小 (线性),下限由 throttle 控制。"""
        equity = features.get("equity")
        if equity is not None:
            drawdown = self.update_equity(float(equity))
        else:
            drawdown = float(features.get("current_drawdown", 0.0) or 0.0)
        drawdown = max(0.0, min(1.0, drawdown))
        return max(1.0 - self.max_drawdown_throttle, 1.0 - drawdown)

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

        # 对最优比例设硬上限,避免噪声输入导致过度下注。
        kelly_capped = min(kelly_fraction_optimal, self.max_kelly_fraction)

        # 使用 fractional Kelly
        position_fraction = kelly_capped * self.kelly_fraction

        # 波动率归一化:实际波动 (优先用显式 volatility_bps,退化为 spread_bps)
        # 高于参考值时按比例缩减仓位。
        realized_vol = float(features.get("volatility_bps", spread_bps) or 0.0)
        vol_scale = 1.0
        if realized_vol > 0:
            vol_scale = min(1.0, self.target_volatility_bps / realized_vol)

        # 回撤节流
        dd_scale = self._drawdown_scale(features)

        position_size = position_fraction * self.max_position_size * vol_scale * dd_scale
        position_size = min(position_size, self.max_position_size)

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
            reason=(
                f"kelly:imb={depth_imbalance:.2f},p={win_prob:.2f},"
                f"kelly={kelly_fraction_optimal:.3f},vol={vol_scale:.2f},dd={dd_scale:.2f}"
            ),
        )
