"""
Realtime Ingestor Service - 实时数据采集服务

职责：
- 订阅 Polymarket CLOB WebSocket 市场频道和用户频道
- 拉取 order book、trades、best bid/ask、订单状态和成交回报
- 通过单一 reducer 处理 book 快照 + price_change 增量更新
- 自动重连、去重、补拉快照；可选地把原始事件写入 append-only 日志
"""
import asyncio
import contextlib
import structlog
from datetime import datetime
from typing import Set

from libs.polymarket import PolymarketWebSocket, PolymarketClient
from libs.polymarket.book_state import (
    BookState,
    PolymarketBookReducer,
    parse_provider_timestamp,
)
from libs.events import get_event_bus, Topics
from libs.schemas import Market, OrderbookTick, TradeTick
from libs.config import get_settings

logger = structlog.get_logger()

# 会写入 raw book log 的消息类型（记录原始 payload，处理之前）
_LOGGED_EVENT_TYPES = {"book", "price_change", "last_trade_price"}


class RealtimeIngestorService:
    """实时数据采集服务"""

    def __init__(self, book_log=None):
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
        self._ws_task: asyncio.Task | None = None
        # 快照拉取通过有界队列 + worker 池并发处理，避免市场发现扫描被串行 REST 调用阻塞
        self._snapshot_concurrency = 8
        self._snapshot_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=512)
        self._snapshot_workers: list[asyncio.Task] = []

        # 订单簿 reducer：快照 + price_change 增量的唯一实现（replay 复用同一实现）
        self.book_reducer = PolymarketBookReducer()
        # price_change 先于快照到达时，请求 resync（去重，避免重复排队）
        self._resync_pending: Set[str] = set()

        # 可选的 append-only 原始事件日志（默认 None，不落盘）
        self.book_log = book_log

        # 设置消息处理器
        self.ws.set_message_handler(self._handle_message)

    async def start(self):
        """启动服务"""
        logger.info("starting_realtime_ingestor_service")
        self._running = True

        if self.book_log is not None:
            await self.book_log.start()

        # 订阅市场发现事件
        await self.event_bus.subscribe(Topics.MARKET_DISCOVERED, self._on_market_discovered)

        # 启动快照 worker 池
        self._snapshot_workers = [
            asyncio.create_task(self._snapshot_worker())
            for _ in range(self._snapshot_concurrency)
        ]

        # WebSocket waits until a real asset is discovered. This avoids empty
        # background connections to Polymarket when Gamma is unavailable.

    async def stop(self):
        """停止服务"""
        logger.info("stopping_realtime_ingestor_service")
        self._running = False
        for worker in self._snapshot_workers:
            worker.cancel()
        for worker in self._snapshot_workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._snapshot_workers = []
        await self.ws.close()
        if self._ws_task:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        await self.rest_client.close()
        if self.book_log is not None:
            await self.book_log.stop()

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

        await self._ensure_websocket_started()

        # 订阅资产（先订阅，再排队拉取该市场的初始快照，保持单市场顺序）
        await self.ws.subscribe(asset_id)
        self.subscribed_assets.add(asset_id)

        # 初始快照交给 worker 池异步拉取，避免阻塞市场发现事件链
        await self._snapshot_queue.put((market_id, asset_id))

    async def _snapshot_worker(self):
        """快照拉取 worker：从队列消费并并发执行 REST 快照拉取"""
        while True:
            market_id, asset_id = await self._snapshot_queue.get()
            try:
                await self._fetch_snapshot(market_id, asset_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "snapshot_worker_error",
                    market_id=market_id,
                    asset_id=asset_id,
                    error=str(e),
                )
            finally:
                self._snapshot_queue.task_done()

    async def _fetch_snapshot(self, market_id: str, asset_id: str):
        """拉取订单簿快照"""
        try:
            snapshot = await self.rest_client.get_orderbook(asset_id)

            state = self.book_reducer.apply_snapshot(
                snapshot,
                asset_id=asset_id,
                market_id=market_id,
            )
            self._resync_pending.discard(asset_id)
            if state is not None:
                await self._publish_book_state(state)

            logger.debug("fetched_orderbook_snapshot", market_id=market_id, asset_id=asset_id)

        except Exception as e:
            logger.error(
                "failed_to_fetch_snapshot",
                market_id=market_id,
                asset_id=asset_id,
                error=str(e),
            )

    async def _ensure_websocket_started(self):
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self.ws.connect())

    async def _handle_message(self, data: dict):
        """处理 WebSocket 消息"""
        if not isinstance(data, dict):
            logger.debug("ignoring_non_dict_message", message_type=type(data).__name__)
            return

        msg_type = data.get("event_type") or data.get("type")

        # 原始事件先落日志（处理之前，保证 replay 输入未被加工）
        if self.book_log is not None and msg_type in _LOGGED_EVENT_TYPES:
            try:
                self.book_log.log_event(
                    asset_id=data.get("asset_id"),
                    event_type=msg_type,
                    payload=data,
                    receive_ts=datetime.utcnow(),
                    source_ts=parse_provider_timestamp(data.get("timestamp")),
                )
            except Exception as e:
                logger.error("book_log_write_failed", error=str(e))

        if msg_type == "book":
            await self._handle_orderbook_update(data)
        elif msg_type == "last_trade_price":
            await self._handle_trade(data)
        elif msg_type == "price_change":
            await self._handle_price_change(data)
        elif msg_type == "order_update":
            await self._handle_order_update(data)
        else:
            logger.debug("unknown_message_type", type=msg_type)

    async def _handle_orderbook_update(self, data: dict):
        """处理订单簿快照（book 消息）"""
        market_id = data.get("market")
        asset_id = data.get("asset_id")
        if not market_id:
            return

        try:
            state = self.book_reducer.apply_snapshot(
                data,
                asset_id=asset_id,
                market_id=market_id,
            )
            if state is None:
                return
            self._resync_pending.discard(state.asset_id)
            await self._publish_book_state(state)

        except Exception as e:
            logger.error(
                "failed_to_handle_orderbook_update",
                market_id=market_id,
                asset_id=asset_id,
                error=str(e),
            )

    async def _handle_price_change(self, data: dict):
        """处理 price_change 增量更新"""
        try:
            states = self.book_reducer.apply_price_change(data)
            for state in states:
                if not state.has_snapshot:
                    # 没有基础快照：标记 stale 并请求 resync，不发布猜测的簿
                    await self._request_resync(state.asset_id, data.get("market"))
                    continue
                await self._publish_book_state(state)
        except Exception as e:
            logger.error(
                "failed_to_handle_price_change",
                asset_id=data.get("asset_id"),
                error=str(e),
            )

    async def _request_resync(self, asset_id: str, market_id: str | None):
        """price_change 先于快照到达：请求一次快照 resync（去重）"""
        if asset_id in self._resync_pending:
            return
        self._resync_pending.add(asset_id)
        logger.debug("book_resync_requested", asset_id=asset_id)
        try:
            self._snapshot_queue.put_nowait((market_id or "", asset_id))
        except asyncio.QueueFull:
            # 队列满时放弃本次排队，保留 pending 状态等待下一个快照
            logger.warning("snapshot_queue_full_resync_deferred", asset_id=asset_id)
            self._resync_pending.discard(asset_id)

    async def _publish_book_state(self, state: BookState):
        """发布经过校验的订单簿状态（保持既有事件 schema 兼容）"""
        orderbook = self._orderbook_from_state(state)
        await self.event_bus.publish(Topics.ORDERBOOK_TICK, orderbook)

        # 同时发布 BBO 事件
        await self.event_bus.publish(
            Topics.BBO_TICK,
            {
                "market_id": orderbook.market_id,
                "asset_id": orderbook.asset_id,
                "timestamp": orderbook.timestamp,
                "bid_price": orderbook.bid_price,
                "ask_price": orderbook.ask_price,
                "bid_size": orderbook.bid_size,
                "ask_size": orderbook.ask_size,
                "quality": orderbook.quality,
            },
        )

    def _orderbook_from_state(self, state: BookState) -> OrderbookTick:
        """把 BookState 转成对外发布的 OrderbookTick"""
        best_bid = state.best_bid
        best_ask = state.best_ask

        # 兼容字段：timestamp 优先用 provider 时间；缺失时退回本地接收时间，
        # 但 source_ts 保持 None 且 quality 标记 no_timestamp，绝不冒充交易所时间。
        timestamp = state.source_ts or state.receive_ts

        return OrderbookTick(
            market_id=state.market_id or "",
            asset_id=state.asset_id,
            timestamp=timestamp,
            # An unquoted side is None, not 0.0. A zero bid is a real price —
            # "someone is bidding nothing" — and publishing it made a one-sided
            # book indistinguishable from a two-sided one downstream.
            bid_price=best_bid[0] if best_bid else None,
            ask_price=best_ask[0] if best_ask else None,
            bid_size=best_bid[1] if best_bid else None,
            ask_size=best_ask[1] if best_ask else None,
            bids=list(state.bids),
            asks=list(state.asks),
            source_ts=state.source_ts,
            receive_ts=state.receive_ts,
            quality=state.quality,
            sequence_status=state.sequence_status,
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

    def _parse_timestamp(self, value) -> datetime:
        """兼容毫秒时间戳和 ISO 8601（trade 路径，保留本地时间回退）"""
        parsed = parse_provider_timestamp(value)
        return parsed if parsed is not None else datetime.utcnow()
