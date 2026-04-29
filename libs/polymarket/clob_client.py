"""Polymarket CLOB API客户端"""
import httpx
from typing import Optional, Dict

class PolymarketClient:
    def __init__(self):
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"

    def get_markets(self, limit=20):
        """获取市场列表"""
        url = f"{self.gamma_url}/markets"
        params = {"limit": limit, "closed": False, "active": True}
        r = httpx.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_orderbook(self, token_id: str):
        """获取订单簿"""
        url = f"{self.base_url}/book"
        params = {"token_id": token_id}
        r = httpx.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_best_prices(self, token_id: str) -> Optional[Dict]:
        """获取最优价格"""
        try:
            book = self.get_orderbook(token_id)
            if book.get("bids") and book.get("asks"):
                return {
                    "bid": float(book["bids"][0]["price"]),
                    "ask": float(book["asks"][0]["price"])
                }
        except:
            pass
        return None
