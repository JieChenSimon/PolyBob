"""币安交易所客户端"""
import hashlib
import hmac
import time
import httpx
from typing import Dict, Optional
from .base_client import CryptoExchangeClient

class BinanceClient(CryptoExchangeClient):
    def __init__(self, api_key: str = None, api_secret: str = None, paper_trading: bool = True):
        self.base_url = "https://fapi.binance.com"
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.paper_orders = {}
        self.paper_positions = {}

    def _sign(self, params: Dict) -> str:
        """生成签名"""
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取行情"""
        try:
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            params = {"symbol": symbol}
            r = httpx.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            return None

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        try:
            url = f"{self.base_url}/fapi/v1/depth"
            params = {"symbol": symbol, "limit": 20}
            r = httpx.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            return None

    def place_order(self, symbol: str, side: str, price: float, size: float, order_type: str = "LIMIT") -> str:
        """下单"""
        if self.paper_trading:
            order_id = f"paper_{int(time.time()*1000)}"
            self.paper_orders[order_id] = {
                "symbol": symbol, "side": side, "price": price,
                "size": size, "status": "NEW", "type": order_type
            }
            return order_id

        params = {
            "symbol": symbol, "side": side.upper(), "type": order_type,
            "quantity": size, "timestamp": int(time.time() * 1000)
        }
        if order_type == "LIMIT":
            params["price"] = price
            params["timeInForce"] = "GTC"

        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            r = httpx.post(f"{self.base_url}/fapi/v1/order", params=params, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()["orderId"]
        except Exception as e:
            raise Exception(f"下单失败: {e}")

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """撤单"""
        if self.paper_trading:
            if order_id in self.paper_orders:
                self.paper_orders[order_id]["status"] = "CANCELED"
                return True
            return False

        params = {"orderId": order_id, "symbol": symbol, "timestamp": int(time.time() * 1000)}
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            r = httpx.delete(f"{self.base_url}/fapi/v1/order", params=params, headers=headers, timeout=10)
            r.raise_for_status()
            return True
        except:
            return False

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        if self.paper_trading:
            return self.paper_positions.get(symbol, {"symbol": symbol, "size": 0, "entry_price": 0})

        params = {"timestamp": int(time.time() * 1000)}
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            r = httpx.get(f"{self.base_url}/fapi/v2/positionRisk", params=params, headers=headers, timeout=10)
            r.raise_for_status()
            positions = [p for p in r.json() if p["symbol"] == symbol]
            if positions:
                p = positions[0]
                return {"symbol": symbol, "size": float(p["positionAmt"]), "entry_price": float(p["entryPrice"])}
            return {"symbol": symbol, "size": 0, "entry_price": 0}
        except:
            return None

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Dict]:
        """查询订单"""
        if self.paper_trading:
            return self.paper_orders.get(order_id)

        params = {"orderId": order_id, "symbol": symbol, "timestamp": int(time.time() * 1000)}
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            r = httpx.get(f"{self.base_url}/fapi/v1/order", params=params, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except:
            return None
