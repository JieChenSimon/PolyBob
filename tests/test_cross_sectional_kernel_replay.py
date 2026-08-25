import asyncio
from datetime import UTC, datetime

import pytest

from scripts.cross_sectional_kernel_replay import ReplayPositionSource
from scripts.cross_sectional_standalone_replay import (
    apply_breadth_regime_filter,
    data_snapshot_digest,
)
from scripts.cross_sectional_multifold_replay import fold_dates as cross_sectional_fold_dates
from scripts.crypto_tsmom_multifold_replay import signed_positions
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


def test_replay_source_closes_a_short_with_a_buy():
    source = ReplayPositionSource({"replay_positions": [-1.0, -1.0, 0.0]})
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)

    async def run():
        first = await source.on_snapshot("features.snapshots", {
            "market_id": "BTC-USDT", "mid_price": 100, "timestamp": timestamp,
        })
        second = await source.on_snapshot("features.snapshots", {
            "market_id": "BTC-USDT", "mid_price": 100, "timestamp": timestamp,
        })
        third = await source.on_snapshot("features.snapshots", {
            "market_id": "BTC-USDT", "mid_price": 100, "timestamp": timestamp,
        })
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first[0].side == "sell"
    assert second == []
    assert third[0].side == "buy"


def test_standalone_snapshot_digest_changes_when_input_changes(tmp_path):
    first = {"AAA": pd.Series([100.0, 101.0], index=["2025-01-01", "2025-01-02"])}
    second = {"AAA": pd.Series([100.0, 102.0], index=["2025-01-01", "2025-01-02"])}
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    a = data_snapshot_digest(first, str(manifest))
    b = data_snapshot_digest(second, str(manifest))
    assert a["sha256"] != b["sha256"]
    assert a["manifest_sha256"] == b["manifest_sha256"]
    assert a["symbols"] == b["symbols"]


def test_breadth_regime_filter_is_causal_and_preserves_terminal_zero():
    frames = {
        "AAA": pd.Series([1.0, 2.0, 3.0], index=["2025-01-01", "2025-01-02", "2025-01-03"]),
        "BBB": pd.Series([3.0, 2.0, 1.0], index=["2025-01-01", "2025-01-02", "2025-01-03"]),
    }
    positions = {"AAA": [0.0, 1.0, 1.0, 0.0], "BBB": [0.0, 1.0, 1.0, 0.0]}
    filtered, breadth = apply_breadth_regime_filter(frames, positions, lookback=1, breadth_min=0.5)
    assert breadth["2025-01-02"] == pytest.approx(0.5)
    assert filtered["AAA"][-1] == 0.0
    assert filtered["AAA"][1] == 1.0


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


def test_signed_tsmom_emits_both_directions_without_lookahead():
    prices = [100.0] * 121
    prices[1:61] = [100.0 + i for i in range(1, 61)]
    prices[61:] = [160.0 - i for i in range(0, 60)]
    positions = signed_positions(prices, lookback=20, vol_lookback=20, threshold=0.25)
    assert positions[0] == 0.0
    assert positions[20] == 1.0
    assert -1.0 in positions[61:]
