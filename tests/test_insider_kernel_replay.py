from datetime import UTC, datetime

import asyncio
import pandas as pd

from scripts.insider_kernel_replay import (
    EventReplaySource,
    build_event_positions,
    build_risk_fractions,
    concentration,
    filter_events_by_pre_event_vol,
    filter_events_by_market_return,
    filter_by_filing_delay,
)
from libs.data.sec_insider import InsiderTrade


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


def test_risk_fractions_use_only_pre_event_bars_and_keep_base_median():
    dates = pd.date_range("2024-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    calm = pd.Series([100.0 + i * 0.1 for i in range(80)], index=dates)
    volatile = pd.Series([100.0 + (i % 2) * 10.0 for i in range(80)], index=dates)
    fractions = build_risk_fractions(
        {"CALM": calm, "VOL": volatile},
        [("CALM", "2024-03-01"), ("VOL", "2024-03-01")],
        0.0025,
    )
    assert fractions["CALM"] > fractions["VOL"]
    assert all(0.0025 * 0.25 <= value <= 0.0025 * 2 for value in fractions.values())


def test_pre_event_volatility_filter_is_causal_and_fail_closed():
    dates = pd.date_range("2024-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    calm = pd.Series([100.0 + i * 0.1 for i in range(80)], index=dates)
    volatile = pd.Series([100.0 + (i % 2) * 10.0 for i in range(80)], index=dates)
    events = [("CALM", "2024-03-01"), ("VOL", "2024-03-01"),
              ("MISSING", "2024-03-01")]
    selected = filter_events_by_pre_event_vol(
        {"CALM": calm, "VOL": volatile}, events, max_volatility=0.5
    )
    assert selected == [("CALM", "2024-03-01")]


def test_market_filter_uses_only_bars_before_filing():
    dates = pd.date_range("2024-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    market = pd.Series([100.0 + i for i in range(80)], index=dates)
    events = [("A", "2024-03-01"), ("B", "2024-03-02")]
    selected = filter_events_by_market_return(market, events, lookback=20, min_return=0.1)
    assert selected == events


def test_filing_delay_filter_is_causal_and_fail_closed():
    def trade(filing, transaction):
        return InsiderTrade("ABC", "Issuer", filing, transaction, "P", 100, 10)

    selected = filter_by_filing_delay([
        trade("2024-01-10", "2024-01-05"),
        trade("2024-01-10", "2023-12-01"),
        trade("2024-01-10", ""),
    ], max_days=7)
    assert len(selected) == 1
    assert selected[0].trans_date == "2024-01-05"
