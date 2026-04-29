#!/usr/bin/env python3
"""获取Polymarket历史数据用于回测"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import json
from datetime import datetime, timedelta

def fetch_polymarket_markets():
    """获取活跃市场列表"""
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "limit": 10,
        "active": True,
        "closed": False
    }

    try:
        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取市场列表失败: {e}")
        return []

def fetch_market_prices(condition_id, limit=500):
    """获取市场价格历史"""
    url = f"https://clob.polymarket.com/prices-history"
    params = {
        "market": condition_id,
        "interval": "1m",
        "fidelity": limit
    }

    try:
        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"获取价格历史失败: {e}")
        return []

def main():
    print("正在获取Polymarket数据...")

    # 获取市场列表
    markets = fetch_polymarket_markets()

    if not markets:
        print("未获取到市场数据，使用模拟数据")
        return

    print(f"找到 {len(markets)} 个活跃市场")

    # 获取前3个市场的历史数据
    all_data = []
    for i, market in enumerate(markets[:3]):
        # 尝试多个可能的ID字段
        market_id = market.get("condition_id") or market.get("id") or market.get("market_id")
        title = market.get("question", "Unknown")

        if not market_id:
            print(f"\n[{i+1}/3] {title[:50]}... (跳过: 无market_id)")
            continue

        print(f"\n[{i+1}/3] {title[:50]}...")
        print(f"  Market ID: {market_id}")

        prices = fetch_market_prices(market_id)

        if prices:
            print(f"  获取到 {len(prices)} 条价格记录")
            all_data.extend(prices)

    # 保存数据
    output_file = "data/polymarket_historical.json"
    with open(output_file, 'w') as f:
        json.dump(all_data, f, indent=2)

    print(f"\n✓ 数据已保存到 {output_file}")
    print(f"  总计: {len(all_data)} 条记录")

if __name__ == "__main__":
    main()
