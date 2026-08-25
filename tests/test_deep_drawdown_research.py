from __future__ import annotations

import pandas as pd

from scripts.deep_drawdown_research import (
    _accepted_before_event,
    _event_outcomes,
    _first_drawdown_events,
)


def test_sec_acceptance_must_precede_event_decision_date():
    assert _accepted_before_event("2026-01-03T23:59:59Z", "2026-01-04") is True
    assert _accepted_before_event("2026-01-04T00:00:01Z", "2026-01-04") is False
    assert _accepted_before_event("missing", "2026-01-04") is False


def test_sec_acceptance_with_timezone_is_compared_in_utc():
    assert _accepted_before_event("2026-01-04T00:30:00+01:00", "2026-01-04") is True


def _bars() -> pd.DataFrame:
    closes = [100, 110, 90, 50, 48, 52, 55, 60, 65, 70, 75, 80]
    return pd.DataFrame({
        "event_date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "open": closes,
        "close": closes,
    })


def test_uses_prior_peak_and_one_event_per_episode():
    events = _first_drawdown_events(_bars())
    assert len(events) == 1
    assert events[0]["event_date"] == "2026-01-04"
    assert events[0]["drawdown"] > 0.5


def test_unresolved_long_horizon_is_fail_closed():
    events = _first_drawdown_events(_bars())
    outcomes = _event_outcomes(_bars(), events[0], 20.0)
    assert outcomes[0]["status"] == "UNKNOWN"
    assert outcomes[0]["net_return"] is None
