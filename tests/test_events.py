"""
测试事件总线
"""
import pytest
import asyncio
from libs.events import CRITICAL_TOPICS, LOSSY_TOPICS, EventBus, Topics


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish():
    """测试事件订阅和发布"""
    bus = EventBus()
    received_data = []

    async def handler(data):
        received_data.append(data)

    # 订阅
    await bus.subscribe(Topics.MARKET_DISCOVERED, handler)

    # 发布
    test_data = {"market_id": "test_123"}
    await bus.publish(Topics.MARKET_DISCOVERED, test_data)

    # 等待异步投递完成
    await bus.drain()

    # 验证
    assert len(received_data) == 1
    assert received_data[0] == test_data


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    """测试多个订阅者"""
    bus = EventBus()
    received_count = [0, 0]

    async def handler1(data):
        received_count[0] += 1

    async def handler2(data):
        received_count[1] += 1

    # 订阅
    await bus.subscribe(Topics.ORDERBOOK_TICK, handler1)
    await bus.subscribe(Topics.ORDERBOOK_TICK, handler2)

    # 发布
    await bus.publish(Topics.ORDERBOOK_TICK, {"test": "data"})

    # 等待异步投递完成
    await bus.drain()

    # 验证两个处理器都收到了事件
    assert received_count[0] == 1
    assert received_count[1] == 1


@pytest.mark.asyncio
async def test_lossy_topic_coalesces_under_burst():
    """行情主题在队列打满时按 key 保留最新并计数"""
    bus = EventBus(default_queue_maxsize=4)
    received = []
    release = asyncio.Event()

    async def slow_handler(data):
        await release.wait()
        received.append(data)

    await bus.subscribe(Topics.ORDERBOOK_TICK, slow_handler)

    # 突发发布：同一个 market 的 50 次更新 + 另一个 market 的 1 次更新
    for seq in range(50):
        await bus.publish(Topics.ORDERBOOK_TICK, {"market_id": "m1", "seq": seq})
    await bus.publish(Topics.ORDERBOOK_TICK, {"market_id": "m2", "seq": 0})

    release.set()
    await bus.drain()

    # m1 被合并为少量投递，且最后一次投递必须是最新值（seq=49）
    m1_payloads = [item for item in received if item["market_id"] == "m1"]
    assert m1_payloads, "m1 must be delivered at least once"
    assert m1_payloads[-1]["seq"] == 49
    assert len(m1_payloads) < 50
    # m2 也被投递
    assert any(item["market_id"] == "m2" for item in received)

    stats = bus.stats()
    assert stats["coalesced_total"] > 0
    assert stats["coalesced"][Topics.ORDERBOOK_TICK] > 0


@pytest.mark.asyncio
async def test_lossy_topic_drop_oldest_without_key():
    """无 key 的行情负载在队列打满时丢最旧并计数"""
    bus = EventBus(default_queue_maxsize=2)
    received = []
    release = asyncio.Event()

    async def slow_handler(data):
        await release.wait()
        received.append(data)

    await bus.subscribe(Topics.TRADE_TICK, slow_handler)

    for seq in range(10):
        await bus.publish(Topics.TRADE_TICK, ["no-key-payload", seq])

    release.set()
    await bus.drain()

    assert len(received) < 10
    # 最新的负载必须保留
    assert received[-1] == ["no-key-payload", 9]
    stats = bus.stats()
    assert stats["dropped"][Topics.TRADE_TICK] > 0
    assert stats["dropped_total"] > 0


@pytest.mark.asyncio
async def test_critical_topic_never_drops():
    """关键主题（订单）不丢事件：队满时对生产者施加背压"""
    assert Topics.ORDER_UPDATE in CRITICAL_TOPICS
    assert Topics.ORDER_UPDATE not in LOSSY_TOPICS

    bus = EventBus(default_queue_maxsize=2)
    received = []

    async def slow_handler(data):
        await asyncio.sleep(0.001)
        received.append(data)

    await bus.subscribe(Topics.ORDER_UPDATE, slow_handler)

    total = 25
    for seq in range(total):
        await bus.publish(Topics.ORDER_UPDATE, {"order_id": "o1", "seq": seq})

    await bus.drain()

    # 全部按序送达，一个不丢
    assert [item["seq"] for item in received] == list(range(total))
    stats = bus.stats()
    assert stats["dropped_total"] == 0


@pytest.mark.asyncio
async def test_publish_does_not_block_on_slow_subscriber():
    """生产者不再被最慢订阅者拖住（行情主题发布应立即返回）"""
    bus = EventBus()
    release = asyncio.Event()

    async def very_slow_handler(data):
        await release.wait()

    await bus.subscribe(Topics.ORDERBOOK_TICK, very_slow_handler)

    loop = asyncio.get_running_loop()
    start = loop.time()
    for seq in range(100):
        await bus.publish(Topics.ORDERBOOK_TICK, {"market_id": "m1", "seq": seq})
    elapsed = loop.time() - start

    assert elapsed < 0.5, "publish must be enqueue-only, not blocked by the handler"
    release.set()
    await bus.drain()


@pytest.mark.asyncio
async def test_handler_error_does_not_kill_consumer():
    """处理器异常不影响其他订阅者，也不杀死消费任务"""
    bus = EventBus()
    received = []

    async def failing_handler(data):
        raise ValueError("boom")

    async def good_handler(data):
        received.append(data)

    await bus.subscribe(Topics.MARKET_DISCOVERED, failing_handler)
    await bus.subscribe(Topics.MARKET_DISCOVERED, good_handler)

    await bus.publish(Topics.MARKET_DISCOVERED, {"market_id": "a"})
    await bus.publish(Topics.MARKET_DISCOVERED, {"market_id": "b"})
    await bus.drain()

    assert len(received) == 2


@pytest.mark.asyncio
async def test_close_stops_consumers():
    """close() 先 drain 再取消消费任务"""
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    await bus.subscribe(Topics.MARKET_DISCOVERED, handler)
    await bus.publish(Topics.MARKET_DISCOVERED, {"market_id": "x"})
    await bus.close()

    assert len(received) == 1
