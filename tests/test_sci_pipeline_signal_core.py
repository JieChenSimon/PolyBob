"""P7 — unified research<->live signal path.

Proves that the live ``SpreadReversionStrategy`` and the backtest signal
generator produce identical signals because they share one causal core in
``strategies/signal_core``, and that the shared core is provably free of
look-ahead."""

from __future__ import annotations

from libs.quant.pit import assert_no_lookahead
from strategies.signal_core import (
    SpreadReversionParams,
    spread_reversion_entry,
    spread_reversion_signals,
)
from strategies.spread_reversion import SpreadReversionStrategy


def _spread_series() -> list[float]:
    # A calm baseline (with variance so std > 0, ~4.3 bps) punctuated by
    # moderate spikes that sit between the 2σ entry band and the 4σ stop band —
    # i.e. genuine reversion entries — then a return to calm, and finally an
    # extreme spike that must be refused as a structural break.
    series: list[float] = []
    for i in range(60):
        series.append(50.0 + (i % 7) * 2.0)  # ~50-62 bps
    series += [68.0, 70.0, 69.0]  # ~2.7-3.3σ above the mean -> enter
    for i in range(20):
        series.append(52.0 + (i % 5) * 1.5)
    series += [500.0]  # far beyond zscore_stop -> must NOT enter
    return series


PARAMS = SpreadReversionParams(
    entry_threshold_std=2.0,
    min_spread_bps=50.0,
    zscore_stop_std=4.0,
    min_samples=20,
    lookback_window=60,
)

LIVE_CONFIG = {
    "entry_threshold_std": PARAMS.entry_threshold_std,
    "min_spread_bps": PARAMS.min_spread_bps,
    "zscore_stop_std": PARAMS.zscore_stop_std,
    "min_samples": PARAMS.min_samples,
    "lookback_window": PARAMS.lookback_window,
    "confirm_bars": 1,  # match the causal core exactly (no extra live filter)
}


def test_research_equals_live_signals():
    spreads = _spread_series()

    research = spread_reversion_signals(spreads, PARAMS)

    strategy = SpreadReversionStrategy(LIVE_CONFIG)
    live: list[int] = []
    for spread in spreads:
        signal = strategy.generate_signal_sync(
            {"market_id": "m", "spread_bps": spread, "mid_price": 1.0, "bid_price": 0.99}
        )
        live.append(1 if signal is not None else 0)

    assert live == research
    # The scenario must actually exercise entries, or equivalence is vacuous.
    assert sum(research) >= 1


def test_shared_core_has_no_lookahead():
    spreads = _spread_series()
    # Bar k's signal must not change when future bars are appended.
    assert_no_lookahead(lambda history: spread_reversion_signals(history, PARAMS), spreads)


def test_structural_break_is_not_entered():
    # A z-score beyond the stop threshold means "don't catch a falling knife".
    window = [50.0] * 30 + [50_000.0]
    decision = spread_reversion_entry(window, PARAMS)
    assert decision.enter is False
    assert decision.z_score >= PARAMS.zscore_stop_std
