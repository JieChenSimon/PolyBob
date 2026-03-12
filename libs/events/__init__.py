"""
Events - 事件总线和事件定义
"""
import asyncio
from typing import Any, Callable, Dict, List
from datetime import datetime
import structlog

logger = structlog.get_logger()


class EventBus:
    """简单的内存事件总线（MVP版本，后续可替换为Redis Streams或NATS）"""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str, handler: Callable):
        """订阅事件"""
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(handler)
            logger.info("subscribed_to_topic", topic=topic, handler=handler.__name__)

    async def publish(self, topic: str, data: Any):
        """发布事件"""
        handlers = self._subscribers.get(topic, [])
        if not handlers:
            logger.debug("no_subscribers", topic=topic)
            return

        logger.debug("publishing_event", topic=topic, handler_count=len(handlers))

        # 并发调用所有订阅者
        tasks = [self._safe_call(handler, topic, data) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

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
                handler=handler.__name__,
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

    # 信号
    SIGNAL_GENERATED = "signals.generated"

    # 风控
    RISK_DECISION = "risk.decisions"
    RISK_ALERT = "risk.alerts"

    # 订单
    ORDER_REQUEST = "orders.requests"
    ORDER_UPDATE = "orders.updates"
    FILL_UPDATE = "orders.fills"

    # AI
    AI_NOTE = "ai.notes"

    # 系统
    WEBSOCKET_CONNECTED = "system.websocket.connected"
    WEBSOCKET_DISCONNECTED = "system.websocket.disconnected"
