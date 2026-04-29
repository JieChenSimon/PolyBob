"""
增强统计套利策略 - 使用协整检验和动态对冲比率
"""
from typing import Optional
from collections import defaultdict, deque
import numpy as np

from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side
from libs.quant.cointegration_enhanced import (
    engle_granger_test_enhanced,
    optimal_lookback_window
)
from libs.quant.cointegration import kalman_filter_hedge_ratio, calculate_spread_zscore


class EnhancedStatArbStrategy(Strategy):
    """增强统计套利策略"""

    def __init__(self, config: dict = None):
        super().__init__("enhanced_stat_arb", config)

        self.min_cointegration_strength = self.config.get("min_cointegration_strength", 0.5)
        self.entry_threshold_std = self.config.get("entry_threshold_std", 2.5)
        self.exit_threshold_std = self.config.get("exit_threshold_std", 0.5)

        self.price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self.cointegrated_pairs: dict[tuple, dict] = {}

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        market_id = features.get("market_id")
        mid_price = features.get("mid_price", 0)

        if not market_id or mid_price == 0:
            return None

        self.price_history[market_id].append(mid_price)

        if len(self.price_history[market_id]) < 50:
            return None

        # 寻找协整对
        for other_id, other_prices in self.price_history.items():
            if other_id == market_id or len(other_prices) < 50:
                continue

            pair_key = tuple(sorted([market_id, other_id]))

            # 定期更新协整检验
            if pair_key not in self.cointegrated_pairs or len(self.price_history[market_id]) % 20 == 0:
                y = np.array(list(self.price_history[market_id]))
                x = np.array(list(other_prices))
                result = engle_granger_test_enhanced(y, x)

                if result.is_cointegrated and result.cointegration_strength >= self.min_cointegration_strength:
                    lookback = optimal_lookback_window(result.half_life)
                    self.cointegrated_pairs[pair_key] = {
                        'hedge_ratio': result.hedge_ratio,
                        'half_life': result.half_life,
                        'lookback': lookback,
                        'strength': result.cointegration_strength
                    }

            if pair_key not in self.cointegrated_pairs:
                continue

            # 使用Kalman Filter动态对冲比率
            y = np.array(list(self.price_history[market_id]))
            x = np.array(list(other_prices))
            beta_estimates, _ = kalman_filter_hedge_ratio(y, x)
            current_beta = beta_estimates[-1]

            # 计算Z-score
            lookback = self.cointegrated_pairs[pair_key]['lookback']
            zscores = calculate_spread_zscore(y, x, current_beta, lookback)
            current_z = zscores[-1]

            # 生成信号
            if current_z > self.entry_threshold_std:
                confidence = min(0.9, 0.6 + (current_z - self.entry_threshold_std) * 0.05)
                edge_bps = abs(current_z) * 50

                return StrategySignal(
                    market_id=market_id,
                    side=Side.SELL_YES,
                    price=features.get("ask_price", mid_price * 1.01),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"enhanced_stat_arb:z={current_z:.2f},hl={self.cointegrated_pairs[pair_key]['half_life']:.1f}"
                )

            elif current_z < -self.entry_threshold_std:
                confidence = min(0.9, 0.6 + (abs(current_z) - self.entry_threshold_std) * 0.05)
                edge_bps = abs(current_z) * 50

                return StrategySignal(
                    market_id=market_id,
                    side=Side.BUY_YES,
                    price=features.get("bid_price", mid_price * 0.99),
                    size=10.0,
                    confidence=confidence,
                    expected_edge_bps=edge_bps,
                    reason=f"enhanced_stat_arb:z={current_z:.2f},hl={self.cointegrated_pairs[pair_key]['half_life']:.1f}"
                )

        return None
