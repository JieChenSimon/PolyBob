#!/usr/bin/env python3
"""Polymarket数据采集 - 使用CLOB API"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import json
import time
from datetime import datetime

def get_active_markets():
    """获取活跃市场"""
    url = "https://gamma-api.polymarket.com/markets"
    params = {"limit": 20, "active": True, "closed": False}

    response = httpx.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def get_market_orderbook(token_id):
    """获取订单簿快照"""
    url = f"https://clob.polymarket.com/book"
    params = {"token_id": token_id}

    response = httpx.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

def collect_data(duration_minutes=5):
    """收集实时数据"""
    print(f"开始收集数据，持续{duration_minutes}分钟...")

    markets = get_active_markets()
    print(f"找到 {len(markets)} 个市场")

    # 选择前5个市场
    selected = markets[:5]
    data_points = []

    start_time = time.time()
    iteration = 0

    while (time.time() - start_time) < duration_minutes * 60:
        iteration += 1
        print(f"\n[迭代 {iteration}]")

        for market in selected:
            try:
                # 获取token_id
                tokens = market.get("tokens", [])
                if not tokens:
                    continue

                token_id = tokens[0].get("token_id")
                if not token_id:
                    continue

                # 获取订单簿
                book = get_market_orderbook(token_id)

                if book.get("bids") and book.get("asks"):
                    best_bid = float(book["bids"][0]["price"])
                    best_ask = float(book["asks"][0]["price"])

                    data_points.append({
                        "timestamp": datetime.now().isoformat(),
                        "market_id": market.get("condition_id", "unknown"),
                        "question": market.get("question", "")[:50],
                        "bid_price": best_bid,
                        "ask_price": best_ask,
                        "mid_price": (best_bid + best_ask) / 2,
                        "spread_bps": (best_ask - best_bid) / ((best_bid + best_ask) / 2) * 10000
                    })

                    print(f"  {market.get('question', '')[:40]}... mid={data_points[-1]['mid_price']:.3f}")

            except Exception as e:
                print(f"  错误: {e}")
                continue

        time.sleep(10)  # 每10秒采集一次

    return data_points

def main():
    print("=" * 60)
    print("Polymarket实时数据采集")
    print("=" * 60)

    data = collect_data(duration_minutes=5)

    output_file = "data/polymarket_realtime.json"
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n✓ 采集完成")
    print(f"  数据点: {len(data)}")
    print(f"  保存至: {output_file}")

if __name__ == "__main__":
    main()
