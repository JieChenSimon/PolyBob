"""
事件总线集成测试
"""
import pytest
import asyncio
from datetime import datetime
from typing import List


class SimpleEventBus:
    """简单事件总线实现用于测试"""

    def __init__(self):
        self.subscribers = {}
        self.published_events = []

    async def subscribe(self, topic: str, handler):
        """订阅主题"""
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(handler)

    async def unsubscribe(self, topic: str, handler):
        """取消订阅"""
        if topic in self.subscribers:
            self.subscribers[topic].remove(handler)

    async def publish(self, topic: str, data: dict):
        """发布事件"""
        self.published_events.append((topic, data, datetime.utcnow()))

        if topic in self.subscribers:
            tasks = [handler(data) for handler in self.subscribers[topic]]
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_basic_pub_sub():
    """测试基本发布订阅"""
    bus = SimpleEventBus()
    received_events = []

    async def handler(data):
        received_events.append(data)

    await bus.subscribe("test_topic", handler)
    await bus.publish("test_topic", {"value": 123})

    await asyncio.sleep(0.01)
    assert len(received_events) == 1
    assert received_events[0]["value"] == 123


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """测试多订阅者"""
    bus = SimpleEventBus()
    received_1 = []
    received_2 = []

    async def handler1(data):
        received_1.append(data)

    async def handler2(data):
        received_2.append(data)

    await bus.subscribe("topic", handler1)
    await bus.subscribe("topic", handler2)
    await bus.publish("topic", {"msg": "hello"})

    await asyncio.sleep(0.01)
    assert len(received_1) == 1
    assert len(received_2) == 1


@pytest.mark.asyncio
async def test_event_ordering():
    """测试事件顺序"""
    bus = SimpleEventBus()
    received_order = []

    async def handler(data):
        received_order.append(data["seq"])

    await bus.subscribe("topic", handler)

    for i in range(5):
        await bus.publish("topic", {"seq": i})

    await asyncio.sleep(0.01)
    assert received_order == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_error_handling():
    """测试错误处理"""
    bus = SimpleEventBus()
    success_count = []

    async def failing_handler(data):
        raise ValueError("Handler error")

    async def success_handler(data):
        success_count.append(1)

    await bus.subscribe("topic", failing_handler)
    await bus.subscribe("topic", success_handler)
    await bus.publish("topic", {"test": True})

    await asyncio.sleep(0.01)
    # 即使一个handler失败,其他handler应该继续执行
    assert len(success_count) == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    """测试取消订阅"""
    bus = SimpleEventBus()
    received = []

    async def handler(data):
        received.append(data)

    await bus.subscribe("topic", handler)
    await bus.publish("topic", {"msg": "first"})
    await asyncio.sleep(0.01)

    await bus.unsubscribe("topic", handler)
    await bus.publish("topic", {"msg": "second"})
    await asyncio.sleep(0.01)

    assert len(received) == 1
    assert received[0]["msg"] == "first"


@pytest.mark.asyncio
async def test_concurrent_publishing():
    """测试并发发布"""
    bus = SimpleEventBus()
    received = []

    async def handler(data):
        await asyncio.sleep(0.001)
        received.append(data)

    await bus.subscribe("topic", handler)

    # 并发发布多个事件
    tasks = [bus.publish("topic", {"id": i}) for i in range(10)]
    await asyncio.gather(*tasks)

    await asyncio.sleep(0.1)
    assert len(received) == 10
