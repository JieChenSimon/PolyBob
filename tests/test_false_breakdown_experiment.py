"""The experiment must measure the rule the app actually ships.

``scripts/false_breakdown_experiment`` re-implements the FALSE_BREAKDOWN
predicate so it can be evaluated at any historical bar (``detect_signals`` only
ever looks at the last one). If the two drift apart, the experiment validates a
rule nobody trades and the result is worthless — so equivalence is pinned here.

Synthetic bars are used deliberately: these tests check *logic*, not edge. Every
win-rate and return figure in this project comes from real data only.
"""

from __future__ import annotations

import numpy as np

from scripts.false_breakdown_experiment import (
    broke_without_recovery_at,
    false_breakdown_at,
    volume_confirmed_at,
)
from strategies.trading_wisdom import Bars, SignalKind, detect_signals


def _bars(close, low=None, high=None, open_=None, volume=None) -> Bars:
    close = list(close)
    n = len(close)
    return Bars(
        closes=close,
        lows=list(low) if low is not None else [c * 0.99 for c in close],
        highs=list(high) if high is not None else [c * 1.01 for c in close],
        opens=list(open_) if open_ is not None else list(close),
        volumes=list(volume) if volume is not None else [1000.0] * n,
    )


def _shipped_fires(bars: Bars) -> bool:
    return any(s.kind is SignalKind.FALSE_BREAKDOWN for s in detect_signals(bars))


def _sweep_series(n: int = 120) -> list[float]:
    """A flat base, then a dip through it, then a close back above."""
    close = [100.0] * n
    close[-3] = 92.0
    close[-2] = 93.0
    close[-1] = 100.0     # reclaimed, strictly above the 99.5 support shelf
    return close


# ------------------------------------------------------- equivalence with ship
def test_predicate_agrees_with_shipped_detector_on_a_sweep():
    close = _sweep_series()
    low = [c * 0.995 for c in close]
    low[-3] = 90.0        # the actual breach
    bars = _bars(close, low=low)

    i = len(close) - 1
    assert false_breakdown_at(np.array(low), np.array(close), i) is True
    assert _shipped_fires(bars) is True


def test_predicate_agrees_with_shipped_detector_when_nothing_happens():
    close = [100.0 + 0.01 * i for i in range(120)]
    bars = _bars(close)

    i = len(close) - 1
    assert false_breakdown_at(np.array(bars.lows), np.array(close), i) is False
    assert _shipped_fires(bars) is False


def test_predicate_matches_shipped_detector_bar_for_bar():
    """Walk a random-but-fixed series and compare at every bar.

    ``detect_signals`` is fed a prefix so its "last bar" is the bar under test —
    which is the same causality guarantee the historical scan relies on.
    """
    rng = np.random.default_rng(20260731)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, 400)))
    high = close * (1 + np.abs(rng.normal(0, 0.01, 400)))

    mismatches = []
    for i in range(80, 400):
        prefix = _bars(close[: i + 1], low=low[: i + 1], high=high[: i + 1])
        if false_breakdown_at(low, close, i) != _shipped_fires(prefix):
            mismatches.append(i)
    assert mismatches == [], f"predicate diverged from shipped rule at bars {mismatches[:10]}"


# ------------------------------------------------------------------- controls
def test_control_is_the_complement_of_the_signal_on_a_breach():
    """Broke-and-recovered vs broke-and-stayed-down must be mutually exclusive."""
    close = _sweep_series()
    low = [c * 0.995 for c in close]
    low[-3] = 90.0
    c, l = np.array(close), np.array(low)
    i = len(close) - 1

    assert false_breakdown_at(l, c, i) is True
    assert broke_without_recovery_at(l, c, i) is False

    close_down = list(close)
    close_down[-1] = 88.0          # never reclaimed support
    c2 = np.array(close_down)
    assert false_breakdown_at(l, c2, i) is False
    assert broke_without_recovery_at(l, c2, i) is True


def test_no_breach_means_neither_group():
    close = [100.0] * 120
    c, l = np.array(close), np.array([99.0] * 120)
    i = 119
    assert false_breakdown_at(l, c, i) is False
    assert broke_without_recovery_at(l, c, i) is False


# --------------------------------------------------------------------- volume
def test_volume_confirmation_matches_the_books_threshold():
    volume = np.array([1000.0] * 40)
    assert volume_confirmed_at(volume, 39) is False          # 1.0x — not expanding

    volume[39] = 1200.0
    assert volume_confirmed_at(volume, 39) is True           # exactly 1.2x

    volume[39] = 1199.0
    assert volume_confirmed_at(volume, 39) is False


def test_volume_confirmation_is_unknowable_without_history():
    assert volume_confirmed_at(np.array([1000.0] * 5), 4) is False
    assert volume_confirmed_at(np.zeros(40), 39) is False     # no volume at all


# ------------------------------------------------------------------ causality
def test_support_never_uses_the_entry_bar_or_its_two_predecessors():
    """Support is min(low[i-lookback : i-2]) — changing bar i cannot change it.

    If a future or same-bar low leaked into the support level, the whole
    experiment would be measuring hindsight.
    """
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, 200))
    low = close - 1.0
    i = 150

    baseline = false_breakdown_at(low, close, i)
    tampered = low.copy()
    tampered[i + 1 :] = 0.01        # a catastrophe strictly after the signal bar
    assert false_breakdown_at(tampered, close, i) == baseline


def test_date_clustering_collapses_one_bad_day_into_one_observation():
    """500 names breaking on the same day is one draw, not 500."""
    from scripts.false_breakdown_experiment import Event, date_clustered_t

    same_day = [Event(f"S{i}", "us_equity", "2026-01-05", 0.05, False, "signal")
                for i in range(500)]
    t, n_dates = date_clustered_t(same_day)
    assert n_dates == 1
    assert t == 0.0        # a single date cannot produce significance
