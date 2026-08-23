"""
Strategy Engine Service - 策略引擎服务
"""
import asyncio
import structlog
from typing import Dict, List, Optional
from datetime import datetime
import time

from libs.events import get_event_bus, Topics
from libs.schemas import Signal, Side
from .base import Strategy, StrategySignal

logger = structlog.get_logger()


class StrategyEngineService:
    """策略引擎服务 - 优化版本"""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.strategies: List[Strategy] = []
        self._running = False
        self._signal_counter = 0

        # 性能监控
        self._last_execution_time = 0.0
        self._execution_count = 0

    def register_strategy(self, strategy: Strategy):
        """注册策略"""
        self.strategies.append(strategy)
        strategy_name = (
            strategy.get_name()
            if hasattr(strategy, "get_name")
            else getattr(strategy, "name", strategy.__class__.__name__)
        )
        logger.info(
            "strategy_registered",
            strategy_id=strategy.strategy_id,
            strategy_name=strategy_name,
        )

    async def start(self):
        """启动服务"""
        logger.info("starting_strategy_engine",
                   strategy_count=len(self.strategies))
        self._running = True

        # 订阅特征快照
        await self.event_bus.subscribe(
            Topics.FEATURE_SNAPSHOT,
            self._on_feature_snapshot
        )

    async def stop(self):
        """停止服务"""
        logger.info("stopping_strategy_engine")
        self._running = False
        await self.event_bus.unsubscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)

    async def _on_feature_snapshot(self, features: dict):
        """处理特征快照 - 优化版本"""
        if not self._running:
            return

        start_time = time.perf_counter()

        # 并发执行所有启用的策略
        tasks = [
            self._run_strategy(strategy, features)
            for strategy in self.strategies
            if getattr(strategy, "enabled", True)
        ]

        signals = await asyncio.gather(*tasks, return_exceptions=True)

        # 快速发布有效信号
        for signal in signals:
            if isinstance(signal, StrategySignal):
                await self._publish_signal(signal)
            elif isinstance(signal, Exception):
                logger.error("strategy_error", error=str(signal))

        # 性能监控
        elapsed = time.perf_counter() - start_time
        self._last_execution_time = elapsed
        self._execution_count += 1

        if elapsed > 0.1:  # 超过100ms告警
            logger.warning("slow_strategy_execution",
                          elapsed_ms=elapsed * 1000,
                          strategy_count=len(tasks))

    async def _run_strategy(
        self,
        strategy: Strategy,
        features: dict
    ) -> StrategySignal | None:
        """运行单个策略"""
        try:
            return await strategy.generate_signal(features)
        except Exception as e:
            logger.error("strategy_execution_error",
                        strategy_id=strategy.strategy_id,
                        error=str(e),
                        exc_info=True)
            return None

    async def _publish_signal(self, signal: StrategySignal):
        """发布信号"""
        self._signal_counter += 1

        # 转换为标准 Signal schema
        signal_obj = Signal(
            signal_id=f"sig_{self._signal_counter}_{int(signal.timestamp.timestamp())}",
            market_id=signal.market_id,
            strategy_id=signal.reason.split(":")[0] if ":" in signal.reason else "unknown",
            timestamp=signal.timestamp,
            side=signal.side,
            price=signal.price,
            size=signal.size,
            expected_edge_bps=signal.expected_edge_bps,
            confidence=signal.confidence,
            ttl_seconds=60,
            reason_code=signal.reason
        )

        await self.event_bus.publish(Topics.SIGNAL_GENERATED, signal_obj)

        logger.info("signal_generated",
                   signal_id=signal_obj.signal_id,
                   market_id=signal.market_id,
                   side=signal.side.value,
                   confidence=signal.confidence,
                   edge_bps=signal.expected_edge_bps)
