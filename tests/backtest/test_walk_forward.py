"""
Walk-Forward分析测试
防止过拟合，验证策略稳定性
"""
import pytest
from datetime import datetime, timedelta
from typing import List, Dict
import numpy as np


class WalkForwardWindow:
    """Walk-forward窗口"""
    def __init__(self, train_start, train_end, test_start, test_end):
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end


class WalkForwardAnalyzer:
    """Walk-forward分析器"""

    def __init__(self, train_days=180, test_days=30, step_days=30):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days

    def generate_windows(self, start_date, end_date) -> List[WalkForwardWindow]:
        """生成滚动窗口"""
        windows = []
        current = start_date

        while current + timedelta(days=self.train_days + self.test_days) <= end_date:
            train_start = current
            train_end = current + timedelta(days=self.train_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_days)

            windows.append(WalkForwardWindow(train_start, train_end, test_start, test_end))
            current += timedelta(days=self.step_days)

        return windows

    def analyze_stability(self, results: List[Dict]) -> Dict:
        """分析策略稳定性"""
        sharpe_ratios = [r['sharpe_ratio'] for r in results]
        returns = [r['total_return'] for r in results]

        return {
            'avg_sharpe': np.mean(sharpe_ratios),
            'sharpe_std': np.std(sharpe_ratios),
            'sharpe_stability': bool(np.std(sharpe_ratios) < 0.5),  # 目标: std < 0.5
            'win_rate': sum(1 for r in returns if r > 0) / len(returns),
            'consistency': sum(1 for r in returns if r > 0) / len(returns) > 0.7,
        }


@pytest.mark.backtest
def test_walk_forward_window_generation():
    """测试窗口生成"""
    analyzer = WalkForwardAnalyzer(train_days=180, test_days=30, step_days=30)
    start = datetime(2023, 1, 1)
    end = datetime(2024, 1, 1)

    windows = analyzer.generate_windows(start, end)

    assert len(windows) > 0
    assert windows[0].train_start == start
    assert windows[0].test_end == windows[0].test_start + timedelta(days=30)


@pytest.mark.backtest
def test_stability_analysis():
    """测试稳定性分析"""
    analyzer = WalkForwardAnalyzer()

    # 模拟稳定策略结果
    stable_results = [
        {'sharpe_ratio': 1.8, 'total_return': 0.15},
        {'sharpe_ratio': 1.9, 'total_return': 0.18},
        {'sharpe_ratio': 1.7, 'total_return': 0.12},
        {'sharpe_ratio': 2.0, 'total_return': 0.20},
    ]

    metrics = analyzer.analyze_stability(stable_results)

    assert metrics['sharpe_stability'] is True
    assert metrics['consistency'] is True
    assert metrics['win_rate'] == 1.0


@pytest.mark.backtest
def test_unstable_strategy_detection():
    """测试不稳定策略检测"""
    analyzer = WalkForwardAnalyzer()

    # 模拟不稳定策略
    unstable_results = [
        {'sharpe_ratio': 3.0, 'total_return': 0.50},
        {'sharpe_ratio': 0.5, 'total_return': -0.10},
        {'sharpe_ratio': 2.5, 'total_return': 0.30},
        {'sharpe_ratio': -0.5, 'total_return': -0.20},
    ]

    metrics = analyzer.analyze_stability(unstable_results)

    assert metrics['sharpe_stability'] is False
    assert metrics['consistency'] is False


@pytest.mark.backtest
def test_parameter_sensitivity():
    """测试参数敏感性"""

    def mock_strategy_performance(param_value):
        """模拟策略在不同参数下的表现"""
        # 好策略: 参数变化时性能平稳
        base_sharpe = 1.8
        noise = (param_value - 1.0) * 0.3  # 参数偏离基准的影响
        return base_sharpe + noise

    base_param = 1.0
    base_sharpe = mock_strategy_performance(base_param)

    # 测试参数±20%变化
    sharpe_plus_20 = mock_strategy_performance(1.2)
    sharpe_minus_20 = mock_strategy_performance(0.8)

    # 性能下降应 <40%
    degradation_plus = abs(sharpe_plus_20 - base_sharpe) / base_sharpe
    degradation_minus = abs(sharpe_minus_20 - base_sharpe) / base_sharpe

    assert degradation_plus < 0.4
    assert degradation_minus < 0.4
