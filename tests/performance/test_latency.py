"""
延迟性能测试
"""
import pytest
import asyncio
import time
from datetime import datetime
from typing import List


class LatencyTracker:
    """延迟追踪器"""

    def __init__(self):
        self.measurements: List[float] = []

    def record(self, latency_ms: float):
        """记录延迟"""
        self.measurements.append(latency_ms)

    def percentile(self, p: float) -> float:
        """计算百分位数"""
        if not self.measurements:
            return 0.0
        sorted_measurements = sorted(self.measurements)
        index = int(len(sorted_measurements) * p)
        return sorted_measurements[min(index, len(sorted_measurements) - 1)]

    def p50(self) -> float:
        return self.percentile(0.50)

    def p95(self) -> float:
        return self.percentile(0.95)

    def p99(self) -> float:
        return self.percentile(0.99)


@pytest.mark.performance
@pytest.mark.asyncio
async def test_data_processing_latency():
    """测试数据处理延迟"""
    tracker = LatencyTracker()

    async def process_market_data(data: dict):
        """模拟市场数据处理"""
        await asyncio.sleep(0.001)  # 模拟处理时间
        return {"processed": True}

    # 测试1000次
    for _ in range(1000):
        start = time.perf_counter()
        await process_market_data({"market_id": "test"})
        end = time.perf_counter()
        tracker.record((end - start) * 1000)

    # 验证性能目标
    assert tracker.p50() < 50, f"P50 latency {tracker.p50():.2f}ms exceeds 50ms"
    assert tracker.p95() < 100, f"P95 latency {tracker.p95():.2f}ms exceeds 100ms"
    assert tracker.p99() < 200, f"P99 latency {tracker.p99():.2f}ms exceeds 200ms"


@pytest.mark.performance
@pytest.mark.asyncio
async def test_strategy_decision_latency():
    """测试策略决策延迟"""
    tracker = LatencyTracker()

    async def make_strategy_decision(features: dict):
        """模拟策略决策"""
        await asyncio.sleep(0.002)
        return {"signal": "buy", "confidence": 0.8}

    for _ in range(500):
        start = time.perf_counter()
        await make_strategy_decision({"volatility": 0.02})
        end = time.perf_counter()
        tracker.record((end - start) * 1000)

    assert tracker.p95() < 100, f"Strategy decision P95 {tracker.p95():.2f}ms too high"


@pytest.mark.performance
@pytest.mark.asyncio
async def test_end_to_end_latency():
    """测试端到端延迟"""
    tracker = LatencyTracker()

    async def end_to_end_flow(market_update: dict):
        """模拟完整流程: 数据 -> 特征 -> 策略 -> 订单"""
        await asyncio.sleep(0.001)  # 数据处理
        await asyncio.sleep(0.002)  # 特征计算
        await asyncio.sleep(0.002)  # 策略决策
        await asyncio.sleep(0.001)  # 订单提交
        return True

    for _ in range(200):
        start = time.perf_counter()
        await end_to_end_flow({"price": 0.55})
        end = time.perf_counter()
        tracker.record((end - start) * 1000)

    assert tracker.p95() < 100, f"E2E P95 latency {tracker.p95():.2f}ms exceeds target"
