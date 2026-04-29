#!/usr/bin/env python3
"""BTC决策 - 集成双均线策略"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime
from strategies.dual_ma_strategy import DualMAStrategy

def get_btc_prices():
    """获取BTC价格"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 100}
    r = httpx.get(url, params=params, timeout=10)
    data = r.json()
    return np.array([float(k[4]) for k in data])

def calculate_rsi(prices, period=14):
    """计算RSI"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    rs = avg_gain / avg_loss if avg_loss > 0 else 0
    return 100 - (100 / (1 + rs))

def make_decision(ma_signals, rsi, price):
    """综合决策"""
    score = 0
    reasons = []

    # 双均线信号
    if ma_signals['signal'] == 'golden_cross':
        score += 2
        reasons.append("🟢 金叉信号（强烈看涨）")
    elif ma_signals['signal'] == 'death_cross':
        score -= 2
        reasons.append("🔴 死叉信号（强烈看跌）")
    elif ma_signals['distance'] > 0.5:
        score += 1
        reasons.append(f"📈 快线高于慢线{ma_signals['distance']:.2f}%")
    elif ma_signals['distance'] < -0.5:
        score -= 1
        reasons.append(f"📉 快线低于慢线{abs(ma_signals['distance']):.2f}%")

    # RSI辅助
    if rsi < 30:
        score += 1
        reasons.append(f"✓ RSI超卖({rsi:.0f})")
    elif rsi > 70:
        score -= 1
        reasons.append(f"✗ RSI超买({rsi:.0f})")

    # 决策
    if score >= 2:
        return "做多", min(0.9, 0.6 + score * 0.1), reasons
    elif score <= -2:
        return "做空", min(0.9, 0.6 + abs(score) * 0.1), reasons
    return "观望", 0.4, reasons

def main():
    print("=" * 60)
    print("🚀 BTC双均线交易决策系统")
    print("=" * 60)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    prices = get_btc_prices()
    strategy = DualMAStrategy(fast_period=5, slow_period=20)
    ma_signals = strategy.calculate_signals(prices)
    rsi = calculate_rsi(prices)

    print(f"💰 当前价格: ${prices[-1]:,.2f}")
    print(f"📊 快线MA5: ${ma_signals['fast_ma']:,.2f}")
    print(f"📊 慢线MA20: ${ma_signals['slow_ma']:,.2f}")
    print(f"📈 RSI: {rsi:.0f}\n")

    decision, confidence, reasons = make_decision(ma_signals, rsi, prices[-1])

    print("=" * 60)
    print(f"🎯 决策: {decision}")
    print(f"📊 置信度: {confidence*100:.0f}%")
    print("=" * 60)
    for r in reasons:
        print(f"  {r}")
    print()

if __name__ == "__main__":
    main()
