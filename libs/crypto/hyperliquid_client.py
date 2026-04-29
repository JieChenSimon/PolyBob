"""Hyperliquid交易所客户端"""
import httpx
from typing import Dict, Optional
from .base_client import CryptoExchangeClient

class HyperliquidClient(CryptoExchangeClient):
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.base_url = "https://api.hyperliquid.xyz"
        self.api_key = api_key
        self.api_secret = api_secret

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取行情"""
        try:
            url = f"{self.base_url}/info"
            data = {"type": "metaAndAssetCtxs"}
            r = httpx.post(url, json=data, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            return None

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        try:
            url = f"{self.base_url}/info"
            data = {"type": "l2Book", "coin": symbol}
            r = httpx.post(url, json=data, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            return None

    def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "LIMIT",
    ) -> str:
        """下单（需要签名）"""
        # 简化版：仅返回模拟订单ID
        return f"hl_order_{symbol}_{side}"

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """撤单"""
        return True

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        return {"symbol": symbol, "size": 0, "entry_price": 0}

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Dict]:
        """查询订单"""
        return {"order_id": order_id, "symbol": symbol, "status": "NEW"}
