from datetime import UTC, datetime, timedelta

import pytest

from modules.simulation.sources import DeepDrawdownSignalSource, MomentumSignalSource


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


@pytest.mark.asyncio
async def test_deep_drawdown_source_is_causal_and_stages_next_bar_entries():
    source = DeepDrawdownSignalSource({
        "drawdown_fraction": 0.50,
        "tranche_delays_days": [0, 1, 2],
        "hold_days": 4,
        "max_nav_fraction": 0.06,
    })
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    emitted = []
    for offset, price in enumerate([100.0, 90.0, 50.0]):
        emitted.extend(await source.on_snapshot("features.snapshots", {
            "market_id": "m1",
            "mid_price": price,
            "timestamp": timestamp + timedelta(days=offset),
        }))
    # The close that crosses the threshold only schedules the next executable
    # bar; it must not create a look-ahead fill on the trigger bar.
    assert emitted == []
    first = await source.on_snapshot("features.snapshots", {
        "market_id": "m1", "mid_price": 48.0,
        "timestamp": timestamp + timedelta(days=4),
    })
    assert len(first) == 1
    assert first[0].side == "buy"
    assert first[0].signal_meta["position_fraction"] == pytest.approx(0.02)
    assert first[0].signal_meta["event_date"].startswith("2026-01-03")
