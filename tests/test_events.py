"""
测试事件总线
"""
import pytest
import asyncio
from libs.events import EventBus, Topics


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

    # 等待异步处理
    await asyncio.sleep(0.1)

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

    # 等待异步处理
    await asyncio.sleep(0.1)

    # 验证两个处理器都收到了事件
    assert received_count[0] == 1
    assert received_count[1] == 1
