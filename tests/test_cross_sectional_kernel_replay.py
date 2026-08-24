import asyncio
from datetime import UTC, datetime

import pytest

from scripts.cross_sectional_kernel_replay import ReplayPositionSource
from scripts.cross_sectional_multifold_replay import fold_dates as cross_sectional_fold_dates
from scripts.mean_reversion_multifold_replay import buy_and_hold_return, fold_dates
import pandas as pd


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


def test_multifold_cut_dates_are_chronological_and_date_aligned():
    dates = [date.strftime("%Y-%m-%d") for date in pd.date_range("2020-01-01", periods=360)]
    cuts = fold_dates(dates, (0.5, 0.7, 0.8))
    assert cuts == sorted(cuts)
    assert len(set(cuts)) == 3

    series = pd.Series([100.0, 110.0, 121.0], index=["2020-01-01", "2020-01-02", "2020-01-03"])
    assert buy_and_hold_return(series, "2020-01-02") == pytest.approx(0.21)


def test_cross_sectional_multifold_cut_dates_are_chronological():
    dates = [date.strftime("%Y-%m-%d") for date in pd.date_range("2020-01-01", periods=360)]
    cuts = cross_sectional_fold_dates(dates, (0.5, 0.7, 0.8))
    assert cuts == sorted(cuts)
    assert len(set(cuts)) == 3
