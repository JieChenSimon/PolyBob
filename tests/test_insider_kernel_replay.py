from datetime import UTC, datetime

import asyncio
import pandas as pd

from scripts.insider_kernel_replay import EventReplaySource, build_event_positions, concentration


def test_insider_event_enters_next_bar_and_holds_fixed_sessions():
    dates = pd.date_range("2025-01-01", periods=8).strftime("%Y-%m-%d").tolist()
    frames = {"ABC": pd.Series([100.0] * len(dates), index=dates)}
    positions = build_event_positions(frames, [("ABC", "2025-01-02")], hold_sessions=3)
    assert positions["ABC"] == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]


def test_event_source_closes_an_active_long_with_sell():
    source = EventReplaySource({"event_positions": {"ABC": [0.0, 1.0, 1.0, 0.0]}})
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)

    async def run():
        signals = []
        for _ in range(4):
            signals.append(await source.on_snapshot("features.snapshots", {
                "market_id": "ABC", "mid_price": 100.0, "timestamp": timestamp,
            }))
        return signals

    signals = asyncio.run(run())
    assert signals[0] == []
    assert signals[1][0].side == "buy"
    assert signals[2] == []
    assert signals[3][0].side == "sell"


def test_concentration_reports_positive_pnl_tail_without_hiding_losses():
    result = concentration({
        "per_instrument": {
            "A": {"realized_pnl": 100.0},
            "B": {"realized_pnl": 50.0},
            "C": {"realized_pnl": -25.0},
        }
    })
    assert result["instruments"] == 3
    assert result["positive_instrument_fraction"] == 2 / 3
    assert result["top1_positive_pnl_share"] == 100 / 125
