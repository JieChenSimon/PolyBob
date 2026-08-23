import numpy as np

from libs.quant.research_pipeline import aggregate_portfolio, moving_average_positions, walk_forward_symbol


def test_moving_average_signal_is_causal_shape():
    prices = np.arange(1.0, 50.0)
    positions = moving_average_positions(prices, fast=3, slow=8)
    assert len(positions) == len(prices)
    assert np.all(positions[:7] == 0)


def test_walk_forward_requires_oos_and_reports_baseline():
    prices = np.linspace(100, 150, 500)
    result = walk_forward_symbol(
        "TEST", prices, candidates=({"fast": 5, "slow": 20}, {"fast": 10, "slow": 40}),
        cost_bps=10, train_size=200, test_size=50, step=50,
    )
    assert result.status in {"candidate_beats_baseline", "tested_no_edge"}
    assert result.oos_return is not None
    assert result.baseline_return is not None
    assert len(result.folds) > 0


def test_empty_portfolio_is_unknown_not_zero():
    assert aggregate_portfolio([])["status"] == "unknown"
