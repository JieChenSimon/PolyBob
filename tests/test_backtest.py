"""
Tests for backtest engine
"""
import pytest
from datetime import datetime, timedelta
from libs.backtest import BacktestEngine
from libs.backtest.engine import BacktestConfig
from libs.backtest.metrics import PerformanceMetrics
from libs.schemas import Side


def test_backtest_engine_initialization():
    """测试回测引擎初始化"""
    config = BacktestConfig(initial_capital=5000.0)
    engine = BacktestEngine(config)

    assert engine.capital == 5000.0
    assert len(engine.positions) == 0
    assert len(engine.trades) == 0


def test_execute_buy_signal():
    """测试买入信号执行"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    success = engine.execute_signal(
        timestamp=timestamp,
        market_id="market_1",
        side=Side.BUY_YES,
        price=0.5,
        size=100.0
    )

    assert success
    assert len(engine.trades) == 1
    assert engine.positions["market_1"] == 100.0
    assert engine.capital < 10000.0  # 扣除成本


def test_insufficient_capital():
    """测试资金不足"""
    config = BacktestConfig(initial_capital=100.0)
    engine = BacktestEngine(config)
    timestamp = datetime.utcnow()

    success = engine.execute_signal(
        timestamp=timestamp,
        market_id="market_1",
        side=Side.BUY_YES,
        price=0.5,
        size=1000.0  # 需要 500+ 资金
    )

    assert not success
    assert len(engine.trades) == 0


def test_equity_curve():
    """测试权益曲线"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    # 执行交易
    engine.execute_signal(timestamp, "market_1", Side.BUY_YES, 0.5, 100.0)

    # 更新权益
    engine.update_equity(timestamp, {"market_1": 0.6})

    assert len(engine.equity_curve) == 1
    assert engine.equity_curve[0][1] > 10000.0  # 盈利


def test_performance_metrics():
    """测试性能指标"""
    returns = [0.01, 0.02, -0.01, 0.03, -0.005]
    sharpe = PerformanceMetrics.sharpe_ratio(returns)

    assert sharpe > 0


def test_backtest_results():
    """测试回测结果"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    # 执行交易
    engine.execute_signal(timestamp, "market_1", Side.BUY_YES, 0.5, 100.0)
    engine.update_equity(timestamp, {"market_1": 0.6})

    results = engine.get_results()

    assert "total_return" in results
    assert "max_drawdown" in results
    assert results["num_trades"] == 1
