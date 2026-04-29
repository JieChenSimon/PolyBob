"""Spread arbitrage strategy - 基于 pair snapshot 自动生成 intent"""
from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from libs.events import Topics, get_event_bus

logger = structlog.get_logger()


class SpreadArbitrageV1:
    def __init__(self, config: dict, intent_service=None):
        self.strategy_id = "spread_arbitrage_v1"
        self.event_bus = get_event_bus()
        self.intent_service = intent_service

        self.min_net_edge_bps = float(config.get("min_net_edge_bps", 12.0))
        self.min_abs_spread_bps = float(config.get("min_abs_spread_bps", 8.0))
        self.min_confidence = float(config.get("min_confidence", 0.55))
        self.order_quantity = float(config.get("order_quantity", 0.01))
        self.cooldown = timedelta(seconds=float(config.get("cooldown_seconds", 30)))

        self._running = False
        self._last_intent_at: dict[str, datetime] = {}

    async def start(self):
        logger.info("starting_strategy", strategy_id=self.strategy_id)
        self._running = True
        await self.event_bus.subscribe(Topics.PAIR_SNAPSHOT, self._on_pair_snapshot)

    async def stop(self):
        logger.info("stopping_strategy", strategy_id=self.strategy_id)
        self._running = False

    async def _on_pair_snapshot(self, snapshot: dict):
        if not self._running or self.intent_service is None:
            return

        pair_id = str(snapshot["pair_id"])
        now = datetime.utcnow()
        last_intent_at = self._last_intent_at.get(pair_id)
        if last_intent_at and now - last_intent_at < self.cooldown:
            return

        net_edge_bps = float(snapshot.get("net_edge_bps") or 0.0)
        spread_bps = float(snapshot.get("spread_bps") or 0.0)
        z_score = abs(float(snapshot.get("z_score") or 0.0))
        confidence = min(1.0, 0.45 + z_score * 0.15 + max(net_edge_bps, 0.0) / 100)

        if net_edge_bps < self.min_net_edge_bps:
            return
        if abs(spread_bps) < self.min_abs_spread_bps:
            return
        if confidence < self.min_confidence:
            return

        side = snapshot.get("opportunity_side")
        if side == "long_right_short_left":
            legs = [
                {
                    "venue": snapshot["left"]["venue"],
                    "symbol": snapshot["left"]["symbol"],
                    "side": "sell",
                    "quantity": self.order_quantity,
                    "limit_price": snapshot["left_bid"],
                    "role": "primary",
                },
                {
                    "venue": snapshot["right"]["venue"],
                    "symbol": snapshot["right"]["symbol"],
                    "side": "buy",
                    "quantity": self.order_quantity,
                    "limit_price": snapshot["right_ask"],
                    "role": "hedge",
                },
            ]
        else:
            legs = [
                {
                    "venue": snapshot["left"]["venue"],
                    "symbol": snapshot["left"]["symbol"],
                    "side": "buy",
                    "quantity": self.order_quantity,
                    "limit_price": snapshot["left_ask"],
                    "role": "primary",
                },
                {
                    "venue": snapshot["right"]["venue"],
                    "symbol": snapshot["right"]["symbol"],
                    "side": "sell",
                    "quantity": self.order_quantity,
                    "limit_price": snapshot["right_bid"],
                    "role": "hedge",
                },
            ]

        created = await self.intent_service.create_intent(
            strategy_id=self.strategy_id,
            rationale=f"auto spread arbitrage for {pair_id}",
            expected_edge_bps=net_edge_bps,
            confidence=confidence,
            metadata={"pair_id": pair_id, "mode": "cross_exchange"},
            legs=legs,
        )
        await self.intent_service.submit_intent(created["intent_id"])
        self._last_intent_at[pair_id] = now
