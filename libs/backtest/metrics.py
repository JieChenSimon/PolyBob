"""
Performance Metrics - 性能评估指标
"""
from typing import List, Tuple
from datetime import datetime
import math


class PerformanceMetrics:
    """性能指标计算"""

    @staticmethod
    def sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
        """计算夏普比率"""
        if not returns or len(returns) < 2:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return 0.0

        return (mean_return - risk_free_rate) / std_dev

    @staticmethod
    def win_rate(trades: List) -> float:
        """计算胜率"""
        if not trades:
            return 0.0

        winning_trades = sum(1 for t in trades if hasattr(t, 'pnl') and t.pnl > 0)
        return winning_trades / len(trades)

    @staticmethod
    def profit_factor(trades: List) -> float:
        """计算盈亏比"""
        if not trades:
            return 0.0

        gross_profit = sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl < 0))

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @staticmethod
    def calculate_returns(equity_curve: List[Tuple[datetime, float]]) -> List[float]:
        """计算收益率序列"""
        if len(equity_curve) < 2:
            return []

        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i-1][1]
            curr_equity = equity_curve[i][1]
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)

        return returns
