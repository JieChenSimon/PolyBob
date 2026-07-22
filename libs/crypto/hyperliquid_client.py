"""Hyperliquid交易所客户端

Market-data reads (`get_ticker`, `get_orderbook`) are real HTTP calls. The
order-management methods (`place_order`, `cancel_order`, `get_position`) are
**unsigned stubs**: Hyperliquid requires EIP-712 signed actions with real
keys/infra, which is not wired here. They exist only so the paper-trading
path has a callable surface. They must never be treated as live executions —
the live venue is registered as unavailable in ``apps/api/main.py`` so a
no-op is never reported as a fill (see ``ContractExecutor(available=...)`` and
``BasketExecutor``).
"""
import httpx
from typing import Dict, Optional

import structlog

from .base_client import CryptoExchangeClient, get_shared_async_http_client

logger = structlog.get_logger()

# Exceptions that mean "upstream/parse failed"; we degrade to None rather than
# swallowing everything (a bare ``except`` would also hide bugs like NameError).
_MARKET_DATA_ERRORS = (httpx.HTTPError, ValueError, KeyError)


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
        except _MARKET_DATA_ERRORS as exc:
            logger.warning(
                "hyperliquid_ticker_unavailable",
                symbol=symbol,
                error=str(exc) or exc.__class__.__name__,
            )
            return None

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        try:
            url = f"{self.base_url}/info"
            data = {"type": "l2Book", "coin": symbol}
            r = httpx.post(url, json=data, timeout=10)
            r.raise_for_status()
            return r.json()
        except _MARKET_DATA_ERRORS as exc:
            logger.warning(
                "hyperliquid_orderbook_unavailable",
                symbol=symbol,
                error=str(exc) or exc.__class__.__name__,
            )
            return None

    async def get_orderbook_async(self, symbol: str) -> Optional[Dict]:
        """获取订单簿（异步版；共享连接池，不阻塞事件循环）"""
        try:
            client = get_shared_async_http_client()
            url = f"{self.base_url}/info"
            data = {"type": "l2Book", "coin": symbol}
            r = await client.post(url, json=data, timeout=10)
            r.raise_for_status()
            return r.json()
        except _MARKET_DATA_ERRORS as exc:
            logger.warning(
                "hyperliquid_orderbook_async_unavailable",
                symbol=symbol,
                error=str(exc) or exc.__class__.__name__,
            )
            return None

    def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "LIMIT",
    ) -> str:
        """下单（未实现：需要 EIP-712 签名与真实密钥）。

        STUB: no signed order is sent. This returns a synthetic id only for the
        paper-trading surface. The live venue is registered unavailable so this
        is never invoked on the real execution path. Do NOT wire this into a
        live account without implementing signed actions.
        """
        return f"hl_stub_{symbol}_{side}"

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """撤单（未实现 STUB：无签名请求发送）。"""
        return True

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓（未实现 STUB：始终返回空持仓）。"""
        return {"symbol": symbol, "size": 0, "entry_price": 0}

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Dict]:
        """查询订单（未实现 STUB）。"""
        return {"order_id": order_id, "symbol": symbol, "status": "NEW"}
