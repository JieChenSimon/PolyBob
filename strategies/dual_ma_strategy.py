"""双均线交易策略模块"""
import numpy as np

class DualMAStrategy:
    """双均线策略"""

    def __init__(self, fast_period=5, slow_period=20):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def calculate_signals(self, prices):
        """计算双均线信号"""
        if len(prices) < self.slow_period:
            return None

        # 快线和慢线
        fast_ma = np.mean(prices[-self.fast_period:])
        slow_ma = np.mean(prices[-self.slow_period:])

        # 前一根K线的均线
        prev_fast = np.mean(prices[-self.fast_period-1:-1])
        prev_slow = np.mean(prices[-self.slow_period-1:-1])

        # 金叉死叉判断
        current_cross = fast_ma - slow_ma
        prev_cross = prev_fast - prev_slow

        signal = None
        if prev_cross <= 0 and current_cross > 0:
            signal = "golden_cross"  # 金叉
        elif prev_cross >= 0 and current_cross < 0:
            signal = "death_cross"  # 死叉

        return {
            'fast_ma': fast_ma,
            'slow_ma': slow_ma,
            'signal': signal,
            'distance': (fast_ma - slow_ma) / slow_ma * 100
        }
