"""
Spread Reversion Strategy - 价差回归策略

数学原理:
- 价差 = ask_price - bid_price
- 当价差超过历史均值 + k*std 时,预期回归 (Bollinger-band / z-score 思想)

设计要点 (grounded in mean-reversion best practice):
- **z-score entry band**: 进场阈值 ~2σ,约 95% 的正常观测落在 ±2σ 内,超出属"稀有且
  有意义"的偏离,才值得下注。
- **z-score stop / structural-break guard**: 当 z 超过 ``zscore_stop_std`` (默认 4σ)
  时,价差可能因结构性事件永久走阔——此时不应继续"接飞刀",而是放弃进场。
- **confirmation bars**: 要求连续 ``confirm_bars`` 根 bar 满足进场条件,过滤单根
  尖刺造成的假信号。
- **sample std (ddof=1)**: 用无偏样本标准差估计带宽,小样本下比总体标准差更稳健。

参数全部带安全默认值,构造签名与返回结构保持不变 (向后兼容)。
"""
from collections import deque
from datetime import datetime, timedelta
from typing import Optional
import math

from services.strategy_engine.base import Strategy, StrategySignal
from strategies.signal_core import SpreadReversionParams, spread_reversion_entry
from libs.schemas import Side


class SpreadReversionStrategy(Strategy):
    """价差回归策略"""

    def __init__(self, config: dict = None):
        super().__init__("spread_reversion", config)

        # 参数
        self.lookback_window = self.config.get("lookback_window", 60)
        self.entry_threshold_std = self.config.get("entry_threshold_std", 2.0)
        self.min_spread_bps = self.config.get("min_spread_bps", 50.0)
        # 进场后价差回到 ±exit_threshold_std 视为均衡 (供下游平仓逻辑参考)。
        self.exit_threshold_std = self.config.get("exit_threshold_std", 0.5)
        # 超过该 z 视为结构性走阔,放弃进场 (不接飞刀)。
        self.zscore_stop_std = self.config.get("zscore_stop_std", 4.0)
        # 需要连续多少根 bar 确认后才进场,过滤单根尖刺。
        self.confirm_bars = max(1, int(self.config.get("confirm_bars", 1)))
        self.base_size = self.config.get("base_size", 10.0)
        # 最少样本数才开始计算 (与历史行为保持一致)。
        self.min_samples = max(2, int(self.config.get("min_samples", 20)))

        # 历史数据
        self.spread_history: dict[str, deque] = {}

    def generate_signal_sync(self, features: dict) -> Optional[StrategySignal]:
        """Synchronous core so the same causal logic is reachable without an
        event loop (used by look-ahead guards / research loops)."""
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

        # 进场判定走共享因果核心 (strategies/signal_core)，research 与 live 使用
        # 完全相同的一段代码，从架构上保证 research == live 且无未来函数 (P7)。
        params = SpreadReversionParams(
            entry_threshold_std=self.entry_threshold_std,
            min_spread_bps=self.min_spread_bps,
            zscore_stop_std=self.zscore_stop_std,
            min_samples=self.min_samples,
            lookback_window=self.lookback_window,
        )
        decision = spread_reversion_entry(list(history), params)
        if not decision.enter:
            return None
        mean_spread, std_spread = decision.mean, decision.std
        z_score = decision.z_score
        # 额外的 live-only 过滤：连续 confirm_bars 根确认，过滤单根尖刺。
        if not self._confirmed(history, mean_spread, std_spread):
            return None

        # 有界 logistic 置信度:随 z 超过阈值平滑上升并饱和到 0.95。
        excess = z_score - self.entry_threshold_std
        confidence = 0.5 + 0.45 * (1.0 - math.exp(-excess))
        confidence = max(0.5, min(0.95, confidence))
        edge_bps = (spread_bps - mean_spread) / 2  # 预期赚取一半价差回归

        # 波动率归一化仓位:价差越"极端"仓位越大,但对绝对波动做温和缩放。
        size = self.base_size * min(1.5, 0.5 + confidence)

        return StrategySignal(
            market_id=market_id,
            side=Side.BUY_YES,
            price=features.get("bid_price", mid_price * 0.99),
            size=size,
            confidence=confidence,
            expected_edge_bps=edge_bps,
            reason=f"spread_reversion:z={z_score:.2f},spread={spread_bps:.1f}bps",
        )

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号 (异步入口,保持原有公共 API)。"""
        return self.generate_signal_sync(features)

    @staticmethod
    def _mean_std(history) -> tuple[float, float]:
        """无偏样本均值/标准差 (ddof=1)。"""
        n = len(history)
        mean = sum(history) / n
        if n < 2:
            return mean, 0.0
        variance = sum((x - mean) ** 2 for x in history) / (n - 1)
        return mean, math.sqrt(variance)

    def _confirmed(self, history, mean: float, std: float) -> bool:
        """最近 ``confirm_bars`` 根 bar 的 z 都需超过进场阈值。"""
        if self.confirm_bars <= 1:
            return True
        recent = list(history)[-self.confirm_bars:]
        if len(recent) < self.confirm_bars:
            return False
        return all((x - mean) / std > self.entry_threshold_std for x in recent)
