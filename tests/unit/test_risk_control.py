"""
风控规则单元测试
"""
import pytest
from datetime import datetime


class MockRiskController:
    """Mock风控控制器用于测试"""

    def __init__(self, config: dict):
        self.max_position_size = config.get("max_position_size", 1000.0)
        self.max_daily_trades = config.get("max_daily_trades", 50)
        self.max_drawdown_pct = config.get("max_drawdown_pct", 0.15)
        self.min_capital = config.get("min_capital", 1000.0)

        self.daily_trades = 0
        self.peak_equity = 10000.0
        self.current_equity = 10000.0

    def check_position_limit(self, position_size: float) -> bool:
        """检查仓位限制"""
        return position_size <= self.max_position_size

    def check_capital_sufficient(self, required_capital: float, available_capital: float) -> bool:
        """检查资金充足性"""
        return available_capital >= required_capital and available_capital >= self.min_capital

    def check_daily_trade_limit(self) -> bool:
        """检查日内交易次数"""
        return self.daily_trades < self.max_daily_trades

    def check_drawdown(self) -> bool:
        """检查最大回撤"""
        drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
        return drawdown < self.max_drawdown_pct

    def record_trade(self):
        """记录交易"""
        self.daily_trades += 1

    def update_equity(self, equity: float):
        """更新权益"""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity


def test_position_limit_check():
    """测试仓位限制检查"""
    config = {"max_position_size": 1000.0}
    controller = MockRiskController(config)

    assert controller.check_position_limit(500.0) is True
    assert controller.check_position_limit(1000.0) is True
    assert controller.check_position_limit(1001.0) is False


def test_capital_sufficiency():
    """测试资金充足性验证"""
    config = {"min_capital": 1000.0}
    controller = MockRiskController(config)

    assert controller.check_capital_sufficient(500.0, 2000.0) is True
    assert controller.check_capital_sufficient(500.0, 800.0) is False
    assert controller.check_capital_sufficient(2000.0, 1500.0) is False


def test_daily_trade_limit():
    """测试日内交易次数限制"""
    config = {"max_daily_trades": 3}
    controller = MockRiskController(config)

    assert controller.check_daily_trade_limit() is True
    controller.record_trade()
    assert controller.check_daily_trade_limit() is True
    controller.record_trade()
    assert controller.check_daily_trade_limit() is True
    controller.record_trade()
    assert controller.check_daily_trade_limit() is False


def test_max_drawdown_protection():
    """测试最大回撤保护"""
    config = {"max_drawdown_pct": 0.15}
    controller = MockRiskController(config)

    # 初始状态
    assert controller.check_drawdown() is True

    # 小幅回撤
    controller.update_equity(9000.0)
    assert controller.check_drawdown() is True

    # 达到限制
    controller.update_equity(8500.0)
    assert controller.check_drawdown() is False

    # 恢复后更新peak
    controller.update_equity(11000.0)
    assert controller.check_drawdown() is True
    assert controller.peak_equity == 11000.0


def test_combined_risk_checks():
    """测试组合风控检查"""
    config = {
        "max_position_size": 1000.0,
        "max_daily_trades": 5,
        "max_drawdown_pct": 0.20,
        "min_capital": 1000.0,
    }
    controller = MockRiskController(config)

    # 所有检查通过
    assert controller.check_position_limit(800.0) is True
    assert controller.check_capital_sufficient(500.0, 5000.0) is True
    assert controller.check_daily_trade_limit() is True
    assert controller.check_drawdown() is True

    # 模拟多次交易
    for _ in range(5):
        controller.record_trade()
    assert controller.check_daily_trade_limit() is False

    # 模拟大幅回撤
    controller.update_equity(7500.0)
    assert controller.check_drawdown() is False
