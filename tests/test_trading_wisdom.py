"""Tests for the 炒股的智慧 critical-point module."""

from __future__ import annotations

import numpy as np
import pytest

from libs.quant.pit import find_lookahead
from strategies.trading_wisdom import (
    Bars,
    Direction,
    SignalKind,
    detect_signals,
    position_size,
    swing_points,
    trailing_stop,
)


def _bars(closes, volumes=None, opens=None):
    closes = list(closes)
    return Bars(
        closes=closes,
        highs=[c * 1.01 for c in closes],
        lows=[c * 0.99 for c in closes],
        opens=opens if opens is not None else closes,
        volumes=volumes if volumes is not None else [1000.0] * len(closes),
    )


# --- structure -------------------------------------------------------------


def test_swing_points_finds_peaks_and_troughs():
    values = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7], dtype=float)
    peaks, troughs = swing_points(values, window=3)
    assert any(4 <= p <= 5 for p in peaks)
    assert any(7 <= t <= 9 for t in troughs)


def test_no_signals_without_enough_history():
    assert detect_signals(_bars([10, 11, 12])) == []


# --- buy setups ------------------------------------------------------------


def test_resistance_breakout_requires_volume_for_confidence():
    base = [10.0] * 40 + [10.1, 10.2, 10.15]
    quiet = detect_signals(_bars(base + [11.0]))
    loud = detect_signals(_bars(base + [11.0], volumes=[1000.0] * 43 + [5000.0]))

    quiet_break = [s for s in quiet if s.kind is SignalKind.RESISTANCE_BREAKOUT]
    loud_break = [s for s in loud if s.kind is SignalKind.RESISTANCE_BREAKOUT]
    assert quiet_break and loud_break
    # The book: a breakout without volume "has no meaning" — reflected in confidence.
    assert loud_break[0].confidence > quiet_break[0].confidence
    assert loud_break[0].volume_confirmed and not quiet_break[0].volume_confirmed


def test_false_breakdown_is_detected_but_carries_low_confidence():
    """The book's boldest claim, held to this project's own evidence standard.

    《炒股的智慧》 calls the false breakdown a "十次有九次" setup. Measured here on
    2,557 real events it wins 45.8% — indistinguishable from both the
    "broke and never recovered" control and the unconditional base rate. The
    signal is still surfaced (seeing a pattern fire and knowing it failed testing
    beats not seeing it), but its confidence has to reflect the measurement
    rather than the claim, or the engine is quoting a book at the operator and
    calling it evidence.
    """
    closes = [10.0] * 40 + [9.2, 9.3, 10.4]
    volumes = [1000.0] * 40 + [4000.0, 4000.0, 5000.0]
    signals = detect_signals(_bars(closes, volumes=volumes))
    false_breakdowns = [s for s in signals if s.kind is SignalKind.FALSE_BREAKDOWN]
    assert false_breakdowns
    signal = false_breakdowns[0]
    assert signal.direction is Direction.BUY
    assert signal.stop_price is not None and signal.stop_price < signal.price
    # Low, not high: the measurement falsified the claim.
    assert signal.confidence <= 0.25
    # And the rationale must carry the falsification, not just a number.
    assert "45.8%" in signal.rationale_zh


def test_volume_confirmation_does_not_raise_false_breakdown_confidence():
    """The subset the book calls strongest measured worst (-0.47%, 45.9%)."""
    closes = [10.0] * 40 + [9.2, 9.3, 10.4]
    loud = detect_signals(_bars(closes, volumes=[1000.0] * 40 + [4000.0, 4000.0, 5000.0]))
    quiet = detect_signals(_bars(closes, volumes=[1000.0] * 43))

    loud_signal = next(s for s in loud if s.kind is SignalKind.FALSE_BREAKDOWN)
    quiet_signal = next(s for s in quiet if s.kind is SignalKind.FALSE_BREAKDOWN)
    assert loud_signal.confidence <= quiet_signal.confidence


def test_stop_never_risks_more_than_the_ceiling():
    closes = [100.0] * 40 + [50.0, 51.0, 101.0]      # structure implies a huge stop
    for signal in detect_signals(_bars(closes)):
        if signal.stop_pct is not None:
            assert signal.stop_pct <= 0.20 + 1e-9


# --- exit setups -----------------------------------------------------------


def test_parabolic_exhaustion_fires_on_first_down_close():
    closes = [10.0] * 30 + list(np.linspace(10, 22, 10)) + [21.0]
    opens = closes[:-1] + [22.5]                      # last bar closes below open
    signals = detect_signals(_bars(closes, opens=opens))
    assert any(s.kind is SignalKind.PARABOLIC_EXHAUSTION and s.direction is Direction.EXIT
               for s in signals)


def test_distribution_fires_on_volume_surge_with_stalled_price():
    closes = [10.0] * 20 + list(np.linspace(10, 12, 10)) + [12.0, 12.02, 12.0]
    volumes = [1000.0] * 30 + [1000.0, 1000.0, 9000.0]
    signals = detect_signals(_bars(closes, volumes=volumes))
    assert any(s.kind is SignalKind.DISTRIBUTION for s in signals)


# --- causality (the non-negotiable property) -------------------------------


def test_signals_are_causal():
    rng = np.random.default_rng(0)
    closes = list(100 + np.cumsum(rng.normal(0, 1, 120)))

    def signal_series(prices):
        out = []
        for i in range(len(prices)):
            window = prices[: i + 1]
            found = detect_signals(_bars(window)) if len(window) >= 25 else []
            out.append(len(found))
        return out

    assert find_lookahead(signal_series, closes) == []


# --- trailing stop & sizing ------------------------------------------------


def test_trailing_stop_ratchets_to_the_latest_swing_low():
    # A clean rising staircase: each pullback low is higher than the last, so the
    # stop should sit at the most recent (highest) swing low.
    closes = []
    for step in range(8):
        base = 10 + step * 2
        closes += [base, base + 1.5, base + 1.0]     # up, up, pull back
    stop = trailing_stop(_bars(closes), entry_index=2, window=1)
    assert stop is not None
    assert stop > closes[2]                          # ratcheted above the entry area


def test_trailing_stop_falls_back_to_a_capped_stop_without_swing_lows():
    # Straight line up: no pullbacks, so no swing low exists to ratchet to.
    closes = list(np.linspace(10, 20, 30))
    stop = trailing_stop(_bars(closes), entry_index=1)
    assert stop is not None and stop < closes[1]


def test_position_size_enforces_the_books_rules():
    ok = position_size(capital=100_000, entry=10.0, stop=9.2, target=13.0)
    assert ok["allowed"] and ok["allocation"] == 10_000.0      # one of ten parts

    too_wide = position_size(capital=100_000, entry=10.0, stop=7.0)
    assert not too_wide["allowed"] and "ceiling" in too_wide["reason"]

    poor_rr = position_size(capital=100_000, entry=10.0, stop=9.0, target=11.0)
    assert not poor_rr["allowed"] and "risk/reward" in poor_rr["reason"]

    assert not position_size(capital=100_000, entry=10.0, stop=11.0)["allowed"]


def test_unknown_account_equity_yields_a_rule_not_an_amount():
    """No configured equity must not become an invented one.

    The verdict API passed a hardcoded ``capital=100_000`` into this function, so
    the product's "how much to buy" field showed an exact allocation and share
    count derived from an account that does not exist. The rule — one tenth of
    equity, risk as a fraction — is genuinely knowable without an account size;
    the amounts are not.
    """
    sized = position_size(capital=None, entry=10.0, stop=9.2, target=13.0)
    assert sized["allowed"] is True
    assert sized["capital_known"] is False
    # The rule survives.
    assert sized["capital_fraction"] == 0.1
    assert sized["risk_pct"] == pytest.approx(0.08)
    assert sized["risk_fraction_of_equity"] == pytest.approx(0.008)
    # The amounts do not — and are None, never zero.
    assert sized["allocation"] is None
    assert sized["shares"] is None
    assert sized["risk_amount"] is None
    assert sized["capital"] is None


def test_zero_equity_is_treated_as_unknown_not_as_a_zero_position():
    """``capital=0`` cannot produce a real 0-share recommendation."""
    sized = position_size(capital=0.0, entry=10.0, stop=9.2, target=13.0)
    assert sized["capital_known"] is False
    assert sized["shares"] is None


def test_a_configured_equity_still_produces_amounts():
    """Setting POLYBOB_ACCOUNT_EQUITY must restore the concrete figures."""
    sized = position_size(capital=50_000.0, entry=10.0, stop=9.2, target=13.0)
    assert sized["capital_known"] is True
    assert sized["allocation"] == 5_000.0
    assert sized["shares"] == 500
    assert sized["risk_amount"] == pytest.approx(400.0)


def test_the_api_does_not_default_the_account_equity():
    """Nothing may quietly reintroduce a default account size."""
    from libs.config import Settings

    assert Settings().polybob_account_equity is None
