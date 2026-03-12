"""
Polymarket WebSocket 客户端
"""
import asyncio
import json
import websockets
import structlog
from datetime import datetime
from typing import Callable, Set

logger = structlog.get_logger()


class PolymarketWebSocket:
    """Polymarket WebSocket 客户端"""

    def __init__(
        self,
        url: str,
        reconnect_interval: int = 5,
        max_reconnect_attempts: int | None = None,
    ):
        self.url = url
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.ws = None
        self.subscriptions: Set[str] = set()
        self.last_message_time: datetime | None = None
        self.message_handler: Callable | None = None
        self._running = False

    def set_message_handler(self, handler: Callable):
        """设置消息处理器"""
        self.message_handler = handler

    async def connect(self):
        """连接并自动重连"""
        self._running = True
        attempt = 0

        while self._running:
            try:
                self.ws = await websockets.connect(self.url)
                logger.info("websocket_connected", url=self.url)

                # 重新订阅
                await self._resubscribe()

                # 开始接收消息
                await self._receive_loop()

            except Exception as e:
                attempt += 1
                logger.error(
                    "websocket_error",
                    url=self.url,
                    attempt=attempt,
                    error=str(e),
                )

                if self.max_reconnect_attempts and attempt >= self.max_reconnect_attempts:
                    logger.error("max_reconnect_attempts_reached")
                    raise

                await asyncio.sleep(self.reconnect_interval)

    async def subscribe(self, market_id: str):
        """订阅市场"""
        self.subscriptions.add(market_id)

        if self.ws:
            await self._send_subscribe(market_id)

    async def unsubscribe(self, market_id: str):
        """取消订阅市场"""
        self.subscriptions.discard(market_id)

        if self.ws:
            await self._send_unsubscribe(market_id)

    async def _resubscribe(self):
        """重新订阅所有市场"""
        for market_id in self.subscriptions:
            await self._send_subscribe(market_id)

    async def _send_subscribe(self, market_id: str):
        """发送订阅消息"""
        message = {
            "type": "subscribe",
            "market_id": market_id,
        }
        await self.ws.send(json.dumps(message))
        logger.info("subscribed_to_market", market_id=market_id)

    async def _send_unsubscribe(self, market_id: str):
        """发送取消订阅消息"""
        message = {
            "type": "unsubscribe",
            "market_id": market_id,
        }
        await self.ws.send(json.dumps(message))
        logger.info("unsubscribed_from_market", market_id=market_id)

    async def _receive_loop(self):
        """接收消息循环"""
        async for message in self.ws:
            self.last_message_time = datetime.utcnow()

            try:
                data = json.loads(message)
                await self._handle_message(data)
            except Exception as e:
                logger.error("failed_to_handle_message", error=str(e), exc_info=True)

    async def _handle_message(self, data: dict):
        """处理消息"""
        if self.message_handler:
            try:
                if asyncio.iscoroutinefunction(self.message_handler):
                    await self.message_handler(data)
                else:
                    self.message_handler(data)
            except Exception as e:
                logger.error("message_handler_error", error=str(e), exc_info=True)

    async def close(self):
        """关闭连接"""
        self._running = False
        if self.ws:
            await self.ws.close()
            logger.info("websocket_closed")
