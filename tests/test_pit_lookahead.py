"""Tests for point-in-time data and the look-ahead (leakage) guard."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from libs.quant.pit import (
    LookaheadError,
    Observation,
    PointInTimeSeries,
    assert_no_lookahead,
    find_lookahead,
    lag_signals,
)

BASE = datetime(2026, 1, 1)


def _t(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


# --- point-in-time series -------------------------------------------------


def test_as_of_hides_values_published_in_the_future():
    series = PointInTimeSeries[float]()
    # An earnings figure for T=0 that only becomes available at T=60 (report lag).
    series.add_value(_t(0), 100.0, available_at=_t(60))
    series.add_value(_t(0), 10.0, available_at=_t(0))  # a price, available immediately

    # At T=30 the earnings figure is NOT yet knowable.
    values = series.values_as_of(_t(30))
    assert 100.0 not in values
    assert 10.0 in values

    # At T=60 it becomes available.
    assert 100.0 in series.values_as_of(_t(60))


def test_observation_rejects_availability_before_event():
    with pytest.raises(ValueError):
        Observation(event_time=_t(10), available_at=_t(5), value=1.0)


def test_latest_as_of_returns_most_recent_visible_event():
    series = PointInTimeSeries[int]()
    series.add_value(_t(0), 1)
    series.add_value(_t(10), 2)
    series.add_value(_t(20), 3, available_at=_t(99))
    latest = series.latest_as_of(_t(15))
    assert latest is not None and latest.value == 2


# --- signal lagging -------------------------------------------------------


def test_lag_signals_shifts_forward_one_bar():
    assert lag_signals([1, 2, 3]) == [None, 1, 2]
    assert lag_signals([1, 2, 3], fill=0) == [0, 1, 2]
    assert lag_signals([]) == []


# --- leakage harness ------------------------------------------------------


def _causal_moving_average(bars):
    """Trailing 3-bar mean using only past+current bars (no leakage)."""
    out = []
    for i in range(len(bars)):
        window = bars[max(0, i - 2) : i + 1]
        out.append(sum(window) / len(window))
    return out


def _leaky_centered_average(bars):
    """Centered 3-bar mean — peeks at the *next* bar (look-ahead)."""
    out = []
    n = len(bars)
    for i in range(n):
        window = bars[max(0, i - 1) : min(n, i + 2)]  # includes i+1
        out.append(sum(window) / len(window))
    return out


def test_causal_signal_passes_guard():
    bars = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert find_lookahead(_causal_moving_average, bars) == []
    assert_no_lookahead(_causal_moving_average, bars)  # does not raise


def test_leaky_signal_is_detected():
    bars = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    leaks = find_lookahead(_leaky_centered_average, bars)
    # Every non-final bar looked ahead one step.
    assert leaks == [0, 1, 2, 3, 4]
    with pytest.raises(LookaheadError):
        assert_no_lookahead(_leaky_centered_average, bars)


def test_guard_validates_alignment():
    def wrong_length(bars):
        return [0.0]  # not aligned 1:1

    with pytest.raises(ValueError):
        find_lookahead(wrong_length, [1.0, 2.0, 3.0])
