"""
事件总线集成测试（使用真实的 libs.events.EventBus）
"""
import pytest
import asyncio

from libs.events import EventBus


@pytest.mark.asyncio
async def test_basic_pub_sub():
    """测试基本发布订阅"""
    bus = EventBus()
    received_events = []

    async def handler(data):
        received_events.append(data)

    await bus.subscribe("test_topic", handler)
    await bus.publish("test_topic", {"value": 123})

    await bus.drain()
    assert len(received_events) == 1
    assert received_events[0]["value"] == 123


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """测试多订阅者"""
    bus = EventBus()
    received_1 = []
    received_2 = []

    async def handler1(data):
        received_1.append(data)

    async def handler2(data):
        received_2.append(data)

    await bus.subscribe("topic", handler1)
    await bus.subscribe("topic", handler2)
    await bus.publish("topic", {"msg": "hello"})

    await bus.drain()
    assert len(received_1) == 1
    assert len(received_2) == 1


@pytest.mark.asyncio
async def test_event_ordering():
    """测试事件顺序（非行情主题为无损 FIFO）"""
    bus = EventBus()
    received_order = []

    async def handler(data):
        received_order.append(data["seq"])

    await bus.subscribe("topic", handler)

    for i in range(5):
        await bus.publish("topic", {"seq": i})

    await bus.drain()
    assert received_order == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_error_handling():
    """测试错误处理"""
    bus = EventBus()
    success_count = []

    async def failing_handler(data):
        raise ValueError("Handler error")

    async def success_handler(data):
        success_count.append(1)

    await bus.subscribe("topic", failing_handler)
    await bus.subscribe("topic", success_handler)
    await bus.publish("topic", {"test": True})

    await bus.drain()
    # 即使一个handler失败,其他handler应该继续执行
    assert len(success_count) == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    """测试取消订阅"""
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    await bus.subscribe("topic", handler)
    await bus.publish("topic", {"msg": "first"})
    await bus.drain()

    await bus.unsubscribe("topic", handler)
    await bus.publish("topic", {"msg": "second"})
    await bus.drain()

    assert len(received) == 1
    assert received[0]["msg"] == "first"


@pytest.mark.asyncio
async def test_concurrent_publishing():
    """测试并发发布"""
    bus = EventBus()
    received = []

    async def handler(data):
        await asyncio.sleep(0.001)
        received.append(data)

    await bus.subscribe("topic", handler)

    # 并发发布多个事件
    tasks = [bus.publish("topic", {"id": i}) for i in range(10)]
    await asyncio.gather(*tasks)

    await bus.drain()
    assert len(received) == 10
