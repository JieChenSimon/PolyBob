"""
Polymarket WebSocket 客户端
"""
import asyncio
import json
import websockets
import structlog
from datetime import datetime
from typing import Callable, Iterable, Set

from libs.terminal_status import render_status

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

    async def subscribe(self, asset_ids: str | Iterable[str]):
        """订阅资产"""
        normalized = self._normalize_asset_ids(asset_ids)
        self.subscriptions.update(normalized)

        if self.ws and normalized:
            await self._send_subscription(normalized, operation="subscribe")

    async def unsubscribe(self, asset_ids: str | Iterable[str]):
        """取消订阅资产"""
        normalized = self._normalize_asset_ids(asset_ids)
        for asset_id in normalized:
            self.subscriptions.discard(asset_id)

        if self.ws and normalized:
            await self._send_subscription(normalized, operation="unsubscribe")

    async def _resubscribe(self):
        """重新订阅所有市场"""
        if self.subscriptions:
            await self._send_subscription(sorted(self.subscriptions))

    async def _send_subscription(
        self,
        asset_ids: list[str],
        operation: str | None = None,
    ):
        """发送订阅或取消订阅消息"""
        message = {
            "assets_ids": asset_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }
        if operation:
            message["operation"] = operation

        await self.ws.send(json.dumps(message))
        logger.debug(
            "market_subscription_updated",
            operation=operation or "subscribe",
            asset_count=len(asset_ids),
            asset_ids=asset_ids[:3],
        )
        render_status(
            f"subscriptions {operation or 'subscribe'}: {len(self.subscriptions)} assets"
        )

    async def _receive_loop(self):
        """接收消息循环"""
        async for message in self.ws:
            self.last_message_time = datetime.utcnow()

            try:
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="ignore")

                message = message.strip()
                if not message:
                    continue

                data = json.loads(message)
                if isinstance(data, list):
                    for item in data:
                        await self._handle_message(item)
                else:
                    await self._handle_message(data)
            except Exception as e:
                logger.error(
                    "failed_to_handle_message",
                    error=str(e),
                    raw_message_preview=message[:200] if isinstance(message, str) else None,
                    exc_info=True,
                )

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

    def _normalize_asset_ids(self, asset_ids: str | Iterable[str]) -> list[str]:
        """标准化 asset ids"""
        if isinstance(asset_ids, str):
            return [asset_ids]
        return [asset_id for asset_id in asset_ids if asset_id]
