"""
持续监控指标定义
"""
from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class StrategyHealthMetrics:
    """策略健康度指标"""
    sharpe_ratio_30d: float
    max_drawdown_30d: float
    win_rate: float
    profit_factor: float
    daily_trades: float
    avg_holding_hours: float
    timestamp: datetime

    def is_healthy(self) -> Dict[str, bool]:
        """检查策略健康状态"""
        return {
            'sharpe_ok': self.sharpe_ratio_30d > 1.5,
            'drawdown_ok': self.max_drawdown_30d < 0.15,
            'win_rate_ok': self.win_rate > 0.55,
            'profit_factor_ok': self.profit_factor > 1.8,
            'trade_frequency_ok': 5 <= self.daily_trades <= 20,
            'holding_time_ok': 2 <= self.avg_holding_hours <= 48,
        }

    def get_alerts(self) -> List[str]:
        """获取预警信息"""
        alerts = []
        health = self.is_healthy()

        if not health['sharpe_ok']:
            alerts.append(f"Sharpe ratio低于目标: {self.sharpe_ratio_30d:.2f}")
        if not health['drawdown_ok']:
            alerts.append(f"回撤超标: {self.max_drawdown_30d:.1%}")
        if not health['win_rate_ok']:
            alerts.append(f"胜率偏低: {self.win_rate:.1%}")
        if not health['trade_frequency_ok']:
            alerts.append(f"交易频率异常: {self.daily_trades:.1f}笔/天")

        return alerts


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self.latency_history: List[float] = []
        self.alert_threshold_p95 = 150.0  # ms

    def record_latency(self, latency_ms: float):
        """记录延迟"""
        self.latency_history.append(latency_ms)
        if len(self.latency_history) > 10000:
            self.latency_history = self.latency_history[-10000:]

    def check_latency_alert(self) -> bool:
        """检查延迟预警"""
        if len(self.latency_history) < 100:
            return False

        recent = self.latency_history[-100:]
        p95 = sorted(recent)[int(len(recent) * 0.95)]

        return p95 > self.alert_threshold_p95
