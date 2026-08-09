"""
Statistical Arbitrage Strategy - 统计套利策略

数学原理:
- 寻找相关市场的定价偏差
- 协整关系: Y = β*X + ε, 其中 ε 均值回归
- 当偏差超过阈值时,做多低估/做空高估

设计要点 (grounded in pairs-trading best practice):
- **时间对齐的价差**: 用两条序列的"最近 n 个同步观测"计算价差,避免错位索引把
  不同时刻的价格相减 (原实现的 bug)。
- **half-life gate (OU/AR(1))**: 估计价差回归半衰期,只交易回归速度合理的对
  (太慢=可能非平稳,太快=噪声),半衰期同时决定 z-score 的回看窗口。
- **z-score entry ~2.5σ + z-stop**: 进场用 ~2.5σ (保守),z 超过 ``zscore_stop_std``
  视为结构性走阔,放弃进场。
- 相关性仅作粗筛;真正的进场以价差 z-score 为准。
"""
from typing import Optional
from collections import defaultdict, deque
import math

from modules.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side


class StatisticalArbitrageStrategy(Strategy):
    """统计套利策略"""

    def __init__(self, config: dict = None):
        super().__init__("stat_arb", config)

        # 参数
        self.correlation_threshold = self.config.get("correlation_threshold", 0.7)
        self.entry_threshold_std = self.config.get("entry_threshold_std", 2.5)
        # 结构性走阔保护:z 超过该值放弃进场。
        self.zscore_stop_std = self.config.get("zscore_stop_std", 4.0)
        # 可交易半衰期区间 (以 bar 计)。
        self.min_half_life = self.config.get("min_half_life", 1.0)
        self.max_half_life = self.config.get("max_half_life", 100.0)
        self.min_samples = max(2, int(self.config.get("min_samples", 30)))

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
        if len(self.price_history[market_id]) < self.min_samples:
            return None

        # 寻找相关市场
        for other_id, other_prices in self.price_history.items():
            if other_id == market_id or len(other_prices) < self.min_samples:
                continue

            # 时间对齐:取两条序列的最近 n 个观测。
            n = min(len(self.price_history[market_id]), len(other_prices))
            y = list(self.price_history[market_id])[-n:]
            x = list(other_prices)[-n:]

            # 计算相关性 (粗筛)
            corr = self._calculate_correlation(y, x)
            if abs(corr) < self.correlation_threshold:
                continue

            # 对齐后的价差序列
            spreads = [y[i] - x[i] for i in range(n)]
            mean_spread = sum(spreads) / n
            variance = sum((s - mean_spread) ** 2 for s in spreads) / max(1, n - 1)
            std_spread = math.sqrt(variance)
            if std_spread == 0:
                continue

            # half-life gate:回归速度需落在可交易区间内。
            half_life = self._half_life(spreads, mean_spread)
            if half_life is None or not (self.min_half_life <= half_life <= self.max_half_life):
                continue

            current_spread = spreads[-1]
            z_score = (current_spread - mean_spread) / std_spread

            # 结构性走阔保护。
            if abs(z_score) >= self.zscore_stop_std:
                continue

            edge_bps = abs(z_score) * std_spread / mid_price * 10000

            # 价差过大 -> 做空当前市场
            if z_score > self.entry_threshold_std:
                confidence = min(0.9, 0.5 + (z_score - self.entry_threshold_std) * 0.08)
                return StrategySignal(
                    market_id=market_id,
                    side=Side.SELL_YES,
                    price=features.get("ask_price", mid_price * 1.01),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"stat_arb:pair={other_id[:8]},z={z_score:.2f},corr={corr:.2f},hl={half_life:.1f}",
                )

            # 价差过小 -> 做多当前市场
            elif z_score < -self.entry_threshold_std:
                confidence = min(0.9, 0.5 + (abs(z_score) - self.entry_threshold_std) * 0.08)
                return StrategySignal(
                    market_id=market_id,
                    side=Side.BUY_YES,
                    price=features.get("bid_price", mid_price * 0.99),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"stat_arb:pair={other_id[:8]},z={z_score:.2f},corr={corr:.2f},hl={half_life:.1f}",
                )

        return None

    @staticmethod
    def _half_life(spreads: list, mean: float) -> Optional[float]:
        """OU/AR(1) 半衰期估计。

        回归 Δs_t = λ * (s_{t-1} - mean) + ε,则半衰期 = -ln(2)/ln(1+λ)。
        仅当序列表现出均值回归 (-1 < λ < 0) 时返回正的半衰期,否则返回 None。
        仅用过去数据,天然因果。
        """
        n = len(spreads)
        if n < 3:
            return None
        lagged = [spreads[i - 1] - mean for i in range(1, n)]
        delta = [spreads[i] - spreads[i - 1] for i in range(1, n)]
        denom = sum(v * v for v in lagged)
        if denom == 0:
            return None
        lam = sum(lagged[i] * delta[i] for i in range(len(lagged))) / denom
        # 需要均值回归 (负的、且 1+λ 落在 (0,1))。
        if lam >= 0 or (1.0 + lam) <= 0:
            return None
        return -math.log(2) / math.log(1.0 + lam)

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
