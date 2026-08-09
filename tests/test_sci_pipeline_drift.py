"""P8c — drift monitor circuit breaker.

Proves that a shifted distribution flips the breaker while a stable one does
not, that the breaker latches until explicitly reset, and that under-sampled
series never trip it (fail-safe)."""

from __future__ import annotations

import numpy as np

from libs.quant.drift import DriftLevel
from modules.monitoring.drift_monitor import DriftMonitor


def _rng():
    return np.random.default_rng(42)


def test_stable_distribution_does_not_halt():
    rng = _rng()
    monitor = DriftMonitor(window=200, min_samples=50)
    monitor.set_reference("mid", rng.normal(0.0, 1.0, size=200).tolist())
    monitor.extend("mid", rng.normal(0.0, 1.0, size=200).tolist())

    assert monitor.should_halt() is False
    report = monitor.evaluate("mid")
    assert report is not None and report.level is DriftLevel.NONE


def test_shifted_distribution_trips_the_breaker():
    rng = _rng()
    monitor = DriftMonitor(window=200, min_samples=50)
    monitor.set_reference("mid", rng.normal(0.0, 1.0, size=200).tolist())
    # A large mean shift -> PSI well above 0.25 (significant).
    monitor.extend("mid", rng.normal(6.0, 1.0, size=200).tolist())

    assert monitor.should_halt() is True
    status = monitor.status()
    assert status["halted"] is True
    assert status["reasons"]
    assert status["tripped_at"] is not None


def test_breaker_latches_until_reset():
    rng = _rng()
    monitor = DriftMonitor(window=200, min_samples=50)
    monitor.set_reference("mid", rng.normal(0.0, 1.0, size=200).tolist())
    monitor.extend("mid", rng.normal(6.0, 1.0, size=200).tolist())
    assert monitor.should_halt() is True

    # Even after the current window returns to baseline, the latch holds.
    monitor.extend("mid", rng.normal(0.0, 1.0, size=200).tolist())
    assert monitor.should_halt() is True

    monitor.reset()
    assert monitor.should_halt() is False


def test_under_sampled_series_is_failsafe():
    rng = _rng()
    monitor = DriftMonitor(window=200, min_samples=50)
    monitor.set_reference("mid", rng.normal(0.0, 1.0, size=10).tolist())
    monitor.extend("mid", rng.normal(6.0, 1.0, size=10).tolist())

    # Not enough samples to judge -> no evaluation, no false halt.
    assert monitor.evaluate("mid") is None
    assert monitor.should_halt() is False
