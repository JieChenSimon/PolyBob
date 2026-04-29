#!/usr/bin/env python3
"""策略回测验证 - 运行前验证"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx

def get_historical_data():
    """获取历史数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 1000}
    r = httpx.get(url, params=params, timeout=15)
    return np.array([float(k[4]) for k in r.json()])

def calculate_indicators(prices):
    sma5 = np.mean(prices[-5:])
    sma20 = np.mean(prices[-20:])
    deltas = np.diff(prices[-15:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)
    rsi = 100 - (100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10)))
    macd = prices[-12:].mean() - prices[-26:].mean()
    return {'sma5': sma5, 'sma20': sma20, 'rsi': rsi, 'macd': macd}

def generate_signal(indicators):
    score = 0
    if indicators['sma5'] > indicators['sma20']: score += 1
    else: score -= 1
    if indicators['rsi'] < 30: score += 1
    elif indicators['rsi'] > 70: score -= 1
    if indicators['macd'] > 0: score += 1
    else: score -= 1
    return "long" if score > 0 else "short", min(abs(score) / 3.0, 1.0)

def run_backtest():
    print("=" * 60)
    print("策略回测验证")
    print("=" * 60)

    prices = get_historical_data()
    print(f"\n获取 {len(prices)} 根K线")

    capital = 10000
    position = 0
    trades = []

    for i in range(50, len(prices)):
        indicators = calculate_indicators(prices[:i+1])
        direction, confidence = generate_signal(indicators)

        if confidence < 0.5:
            direction = "neutral"

        if position == 0 and direction == "long":
            kelly = min(confidence * 0.5, 0.5)
            size = (capital * kelly) / prices[i]
            position = size
            entry_price = prices[i]
            capital *= (1 - kelly)
            trades.append({'type': 'open', 'price': prices[i]})
        elif position > 0 and direction != "long":
            pnl = (prices[i] - entry_price) * position
            capital += prices[i] * position
            trades.append({'type': 'close', 'pnl': pnl})
            position = 0

    if position > 0:
        pnl = (prices[-1] - entry_price) * position
        capital += prices[-1] * position
        trades.append({'type': 'close', 'pnl': pnl})

    total_return = (capital - 10000) / 10000
    wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
    win_rate = wins / len([t for t in trades if 'pnl' in t]) if trades else 0

    print(f"\n初始资金: $10,000")
    print(f"最终资金: ${capital:,.2f}")
    print(f"总收益: {total_return*100:.2f}%")
    print(f"交易次数: {len(trades)}")
    print(f"胜率: {win_rate*100:.1f}%")
    print("\n" + "=" * 60)

    if total_return > 0 and win_rate > 0.4:
        print("✅ 策略验证通过，可以启动")
    else:
        print("⚠️  策略表现不佳，建议优化")

if __name__ == "__main__":
    run_backtest()
