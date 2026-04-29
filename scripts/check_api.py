#!/usr/bin/env python3
"""检查Polymarket API响应结构"""
import httpx
import json

url = "https://gamma-api.polymarket.com/markets"
params = {"limit": 2, "active": True}

response = httpx.get(url, params=params, timeout=10)
data = response.json()

print("API响应结构:")
print(json.dumps(data[0] if data else {}, indent=2)[:500])
