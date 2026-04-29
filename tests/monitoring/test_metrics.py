"""
监控指标测试
"""
import pytest
from datetime import datetime
from tests.monitoring.metrics import StrategyHealthMetrics, PerformanceMonitor


def test_healthy_strategy_metrics():
    """测试健康策略指标"""
    metrics = StrategyHealthMetrics(
        sharpe_ratio_30d=2.0,
        max_drawdown_30d=0.10,
        win_rate=0.60,
        profit_factor=2.0,
        daily_trades=10.0,
        avg_holding_hours=24.0,
        timestamp=datetime.utcnow()
    )

    health = metrics.is_healthy()
    assert all(health.values())
    assert len(metrics.get_alerts()) == 0


def test_unhealthy_strategy_detection():
    """测试不健康策略检测"""
    metrics = StrategyHealthMetrics(
        sharpe_ratio_30d=0.8,  # 低于1.5
        max_drawdown_30d=0.20,  # 超过15%
        win_rate=0.45,  # 低于55%
        profit_factor=1.2,
        daily_trades=30.0,  # 过度交易
        avg_holding_hours=1.0,
        timestamp=datetime.utcnow()
    )

    health = metrics.is_healthy()
    assert not health['sharpe_ok']
    assert not health['drawdown_ok']
    assert not health['win_rate_ok']

    alerts = metrics.get_alerts()
    assert len(alerts) > 0


def test_performance_monitor():
    """测试性能监控"""
    monitor = PerformanceMonitor()

    # 记录正常延迟
    for _ in range(100):
        monitor.record_latency(50.0)

    assert not monitor.check_latency_alert()

    # 记录高延迟
    for _ in range(20):
        monitor.record_latency(200.0)

    assert monitor.check_latency_alert()
