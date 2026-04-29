#!/usr/bin/env python3
"""增强版BTC决策 - 数学模型 + AI分析"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime

def get_btc_data():
    """获取BTC数据和新闻"""
    # K线数据
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 100}
    r = httpx.get(url, params=params, timeout=10)
    data = r.json()
    prices = np.array([float(k[4]) for k in data])

    # 24h统计
    url2 = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r2 = httpx.get(url2, params={"symbol": "BTCUSDT"}, timeout=10)
    stats = r2.json()

    return prices, stats

def calculate_signals(prices, stats):
    """计算综合信号"""
    # 技术指标
    sma5 = np.mean(prices[-5:])
    sma20 = np.mean(prices[-20:])

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rsi = 100 - (100 / (1 + np.mean(gains[-14:]) / np.mean(losses[-14:])))

    # 24h数据
    price_change = float(stats['priceChangePercent'])
    volume_change = float(stats['volume']) / float(stats['quoteVolume'])

    return {
        'price': prices[-1],
        'sma5': sma5,
        'sma20': sma20,
        'rsi': rsi,
        'change_24h': price_change,
        'volume': volume_change
    }

def make_final_decision(signals):
    """综合决策"""
    score = 0
    reasons = []

    # 趋势
    if signals['sma5'] > signals['sma20']:
        score += 1
        reasons.append("✓ 上升趋势")
    else:
        score -= 1
        reasons.append("✗ 下降趋势")

    # RSI
    if signals['rsi'] < 35:
        score += 1
        reasons.append(f"✓ RSI超卖({signals['rsi']:.0f})")
    elif signals['rsi'] > 65:
        score -= 1
        reasons.append(f"✗ RSI超买({signals['rsi']:.0f})")

    # 24h变化
    if signals['change_24h'] > 2:
        score += 1
        reasons.append(f"✓ 24h涨幅{signals['change_24h']:.1f}%")
    elif signals['change_24h'] < -2:
        score -= 1
        reasons.append(f"✗ 24h跌幅{signals['change_24h']:.1f}%")

    if score >= 2:
        return "做多", 0.8, reasons
    elif score <= -2:
        return "做空", 0.8, reasons
    elif score == 1:
        return "做多", 0.6, reasons
    elif score == -1:
        return "做空", 0.6, reasons
    return "观望", 0.3, reasons

def main():
    print("=" * 60)
    print("🚀 BTC智能交易决策系统")
    print("=" * 60)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    prices, stats = get_btc_data()
    signals = calculate_signals(prices, stats)

    print(f"💰 当前价格: ${signals['price']:,.2f}")
    print(f"📈 24h涨跌: {signals['change_24h']:.2f}%")
    print(f"📊 RSI: {signals['rsi']:.0f}\n")

    decision, confidence, reasons = make_final_decision(signals)

    print("=" * 60)
    print(f"🎯 决策: {decision}")
    print(f"📊 置信度: {confidence*100:.0f}%")
    print("=" * 60)
    for r in reasons:
        print(f"  {r}")
    print()

if __name__ == "__main__":
    main()
