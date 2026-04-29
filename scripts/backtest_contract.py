#!/usr/bin/env python3
"""合约策略回测验证"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pandas as pd
from datetime import datetime, timedelta
from libs.backtest import BacktestEngine, BacktestConfig, PerformanceMetrics

def fetch_binance_klines(symbol: str, interval: str, days: int = 90):
    """获取币安历史K线数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time,
        "limit": 1500
    }

    r = httpx.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)

    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

def dual_ma_strategy(df: pd.DataFrame, fast: int = 10, slow: int = 30):
    """双均线策略"""
    df['ma_fast'] = df['close'].rolling(fast).mean()
    df['ma_slow'] = df['close'].rolling(slow).mean()
    df['signal'] = 0
    df.loc[df['ma_fast'] > df['ma_slow'], 'signal'] = 1
    df.loc[df['ma_fast'] < df['ma_slow'], 'signal'] = -1
    return df

def run_backtest():
    """执行回测"""
    print("=== BTC合约双均线策略回测 ===\n")

    # 1. 获取历史数据
    print("获取BTC历史数据（最近3个月）...")
    df = fetch_binance_klines("BTCUSDT", "1h", days=90)
    print(f"数据量: {len(df)} 条\n")

    # 2. 应用策略
    df = dual_ma_strategy(df)
    df = df.dropna()

    # 3. 回测
    config = BacktestConfig(initial_capital=10000, fee_rate=0.0004)
    engine = BacktestEngine(config)

    position = 0
    for idx, row in df.iterrows():
        signal = row['signal']
        price = row['close']

        if signal == 1 and position == 0:
            size = engine.capital / price * 0.95
            from libs.schemas import Side
            engine.execute_signal(row['timestamp'], "BTCUSDT", Side.BUY_YES, price, size)
            position = 1
        elif signal == -1 and position == 1:
            size = engine.positions.get("BTCUSDT", 0)
            if size > 0:
                from libs.schemas import Side
                engine.execute_signal(row['timestamp'], "BTCUSDT", Side.SELL_YES, price, size)
                position = 0

        engine.update_equity(row['timestamp'], {"BTCUSDT": price})

    # 4. 计算指标
    results = engine.get_results()
    returns = PerformanceMetrics.calculate_returns(engine.equity_curve)
    sharpe = PerformanceMetrics.sharpe_ratio(returns)

    # 计算胜率和盈亏比
    trades_pnl = []
    for i in range(0, len(engine.trades) - 1, 2):
        if i + 1 < len(engine.trades):
            buy_trade = engine.trades[i]
            sell_trade = engine.trades[i + 1]
            pnl = (sell_trade.price - buy_trade.price) * buy_trade.size - buy_trade.fee - sell_trade.fee
            trades_pnl.append(pnl)

    win_rate = sum(1 for p in trades_pnl if p > 0) / len(trades_pnl) if trades_pnl else 0
    gross_profit = sum(p for p in trades_pnl if p > 0)
    gross_loss = abs(sum(p for p in trades_pnl if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    # 5. 输出报告
    print("=== 回测结果 ===")
    print(f"初始资金: ${results['initial_capital']:.2f}")
    print(f"最终权益: ${results['final_equity']:.2f}")
    print(f"总收益率: {results['total_return_pct']:.2f}%")
    print(f"最大回撤: {results['max_drawdown_pct']:.2f}%")
    print(f"夏普比率: {sharpe:.2f}")
    print(f"交易次数: {results['num_trades']}")
    print(f"胜率: {win_rate*100:.2f}%")
    print(f"盈亏比: {profit_factor:.2f}")
    print(f"总手续费: ${results['total_fees']:.2f}")

if __name__ == "__main__":
    run_backtest()
