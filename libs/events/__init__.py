"""
Events - 事件总线和事件定义

Backpressure-aware in-memory event bus:

- Each subscriber gets a bounded ``asyncio.Queue`` drained by a dedicated
  consumer task, so ``publish`` is an enqueue and producers (e.g. the
  Polymarket WS reader) never stall behind the slowest handler.
- Critical topics (orders / intents / fills / risk decisions) are lossless:
  when a subscriber queue is full the producer awaits (backpressure) instead
  of dropping.
- High-frequency market-data topics coalesce keep-latest per key
  (market/asset/pair id) and drop-oldest when a queue is full; drops and
  coalesces are counted and exposed via ``EventBus.stats()``.
- ``drain()`` awaits until every queue is empty and all handlers are idle,
  which is what tests use in place of the old synchronous inline delivery.
"""
import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
import structlog

logger = structlog.get_logger()

# Default bound for each subscriber queue.
DEFAULT_QUEUE_MAXSIZE = 1024

# Payload keys tried (in order) to derive a coalescing key for lossy topics.
_COALESCE_KEY_FIELDS = ("asset_id", "market_id", "pair_id", "symbol")


class _Subscription:
    """One handler's bounded queue + consumer-task state."""

    __slots__ = (
        "topic",
        "handler",
        "maxsize",
        "queue",
        "latest",
        "pending_keys",
        "task",
        "busy",
    )

    def __init__(self, topic: str, handler: Callable, maxsize: int):
        self.topic = topic
        self.handler = handler
        self.maxsize = maxsize
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        # Coalescing state for lossy topics: key -> latest payload.
        self.latest: Dict[Any, Any] = {}
        self.pending_keys: set = set()
        self.task: Optional[asyncio.Task] = None
        self.busy = False

    def reset(self):
        """Rebuild queue state after an event-loop change (tests)."""
        self.queue = asyncio.Queue(maxsize=self.maxsize)
        self.latest = {}
        self.pending_keys = set()
        self.task = None
        self.busy = False

    def idle(self) -> bool:
        return self.queue.empty() and not self.busy


class EventBus:
    """有界队列事件总线（每个订阅者一个消费任务，生产者只入队）。"""

    def __init__(self, default_queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE):
        self._default_queue_maxsize = default_queue_maxsize
        self._subscribers: Dict[str, List[_Subscription]] = {}
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = False
        # Counters exposed via stats().
        self._published = 0
        self._delivered = 0
        self._dropped: Dict[str, int] = {}
        self._coalesced: Dict[str, int] = {}

    # ------------------------------------------------------------------ API

    async def subscribe(self, topic: str, handler: Callable, maxsize: int | None = None):
        """订阅事件"""
        async with self._lock:
            sub = _Subscription(topic, handler, maxsize or self._default_queue_maxsize)
            self._subscribers.setdefault(topic, []).append(sub)
            logger.info(
                "subscribed_to_topic",
                topic=topic,
                handler=getattr(handler, "__name__", repr(handler)),
            )
        self._ensure_started()

    async def unsubscribe(self, topic: str, handler: Callable):
        """取消订阅"""
        async with self._lock:
            subs = self._subscribers.get(topic, [])
            for sub in list(subs):
                if sub.handler is handler:
                    subs.remove(sub)
                    if sub.task is not None and not sub.task.done():
                        sub.task.cancel()

    async def publish(self, topic: str, data: Any):
        """发布事件（入队；关键主题在队满时对生产者施加背压，行情主题合并/丢弃）"""
        self._ensure_started()
        subs = self._subscribers.get(topic, [])
        if not subs:
            logger.debug("no_subscribers", topic=topic)
            return

        self._published += 1
        lossy = topic in LOSSY_TOPICS

        for sub in subs:
            if lossy:
                self._enqueue_lossy(sub, topic, data)
            else:
                # Lossless: backpressure the producer when the queue is full.
                await sub.queue.put(("payload", data))

    async def drain(self):
        """等待所有队列清空且所有处理器空闲。"""
        self._ensure_started()
        while True:
            subs = [s for subs in self._subscribers.values() for s in subs]
            if all(sub.idle() for sub in subs):
                return
            await asyncio.sleep(0.001)

    async def close(self):
        """优雅关闭：先 drain，再取消所有消费任务。"""
        try:
            await self.drain()
        finally:
            self._closed = True
            tasks = []
            for subs in self._subscribers.values():
                for sub in subs:
                    if sub.task is not None and not sub.task.done():
                        sub.task.cancel()
                        tasks.append(sub.task)
                    sub.task = None
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # pragma: no cover - defensive
                    pass

    def stats(self) -> dict:
        """队列/丢弃/合并计数（监控与测试用）。"""
        return {
            "published": self._published,
            "delivered": self._delivered,
            "dropped": dict(self._dropped),
            "dropped_total": sum(self._dropped.values()),
            "coalesced": dict(self._coalesced),
            "coalesced_total": sum(self._coalesced.values()),
            "queue_depths": {
                topic: [sub.queue.qsize() for sub in subs]
                for topic, subs in self._subscribers.items()
            },
        }

    # ------------------------------------------------------------- internals

    def _ensure_started(self):
        """Lazily (re)start consumer tasks on the current running loop."""
        if self._closed:
            self._closed = False  # a reused bus revives on next activity
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # New event loop (typical in tests): old tasks/queues are dead.
            self._loop = loop
            for subs in self._subscribers.values():
                for sub in subs:
                    sub.reset()
        for subs in self._subscribers.values():
            for sub in subs:
                if sub.task is None or sub.task.done():
                    sub.task = loop.create_task(self._consume(sub))

    def _enqueue_lossy(self, sub: _Subscription, topic: str, data: Any):
        key = self._coalesce_key(data)
        if key is not None and key in sub.pending_keys:
            # Keep-latest per key: replace the pending payload in place.
            sub.latest[key] = data
            self._coalesced[topic] = self._coalesced.get(topic, 0) + 1
            return

        item: Tuple[str, Any]
        if key is not None:
            sub.latest[key] = data
            item = ("key", key)
        else:
            item = ("payload", data)

        while True:
            try:
                sub.queue.put_nowait(item)
                if key is not None:
                    sub.pending_keys.add(key)
                return
            except asyncio.QueueFull:
                # Drop-oldest and retry.
                try:
                    old_kind, old_value = sub.queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - tiny race
                    continue
                sub.queue.task_done()
                if old_kind == "key":
                    sub.pending_keys.discard(old_value)
                    sub.latest.pop(old_value, None)
                self._dropped[topic] = self._dropped.get(topic, 0) + 1

    @staticmethod
    def _coalesce_key(data: Any) -> Any:
        if isinstance(data, dict):
            for field in _COALESCE_KEY_FIELDS:
                value = data.get(field)
                if value is not None:
                    return value
        return None

    async def _consume(self, sub: _Subscription):
        while True:
            kind, value = await sub.queue.get()
            if kind == "key":
                sub.pending_keys.discard(value)
                payload = sub.latest.pop(value, None)
            else:
                payload = value
            sub.busy = True
            try:
                await self._safe_call(sub.handler, sub.topic, payload)
                self._delivered += 1
            finally:
                sub.busy = False
                sub.queue.task_done()

    async def _safe_call(self, handler: Callable, topic: str, data: Any):
        """安全调用处理器，捕获异常"""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(data)
            else:
                handler(data)
        except Exception as e:
            logger.error(
                "event_handler_error",
                topic=topic,
                handler=getattr(handler, "__name__", repr(handler)),
                error=str(e),
                exc_info=True,
            )


# 全局事件总线实例
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局事件总线"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# 事件主题定义
class Topics:
    """事件主题常量"""
    # 市场发现
    MARKET_DISCOVERED = "markets.discovered"
    MARKET_STATUS_CHANGED = "markets.status_changed"
    MARKET_WATCHLIST_UPDATED = "markets.watchlist_updated"

    # 市场数据
    ORDERBOOK_TICK = "marketdata.orderbook"
    TRADE_TICK = "marketdata.trades"
    BBO_TICK = "marketdata.bbo"

    # 特征
    FEATURE_SNAPSHOT = "features.snapshots"
    FEATURE_ALERT = "features.alert"
    PAIR_SNAPSHOT = "features.pairs.snapshots"
    PAIR_ALERT = "features.pairs.alert"
    ONCHAIN_TRANSFER_INGESTED = "features.onchain.transfer_ingested"
    ONCHAIN_DISTRIBUTION_ALERT = "features.onchain.distribution_alert"

    # 信号
    SIGNAL_GENERATED = "signals.generated"
    STRATEGY_INSTANCE_CREATED = "strategies.instances.created"
    STRATEGY_INSTANCE_STARTED = "strategies.instances.started"
    STRATEGY_INSTANCE_STOPPED = "strategies.instances.stopped"
    STRATEGY_INSTANCE_DELETED = "strategies.instances.deleted"
    STRATEGY_INTENT_CREATED = "strategies.intents.created"

    # 风控
    RISK_DECISION = "risk.decisions"
    RISK_ALERT = "risk.alerts"
    RISK_INTENT_CHECKED = "risk.intents.checked"
    RISK_KILL_SWITCH_TRIGGERED = "risk.kill_switch.triggered"

    # 订单
    ORDER_REQUEST = "orders.requests"
    ORDER_UPDATE = "orders.updates"
    FILL_UPDATE = "orders.fills"
    ORDER_BASKET_SUBMITTED = "orders.baskets.submitted"
    ORDER_LEG_UPDATED = "orders.legs.updated"
    PORTFOLIO_EXPOSURE_CHANGED = "portfolio.exposure.changed"

    # AI
    AI_NOTE = "ai.notes"

    # 系统
    WEBSOCKET_CONNECTED = "system.websocket.connected"
    WEBSOCKET_DISCONNECTED = "system.websocket.disconnected"


# 关键主题（订单/意图/成交/风控/信号）：绝不丢弃，队满时生产者等待。
CRITICAL_TOPICS = frozenset(
    {
        Topics.ORDER_REQUEST,
        Topics.ORDER_UPDATE,
        Topics.FILL_UPDATE,
        Topics.ORDER_BASKET_SUBMITTED,
        Topics.ORDER_LEG_UPDATED,
        Topics.STRATEGY_INTENT_CREATED,
        Topics.SIGNAL_GENERATED,
        Topics.RISK_DECISION,
        Topics.RISK_INTENT_CHECKED,
        Topics.RISK_KILL_SWITCH_TRIGGERED,
        Topics.PORTFOLIO_EXPOSURE_CHANGED,
    }
)

# 高频行情主题：队满时按 key 合并（keep-latest）或丢最旧，并计数。
LOSSY_TOPICS = frozenset(
    {
        Topics.ORDERBOOK_TICK,
        Topics.TRADE_TICK,
        Topics.BBO_TICK,
        Topics.FEATURE_SNAPSHOT,
        Topics.PAIR_SNAPSHOT,
    }
)
