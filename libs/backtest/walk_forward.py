"""
Walk-Forward Analysis Framework
滚动窗口分析框架,避免过拟合
"""
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class WalkForwardWindow:
    """Walk-Forward窗口"""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass
class WalkForwardResult:
    """Walk-Forward结果"""
    window: WalkForwardWindow
    train_metrics: Dict[str, float]
    test_metrics: Dict[str, float]
    is_stable: bool


class WalkForwardAnalyzer:
    """Walk-Forward分析器"""

    def __init__(
        self,
        train_months: int = 6,
        test_months: int = 1,
        step_months: int = 1
    ):
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months

    def generate_windows(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[WalkForwardWindow]:
        """生成滚动窗口"""
        windows = []
        current = start_date

        while True:
            train_start = current
            train_end = current + timedelta(days=30 * self.train_months)
            test_start = train_end
            test_end = test_start + timedelta(days=30 * self.test_months)

            if test_end > end_date:
                break

            windows.append(WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end
            ))

            current += timedelta(days=30 * self.step_months)

        return windows

    def analyze(
        self,
        backtest_func,
        windows: List[WalkForwardWindow],
        stability_threshold: float = 1.0
    ) -> List[WalkForwardResult]:
        """执行Walk-Forward分析"""
        results = []

        for window in windows:
            # 训练期回测
            train_metrics = backtest_func(
                window.train_start,
                window.train_end
            )

            # 测试期回测
            test_metrics = backtest_func(
                window.test_start,
                window.test_end
            )

            # 稳定性检查
            test_sharpe = test_metrics.get('sharpe_ratio', 0)
            is_stable = test_sharpe >= stability_threshold

            results.append(WalkForwardResult(
                window=window,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                is_stable=is_stable
            ))

            logger.info(
                "walk_forward_window",
                train_sharpe=train_metrics.get('sharpe_ratio'),
                test_sharpe=test_sharpe,
                stable=is_stable
            )

        return results

    def aggregate_results(
        self,
        results: List[WalkForwardResult]
    ) -> Dict[str, Any]:
        """聚合分析结果"""
        test_sharpes = [r.test_metrics.get('sharpe_ratio', 0) for r in results]
        test_returns = [r.test_metrics.get('total_return', 0) for r in results]
        stable_count = sum(1 for r in results if r.is_stable)

        return {
            'num_windows': len(results),
            'stable_windows': stable_count,
            'stability_rate': stable_count / len(results) if results else 0,
            'avg_test_sharpe': sum(test_sharpes) / len(test_sharpes) if test_sharpes else 0,
            'min_test_sharpe': min(test_sharpes) if test_sharpes else 0,
            'avg_test_return': sum(test_returns) / len(test_returns) if test_returns else 0,
        }
