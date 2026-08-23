"""Polymarket CLOB API客户端"""
from typing import Optional, Dict

from libs.data.http_client import http_request_json

class PolymarketClient:
    def __init__(self):
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"

    def get_markets(self, limit=20):
        """获取市场列表"""
        url = f"{self.gamma_url}/markets"
        params = {"limit": limit, "closed": False, "active": True}
        return http_request_json("GET", url, params=params, timeout=10)

    def get_orderbook(self, token_id: str):
        """获取订单簿"""
        url = f"{self.base_url}/book"
        params = {"token_id": token_id}
        return http_request_json("GET", url, params=params, timeout=10)

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
