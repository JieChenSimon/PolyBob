#!/usr/bin/env python3
"""实时BTC交易决策系统"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime

def get_btc_klines(limit=100):
    """获取BTC K线数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "limit": limit
    }
    r = httpx.get(url, params=params, timeout=10)
    data = r.json()

    closes = [float(k[4]) for k in data]
    volumes = [float(k[5]) for k in data]
    return np.array(closes), np.array(volumes)

def calculate_indicators(prices):
    """计算技术指标"""
    # 移动平均
    sma5 = np.mean(prices[-5:])
    sma20 = np.mean(prices[-20:])

    # RSI
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-14:])
    avg_loss = np.mean(losses[-14:])
    rs = avg_gain / avg_loss if avg_loss > 0 else 0
    rsi = 100 - (100 / (1 + rs))

    # 波动率
    returns = np.diff(prices) / prices[:-1]
    volatility = np.std(returns[-20:])

    return {
        'sma5': sma5,
        'sma20': sma20,
        'rsi': rsi,
        'volatility': volatility,
        'current_price': prices[-1]
    }

def make_decision(indicators):
    """做出交易决策"""
    signals = []
    reasons = []

    # 趋势信号
    if indicators['sma5'] > indicators['sma20']:
        signals.append(1)
        reasons.append("短期均线上穿长期均线（看涨）")
    else:
        signals.append(-1)
        reasons.append("短期均线下穿长期均线（看跌）")

    # RSI信号
    if indicators['rsi'] < 30:
        signals.append(1)
        reasons.append(f"RSI超卖({indicators['rsi']:.1f})")
    elif indicators['rsi'] > 70:
        signals.append(-1)
        reasons.append(f"RSI超买({indicators['rsi']:.1f})")

    # 波动率
    if indicators['volatility'] > 0.01:
        reasons.append(f"高波动率({indicators['volatility']*100:.2f}%)")

    # 综合决策
    total = sum(signals)
    if total >= 1:
        decision = "做多"
        confidence = min(0.9, 0.5 + len([s for s in signals if s > 0]) * 0.2)
    elif total <= -1:
        decision = "做空"
        confidence = min(0.9, 0.5 + len([s for s in signals if s < 0]) * 0.2)
    else:
        decision = "观望"
        confidence = 0.3

    return decision, confidence, reasons

def main():
    print("=" * 60)
    print("BTC实时交易决策系统")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 获取数据
    print("\n[1/3] 获取BTC数据...")
    prices, volumes = get_btc_klines(100)
    print(f"✓ 获取 {len(prices)} 根K线")

    # 计算指标
    print("\n[2/3] 计算技术指标...")
    indicators = calculate_indicators(prices)
    print(f"  当前价格: ${indicators['current_price']:,.2f}")
    print(f"  SMA5: ${indicators['sma5']:,.2f}")
    print(f"  SMA20: ${indicators['sma20']:,.2f}")
    print(f"  RSI: {indicators['rsi']:.1f}")
    print(f"  波动率: {indicators['volatility']*100:.2f}%")

    # 做出决策
    print("\n[3/3] 生成交易决策...")
    decision, confidence, reasons = make_decision(indicators)

    print("\n" + "=" * 60)
    print("交易决策")
    print("=" * 60)
    print(f"\n🎯 建议: {decision}")
    print(f"📊 置信度: {confidence*100:.0f}%")
    print(f"\n理由:")
    for i, reason in enumerate(reasons, 1):
        print(f"  {i}. {reason}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
