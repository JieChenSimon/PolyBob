"""Tests for the Round-2 proven strategies, edges, and ensemble combiner."""

from __future__ import annotations

import numpy as np
import pytest

from libs.quant.pit import assert_no_lookahead, find_lookahead
from strategies.ensemble import (
    EnsembleStrategy,
    MetaLabelGate,
    fractional_kelly,
    inverse_volatility_weights,
    risk_parity_combine,
)
from strategies.prediction_market_edges import (
    combinatorial_mispricing,
    favorite_longshot_ok,
    longshot_size_scale,
    yes_no_arbitrage,
)
from strategies.proven_signals import (
    cross_sectional_momentum,
    short_term_reversal,
    time_series_momentum,
)


# --- proven signals: causality + behaviour --------------------------------


def test_tsmom_is_long_in_uptrend_short_in_downtrend():
    up = list(100 + np.arange(60) * 1.0)
    down = list(100 - np.arange(60) * 1.0)
    assert time_series_momentum(up)[-1] > 0
    assert time_series_momentum(down)[-1] < 0


def test_tsmom_is_causal():
    prices = list(100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 100)))
    assert find_lookahead(lambda p: time_series_momentum(p), prices) == []
    assert_no_lookahead(lambda p: time_series_momentum(p), prices)


def test_short_term_reversal_fades_recent_move_and_is_causal():
    prices = list(100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 100)))
    # A sharp up-move should produce a negative (fade) signal.
    spike = list(np.full(30, 100.0)) + [100, 101, 103, 106, 110]
    assert short_term_reversal(spike, lookback=5)[-1] < 0
    assert find_lookahead(lambda p: short_term_reversal(p), prices) == []


def test_cross_sectional_momentum_longs_winners_shorts_losers():
    signals = cross_sectional_momentum(
        {"A": 0.30, "B": 0.10, "C": -0.05, "D": -0.25}, quantile=0.25
    )
    assert signals["A"] == 1
    assert signals["D"] == -1
    assert signals["B"] == 0 and signals["C"] == 0


def test_cross_sectional_momentum_tiny_universe_no_double_assign():
    signals = cross_sectional_momentum({"A": 1.0, "B": -1.0}, quantile=0.5)
    assert set(signals.values()) <= {-1, 0, 1}
    assert signals["A"] == 1 and signals["B"] == -1


# --- prediction-market edges ----------------------------------------------


def test_yes_no_arbitrage_detects_underpriced_pair():
    opp = yes_no_arbitrage(0.48, 0.49)
    assert opp.exists and opp.profit_per_unit == pytest.approx(0.03)
    assert not yes_no_arbitrage(0.55, 0.50).exists


def test_yes_no_arbitrage_accounts_for_fees():
    assert not yes_no_arbitrage(0.48, 0.49, fee=0.05).exists


def test_combinatorial_mispricing_flags_nesting_violation():
    m = combinatorial_mispricing(0.60, 0.50)  # subset > superset -> impossible
    assert m.mispriced and m.action == "sell_subset_buy_superset"
    assert not combinatorial_mispricing(0.40, 0.55).mispriced


def test_favorite_longshot_discipline():
    assert favorite_longshot_ok(0.05, is_buy_yes=True) is False  # cheap YES buy denied
    assert favorite_longshot_ok(0.05, is_buy_yes=False) is True  # selling is fine
    assert favorite_longshot_ok(0.40, is_buy_yes=True) is True
    assert longshot_size_scale(0.05, is_buy_yes=True) == 0.0
    assert longshot_size_scale(0.35, is_buy_yes=True) == 1.0  # past floor+taper
    assert longshot_size_scale(0.20, is_buy_yes=True) == pytest.approx(0.5)  # mid-ramp
    assert 0.0 < longshot_size_scale(0.15, is_buy_yes=True) < 1.0


# --- ensemble combiner ----------------------------------------------------


def test_inverse_vol_weights_favor_low_vol():
    w = inverse_volatility_weights([0.01, 0.04])
    assert w[0] > w[1] and w.sum() == pytest.approx(1.0)


def test_risk_parity_combine_blends_toward_low_vol_signal():
    # Opposing signals; the lower-vol one should win the blend.
    combined = risk_parity_combine([1.0, -1.0], [0.01, 0.05])
    assert combined > 0  # low-vol long dominates


def test_fractional_kelly_caps_size():
    assert abs(fractional_kelly(1.0, fraction=0.25, cap=0.5)) <= 0.5
    assert fractional_kelly(0.0) == 0.0


def test_meta_label_gate_sizes_by_ecdf_and_filters():
    gate = MetaLabelGate(min_confidence=0.5).fit([0.2, 0.4, 0.6, 0.8, 1.0])
    assert gate.size(0.3) == 0.0  # below threshold -> filtered
    assert gate.size(0.9) > gate.size(0.65)  # stronger -> bigger


def test_ensemble_decide_produces_sized_long():
    ens = EnsembleStrategy(gate=MetaLabelGate(min_confidence=0.1))
    decision = ens.decide([0.8, 0.6], [0.01, 0.02], realized_vol=0.02)
    assert decision.direction == 1
    assert 0.0 < decision.size <= 1.0


def test_ensemble_flat_when_signals_cancel():
    ens = EnsembleStrategy()
    decision = ens.decide([1.0, -1.0], [0.02, 0.02])
    assert decision.direction == 0 and decision.size == 0.0


def test_ensemble_applies_longshot_discipline():
    ens = EnsembleStrategy(gate=MetaLabelGate(min_confidence=0.1))
    # Strong long but on a 5-cent YES contract -> size crushed to 0.
    decision = ens.decide([0.9], [0.01], pm_price=0.05, is_buy_yes=True)
    assert decision.size == 0.0
