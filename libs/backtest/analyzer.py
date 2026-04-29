"""
回测结果分析器
"""
from dataclasses import dataclass
from typing import Dict, Any, List
from datetime import datetime
import math


@dataclass
class PerformanceReport:
    """性能报告"""
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    num_trades: int
    win_rate: float
    profit_factor: float


@dataclass
class RiskReport:
    """风险报告"""
    volatility: float
    var_95: float
    cvar_95: float
    max_consecutive_losses: int


@dataclass
class BacktestReport:
    """完整回测报告"""
    performance: PerformanceReport
    risk: RiskReport
    trades: List[Dict[str, Any]]
    equity_curve: List[tuple]


class BacktestAnalyzer:
    """回测结果分析器"""

    def analyze(self, engine) -> BacktestReport:
        """生成完整回测报告"""
        from libs.backtest.metrics import PerformanceMetrics

        returns = PerformanceMetrics.calculate_returns(engine.equity_curve)

        performance = PerformanceReport(
            total_return=self._total_return(engine.equity_curve),
            annualized_return=self._annualized_return(engine.equity_curve),
            sharpe_ratio=PerformanceMetrics.sharpe_ratio(returns) if returns else 0.0,
            max_drawdown=self._max_drawdown(engine.equity_curve),
            num_trades=len(engine.trades),
            win_rate=self._win_rate(engine.trades),
            profit_factor=self._profit_factor(engine.trades)
        )

        risk = RiskReport(
            volatility=self._volatility(returns),
            var_95=self._var_95(returns),
            cvar_95=self._cvar_95(returns),
            max_consecutive_losses=self._max_consecutive_losses(engine.trades)
        )

        return BacktestReport(
            performance=performance,
            risk=risk,
            trades=[self._trade_to_dict(t) for t in engine.trades],
            equity_curve=engine.equity_curve
        )

    def _total_return(self, equity_curve: List[tuple]) -> float:
        if not equity_curve:
            return 0.0
        return (equity_curve[-1][1] - equity_curve[0][1]) / equity_curve[0][1]

    def _annualized_return(self, equity_curve: List[tuple]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        total_days = (equity_curve[-1][0] - equity_curve[0][0]).days
        if total_days <= 0:
            return 0.0
        total_return = self._total_return(equity_curve)
        return (1 + total_return) ** (365 / total_days) - 1

    def _max_drawdown(self, equity_curve: List[tuple]) -> float:
        if not equity_curve:
            return 0.0
        peak = equity_curve[0][1]
        max_dd = 0.0
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _win_rate(self, trades: List) -> float:
        if not trades:
            return 0.0
        winning = sum(1 for t in trades if hasattr(t, 'pnl') and t.pnl > 0)
        return winning / len(trades)

    def _profit_factor(self, trades: List) -> float:
        if not trades:
            return 0.0
        gross_profit = sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')

    def _volatility(self, returns: List[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance) * math.sqrt(252)

    def _var_95(self, returns: List[float]) -> float:
        if not returns:
            return 0.0
        sorted_returns = sorted(returns)
        index = int(len(sorted_returns) * 0.05)
        return sorted_returns[index] if index < len(sorted_returns) else 0.0

    def _cvar_95(self, returns: List[float]) -> float:
        var = self._var_95(returns)
        tail_returns = [r for r in returns if r <= var]
        return sum(tail_returns) / len(tail_returns) if tail_returns else 0.0

    def _max_consecutive_losses(self, trades: List) -> int:
        max_streak = 0
        current_streak = 0
        for t in trades:
            if hasattr(t, 'pnl') and t.pnl < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    def _trade_to_dict(self, trade) -> Dict[str, Any]:
        return {
            "timestamp": trade.timestamp.isoformat(),
            "market_id": trade.market_id,
            "side": trade.side.value,
            "price": trade.price,
            "size": trade.size,
            "fee": trade.fee
        }
