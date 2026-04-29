"""
Backtest CLI - 回测命令行工具
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List
import structlog

from libs.backtest import BacktestEngine
from libs.backtest.engine import BacktestConfig
from libs.backtest.metrics import PerformanceMetrics
from libs.schemas import OrderbookTick, Side

logger = structlog.get_logger()


def load_historical_data(data_path: str) -> List[OrderbookTick]:
    """加载历史数据"""
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    with open(path) as f:
        data = json.load(f)

    ticks = []
    for item in data:
        tick = OrderbookTick(
            market_id=item["market_id"],
            timestamp=datetime.fromisoformat(item["timestamp"]),
            bid_price=item["bid_price"],
            ask_price=item["ask_price"],
            bid_size=item["bid_size"],
            ask_size=item["ask_size"],
        )
        ticks.append(tick)

    return ticks


def run_backtest(data_path: str, strategy_func, config: BacktestConfig = None):
    """运行回测"""
    logger.info("loading_data", path=data_path)
    ticks = load_historical_data(data_path)

    logger.info("starting_backtest", num_ticks=len(ticks))
    engine = BacktestEngine(config)

    for tick in ticks:
        # 策略生成信号
        signal = strategy_func(tick)

        if signal:
            engine.execute_signal(
                timestamp=tick.timestamp,
                market_id=tick.market_id,
                side=signal["side"],
                price=signal["price"],
                size=signal["size"]
            )

        # 更新权益
        mid_price = (tick.bid_price + tick.ask_price) / 2
        engine.update_equity(tick.timestamp, {tick.market_id: mid_price})

    # 计算结果
    results = engine.get_results()

    # 计算额外指标
    returns = PerformanceMetrics.calculate_returns(engine.equity_curve)
    results["sharpe_ratio"] = PerformanceMetrics.sharpe_ratio(returns)

    logger.info("backtest_complete", **results)
    return results


def print_results(results: dict):
    """打印回测结果"""
    print("\n" + "="*50)
    print("Backtest Results")
    print("="*50)
    print(f"Initial Capital:    ${results['initial_capital']:,.2f}")
    print(f"Final Equity:       ${results['final_equity']:,.2f}")
    print(f"Total Return:       {results['total_return_pct']:.2f}%")
    print(f"Max Drawdown:       {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:       {results.get('sharpe_ratio', 0):.2f}")
    print(f"Number of Trades:   {results['num_trades']}")
    print(f"Total Fees:         ${results['total_fees']:.2f}")
    print("="*50 + "\n")
