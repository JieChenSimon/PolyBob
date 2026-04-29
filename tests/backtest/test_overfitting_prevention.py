"""
过拟合防止测试
验证训练集与测试集性能一致性
"""
import pytest
import numpy as np
from typing import Dict


class OverfittingDetector:
    """过拟合检测器"""

    @staticmethod
    def check_performance_degradation(train_metrics: Dict, test_metrics: Dict) -> Dict:
        """检查样本外性能衰退"""
        train_sharpe = train_metrics['sharpe_ratio']
        test_sharpe = test_metrics['sharpe_ratio']

        degradation = (train_sharpe - test_sharpe) / train_sharpe if train_sharpe > 0 else 1.0

        return {
            'train_sharpe': train_sharpe,
            'test_sharpe': test_sharpe,
            'degradation_pct': degradation,
            'is_overfitted': degradation > 0.3,  # 衰退>30%视为过拟合
        }

    @staticmethod
    def check_drawdown_consistency(train_dd: float, test_dd: float) -> bool:
        """检查回撤一致性"""
        # 测试集回撤不应超过训练集1.5倍
        return test_dd <= train_dd * 1.5

    @staticmethod
    def check_trade_frequency(daily_trades: float) -> bool:
        """检查交易频率合理性"""
        # 避免过度交易
        return daily_trades < 10


@pytest.mark.backtest
def test_no_overfitting_detection():
    """测试正常策略(无过拟合)"""
    detector = OverfittingDetector()

    train_metrics = {'sharpe_ratio': 2.0, 'max_drawdown': 0.12}
    test_metrics = {'sharpe_ratio': 1.8, 'max_drawdown': 0.15}

    result = detector.check_performance_degradation(train_metrics, test_metrics)

    assert result['is_overfitted'] is False
    assert result['degradation_pct'] < 0.3


@pytest.mark.backtest
def test_overfitting_detection():
    """测试过拟合策略检测"""
    detector = OverfittingDetector()

    train_metrics = {'sharpe_ratio': 3.5, 'max_drawdown': 0.08}
    test_metrics = {'sharpe_ratio': 1.0, 'max_drawdown': 0.25}

    result = detector.check_performance_degradation(train_metrics, test_metrics)

    assert result['is_overfitted'] is True
    assert result['degradation_pct'] > 0.3


@pytest.mark.backtest
def test_drawdown_consistency():
    """测试回撤一致性"""
    detector = OverfittingDetector()

    # 正常情况
    assert detector.check_drawdown_consistency(0.10, 0.12) is True
    assert detector.check_drawdown_consistency(0.10, 0.15) is True

    # 异常情况: 测试集回撤过大
    assert detector.check_drawdown_consistency(0.10, 0.20) is False


@pytest.mark.backtest
def test_trade_frequency_check():
    """测试交易频率检查"""
    detector = OverfittingDetector()

    assert detector.check_trade_frequency(5.0) is True
    assert detector.check_trade_frequency(9.9) is True
    assert detector.check_trade_frequency(15.0) is False  # 过度交易
