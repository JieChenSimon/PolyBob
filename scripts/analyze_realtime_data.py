#!/usr/bin/env python3
"""真实数据回测"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import numpy as np
from datetime import datetime
from collections import defaultdict

def load_realtime_data(filepath):
    """加载实时数据"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data

def group_by_market(data):
    """按市场分组"""
    markets = defaultdict(list)
    for point in data:
        markets[point['market_id']].append(point)
    return markets

def calculate_returns(prices):
    """计算收益率"""
    if len(prices) < 2:
        return []
    returns = []
    for i in range(1, len(prices)):
        ret = (prices[i] - prices[i-1]) / prices[i-1]
        returns.append(ret)
    return returns

def analyze_market_data(data):
    """分析市场数据"""
    print("=" * 60)
    print("真实数据分析")
    print("=" * 60)

    markets = group_by_market(data)

    print(f"\n数据点总数: {len(data)}")
    print(f"市场数量: {len(markets)}")

    for market_id, points in markets.items():
        if len(points) < 5:
            continue

        prices = [p['mid_price'] for p in points]
        spreads = [p['spread_bps'] for p in points]

        returns = calculate_returns(prices)
        volatility = np.std(returns) if returns else 0

        print(f"\n市场: {points[0].get('question', 'Unknown')[:40]}")
        print(f"  数据点: {len(points)}")
        print(f"  价格范围: {min(prices):.3f} - {max(prices):.3f}")
        print(f"  平均价差: {np.mean(spreads):.1f} bps")
        print(f"  波动率: {volatility*100:.2f}%")

if __name__ == "__main__":
    filepath = "data/polymarket_realtime.json"

    try:
        data = load_realtime_data(filepath)
        analyze_market_data(data)
    except FileNotFoundError:
        print(f"数据文件不存在: {filepath}")
        print("请先运行 collect_realtime_data.py")
