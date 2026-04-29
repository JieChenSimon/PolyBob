"""Pair feature engine - 生产跨 venue / 跨品种价差快照"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable
import uuid

import structlog

from libs.events import Topics, get_event_bus
from libs.schemas import ExecutionVenue, InstrumentRef, SpreadPairSnapshot

logger = structlog.get_logger()

QuoteFetcher = Callable[[], Awaitable[dict]]


@dataclass
class PairDefinition:
    pair_id: str
    left: InstrumentRef
    right: InstrumentRef
    fetch_quotes: QuoteFetcher


class PairFeatureEngineService:
    def __init__(self, pair_definitions: list[PairDefinition], poll_interval_seconds: float = 5.0):
        self.event_bus = get_event_bus()
        self.pair_definitions = pair_definitions
        self.poll_interval_seconds = poll_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self.snapshots: dict[str, SpreadPairSnapshot] = {}
        self.spread_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))

    async def start(self):
        logger.info("starting_pair_feature_engine", pair_count=len(self.pair_definitions))
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        logger.info("stopping_pair_feature_engine")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def list_snapshots(self) -> list[dict]:
        return [snapshot.model_dump(mode="json") for snapshot in self.snapshots.values()]

    def list_pairs(self) -> list[dict]:
        return [
            {
                "pair_id": pair.pair_id,
                "left": pair.left.model_dump(mode="json"),
                "right": pair.right.model_dump(mode="json"),
                "poll_interval_seconds": self.poll_interval_seconds,
            }
            for pair in self.pair_definitions
        ]

    def get_snapshot(self, pair_id: str) -> dict | None:
        snapshot = self.snapshots.get(pair_id)
        return snapshot.model_dump(mode="json") if snapshot else None

    async def _poll_loop(self):
        while self._running:
            try:
                for pair in self.pair_definitions:
                    snapshot = await self._build_snapshot(pair)
                    if snapshot is None:
                        continue
                    self.snapshots[pair.pair_id] = snapshot
                    await self.event_bus.publish(Topics.PAIR_SNAPSHOT, snapshot.model_dump(mode="json"))
            except Exception as exc:
                logger.error("pair_feature_engine_error", error=str(exc), exc_info=True)

            await asyncio.sleep(self.poll_interval_seconds)

    async def _build_snapshot(self, pair: PairDefinition) -> SpreadPairSnapshot | None:
        quotes = await pair.fetch_quotes()
        left = quotes.get("left", {})
        right = quotes.get("right", {})

        try:
            left_bid = float(left["bid"])
            left_ask = float(left["ask"])
            right_bid = float(right["bid"])
            right_ask = float(right["ask"])
        except (KeyError, TypeError, ValueError):
            return None

        if left_bid <= 0 or left_ask <= 0 or right_bid <= 0 or right_ask <= 0:
            return None

        left_mid = (left_bid + left_ask) * 0.5
        right_mid = (right_bid + right_ask) * 0.5
        avg_mid = (left_mid + right_mid) * 0.5
        if avg_mid <= 0:
            return None

        spread_bps = ((left_mid - right_mid) / avg_mid) * 10000
        long_right_short_left = ((left_bid - right_ask) / avg_mid) * 10000
        long_left_short_right = ((right_bid - left_ask) / avg_mid) * 10000
        net_edge_bps = max(long_right_short_left, long_left_short_right)
        opportunity_side = (
            "long_right_short_left"
            if long_right_short_left >= long_left_short_right
            else "long_left_short_right"
        )

        history = self.spread_history[pair.pair_id]
        history.append(spread_bps)
        z_score = None
        if len(history) >= 5:
            values = list(history)
            mean_value = sum(values) / len(values)
            variance = sum((value - mean_value) ** 2 for value in values) / len(values)
            std_value = variance ** 0.5
            if std_value > 0:
                z_score = (spread_bps - mean_value) / std_value

        return SpreadPairSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:10]}",
            pair_id=pair.pair_id,
            timestamp=datetime.utcnow(),
            left=pair.left,
            right=pair.right,
            left_bid=left_bid,
            left_ask=left_ask,
            right_bid=right_bid,
            right_ask=right_ask,
            left_mid=left_mid,
            right_mid=right_mid,
            spread_bps=spread_bps,
            z_score=z_score,
            hedge_ratio=1.0,
            net_edge_bps=net_edge_bps,
            opportunity_side=opportunity_side,
        )
