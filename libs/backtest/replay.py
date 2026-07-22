"""
历史数据回放器
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()


class HistoricalDataReplayer:
    """历史数据回放器"""

    def __init__(self, data_source: str, start_date: datetime, end_date: datetime):
        self.data_source = data_source
        self.start_date = start_date
        self.end_date = end_date
        self.current_time = start_date
        self.events: List[Dict[str, Any]] = []
        self._sorted_events_cache: List[Dict[str, Any]] | None = None
        self._sorted_cache_key: tuple | None = None

    def load_data(self):
        """从数据源加载历史数据"""
        # TODO: 实现从不同数据源加载
        # - PostgreSQL
        # - Parquet文件
        # - CSV文件
        logger.info("loading_historical_data",
                   source=self.data_source,
                   start=self.start_date,
                   end=self.end_date)
        pass

    def _get_sorted_events(self) -> List[Dict[str, Any]]:
        """Return events ordered by timestamp without copying when possible.

        Fast path: a single O(n) pass detects an already-sorted list, which is
        then iterated in place. Otherwise the sorted copy is built once and
        cached so repeated replays do not re-sort.
        """
        events = self.events
        if all(
            events[i]["timestamp"] <= events[i + 1]["timestamp"]
            for i in range(len(events) - 1)
        ):
            return events

        cache_key = (id(events), len(events))
        if self._sorted_events_cache is None or self._sorted_cache_key != cache_key:
            self._sorted_events_cache = sorted(events, key=lambda e: e["timestamp"])
            self._sorted_cache_key = cache_key
        return self._sorted_events_cache

    async def replay(self, event_bus, speed_multiplier: float = 1.0):
        """按时间顺序回放历史事件

        Args:
            event_bus: 事件总线
            speed_multiplier: 回放速度倍数 (1.0=实时, 10.0=10倍速)
        """
        logger.info("starting_replay", speed=speed_multiplier)

        # 按时间戳排序事件 (已排序时零拷贝, 否则排序一次并缓存)
        sorted_events = self._get_sorted_events()

        prev_time = None
        for event in sorted_events:
            event_time = event["timestamp"]

            # 计算延迟
            if prev_time:
                time_diff = (event_time - prev_time).total_seconds()
                sleep_time = time_diff / speed_multiplier
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            # 发布事件到总线
            await event_bus.publish(event["topic"], event["data"])

            prev_time = event_time
            self.current_time = event_time

        logger.info("replay_completed", events_count=len(sorted_events))
