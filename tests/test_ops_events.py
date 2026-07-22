"""
P13 — 事件总线背压/可观测性测试（Ops 视角）。

补充 tests/test_events.py，聚焦:
- 慢消费者不阻塞生产者，且此时队列深度（lag）可观测；
- 关键（order-critical）主题在突发下永不丢弃；
- 有界队列：单个消费者队列深度不超过 maxsize。
"""
import asyncio

import pytest

from libs.events import CRITICAL_TOPICS, LOSSY_TOPICS, EventBus, Topics


@pytest.mark.asyncio
async def test_slow_consumer_does_not_stall_publisher_and_lag_is_observable():
    bus = EventBus(default_queue_maxsize=256)
    release = asyncio.Event()

    async def slow(_data):
        await release.wait()

    await bus.subscribe(Topics.ORDERBOOK_TICK, slow)

    loop = asyncio.get_running_loop()
    start = loop.time()
    for seq in range(200):
        await bus.publish(Topics.ORDERBOOK_TICK, {"market_id": "m", "seq": seq})
    elapsed = loop.time() - start
    assert elapsed < 0.5, "publish must be enqueue-only, not blocked by slow consumer"

    # 队列深度（滞后）可观测。
    stats = bus.stats()
    depths = stats["queue_depths"][Topics.ORDERBOOK_TICK]
    assert depths and max(depths) > 0

    release.set()
    await bus.close()


@pytest.mark.asyncio
async def test_order_critical_topic_never_drops_under_burst():
    assert Topics.ORDER_REQUEST in CRITICAL_TOPICS
    assert Topics.ORDER_REQUEST not in LOSSY_TOPICS

    bus = EventBus(default_queue_maxsize=2)
    received = []

    async def handler(data):
        await asyncio.sleep(0)  # yield so the queue actually fills
        received.append(data["seq"])

    await bus.subscribe(Topics.ORDER_REQUEST, handler)

    total = 40
    for seq in range(total):
        await bus.publish(Topics.ORDER_REQUEST, {"order_id": "o", "seq": seq})
    await bus.drain()

    assert received == list(range(total))
    assert bus.stats()["dropped_total"] == 0
    await bus.close()


@pytest.mark.asyncio
async def test_bounded_queue_depth_never_exceeds_maxsize():
    maxsize = 4
    bus = EventBus(default_queue_maxsize=maxsize)
    release = asyncio.Event()

    async def slow(_data):
        await release.wait()

    await bus.subscribe(Topics.TRADE_TICK, slow)

    for seq in range(100):
        await bus.publish(Topics.TRADE_TICK, ["nokey", seq])
        for depths in bus.stats()["queue_depths"].values():
            for d in depths:
                assert d <= maxsize

    release.set()
    await bus.close()
