import asyncio
from datetime import UTC, datetime

from scripts.cross_sectional_kernel_replay import ReplayPositionSource


def test_replay_source_emits_only_target_changes():
    source = ReplayPositionSource({"replay_positions": [0.0, 0.25, 0.25, 0.0]})
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)

    async def run():
        first = await source.on_snapshot("features.snapshots", {"market_id": "AAPL", "mid_price": 100, "timestamp": timestamp})
        second = await source.on_snapshot("features.snapshots", {"market_id": "AAPL", "mid_price": 100, "timestamp": timestamp})
        third = await source.on_snapshot("features.snapshots", {"market_id": "AAPL", "mid_price": 100, "timestamp": timestamp})
        fourth = await source.on_snapshot("features.snapshots", {"market_id": "AAPL", "mid_price": 100, "timestamp": timestamp})
        return first, second, third, fourth

    first, second, third, fourth = asyncio.run(run())
    assert first == []
    assert second[0].side == "buy"
    assert third == []
    assert fourth[0].side == "sell"
