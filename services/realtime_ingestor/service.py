"""
Realtime Ingestor Service - 实时数据采集服务

职责：
- 订阅 Polymarket CLOB WebSocket 市场频道和用户频道
- 拉取 order book、trades、best bid/ask、订单状态和成交回报
- 自动重连、去重、补拉快照
"""
import asyncio
import structlog
from datetime import datetime
from typing import Set

from libs.polymarket import PolymarketWebSocket, PolymarketClient
from libs.events import get_event_bus, Topics
from libs.schemas import Market, OrderbookTick, TradeTick
from libs.config import get_settings

logger = structlog.get_logger()


class RealtimeIngestorService:
    """实时数据采集服务"""

    def __init__(self):
        self.settings = get_settings()
        self.ws = PolymarketWebSocket(
            url=self.settings.polymarket_clob_ws_url,
            reconnect_interval=5,
        )
        self.rest_client = PolymarketClient(
            base_url=self.settings.polymarket_clob_rest_url,
            api_key=self.settings.polymarket_api_key,
        )
        self.event_bus = get_event_bus()
        self.subscribed_assets: Set[str] = set()
        self._running = False

        # 设置消息处理器
        self.ws.set_message_handler(self._handle_message)

    async def start(self):
        """启动服务"""
        logger.info("starting_realtime_ingestor_service")
        self._running = True

        # 订阅市场发现事件
        await self.event_bus.subscribe(Topics.MARKET_DISCOVERED, self._on_market_discovered)

        # 启动 WebSocket 连接
        asyncio.create_task(self.ws.connect())

    async def stop(self):
        """停止服务"""
        logger.info("stopping_realtime_ingestor_service")
        self._running = False
        await self.ws.close()
        await self.rest_client.close()

    async def _on_market_discovered(self, market: Market):
        """处理市场发现事件"""
        if not self._running:
            return

        market_id = market.market_id
        asset_id = market.primary_asset_id
        if not asset_id:
            logger.warning("market_missing_primary_asset", market_id=market_id)
            return

        logger.debug("subscribing_to_market", market_id=market_id, asset_id=asset_id)

        # 订阅资产
        await self.ws.subscribe(asset_id)
        self.subscribed_assets.add(asset_id)

        # 拉取初始快照
        await self._fetch_snapshot(market_id, asset_id)

    async def _fetch_snapshot(self, market_id: str, asset_id: str):
        """拉取订单簿快照"""
        try:
            snapshot = await self.rest_client.get_orderbook(asset_id)

            # 转换为内部模型
            orderbook = self._parse_orderbook(snapshot, market_id=market_id, asset_id=asset_id)

            # 发布快照事件
            await self.event_bus.publish(Topics.ORDERBOOK_TICK, orderbook)

            logger.debug("fetched_orderbook_snapshot", market_id=market_id, asset_id=asset_id)

        except Exception as e:
            logger.error(
                "failed_to_fetch_snapshot",
                market_id=market_id,
                asset_id=asset_id,
                error=str(e),
            )

    async def _handle_message(self, data: dict):
        """处理 WebSocket 消息"""
        if not isinstance(data, dict):
            logger.debug("ignoring_non_dict_message", message_type=type(data).__name__)
            return

        msg_type = data.get("event_type") or data.get("type")

        if msg_type == "book":
            await self._handle_orderbook_update(data)
        elif msg_type == "last_trade_price":
            await self._handle_trade(data)
        elif msg_type == "price_change":
            return
        elif msg_type == "order_update":
            await self._handle_order_update(data)
        else:
            logger.debug("unknown_message_type", type=msg_type)

    async def _handle_orderbook_update(self, data: dict):
        """处理订单簿更新"""
        market_id = data.get("market")
        asset_id = data.get("asset_id")
        if not market_id:
            return

        try:
            orderbook = self._parse_orderbook(data, market_id=market_id, asset_id=asset_id)
            await self.event_bus.publish(Topics.ORDERBOOK_TICK, orderbook)

            # 同时发布 BBO 事件
            await self.event_bus.publish(
                Topics.BBO_TICK,
                {
                    "market_id": market_id,
                    "asset_id": asset_id,
                    "timestamp": orderbook.timestamp,
                    "bid_price": orderbook.bid_price,
                    "ask_price": orderbook.ask_price,
                    "bid_size": orderbook.bid_size,
                    "ask_size": orderbook.ask_size,
                },
            )

        except Exception as e:
            logger.error(
                "failed_to_handle_orderbook_update",
                market_id=market_id,
                asset_id=asset_id,
                error=str(e),
            )

    async def _handle_trade(self, data: dict):
        """处理成交记录"""
        market_id = data.get("market")
        asset_id = data.get("asset_id")
        if not market_id:
            return

        try:
            trade = TradeTick(
                market_id=market_id,
                asset_id=asset_id,
                timestamp=self._parse_timestamp(data["timestamp"]),
                price=float(data["price"]),
                size=float(data["size"]),
                side=str(data.get("side", "")),
            )

            await self.event_bus.publish(Topics.TRADE_TICK, trade)

        except Exception as e:
            logger.error(
                "failed_to_handle_trade",
                market_id=market_id,
                asset_id=asset_id,
                error=str(e),
            )

    async def _handle_order_update(self, data: dict):
        """处理订单更新"""
        await self.event_bus.publish(Topics.ORDER_UPDATE, data)

    def _parse_orderbook(
        self,
        data: dict,
        market_id: str,
        asset_id: str | None = None,
    ) -> OrderbookTick:
        """解析订单簿数据"""
        bids = self._normalize_levels(data.get("bids", []))
        asks = self._normalize_levels(data.get("asks", []))

        # 提取最优买卖价
        bid_price = bids[0][0] if bids else 0.0
        ask_price = asks[0][0] if asks else 0.0
        bid_size = bids[0][1] if bids else 0.0
        ask_size = asks[0][1] if asks else 0.0

        return OrderbookTick(
            market_id=market_id,
            asset_id=asset_id or data.get("asset_id"),
            timestamp=self._parse_timestamp(data.get("timestamp")),
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            bids=bids,
            asks=asks,
        )

    def _normalize_levels(self, levels: list) -> list[tuple[float, float]]:
        """兼容不同订单簿档位格式"""
        normalized: list[tuple[float, float]] = []
        for level in levels:
            if isinstance(level, dict):
                price = level.get("price")
                size = level.get("size")
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
            else:
                continue

            try:
                normalized.append((float(price), float(size)))
            except (TypeError, ValueError):
                continue
        return normalized

    def _parse_timestamp(self, value) -> datetime:
        """兼容毫秒时间戳和 ISO 8601"""
        if value is None:
            return datetime.utcnow()

        if isinstance(value, (int, float)):
            return datetime.utcfromtimestamp(float(value) / 1000)

        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return datetime.utcfromtimestamp(int(stripped) / 1000)

            normalized = stripped.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return datetime.utcnow()

        return datetime.utcnow()
