#!/usr/bin/env python3
import httpx
import json
from datetime import datetime

url = "https://gamma-api.polymarket.com/markets"
r = httpx.get(url, params={'limit': 5, 'active': True}, timeout=10)
markets = r.json()

data = []
for m in markets[:3]:
    try:
        data.append({
            'timestamp': datetime.now().isoformat(),
            'market_id': m['conditionId'],
            'question': m['question'][:50],
            'bid_price': float(m.get('bestBid', 0)),
            'ask_price': float(m.get('bestAsk', 0)),
            'mid_price': (float(m.get('bestBid', 0)) + float(m.get('bestAsk', 0))) / 2,
            'spread_bps': (float(m.get('bestAsk', 0)) - float(m.get('bestBid', 0))) / ((float(m.get('bestBid', 0)) + float(m.get('bestAsk', 0))) / 2) * 10000 if m.get('bestBid') and m.get('bestAsk') else 0
        })
        print(f"{m['question'][:40]}... bid={m.get('bestBid')}, ask={m.get('bestAsk')}")
    except:
        pass

with open('data/polymarket_snapshot.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"\n采集 {len(data)} 个市场快照")
