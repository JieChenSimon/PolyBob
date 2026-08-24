import pandas as pd
import pytest

from scripts.multi_asset_portfolio_replay import MultiPositionSource, stable_daily_frames


def test_stable_daily_frames_rejects_long_gaps():
    stable = pd.Series([1.0, 2.0], index=["2024-01-01", "2024-01-04"])
    stale = pd.Series([1.0, 2.0], index=["2024-01-01", "2024-01-10"])
    accepted, rejected = stable_daily_frames({"STABLE": stable, "STALE": stale})
    assert list(accepted) == ["STABLE"]
    assert rejected == ["STALE"]


def test_terminal_liquidation_target_contract():
    targets = [1.0, -1.0]
    targets.append(0.0)
    assert targets[-1] == 0.0


@pytest.mark.asyncio
async def test_multi_position_source_preserves_weight_in_signal():
    source = MultiPositionSource({
        "positions_by_symbol": {"A": [0.25, 0.0]},
        "position_fraction_by_instrument": {"A": 1.0},
    })
    first = await source.on_snapshot("features.snapshots", {
        "market_id": "A", "mid_price": 10.0, "timestamp": "2026-01-01T00:00:00+00:00",
    })
    second = await source.on_snapshot("features.snapshots", {
        "market_id": "A", "mid_price": 10.0, "timestamp": "2026-01-02T00:00:00+00:00",
    })
    assert first[0].signal_meta["position_fraction"] == 0.25
    assert second[0].signal_meta["position_fraction"] == 0.0
