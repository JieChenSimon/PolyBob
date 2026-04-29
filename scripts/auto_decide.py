#!/usr/bin/env python3
"""自动决策 - 根据数据分析结果决定下一步"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import numpy as np

def analyze_and_decide(data_file):
    """分析数据并给出决策"""
    with open(data_file, 'r') as f:
        data = json.load(f)

    if len(data) < 10:
        return "insufficient_data"

    # 计算市场特征
    spreads = [p['spread_bps'] for p in data]
    avg_spread = np.mean(spreads)

    prices = [p['mid_price'] for p in data]
    volatility = np.std(prices) / np.mean(prices) if prices else 0

    print(f"平均价差: {avg_spread:.1f} bps")
    print(f"波动率: {volatility*100:.2f}%")

    # 决策逻辑
    if avg_spread > 100:
        return "high_spread"  # 适合做市
    elif volatility > 0.05:
        return "high_volatility"  # 适合统计套利
    else:
        return "low_activity"  # 转向事件驱动

if __name__ == "__main__":
    result = analyze_and_decide("data/polymarket_realtime.json")
    print(f"\n决策: {result}")
