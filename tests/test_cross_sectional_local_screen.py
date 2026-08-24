import numpy as np

import pandas as pd

from scripts.cross_sectional_local_screen import (
    align_frames,
    apply_risk_policy,
    has_unresolved_price_jump,
    select_long_only,
    symbols_from_discovery_manifest,
    equal_weight_benchmark,
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
