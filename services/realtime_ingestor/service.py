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
from libs.schemas import OrderbookTick, TradeTick, Side
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
        self.subscribed_markets: Set[str] = set()
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

    async def _on_market_discovered(self, market):
        """处理市场发现事件"""
        market_id = market.market_id
        logger.info("subscribing_to_market", market_id=market_id)

        # 订阅市场
        await self.ws.subscribe(market_id)
        self.subscribed_markets.add(market_id)

        # 拉取初始快照
        await self._fetch_snapshot(market_id)

    async def _fetch_snapshot(self, market_id: str):
        """拉取订单簿快照"""
        try:
            snapshot = await self.rest_client.get_orderbook(market_id)

            # 转换为内部模型
            orderbook = self._parse_orderbook(market_id, snapshot)

            # 发布快照事件
            await self.event_bus.publish(Topics.ORDERBOOK_TICK, orderbook)

            logger.info("fetched_orderbook_snapshot", market_id=market_id)

        except Exception as e:
            logger.error(
                "failed_to_fetch_snapshot",
                market_id=market_id,
                error=str(e),
            )

    async def _handle_message(self, data: dict):
        """处理 WebSocket 消息"""
        msg_type = data.get("type")

        if msg_type == "orderbook_update":
            await self._handle_orderbook_update(data)
        elif msg_type == "trade":
            await self._handle_trade(data)
        elif msg_type == "order_update":
            await self._handle_order_update(data)
        else:
            logger.debug("unknown_message_type", type=msg_type)

    async def _handle_orderbook_update(self, data: dict):
        """处理订单簿更新"""
        market_id = data.get("market_id")
        if not market_id:
            return

        try:
            orderbook = self._parse_orderbook(market_id, data)
            await self.event_bus.publish(Topics.ORDERBOOK_TICK, orderbook)

            # 同时发布 BBO 事件
            await self.event_bus.publish(
                Topics.BBO_TICK,
                {
                    "market_id": market_id,
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
                error=str(e),
            )

    async def _handle_trade(self, data: dict):
        """处理成交记录"""
        market_id = data.get("market_id")
        if not market_id:
            return

        try:
            trade = TradeTick(
                market_id=market_id,
                timestamp=datetime.fromisoformat(data["timestamp"]),
                price=float(data["price"]),
                size=float(data["size"]),
                side=Side(data["side"]),
            )

            await self.event_bus.publish(Topics.TRADE_TICK, trade)

        except Exception as e:
            logger.error(
                "failed_to_handle_trade",
                market_id=market_id,
                error=str(e),
            )

    async def _handle_order_update(self, data: dict):
        """处理订单更新"""
        await self.event_bus.publish(Topics.ORDER_UPDATE, data)

    def _parse_orderbook(self, market_id: str, data: dict) -> OrderbookTick:
        """解析订单簿数据"""
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        # 提取最优买卖价
        bid_price = float(bids[0][0]) if bids else 0.0
        ask_price = float(asks[0][0]) if asks else 0.0
        bid_size = float(bids[0][1]) if bids else 0.0
        ask_size = float(asks[0][1]) if asks else 0.0

        return OrderbookTick(
            market_id=market_id,
            timestamp=datetime.utcnow(),
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            bids=[(float(p), float(s)) for p, s in bids],
            asks=[(float(p), float(s)) for p, s in asks],
        )
