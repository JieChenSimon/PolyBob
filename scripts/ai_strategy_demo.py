#!/usr/bin/env python3
"""AI事件驱动策略 - 最小实现"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import json

def analyze_event_with_ai(question, description):
    """使用AI分析事件（模拟）"""
    # 简化版：基于关键词判断
    keywords_bullish = ['convicted', 'sentenced', 'guilty']
    keywords_bearish = ['acquitted', 'dismissed', 'dropped']

    text = (question + " " + description).lower()

    if any(k in text for k in keywords_bullish):
        return {'signal': 'buy', 'confidence': 0.6}
    elif any(k in text for k in keywords_bearish):
        return {'signal': 'sell', 'confidence': 0.6}

    return {'signal': 'neutral', 'confidence': 0.3}

def simple_market_making(bid, ask):
    """简单做市策略"""
    mid = (bid + ask) / 2
    spread = ask - bid

    # 在中间价挂单
    our_bid = mid - spread * 0.25
    our_ask = mid + spread * 0.25

    return {'bid': our_bid, 'ask': our_ask}

def main():
    print("AI事件驱动策略演示\n")

    # 获取市场
    r = httpx.get('https://gamma-api.polymarket.com/markets',
                  params={'limit': 5, 'closed': False}, timeout=10)
    markets = r.json()

    for m in markets[:3]:
        question = m['question']
        desc = m.get('description', '')[:200]
        bid = float(m.get('bestBid', 0))
        ask = float(m.get('bestAsk', 0))

        if bid == 0 or ask == 0:
            continue

        print(f"市场: {question[:50]}")
        print(f"  当前: bid={bid:.3f}, ask={ask:.3f}")

        # AI分析
        ai_signal = analyze_event_with_ai(question, desc)
        print(f"  AI信号: {ai_signal['signal']} (置信度={ai_signal['confidence']})")

        # 做市
        quotes = simple_market_making(bid, ask)
        print(f"  做市: bid={quotes['bid']:.3f}, ask={quotes['ask']:.3f}")
        print()

if __name__ == "__main__":
    main()
