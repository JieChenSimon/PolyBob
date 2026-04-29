"""
Backtest - 策略回测框架
"""
from .engine import BacktestEngine, BacktestConfig
from .metrics import PerformanceMetrics
from .report import generate_html_report, generate_markdown_report

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "PerformanceMetrics",
    "generate_html_report",
    "generate_markdown_report",
]
