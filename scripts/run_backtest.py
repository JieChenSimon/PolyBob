#!/usr/bin/env python3
"""
Simple backtest runner
Usage: python scripts/run_backtest.py <data_file>
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.backtest.cli import run_backtest, print_results
from libs.backtest.engine import BacktestConfig
from libs.schemas import Side


def simple_strategy(tick):
    """简单的价差回归策略"""
    mid_price = (tick.bid_price + tick.ask_price) / 2
    spread_bps = (tick.ask_price - tick.bid_price) / mid_price * 10000

    # 价差过大时买入
    if spread_bps > 100:
        return {
            "side": Side.BUY_YES,
            "price": tick.ask_price,
            "size": 10.0
        }

    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_backtest.py <data_file>")
        sys.exit(1)

    data_path = sys.argv[1]

    config = BacktestConfig(
        initial_capital=10000.0,
        fee_rate=0.002,
        slippage_bps=10.0
    )

    results = run_backtest(data_path, simple_strategy, config)
    print_results(results)
