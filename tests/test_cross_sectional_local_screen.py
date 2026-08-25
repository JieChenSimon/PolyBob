import numpy as np
import pytest

import pandas as pd

from scripts.cross_sectional_paper_replay import (
    execution_evidence_status,
    filter_replay_dates,
    summarize_instrument_oos_pnl,
)
from scripts.cross_sectional_standalone_replay import (
    apply_tail_risk_guard,
    binary_target,
    rolling_equity_folds,
    slice_signal_window,
)
from scripts.cross_sectional_oos_inference import daily_oos_excess
from scripts.cross_sectional_local_screen import (
    align_frames,
    apply_risk_policy,
    has_unresolved_price_jump,
    select_long_only,
    symbols_from_discovery_manifest,
    equal_weight_benchmark,
    benchmark_eligible_assets,
    _endpoint_values,
)


def test_cross_sectional_selection_uses_only_past_prices():
    prices = np.array([
        [100, 101, 102, 103, 104, 105],
        [100, 99, 98, 97, 96, 95],
        [100, 100, 100, 100, 100, 100],
        [100, 100, 100, 100, 100, 100],
    ], dtype=float)
    positions = select_long_only(prices, lookback=2, top_frac=0.25)
    assert np.all(positions[:, :2] == 0)
    assert positions[0, 2] == 1.0
    assert positions[1, 2] == 0.0


def test_cross_sectional_selection_is_long_only_and_bounded():
    rng = np.random.default_rng(7)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(8, 20)), axis=1))
    positions = select_long_only(prices, lookback=5, top_frac=0.25)
    assert np.all(positions >= 0)
    assert np.all(positions <= 1)
    nonzero_sums = positions.sum(axis=0)[positions.sum(axis=0) > 0]
    assert np.all(nonzero_sums <= 1.0 + 1e-12)


def test_cross_sectional_rejects_unresolved_price_jump():
    values = np.ones(300)
    values[150] = 100.0
    assert has_unresolved_price_jump(values, 1.5)


def test_risk_policy_never_increases_long_exposure():
    rng = np.random.default_rng(8)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(8, 100)), axis=1))
    base = select_long_only(prices, lookback=20, top_frac=0.3, rebalance_days=5)
    scaled = apply_risk_policy(prices, base, "vol_target_10_dd")
    assert np.all(scaled >= 0)
    assert np.all(scaled <= base + 1e-12)


def test_cross_sectional_frames_align_on_event_date_not_row_number():
    frames = {
        "A": pd.Series([10.0, 11.0], index=["2024-01-02", "2024-01-03"]),
        "B": pd.Series([20.0, 21.0], index=["2024-01-03", "2024-01-04"]),
    }
    aligned = align_frames(frames)
    assert aligned.loc["2024-01-03", "A"] == 11.0
    assert aligned.loc["2024-01-03", "B"] == 20.0
    assert pd.isna(aligned.loc["2024-01-02", "B"])


def test_discovery_screen_excludes_unknown_symbols(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"candidates": [{"symbol": "AAPL", "status": "READY_FOR_RESEARCH"}, '
                    '{"symbol": "BAD", "status": "UNKNOWN"}]}')
    assert symbols_from_discovery_manifest(str(path)) == ["AAPL"]


def test_equal_weight_benchmark_uses_window_endpoints():
    prices = np.array([[100.0, 110.0, 120.0], [100.0, 90.0, 80.0]])
    assert equal_weight_benchmark(prices, 0, 2) == 0.0
    assert benchmark_eligible_assets(prices, 0, 2) == 2


def test_benchmark_uses_only_prior_stale_mark_for_exchange_calendar_gap():
    prices = np.array([[100.0, 110.0, np.nan], [100.0, 90.0, 80.0]])
    assert _endpoint_values(prices, 2).tolist() == [110.0, 80.0]
    assert np.isclose(equal_weight_benchmark(prices, 0, 2), -0.05)


def test_paper_replay_window_is_inclusive_and_does_not_rewrite_history():
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert filter_replay_dates(dates, "2024-01-02", "2024-01-03") == dates[1:]


def test_instrument_oos_evidence_does_not_claim_standalone_return():
    points = [
        {"instrument_id": "AAA", "ts": "2025-01-01T00:00:00+00:00", "pnl": 10.0},
        {"instrument_id": "AAA", "ts": "2025-02-01T00:00:00+00:00", "pnl": 25.0},
    ]
    evidence = summarize_instrument_oos_pnl(
        points, start_date="2025-01-01", end_date="2025-02-01",
    )["AAA"]
    assert evidence["pnl_contribution"] == 15.0
    assert evidence["standalone_return"] is None
    assert evidence["return_target_status"] == "UNKNOWN"


def test_execution_evidence_fails_closed_without_historical_depth():
    evidence = execution_evidence_status({
        "trade_count": 3,
        "full_depth_trade_count": 0,
        "missing_depth_trade_count": 3,
        "quote_observation_count": 0,
        "trade_quote_observation_link_count": 0,
    })
    assert evidence["status"] == "UNKNOWN_NO_EXECUTABLE_DEPTH"
    assert evidence["promotion_allowed"] is False


def test_execution_evidence_requires_quote_links_for_promotion():
    evidence = execution_evidence_status({
        "trade_count": 2,
        "full_depth_trade_count": 2,
        "missing_depth_trade_count": 0,
        "quote_observation_count": 2,
        "trade_quote_observation_link_count": 1,
    })
    assert evidence["status"] == "UNKNOWN_NO_EXECUTABLE_DEPTH"
    assert evidence["promotion_allowed"] is False


def test_standalone_replay_uses_fixed_binary_target_and_window():
    series = pd.Series([10.0, 11.0, 12.0], index=["2025-01-01", "2025-01-02", "2025-01-03"])
    sliced, targets = slice_signal_window(
        series, binary_target([0.0, 0.4, 0.0, 0.0]), "2025-01-02", "2025-01-03",
    )
    assert binary_target([0.0, 0.4, -1.0]) == [0.0, 1.0, 0.0]
    assert sliced.index.tolist() == ["2025-01-02", "2025-01-03"]
    assert targets == [1.0, 0.0, 0.0]


def test_rolling_equity_folds_expose_tail_concentration():
    points = [{"ts": f"2025-01-{index:02d}T00:00:00+00:00", "equity": value}
              for index, value in enumerate([100.0, 110.0, 105.0, 100.0, 99.0, 98.0], start=1)]
    result = rolling_equity_folds(points, fold_count=3)
    assert result["status"] == "FAIL_UNSTABLE"
    assert result["fold_count"] == 3
    assert result["positive_fold_count"] == 1
    assert result["folds"][0]["return"] > 0


def test_tail_risk_guard_exits_and_cools_down_causally():
    series = pd.Series([100.0, 90.0, 85.0, 100.0], index=["a", "b", "c", "d"])
    guarded = apply_tail_risk_guard(
        series, [1.0, 1.0, 1.0, 1.0, 0.0], stop_loss_pct=0.10, cooldown_bars=1,
    )
    assert guarded == [1.0, 0.0, 0.0, 1.0, 0.0]


def test_tail_risk_guard_rejects_invalid_parameters():
    series = pd.Series([100.0, 101.0], index=["a", "b"])
    with pytest.raises(ValueError):
        apply_tail_risk_guard(series, [1.0, 1.0], stop_loss_pct=1.0)


def test_daily_oos_excess_charges_turnover_and_benchmark():
    matrix = np.array([[100.0, 110.0, 121.0], [100.0, 100.0, 100.0]])
    positions = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    returns, dates = daily_oos_excess(
        matrix, positions, ["2025-01-01", "2025-01-02", "2025-01-03"],
        cut=0, cost_bps=0,
    )
    assert dates == ["2025-01-02"]
    assert returns[0] > 0
