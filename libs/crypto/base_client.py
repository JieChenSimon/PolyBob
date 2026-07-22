"""加密货币交易所客户端基类"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Optional

import httpx

# 模块级共享 AsyncClient（懒创建，按事件循环缓存，避免每次请求新建连接池）。
_shared_async_client: httpx.AsyncClient | None = None
_shared_async_client_loop: asyncio.AbstractEventLoop | None = None


def get_shared_async_http_client() -> httpx.AsyncClient:
    """获取共享的 httpx.AsyncClient（懒创建；事件循环变化时重建）。

    必须在运行中的事件循环内调用。测试常用 asyncio.run() 反复创建新循环，
    因此按当前循环缓存，循环失效时重建客户端。
    """
    global _shared_async_client, _shared_async_client_loop
    loop = asyncio.get_running_loop()
    if (
        _shared_async_client is None
        or _shared_async_client.is_closed
        or _shared_async_client_loop is not loop
    ):
        _shared_async_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        _shared_async_client_loop = loop
    return _shared_async_client


async def close_shared_async_http_client() -> None:
    """关闭共享 AsyncClient（优雅停机用）。"""
    global _shared_async_client, _shared_async_client_loop
    client, _shared_async_client, _shared_async_client_loop = _shared_async_client, None, None
    if client is not None and not client.is_closed:
        await client.aclose()

class CryptoExchangeClient(ABC):
    """交易所客户端抽象基类"""

    @abstractmethod
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取行情"""
        pass

    @abstractmethod
    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "LIMIT",
    ) -> str:
        """下单"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        pass

    @abstractmethod
    def get_order(self, order_id: str, symbol: str | None = None) -> Optional[Dict]:
        """查询订单"""
        pass
