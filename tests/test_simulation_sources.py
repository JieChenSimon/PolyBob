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


@pytest.mark.asyncio
async def test_deep_drawdown_confirmation_waits_for_causal_positive_close():
    source = DeepDrawdownSignalSource({
        "drawdown_fraction": 0.50,
        "confirmation_bars": 1,
        "tranche_delays_days": [0],
        "hold_days": 4,
        "max_nav_fraction": 0.05,
    })
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    prices = [100.0, 50.0, 48.0, 49.0]
    emitted = []
    for offset, price in enumerate(prices):
        emitted.extend(await source.on_snapshot("features.snapshots", {
            "market_id": "m1",
            "mid_price": price,
            "timestamp": timestamp + timedelta(days=offset),
        }))
    # 48 is not confirmation; 49 is the first positive close and only
    # schedules the next executable bar, so no signal has appeared yet.
    assert emitted == []
    next_bar = await source.on_snapshot("features.snapshots", {
        "market_id": "m1",
        "mid_price": 50.0,
        "timestamp": timestamp + timedelta(days=4),
    })
    assert len(next_bar) == 1
    assert next_bar[0].signal_meta["confirmation_bars"] == 1
    assert next_bar[0].signal_meta["event_date"].startswith("2026-01-04")


@pytest.mark.asyncio
async def test_deep_drawdown_probe_enters_before_confirmation_and_scales_afterward():
    source = DeepDrawdownSignalSource({
        "drawdown_fraction": 0.50,
        "confirmation_bars": 1,
        "probe_fraction": 1.0 / 3.0,
        "tranche_delays_days": [0, 1, 2],
        "hold_days": 4,
        "max_nav_fraction": 0.06,
    })
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    first = []
    for offset, price in enumerate([100.0, 50.0, 48.0]):
        first.extend(await source.on_snapshot("features.snapshots", {
            "market_id": "m1",
            "mid_price": price,
            "timestamp": timestamp + timedelta(days=offset),
        }))
    # The probe is filled on the bar after the trigger, even though the
    # confirmation has not happened yet.
    assert len(first) == 1
    assert first[0].signal_meta["tranche"] == "probe"
    assert first[0].signal_meta["position_fraction"] == pytest.approx(0.02)
    # 49 was a positive close after the trigger, so the remaining tranches
    # are scheduled; their first order arrives on the following bar.
    confirmation = await source.on_snapshot("features.snapshots", {
        "market_id": "m1", "mid_price": 49.0,
        "timestamp": timestamp + timedelta(days=4),
    })
    assert confirmation == []
    scaled = await source.on_snapshot("features.snapshots", {
        "market_id": "m1", "mid_price": 50.0,
        "timestamp": timestamp + timedelta(days=5),
    })
    assert len(scaled) == 1
    assert scaled[0].signal_meta["position_fraction"] == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_deep_drawdown_quality_date_gate_suppresses_unapproved_episode():
    source = DeepDrawdownSignalSource({"allowed_event_dates": ["2026-01-10"]})
    signals = []
    for day, close in enumerate((100.0, 110.0, 50.0), start=1):
        signals.extend(await source.on_snapshot(
            "features.snapshots",
            {"market_id": "m1", "mid_price": close,
             "timestamp": datetime(2026, 1, day, tzinfo=UTC)},
        ))
    assert signals == []
