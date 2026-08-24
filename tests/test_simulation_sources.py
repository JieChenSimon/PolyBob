from datetime import UTC, datetime, timedelta

import pytest

from modules.simulation.sources import MomentumSignalSource


@pytest.mark.asyncio
async def test_momentum_inverse_candidate_flips_direction():
    base = MomentumSignalSource({"fast_window": 3, "slow_window": 8})
    inverse = MomentumSignalSource({"fast_window": 3, "slow_window": 8, "invert_signal": True})
    timestamp = datetime.now(UTC)
    base_signals = []
    inverse_signals = []
    for offset, price in enumerate(range(1, 9)):
        snapshot = {
            "market_id": "m1",
            "mid_price": float(price),
            "timestamp": timestamp + timedelta(days=offset),
        }
        base_signals.extend(await base.on_snapshot("features.snapshots", snapshot))
        inverse_signals.extend(await inverse.on_snapshot("features.snapshots", snapshot))

    assert base_signals[-1].side == "buy"
    assert inverse_signals[-1].side == "sell"
