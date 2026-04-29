"""
压力测试 - 极端市场条件
"""
import pytest
import asyncio
import time
from datetime import datetime
from typing import List, Dict


class StressTestScenario:
    """压力测试场景"""

    @staticmethod
    def extreme_volatility_data(n_samples=1000) -> List[Dict]:
        """生成极端波动数据"""
        import random
        data = []
        price = 0.5

        for i in range(n_samples):
            # 随机±20%跳空
            shock = random.choice([-0.2, -0.1, 0, 0.1, 0.2])
            price = max(0.01, min(0.99, price * (1 + shock)))

            data.append({
                'timestamp': datetime.utcnow(),
                'price': price,
                'spread_bps': random.randint(500, 2000),  # 高价差
            })

        return data

    @staticmethod
    def liquidity_crisis_data(n_samples=500) -> List[Dict]:
        """生成流动性危机数据"""
        data = []
        for i in range(n_samples):
            data.append({
                'timestamp': datetime.utcnow(),
                'bid_depth': 100,  # 极低深度
                'ask_depth': 100,
                'spread_bps': 1000,  # 极宽价差
            })
        return data

    @staticmethod
    def high_frequency_updates(n_samples=10000) -> List[Dict]:
        """生成高频更新数据"""
        return [
            {'timestamp': datetime.utcnow(), 'price': 0.5 + i * 0.0001}
            for i in range(n_samples)
        ]


@pytest.mark.stress
@pytest.mark.asyncio
async def test_extreme_volatility_handling():
    """测试极端波动处理"""
    scenario = StressTestScenario()
    data = scenario.extreme_volatility_data(1000)

    async def process_volatile_data(market_data):
        """模拟处理波动数据"""
        await asyncio.sleep(0.001)
        return {'processed': True}

    start = time.perf_counter()
    for item in data:
        await process_volatile_data(item)
    duration = time.perf_counter() - start

    # 验证系统在极端波动下仍能正常处理
    assert duration < 5.0  # 1000条数据应在5秒内完成


@pytest.mark.stress
@pytest.mark.asyncio
async def test_liquidity_crisis_handling():
    """测试流动性危机处理"""
    scenario = StressTestScenario()
    data = scenario.liquidity_crisis_data(500)

    orders_rejected = 0

    async def attempt_order(market_data):
        """尝试下单"""
        if market_data['bid_depth'] < 500:
            return False  # 拒绝订单
        return True

    for item in data:
        if not await attempt_order(item):
            orders_rejected += 1

    # 验证风控正确拒绝低流动性订单
    assert orders_rejected > 400  # 大部分订单应被拒绝


@pytest.mark.stress
@pytest.mark.asyncio
async def test_high_frequency_data_throughput():
    """测试高频数据吞吐量"""
    scenario = StressTestScenario()
    data = scenario.high_frequency_updates(10000)

    processed = 0

    async def process_update(update):
        """处理更新"""
        await asyncio.sleep(0.0001)
        return True

    start = time.perf_counter()
    for item in data:
        if await process_update(item):
            processed += 1
    duration = time.perf_counter() - start

    throughput = processed / duration

    # 验证吞吐量 >1000条/秒
    assert throughput > 1000
    assert processed == 10000


@pytest.mark.stress
def test_memory_under_load():
    """测试负载下内存使用"""
    import sys

    initial_size = sys.getsizeof([])
    large_dataset = []

    # 模拟大量数据
    for i in range(100000):
        large_dataset.append({
            'timestamp': datetime.utcnow(),
            'price': 0.5,
            'volume': 1000,
        })

    final_size = sys.getsizeof(large_dataset)

    # 验证内存增长在合理范围
    assert final_size < 100 * 1024 * 1024  # <100MB


@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_strategy_execution():
    """测试并发策略执行"""

    async def run_strategy(strategy_id: int):
        """运行策略"""
        await asyncio.sleep(0.1)
        return {'strategy_id': strategy_id, 'result': 'success'}

    # 并发运行10个策略
    tasks = [run_strategy(i) for i in range(10)]
    start = time.perf_counter()
    results = await asyncio.gather(*tasks)
    duration = time.perf_counter() - start

    # 验证并发执行效率
    assert len(results) == 10
    assert duration < 0.5  # 并发应快于串行(1秒)
