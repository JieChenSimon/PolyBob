#!/usr/bin/env python3
"""增强策略回测 - 使用真实币安数据"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime, timedelta

def get_real_btc_data(days=90):
    """获取真实BTC历史数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"

    # 1小时K线，最近90天
    params = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": 1000
    }

    all_data = []
    for i in range(3):  # 获取3000根K线
        r = httpx.get(url, params=params, timeout=15)
        data = r.json()
        all_data.extend(data)

        if len(data) < 1000:
            break
        params['endTime'] = int(data[0][0]) - 1

    return all_data

def calculate_indicators(prices):
    """计算技术指标"""
    # 双均线
    ma10 = np.mean(prices[-10:])
    ma30 = np.mean(prices[-30:])

    # RSI
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rsi = 100 - (100 / (1 + np.mean(gains[-14:]) / np.mean(losses[-14:])))

    # MACD
    ema12 = prices[-1]
    ema26 = prices[-1]
    for i in range(min(26, len(prices))):
        ema12 = prices[-(i+1)] * (2/13) + ema12 * (11/13)
        ema26 = prices[-(i+1)] * (2/27) + ema26 * (25/27)
    macd = ema12 - ema26

    return {
        'ma10': ma10,
        'ma30': ma30,
        'rsi': rsi,
        'macd': macd
    }

def generate_signal(indicators):
    """生成交易信号"""
    score = 0

    # 趋势
    if indicators['ma10'] > indicators['ma30']:
        score += 1
    else:
        score -= 1

    # RSI
    if indicators['rsi'] < 30:
        score += 1
    elif indicators['rsi'] > 70:
        score -= 1

    # MACD
    if indicators['macd'] > 0:
        score += 1
    else:
        score -= 1

    if score >= 2:
        return 'long'
    elif score <= -2:
        return 'short'
    return 'neutral'

def run_backtest():
    """运行回测"""
    print("=" * 60)
    print("增强策略回测 - 真实币安数据")
    print("=" * 60)

    print("\n[1/3] 获取真实数据...")
    data = get_real_btc_data()
    prices = np.array([float(k[4]) for k in data])
    print(f"✓ 获取 {len(prices)} 根K线")

    print("\n[2/3] 运行回测...")
    capital = 10000
    position = 0
    trades = []

    for i in range(50, len(prices)):
        indicators = calculate_indicators(prices[:i+1])
        signal = generate_signal(indicators)

        if position == 0 and signal == 'long':
            position = capital / prices[i]
            capital = 0
            trades.append({'type': 'buy', 'price': prices[i], 'i': i})
        elif position > 0 and signal != 'long':
            capital = position * prices[i]
            position = 0
            trades.append({'type': 'sell', 'price': prices[i], 'i': i})

    if position > 0:
        capital = position * prices[-1]

    print(f"✓ 交易次数: {len(trades)}")

    print("\n[3/3] 计算指标...")
    total_return = (capital - 10000) / 10000
    print(f"\n初始资金: $10,000")
    print(f"最终资金: ${capital:,.2f}")
    print(f"总收益: {total_return*100:.2f}%")

if __name__ == "__main__":
    run_backtest()
